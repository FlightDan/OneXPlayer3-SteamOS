"""Slot switch regression tests; no real boot selection or reboot requests."""
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'slot-switch' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


boot = load('slot_boot', 'boot.py')
desktop = load('slot_desktop', 'desktop.py')


class FakeBoot:
    def __init__(self, directory):
        self.conf = Path(directory)
        self.current, self.selected, self.operation = 'A', 'A', 'idle'
        self.calls, self.fail, self.ignore, self.conflict = [], False, False, False
        self.write_failure = False
        self.values = {'A': {'boot-requested-at': 20990101000000, 'image-invalid': 0},
                       'B': {'boot-requested-at': 0, 'image-invalid': 0}}
        for slot in ('A', 'B'): (self.conf / (slot + '.conf')).write_text(slot)

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == boot.BUSCTL:
            return 'de.pengutronix.rauc 123 rauc root' if args[-1] == 'list' else 's "' + self.operation + '"'
        if args[0] == boot.SYSTEMCTL:
            if args[1] == 'show': return 'masked' if 'UnitFileState' in args else 'inactive'
            if self.conflict: (self.conf / 'B.conf').write_text('external writer')
            if self.fail or self.conflict: raise RuntimeError('reboot refused')
            return ''
        if args[1] == 'this-image': return self.current
        if args[1] == 'selected-image': return self.selected
        slot = args[args.index('--image') + 1]
        if '--get' in args:
            key = args[-1]; return key + ': ' + str(self.values[slot].get(key, 0))
        if self.write_failure:
            (self.conf / (slot + '.conf')).write_text('uncertain write')
            raise RuntimeError('write failed')
        if not self.ignore:
            (self.conf / (slot + '.conf')).write_text('selected ' + slot)
            self.selected = slot
        return ''


class SwitchChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fw = FakeBoot(self.temp.name)
        self.controller = boot.Controller(self.fw, self.temp.name, Path(self.temp.name) / 'records')
        self.original = {s: (self.fw.conf / (s + '.conf')).read_bytes() for s in ('A', 'B')}
        # Native Windows cannot model root-owned Unix paths. Use actual file
        # contents for state/rollback tests; Linux-only tests cover path guards.
        def read(path, maximum=65536): return Path(path).read_bytes(), 0o600
        self.patches = [patch.object(boot, 'preflight'), patch.object(boot, 'read_file', side_effect=read),
                        patch.object(boot, 'reboot_lock', return_value=nullcontext()),
                        patch.object(boot.Path, 'read_text', autospec=True, side_effect=lambda path, *a, **k: 'ID=steamos\nVERSION_ID=3.10\n' if path.as_posix() == '/etc/os-release' else path.read_bytes().decode())]
        if os.name == 'nt':
            def restore(path, original, expected):
                if read(path) != expected: raise RuntimeError('Concurrent write')
                path.write_bytes(original[0])
            self.patches.append(patch.object(boot, 'restore_file', side_effect=restore))
        for guard in self.patches: guard.start(); self.addCleanup(guard.stop)

    def test_status_is_read_only(self):
        state = self.controller.status()
        self.assertEqual((state['current'], state['target']), ('A', 'B'))
        self.assertFalse(any('--set' in call or call == [boot.SYSTEMCTL, 'reboot'] for call in self.fw.calls))

    def test_future_timestamp_and_both_directions(self):
        for current, target in [('A', 'B'), ('B', 'A')]:
            self.fw.current = self.fw.selected = current
            state = self.controller.status(); result = self.controller.reboot(target, state['token'])
            self.assertEqual(result['target'], target)
            write = next(call for call in reversed(self.fw.calls) if '--set' in call)
            self.assertGreater(int(write[write.index('boot-requested-at') + 1]), 20990101000000)
            self.assertEqual((self.fw.conf / (current + '.conf')).read_bytes(), self.original[current] if current == 'A' else b'selected B')

    def test_busy_invalid_and_unrecognized_current_refuse_writes(self):
        for kind in ('busy', 'invalid', 'unknown'):
            with self.subTest(kind=kind):
                self.fw.operation = 'installing' if kind == 'busy' else 'idle'
                self.fw.values['B']['image-invalid'] = 1 if kind == 'invalid' else 0
                self.fw.current = '?' if kind == 'unknown' else 'A'
                with self.assertRaises(RuntimeError): self.controller.status()
                self.assertFalse(any('--set' in call for call in self.fw.calls))

    def test_stale_confirmation_refuses_write(self):
        state = self.controller.status(); (self.fw.conf / 'B.conf').write_text('updated')
        with self.assertRaisesRegex(RuntimeError, 'state changed'): self.controller.reboot('B', state['token'])
        self.assertFalse(any('--set' in call for call in self.fw.calls))

    def test_reboot_failure_restores_target(self):
        state = self.controller.status(); self.fw.fail = True
        with self.assertRaisesRegex(RuntimeError, 'selection restored'): self.controller.reboot('B', state['token'])
        for slot in ('A', 'B'): self.assertEqual((self.fw.conf / (slot + '.conf')).read_bytes(), self.original[slot])

    def test_readback_failure_does_not_reboot(self):
        state = self.controller.status(); self.fw.ignore = True
        with self.assertRaisesRegex(RuntimeError, 'verification failed'): self.controller.reboot('B', state['token'])
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], self.fw.calls)

    def test_concurrent_writer_preserved_on_reboot_failure(self):
        state = self.controller.status(); self.fw.conflict = True
        with self.assertRaisesRegex(RuntimeError, 'restoration also failed'): self.controller.reboot('B', state['token'])
        self.assertEqual((self.fw.conf / 'B.conf').read_text(), 'external writer')

    def test_invalid_arguments_refused(self):
        for target, token in [('C', 'a' * 64), ('A; reboot', 'a' * 64), ('B', 'invalid')]:
            with self.assertRaises(ValueError): self.controller.reboot(target, token)
        self.assertFalse(self.fw.calls)

    def test_failed_write_does_not_overwrite_unknown_result(self):
        state = self.controller.status(); self.fw.write_failure = True
        with self.assertRaisesRegex(RuntimeError, 'restoration also failed'): self.controller.reboot('B', state['token'])
        self.assertEqual((self.fw.conf / 'B.conf').read_text(), 'uncertain write')
        self.assertNotIn([boot.SYSTEMCTL, 'reboot'], self.fw.calls)

    def test_running_updater_is_never_stopped(self):
        def active(args):
            self.fw.calls.append(args)
            return 'active'
        with self.assertRaisesRegex(RuntimeError, 'updater service is running'):
            boot.Controller(active).reboot('B', 'a' * 64)
        self.assertFalse(any('--set' in call or 'stop' in call for call in self.fw.calls))

    def test_temporary_masks_retained_until_successful_reboot(self):
        calls, masked = [], set()
        def run(args):
            calls.append(args)
            if args[0] == boot.BUSCTL: return ''
            if args[1] == 'show': return ('masked-runtime' if args[2] in masked else 'disabled') if 'UnitFileState' in args else 'inactive'
            if args[1] == 'mask': masked.add(args[-1])
            elif args[1] == 'unmask': masked.remove(args[-1])
            return ''
        with boot.Controller(run).update_guard() as guard: guard['reboot_requested'] = True
        self.assertEqual(masked, {'atomupd.service', 'rauc.service'})
        self.assertFalse(any('unmask' in args for args in calls))

    def test_mask_cleanup_attempts_every_service_after_one_failure(self):
        calls, masked = [], set()
        def run(args):
            calls.append(args)
            if args[0] == boot.BUSCTL: return ''
            if args[1] == 'show': return ('masked-runtime' if args[2] in masked else 'disabled') if 'UnitFileState' in args else 'inactive'
            if args[1] == 'mask': masked.add(args[-1])
            elif args[1] == 'unmask':
                if args[-1] == 'rauc.service': raise RuntimeError('cleanup failed')
                masked.remove(args[-1])
            return ''
        with self.assertRaisesRegex(RuntimeError, 'Could not restore temporary updater masks'):
            with boot.Controller(run).update_guard(): raise RuntimeError('cancelled')
        self.assertIn([boot.SYSTEMCTL, 'unmask', '--runtime', 'atomupd.service'], calls)
        self.assertEqual(masked, {'rauc.service'})

    def test_paused_rauc_is_not_activated(self):
        def inactive(args):
            if args[0] == boot.BUSCTL: return 'de.pengutronix.rauc - - - (activatable)'
            return 'inactive'
        boot.Controller(inactive).idle()


class DesktopChecks(unittest.TestCase):
    def state(self):
        return {'current': 'A', 'selected': 'A', 'target': 'B', 'token': 'a' * 64,
                'installation_records': {'B': {'version': '<b>unsafe</b>', 'system': '3.10', 'build': 'test'}}}

    def test_cancel_never_changes_selection(self):
        with patch.object(desktop, 'helper', return_value=self.state()) as helper, \
             patch.object(desktop.subprocess, 'run') as run:
            run.return_value.returncode = 1
            self.assertEqual(desktop.main(), 0)
            helper.assert_called_once_with('status')

    def test_confirm_uses_reviewed_target_and_token(self):
        state = self.state()
        with patch.object(desktop, 'helper', side_effect=[state, {}]) as helper, \
             patch.object(desktop.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(desktop.main(), 0)
            self.assertEqual(helper.call_args_list[1].args, ('reboot', 'B', state['token']))

    def test_bilingual_copy_and_metadata_escaping(self):
        for zh in (False, True):
            with patch.object(desktop, 'ZH', zh):
                value = desktop.message(self.state())
                self.assertNotIn('<b>unsafe</b>', value)
                self.assertIn('&lt;b&gt;unsafe&lt;/b&gt;', value)
                self.assertIn('安装时记录' if zh else 'installation record', value)
                self.assertIn('存档' if zh else 'saves', value)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Linux root ownership checks')
class PathChecks(unittest.TestCase):
    def test_absolute_image_tool_link_uses_image_namespace(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            target=root/'usr/bin/holo-bootconf'; target.write_text('trusted image tool')
            link=root/'usr/bin/steamos-bootconf'; link.symlink_to('/usr/bin/holo-bootconf')
            self.assertTrue(image_tool(root,'steamos-bootconf'))
            link.unlink(); link.symlink_to('holo-bootconf')
            self.assertTrue(image_tool(root,'steamos-bootconf'))

    def test_host_file_cannot_satisfy_missing_image_dependency(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            (root/'usr/bin/steamos-bootconf').symlink_to('/etc/passwd')
            self.assertFalse(image_tool(root,'steamos-bootconf'))

    def test_writable_image_link_target_and_cycles_are_refused(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/bin').mkdir(parents=True)
            target=root/'usr/bin/holo-bootconf'; target.write_text('untrusted'); target.chmod(0o666)
            link=root/'usr/bin/steamos-bootconf'; link.symlink_to('/usr/bin/holo-bootconf')
            with self.assertRaises(RuntimeError): image_tool(root,'steamos-bootconf')
            target.unlink(); target.symlink_to('steamos-bootconf')
            with self.assertRaisesRegex(RuntimeError,'cycle'): image_tool(root,'steamos-bootconf')

    def test_image_tool_symlink_ancestors_are_resolved_inside_image(self):
        from slot_switch import image_tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'usr/actual-bin').mkdir(parents=True)
            (root/'usr/bin').symlink_to('/usr/actual-bin',target_is_directory=True)
            target=root/'usr/actual-bin/steamos-bootconf'; target.write_text('trusted')
            self.assertTrue(image_tool(root,'steamos-bootconf'))
            target.unlink(); target.mkdir()
            with self.assertRaises(RuntimeError): image_tool(root,'steamos-bootconf')

    def test_link_and_writable_boot_metadata_refused(self):
        # /tmp is intentionally writable: use a trusted /run parent.
        with tempfile.TemporaryDirectory(dir='/run') as directory:
            path = Path(directory) / 'A.conf'; path.write_text('boot data'); path.chmod(0o600)
            self.assertEqual(boot.read_file(path)[0], b'boot data')
            path.chmod(0o666)
            with self.assertRaises(RuntimeError): boot.read_file(path)
            path.unlink(); path.symlink_to('/etc/passwd')
            with self.assertRaises(OSError): boot.read_file(path)


if __name__ == '__main__': unittest.main()
