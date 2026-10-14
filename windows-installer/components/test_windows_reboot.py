"""Windows boot behavior with fake firmware; isolated Linux file lifecycle tests."""
import asyncio
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'windows-reboot' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = load('windows_boot', 'boot.py')
REAL_PREFLIGHT = boot.preflight
plugin = load('windows_plugin', 'main.py')
desktop = load('windows_desktop', 'desktop.py')
WINDOWS = 'Boot000A* Windows Boot Manager\tHD(1,GPT,abc,0,0)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)\n'
MANAGER = 'Boot6000* SteamOS (OXP3)\tHD(1,GPT,def,0,0)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n'


class Firmware:
    def __init__(self, entries=WINDOWS, previous=None, fail=None, ignore_write=False):
        self.entries, self.next, self.fail = entries, previous, fail
        self.calls, self.ignore_write = [], ignore_write

    def __call__(self, args):
        self.calls.append(args)
        if args == [boot.EFI, '-v']:
            return 'BootOrder: 0001,000A\n' + (f'BootNext: {self.next}\n' if self.next else '') + self.entries
        if args[:2] == [boot.EFI, '-n']:
            if not self.ignore_write:
                self.next = args[2]
            if self.fail == 'write':
                self.fail = None
                raise RuntimeError('write failed after mutation')
        elif args == [boot.EFI, '-N']:
            self.next = None
        elif args == [boot.SYSTEMCTL, 'reboot'] and self.fail == 'reboot':
            raise RuntimeError('reboot denied')
        return ''


class BootChecks(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(boot, 'preflight'); self.guard.start()
        self.lock = patch.object(boot, 'reboot_lock', return_value=nullcontext()); self.lock.start()
        self.addCleanup(self.guard.stop); self.addCleanup(self.lock.stop)

    def test_status_is_read_only_and_accepts_loader_path(self):
        fw = Firmware(); value = boot.Controller(fw).status()
        self.assertTrue(value['ready']); self.assertEqual(value['target'], '000A')
        self.assertEqual(fw.calls, [[boot.EFI, '-v']])

    def test_label_alone_does_not_select_a_different_loader(self):
        fw = Firmware('Boot000A* Windows Boot Manager\tFile(\\EFI\\Other\\loader.efi)\n')
        self.assertFalse(boot.Controller(fw).status()['ready'])

    def test_decky_3210_root_flag_is_recognized(self):
        metadata = json.loads((HERE / 'windows-reboot/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['flags'], ['root'])

    def test_current_efibootmgr_unwrapped_path_and_optional_data(self):
        for tail in ('', '57494e444f57530001000000'):
            entries = WINDOWS.replace('File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)',
                                      '\\EFI\\Microsoft\\Boot\\bootmgfw.efi' + tail)
            value = boot.Controller(Firmware(entries)).status()
            self.assertTrue(value['ready']); self.assertEqual(value['target'], '000A')
        entries = WINDOWS.replace('File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)',
                                  '\\EFI\\Microsoft\\Boot\\bootmgfw.efi.bad')
        self.assertFalse(boot.Controller(Firmware(entries)).status()['ready'])

    def test_missing_disabled_and_ambiguous_entries_never_write(self):
        for entries in ('', WINDOWS.replace('000A*', '000A'), WINDOWS + WINDOWS.replace('000A', '000B')):
            fw = Firmware(entries)
            with self.assertRaises(RuntimeError): boot.Controller(fw).reboot('000A')
            self.assertEqual(fw.calls, [[boot.EFI, '-v']])

    def test_changed_target_requires_a_new_confirmation(self):
        fw = Firmware(WINDOWS.replace('000A', '000B'))
        with self.assertRaisesRegex(RuntimeError, 'changed'): boot.Controller(fw).reboot('000A')
        self.assertEqual(fw.calls, [[boot.EFI, '-v']])

    def test_manager_status_selects_steamos_fallback_and_is_read_only(self):
        for path in ('File(\\EFI\\BOOT\\BOOTX64.EFI)', '\\EFI\\BOOT\\BOOTX64.EFI',
                     '\\EFI\\BOOT\\BOOTX64.EFI0100'):
            fw = Firmware(WINDOWS + MANAGER.replace('File(\\EFI\\BOOT\\BOOTX64.EFI)', path))
            value = boot.Controller(fw).status('manager')
            self.assertTrue(value['ready']); self.assertEqual(value['target'], '6000')
            self.assertEqual(fw.calls, [[boot.EFI, '-v']]); self.assertIsNone(fw.next)

    def test_manager_does_not_select_unrelated_fallback_or_direct_steamos_loader(self):
        for entries in (MANAGER.replace('SteamOS (OXP3)', 'USB Disk'),
                        MANAGER.replace('BOOT\\BOOTX64.EFI', 'steamos\\steamcl.efi'),
                        MANAGER.replace('BOOTX64.EFI', 'BOOTX64.EFI.bad'),
                        MANAGER.replace('BOOTX64.EFI', 'BOOTX64.EFI.backup')):
            self.assertFalse(boot.Controller(Firmware(entries)).status('manager')['ready'])

    def test_manager_missing_disabled_ambiguous_and_changed_never_write(self):
        for entries in (WINDOWS, MANAGER.replace('6000*', '6000'),
                        MANAGER + MANAGER.replace('6000', '6001'), MANAGER.replace('6000', '6001')):
            fw = Firmware(entries)
            with self.assertRaises(RuntimeError): boot.Controller(fw).reboot('6000', 'manager')
            self.assertEqual(fw.calls, [[boot.EFI, '-v']])

    def test_manager_rechecks_target_and_verifies_one_shot_before_reboot(self):
        fw = Firmware(WINDOWS + MANAGER)
        self.assertTrue(boot.Controller(fw).reboot('6000', 'manager')['reboot_requested'])
        self.assertEqual(fw.calls, [[boot.EFI, '-v'], [boot.EFI, '-n', '6000'],
                                    [boot.EFI, '-v'], [boot.SYSTEMCTL, 'reboot']])
        fw = Firmware(WINDOWS + MANAGER)
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            boot.Controller(fw).reboot('000A', 'manager')
        self.assertEqual(fw.calls, [[boot.EFI, '-v']])

    def test_manager_failure_restores_bootnext_and_unverified_write_never_reboots(self):
        for previous in (None, '000A'):
            fw = Firmware(MANAGER, previous=previous, fail='reboot')
            with self.assertRaises(RuntimeError): boot.Controller(fw).reboot('6000', 'manager')
            self.assertEqual(fw.next, previous)
        fw = Firmware(MANAGER, ignore_write=True)
        with self.assertRaisesRegex(RuntimeError, 'verification'):
            boot.Controller(fw).reboot('6000', 'manager')
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], fw.calls)

    def test_explicit_managed_refind_path_is_supported(self):
        entries = MANAGER.replace('SteamOS (OXP3)', 'rEFInd').replace('BOOT\\BOOTX64.EFI', 'OXP3-rEFInd\\refind_x64.efi')
        self.assertEqual(boot.Controller(Firmware(entries)).status('manager')['target'], '6000')

    def test_arguments_cannot_be_shell_commands_or_other_boot_entries(self):
        for expected in ('000A;reboot', '--delete-bootnum', '', 10, '000a'):
            fw = Firmware()
            with self.assertRaises(ValueError): boot.Controller(fw).reboot(expected)
            self.assertEqual(fw.calls, [])

    def test_one_shot_is_verified_before_normal_reboot(self):
        fw = Firmware(previous='0001')
        self.assertTrue(boot.Controller(fw).reboot('000A')['reboot_requested'])
        self.assertEqual(fw.calls, [[boot.EFI, '-v'], [boot.EFI, '-n', '000A'],
                                    [boot.EFI, '-v'], [boot.SYSTEMCTL, 'reboot']])
        self.assertEqual(fw.next, '000A')

    def test_reboot_failure_restores_previous_or_clears_our_next_boot(self):
        for previous in (None, '0001'):
            fw = Firmware(previous=previous, fail='reboot')
            with self.assertRaises(RuntimeError): boot.Controller(fw).reboot('000A')
            self.assertEqual(fw.next, previous)
            self.assertNotIn([boot.EFI, '-o', '0001,000A'], fw.calls)

    def test_failed_write_that_mutated_firmware_is_recovered(self):
        fw = Firmware(previous='0001', fail='write')
        with self.assertRaises(RuntimeError): boot.Controller(fw).reboot('000A')
        self.assertEqual(fw.next, '0001')
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], fw.calls)

    def test_unverified_setting_never_reboots(self):
        fw = Firmware(ignore_write=True)
        with self.assertRaisesRegex(RuntimeError, 'verification'): boot.Controller(fw).reboot('000A')
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], fw.calls)

    def test_external_bootnext_writer_is_not_overwritten_by_recovery(self):
        fw = Firmware()
        def run(args):
            if args == [boot.SYSTEMCTL, 'reboot']:
                fw.next = '000B'; raise RuntimeError('reboot denied')
            return fw(args)
        with self.assertRaises(RuntimeError): boot.Controller(run).reboot('000A')
        self.assertEqual(fw.next, '000B')

    def test_loading_plugin_has_no_subprocess_or_reboot(self):
        with patch.object(plugin.asyncio, 'create_subprocess_exec') as run:
            asyncio.run(plugin.Plugin()._main())
            run.assert_not_called()

    def test_rpc_requires_confirmation_and_valid_target(self):
        instance = plugin.Plugin()
        for entry, confirmed in (('000A', False), ('000A', 'true'), ('; reboot', True)):
            with patch.object(plugin.asyncio, 'create_subprocess_exec') as run:
                self.assertFalse(asyncio.run(instance.reboot(entry, confirmed))['ok'])
                run.assert_not_called()

    def test_manager_rpc_requires_confirmation_and_calls_only_fixed_action(self):
        instance = plugin.Plugin()
        for entry, confirmed in (('6000', False), ('6000', 'true'), ('; reboot', True)):
            with patch.object(plugin.asyncio, 'create_subprocess_exec') as run:
                self.assertFalse(asyncio.run(instance.reboot_manager(entry, confirmed))['ok'])
                run.assert_not_called()
        from unittest.mock import AsyncMock
        with patch.object(instance, '_call', new_callable=AsyncMock, return_value={'ok': True}) as call:
            asyncio.run(instance.manager_status()); call.assert_called_once_with('status-manager')
            call.reset_mock()
            asyncio.run(instance.reboot_manager('6000', True)); call.assert_called_once_with('reboot-manager', '6000')

    def test_desktop_cancel_only_reads_status(self):
        with patch.object(desktop, 'helper', return_value={'ready': True, 'target': '000A'}) as call, \
             patch.object(desktop.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as dialog:
            self.assertEqual(desktop.main(), 0)
            call.assert_called_once_with('status')
            arguments = dialog.call_args.args[0]
            self.assertIn('--warningcontinuecancel', arguments)
            self.assertNotIn('--defaultno', arguments)

    def test_desktop_confirmation_uses_detected_entry(self):
        with patch.object(desktop, 'helper', return_value={'ready': True, 'target': '000A'}) as call, \
             patch.object(desktop.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(desktop.main(), 0)
            self.assertEqual(call.call_args_list[-1].args, ('reboot', '000A'))

    def test_system_tool_failure_reports_stderr_and_uses_fixed_environment(self):
        result = subprocess.CompletedProcess([], 1, stdout='', stderr='EFI variables are read-only')
        with patch.object(boot.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(RuntimeError, 'EFI variables are read-only'):
                boot.command([boot.EFI, '-v'])
            self.assertEqual(run.call_args.kwargs['env'], boot.ENV)
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_missing_uefi_fails_before_reading_boot_entries(self):
        with patch.object(boot, 'preflight', wraps=REAL_PREFLIGHT):
            with patch.object(boot.os, 'geteuid', return_value=0, create=True), \
                 patch.object(boot.Path, 'is_dir', return_value=False):
                fw = Firmware()
                with self.assertRaisesRegex(RuntimeError, 'UEFI'): boot.Controller(fw).status()
                self.assertEqual(fw.calls, [])


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0, 'isolated Linux root fixture required')
class LifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'root'; self.payload = self.base / 'payload'
        (self.root / 'etc').mkdir(parents=True)
        (self.root / 'etc/passwd').write_text('deck:x:1000:1000::/home/deck:/bin/bash\n')
        (self.root / 'etc/os-release').write_text('ID=steamos\nVERSION_ID=3.10\nBUILD_ID=20260924.1000\n')
        (self.root / 'usr/bin').mkdir(parents=True)
        for name in ('python3', 'efibootmgr', 'systemctl', 'pkexec', 'kdialog'):
            (self.root / 'usr/bin' / name).write_bytes(b'fixture')
        # Compatible SteamOS staging also installs the mandatory update policy.
        # Model its vendor units so this fixture reaches the reboot lifecycle.
        vendor = self.root / 'usr/lib/systemd/system'; vendor.mkdir(parents=True)
        for name in ('atomupd.service', 'rauc.service'):
            (vendor / name).write_text('[Service]\nExecStart=/usr/bin/true\n')
        shutil.copytree(HERE, self.payload / 'components', ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        (self.payload / 'integration').mkdir(); (self.payload / 'integration/manifest.json').write_text('{}')
        (self.payload / 'plugins/decky').mkdir(parents=True)
        (self.payload / 'plugins/decky/PluginLoader').write_bytes(b'\x7fELF' + b'fixture')
        self.options = dict(schema=1, repairs=[], plugins=['windows-reboot', 'decky'], installer_language='zh-CN', kde_language='system')

    def test_stage_both_slots_repeat_restore_and_owners(self):
        from integration import stage, restore
        other = self.base / 'slot-b'
        shutil.copytree(self.root, other)
        a = stage(self.root, self.payload, self.options, 'A')
        self.assertEqual(a['components']['windows-reboot']['status'], 'files_installed')
        self.assertEqual(stage(self.root, self.payload, self.options, 'A'), a)
        (other / 'home').mkdir()
        subprocess.run(['mount', '--bind', str(self.root / 'home'), str(other / 'home')], check=True)
        self.addCleanup(lambda: subprocess.run(['umount', str(other / 'home')], check=True))
        stage(other, self.payload, self.options, 'B')
        launcher = self.root / 'home/deck/Desktop/oxp3-reboot-windows.desktop'
        helper = self.root / 'usr/local/bin/oxp3-reboot-windows'
        self.assertEqual(launcher.stat().st_uid, 1000); self.assertEqual(helper.stat().st_uid, 0)
        self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
        self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
        with self.assertRaisesRegex(RuntimeError, 'dependent'): restore(self.root, 'A', 'decky')
        self.assertEqual(restore(self.root, 'A', 'windows-reboot'), [])
        self.assertFalse(launcher.exists()); self.assertFalse(helper.exists())
        self.assertEqual(restore(other, 'B', 'windows-reboot'), [])
        self.assertFalse((other / 'usr/local/bin/oxp3-reboot-windows').exists())

    def test_missing_dependency_safely_skips_whole_component(self):
        from integration import stage
        (self.root / 'usr/bin/kdialog').unlink()
        value = stage(self.root, self.payload, self.options, 'A')['components']['windows-reboot']
        self.assertEqual(value['status'], 'not_installed'); self.assertTrue(value['safe_to_skip'])
        self.assertFalse((self.root / 'usr/local/bin/oxp3-reboot-windows').exists())

    def test_user_modified_launcher_blocks_restoration(self):
        from integration import stage, restore
        stage(self.root, self.payload, self.options, 'A')
        launcher = self.root / 'home/deck/Desktop/oxp3-reboot-windows.desktop'
        launcher.write_text('user edit')
        self.assertTrue(restore(self.root, 'A', 'windows-reboot'))
        self.assertEqual(launcher.read_text(), 'user edit')
        self.assertTrue((self.root / 'usr/local/bin/oxp3-reboot-windows').exists())

    def test_writable_privileged_file_is_refused_before_deployment(self):
        from integration import stage
        path = self.root / 'usr/local/lib/oxp3-windows-reboot/boot.py'
        path.parent.mkdir(parents=True); path.write_text('existing'); path.chmod(0o666)
        value = stage(self.root, self.payload, self.options, 'A')['components']['windows-reboot']
        self.assertEqual(value['status'], 'not_installed')
        self.assertEqual(path.read_text(), 'existing')


if __name__ == '__main__': unittest.main(verbosity=2)
