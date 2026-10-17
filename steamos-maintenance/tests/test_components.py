"""Fixture-only checks: planning must never mutate a mounted system tree."""
import base64
import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oxp3_maintenance.components import build_plan, KERNEL, VERSION, GUARD, OLD_GUARD, SANDBOXED_GUARD, PLUGIN_ROOT


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.payload, self.root = self.base / 'payload', self.base / 'root'
        self.root.mkdir()
        self.catalog = {'schema': 1, 'repairs': [], 'plugins': []}
        self.manifest = {}
        self.probe = {'os': dict(VERSION), 'kernel': KERNEL,
                      'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'},
                      'bios': '5.09', 'packages': {'gamescope': '3.16.30-1', 'inputplumber': '0.78.0-1'},
                      'shared_compatible': True, 'target_disk': {'bus': 'NVMe', 'model': 'Other SSD'},
                      'uid': 1000, 'gid': 1000}

    def write(self, base, relative, data):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def component(self, name, files=None, dependencies=(), **metadata):
        self.catalog['repairs'].append({'id': name, 'dependencies': list(dependencies)})
        entries = []
        for index, (target, data) in enumerate((files or {}).items()):
            source = name + '/' + str(index) + '.bin'
            self.write(self.payload, 'integration/' + source, data)
            entries.append({'source': source, 'target': target})
        self.manifest[name] = {'files': entries, 'units': [], 'packages': {}, **metadata}

    def plan(self, selected, managed=None):
        self.write(self.payload, 'components/options.json', json.dumps(self.catalog).encode())
        self.write(self.payload, 'integration/manifest.json', json.dumps(self.manifest).encode())
        return build_plan(self.payload, self.root, selected, self.probe, managed)

    def assert_ready(self, plan, name):
        self.assertEqual(plan['components'][name]['status'], 'ready', plan['components'][name])

    def test_dependency_expansion_and_no_system_mutation(self):
        self.component('manager', {'usr/bin/steamos-manager': b'new'})
        self.component('native-tdp', {'etc/steamos-manager/remotes.d/oxp3.toml': b'tdp'}, ['manager'])
        old = self.write(self.root, 'usr/bin/steamos-manager', b'existing')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        with patch('subprocess.run', side_effect=AssertionError('planner ran command')):
            plan = self.plan(['native-tdp'])
        self.assertEqual(plan['selected'], ['manager', 'native-tdp'])
        self.assert_ready(plan, 'native-tdp')
        self.assertEqual(old.read_bytes(), b'existing')
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_invalid_unknown_duplicate_and_cycle(self):
        self.component('input', {'etc/inputplumber/a.yaml': b'profile'}, ['gyro'])
        self.component('gyro', dependencies=['input'])
        for choices in (['unknown'], ['input', 'input'], ['input']):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.plan(choices)

    def test_every_plugin_has_exact_device_os_kernel_guard(self):
        self.component('decky')
        self.write(self.payload, 'plugins/decky/PluginLoader', b'\x7fELFfixture')
        for field in ('kernel', 'os', 'dmi'):
            saved = copy.deepcopy(self.probe)
            self.probe[field] = 'other' if field == 'kernel' else {}
            plan = self.plan(['decky'])
            self.assertEqual(plan['components']['decky']['status'], 'blocked')
            self.assertEqual(plan['files'], {})
            self.probe = saved

    def test_cross_version_keyboard_uses_portable_shared_policy_only(self):
        self.component('keyboard')
        self.component('fan-driver', {'usr/lib/modules/current/driver.ko': b'native'})
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')
        self.probe.update(kernel='older-kernel', shared_compatible=False, shared_os_compatible=True)
        self.probe['os'].update(VERSION_ID='3.7', BUILD_ID='older')
        plan = self.plan(['keyboard', 'fan-driver'])
        self.assert_ready(plan, 'keyboard')
        self.assertEqual(plan['components']['keyboard']['compatibility']['profile'], 'portable-settings-v1')
        self.assertEqual(plan['components']['fan-driver']['status'], 'blocked')
        self.assertEqual(set(plan['files']), {'home/deck/.config/kwinrc'})
        self.probe['shared_os_compatible'] = False
        self.assertEqual(self.plan(['keyboard'])['components']['keyboard']['status'], 'blocked')

    def test_portable_keyboard_missing_dependency_or_services_are_blocked(self):
        self.component('keyboard')
        self.probe['kernel'] = 'older-kernel'
        self.assertEqual(self.plan(['keyboard'])['components']['keyboard']['status'], 'blocked')
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')
        self.manifest['keyboard']['units'] = ['arbitrary.service']
        self.assertIn('cannot activate services', self.plan(['keyboard'])['components']['keyboard']['reason'])

    def test_flathub_cross_version_requires_actual_flatpak_and_limits_files(self):
        self.component('flathub-ustc', {'usr/bin/unreviewed': b'never deploy'})
        self.probe['os'].update(VERSION_ID='3.7', BUILD_ID='older')
        self.probe['kernel'] = 'older-kernel'
        definition = '[Flatpak Repo]\nUrl=https://dl.flathub.org/repo/\nGPGKey=' + base64.b64encode(b'k' * 1024).decode() + '\n'
        self.write(self.payload, 'components/flathub.flatpakrepo', definition.encode())
        self.assertEqual(self.plan(['flathub-ustc'])['components']['flathub-ustc']['status'], 'blocked')
        executable = self.write(self.root, 'usr/bin/flatpak', b'fixture executable')
        executable.chmod(0o755)
        plan = self.plan(['flathub-ustc'])
        self.assert_ready(plan, 'flathub-ustc')
        self.assertEqual(set(plan['files']), {'etc/flatpak/remotes.d/flathub.flatpakrepo'})

    def test_new_catalog_item_is_visible_but_has_no_implicit_file_adapter(self):
        self.component('future-driver', {'usr/bin/unreviewed': b'native'})
        plan = self.plan(['future-driver'])
        item = plan['components']['future-driver']
        self.assertEqual(item['status'], 'blocked')
        self.assertEqual(item['compatibility']['profile'], 'unsupported-adapter')
        self.assertEqual(plan['files'], {})

    def test_failed_dependency_blocks_dependent_only(self):
        self.component('manager', missing=['Build the compatible manager'])
        self.component('native-tdp', {'etc/tdp.conf': b'1'}, ['manager'])
        self.component('xe-dsb', {'etc/modprobe.d/xe.conf': b'options xe enable_dsb=0'})
        plan = self.plan(['native-tdp', 'xe-dsb'])
        self.assertEqual(plan['components']['native-tdp']['status'], 'blocked')
        self.assertIn('Build the compatible manager', plan['components']['manager']['reason'])
        self.assert_ready(plan, 'xe-dsb')
        self.assertNotIn('etc/tdp.conf', plan['files'])

    def test_packages_bios_and_missing_resources_are_actionable(self):
        self.component('input', {'etc/inputplumber/a.yaml': b'input'})
        self.component('gyro', {'etc/inputplumber/oxp3-gyro-steer.conf': b'enabled=0'}, ['input'])
        self.probe['bios'] = '5.08'
        plan = self.plan(['gyro'])
        self.assertIn('BIOS 5.09', plan['components']['gyro']['reason'])
        self.component('manager', {'usr/bin/steamos-manager': b'elf'}, packages={'steamos-manager': '26.4.1-2'})
        plan = self.plan(['manager'])
        self.assertIn('26.4.1-2', plan['components']['manager']['reason'])

    def test_gyro_uses_fixed_recoverable_binding_helper_and_keeps_module(self):
        module = 'var/lib/oxp3-gyro-v1/oxp3_bmi260.ko'
        service = 'etc/systemd/system/oxp3-gyro.service'
        self.component('gyro', {module: b'original exact module',
                               'var/lib/oxp3-gyro-v1/load.sh': b'old load',
                               'var/lib/oxp3-gyro-v1/unload.sh': b'rmmod old',
                               service: b'[Service]\nTimeoutStartSec=20\nTimeoutStopSec=10\n'})
        plan = self.plan(['gyro'])
        self.assert_ready(plan, 'gyro')
        files = plan['files']
        self.assertEqual(files[module]['data'], b'original exact module')
        prefix = 'var/lib/oxp3-gyro-v1/'
        for name, action in (('load.sh', 'start'), ('unload.sh', 'stop')):
            self.assertEqual(files[prefix + name]['data'],
                             ('#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py ' + action + '\n').encode())
            self.assertEqual(files[prefix + name]['mode'], 0o755)
        helper = Path(__file__).resolve().parents[1] / 'oxp3_maintenance/gyro_binding.py'
        self.assertEqual(files[prefix + 'binding.py']['data'], helper.read_bytes())
        self.assertIn(b'TimeoutStartSec=40', files[service]['data'])
        self.assertIn(b'TimeoutStopSec=20', files[service]['data'])
        self.assertIn(GUARD, files[service]['data'])

    def test_shared_home_and_opt_block_whole_component(self):
        self.component('gamescope-env', {'etc/example': b'root', 'home/deck/.config/env': b'shared'})
        self.component('desktop-hdr', {'opt/runtime/file': b'binary'})
        self.probe['shared_compatible'] = False
        plan = self.plan(['gamescope-env', 'desktop-hdr'])
        self.assertEqual(plan['files'], {})
        self.assertTrue(all(x['status'] == 'blocked' for x in plan['components'].values()))

    def test_image_owned_compressed_firmware_is_preserved(self):
        self.component('wifi', {'usr/lib/firmware/required.ucode': b'accepted', 'usr/lib/firmware/optional.bin': b'bundled'})
        self.manifest['wifi']['files'][1]['missing_only'] = True
        existing = self.write(self.root, 'usr/lib/firmware/optional.bin.zst', b'image firmware')
        plan = self.plan(['wifi'])
        self.assert_ready(plan, 'wifi')
        self.assertNotIn('usr/lib/firmware/optional.bin', plan['files'])
        self.assertEqual(existing.read_bytes(), b'image firmware')

    def test_keyboard_merges_only_requested_keys(self):
        self.component('keyboard')
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')
        relative = 'home/deck/.config/kwinrc'
        self.write(self.root, relative, b'# keep\n[Wayland]\nInputMethod=old\nCustom=ok\n[Other]\nFoo=bar\n')
        plan = self.plan(['keyboard'])
        self.assert_ready(plan, 'keyboard')
        data = plan['files'][relative]['data']
        self.assertIn(b'Custom=ok\n', data)
        self.assertIn(b'[Other]\nFoo=bar', data)
        self.assertIn(b'VirtualKeyboardMode=1', data)
        self.assertEqual(data.count(b'InputMethod='), 1)
        self.assertTrue(plan['files'][relative]['mutable'])

    def test_duplicate_kconfig_group_is_blocked(self):
        self.component('keyboard')
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')
        self.write(self.root, 'home/deck/.config/kwinrc', b'[Wayland]\nA=1\n[Wayland]\nB=2\n')
        plan = self.plan(['keyboard'])
        self.assertIn('Ambiguous', plan['components']['keyboard']['reason'])

    def test_multifunction_merges_the_planned_input_mapping(self):
        mapping = b'  - name: Keyboard key (Ctrl+Meta+O)\n    target_event:\n      gamepad:\n        button: Keyboard\n  - name: Orange Button\n    custom: preserve\n'
        self.component('input', {'usr/share/inputplumber/capability_maps/oxp3-installer.yaml': mapping})
        self.component('multifunction', dependencies=['input'])
        plan = self.plan(['multifunction'])
        self.assert_ready(plan, 'multifunction')
        data = plan['files']['etc/inputplumber/capability_maps.d/oxp3-installer.yaml']['data']
        self.assertIn(b'button: RightPaddle2', data)
        self.assertIn(b'custom: preserve', data)

    def test_mutable_calibration_and_settings_preserved_byte_exact(self):
        self.component('input', {'etc/inputplumber/devices.d/50-onexplayer_3.yaml': b'default', 'usr/lib/modules/' + KERNEL + '/updates/hid-oxp.ko': b'module'})
        self.component('gyro', {'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml': b'default calibration',
                                'etc/inputplumber/oxp3-gyro-steer.conf': b'enabled=0\n'}, ['input'])
        existing = b'gyro_bias: [0.1, -0.2, 0.3]\ncustom: preserve\n'
        self.write(self.root, 'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml', existing)
        self.write(self.root, 'etc/inputplumber/oxp3-gyro-steer.conf', b'enabled=1\n')
        plan = self.plan(['gyro'])
        self.assert_ready(plan, 'gyro')
        self.assertNotIn('etc/inputplumber/devices.d/50-onexplayer_3.yaml', plan['files'])
        self.assertEqual(plan['files']['etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml']['data'], existing)
        self.assertEqual(plan['files']['etc/inputplumber/oxp3-gyro-steer.conf']['data'], b'enabled=1\n')

    def test_service_guard_replaced_without_legacy_activation(self):
        self.component('legacy-runtime', {'etc/systemd/system/oxp3.service': b'[Service]\n' + OLD_GUARD + b'\nExecStart=/bin/true\n'}, units=['oxp3.service'])
        plan = self.plan(['legacy-runtime'])
        data = plan['files']['etc/systemd/system/oxp3.service']['data']
        self.assertIn(GUARD, data)
        self.assertNotIn(OLD_GUARD, data)
        self.assertEqual(plan['components']['legacy-runtime']['units'], ['oxp3.service'])
        self.assertFalse(any('oxp3-selected-components' in x or 'system-update' in x for x in plan['files']))

    def test_private_device_service_guard_sees_host_without_relaxing_daemon(self):
        service = 'etc/systemd/system/oxp3-rapl.service'
        body = (b'[Unit]\nRequires=dbus.socket\n[Service]\n'
                b'Type=dbus\nUser=root\nGroup=root\n'
                b'ExecCondition=/usr/bin/test -d /sys/class/powercap\n'
                b'ExecStart=/usr/bin/python3 -I -B /var/lib/oxp3-rapl/provider.py\n'
                b'NoNewPrivileges=yes\nPrivateDevices=yes\nProtectHome=yes\n'
                b'ProtectSystem=strict\nCapabilityBoundingSet=\n')
        # New payloads, legacy installer units, already maintained units and
        # already fixed units all converge to one host-view guard. No prefix
        # may grant the daemon privileges or turn a failed guard into success.
        for prior in (b'', OLD_GUARD + b'\n', SANDBOXED_GUARD + b'\n', GUARD + b'\n'):
            with self.subTest(prior=prior):
                self.catalog, self.manifest = {'schema': 1, 'repairs': [], 'plugins': []}, {}
                original = body.replace(b'[Service]\n', b'[Service]\n' + prior, 1)
                self.component('native-tdp', {service: original}, units=['oxp3-rapl.service'])
                plan = self.plan(['native-tdp'])
                self.assert_ready(plan, 'native-tdp')
                data = plan['files'][service]['data']
                self.assertEqual(data.splitlines().count(GUARD), 1)
                self.assertEqual(data.replace(GUARD + b'\n', b''), body)
                self.assertNotIn(b'ExecStart=+', data)
                self.assertNotIn(b'ExecCondition=-', data)
                self.assertNotIn(OLD_GUARD, data)
                self.assertNotIn(SANDBOXED_GUARD, data)

    def test_user_services_preserve_original_activation_conditions(self):
        services = {
            'overlay': ('home/deck/.config/systemd/user/oxp3-overlay-telemetry.service',
                        b'ExecStart=/usr/bin/python3 -I -B /var/lib/oxp3-overlay-telemetry/telemetry.py collect\n'),
            'desktop-hdr': ('opt/oxp3-desktop-gamma22/6.7.3-1.6/lib/systemd/user/plasma-kwin_wayland.service',
                            b'ExecStart=/opt/oxp3-desktop-gamma22/6.7.3-1.6/bin/kwin_wayland_wrapper --xwayland\n'),
        }
        # These are the two user-unit destinations in the accepted payload.
        # The old integration guard only checked trusted files/device identity;
        # do not delete it, or other existing conditions, while repairing the
        # later root-only maintenance guard injection.
        conditions = (b'ExecCondition=/usr/bin/test -d /run/user/1000\n' + OLD_GUARD + b'\n'
                      + SANDBOXED_GUARD + b' --custom-condition\n'
                      + b'# ' + GUARD + b'\n')
        for name, (service, start) in services.items():
            for prior in (b'', SANDBOXED_GUARD + b'\n', GUARD + b'\n',
                          SANDBOXED_GUARD + b'\r\n' + GUARD + b'\n'):
                with self.subTest(service=service, prior=prior):
                    self.catalog, self.manifest = {'schema': 1, 'repairs': [], 'plugins': []}, {}
                    original = b'[Unit]\nDescription=User session\n[Service]\n' + conditions + start
                    payload = original.replace(b'[Service]\n', b'[Service]\n' + prior, 1)
                    self.component(name, {service: payload})
                    plan = self.plan([name])
                    self.assert_ready(plan, name)
                    self.assertEqual(plan['files'][service]['data'], original)

    def test_unrelated_service_payload_is_not_given_a_root_guard(self):
        service = 'var/lib/example/example.service'
        original = b'[Service]\nExecCondition=/usr/bin/false\nExecStart=/usr/bin/true\n'
        self.component('overlay', {service: original})
        self.assertEqual(self.plan(['overlay'])['files'][service]['data'], original)

    def test_traversal_and_special_target_are_blocked(self):
        for unsafe in ('../escape', '/etc/escape', 'C:/escape', 'etc\\escape'):
            self.catalog, self.manifest = {'schema': 1, 'repairs': [], 'plugins': []}, {}
            self.component('xe-dsb', {unsafe: b'data'})
            plan = self.plan(['xe-dsb'])
            self.assertEqual(plan['components']['xe-dsb']['status'], 'blocked')
            self.assertEqual(plan['files'], {})

    def test_symlink_ancestor_is_blocked_without_writing_outside(self):
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.root / 'etc').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks unavailable for the test account')
        self.component('xe-dsb', {'etc/modprobe.d/xe.conf': b'new'})
        plan = self.plan(['xe-dsb'])
        self.assertIn('Symlink', plan['components']['xe-dsb']['reason'])
        self.assertEqual(list(outside.iterdir()), [])

    def decky_and_plugin(self):
        self.component('decky')
        self.write(self.payload, 'plugins/decky/PluginLoader', b'\x7fELFfixture')
        self.component('steamgriddb', dependencies=['decky'])
        path = self.payload / 'plugins/steamgriddb/pinned.zip'
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in {'plugin.json': b'{"name":"SteamGridDB"}', 'package.json': b'{"version":"1.8.1"}', 'main.py': b'pass', 'dist/index.js': b'js'}.items():
                archive.writestr('decky-steamgriddb/' + name, data)
        self.write(self.payload, 'plugins/plugins.json', b'[{"id":"steamgriddb","name":"SteamGridDB","version":"1.8.1","archive":"pinned.zip"}]')
        return path

    def test_retired_plugin_is_refused_before_profile_version_validation(self):
        self.decky_and_plugin()
        self.write(self.payload, 'plugins/plugins.json', b'[{"id":"steamgriddb","name":"SteamGridDB","version":"9.0.0","archive":"pinned.zip"}]')
        plan = self.plan(['steamgriddb'])
        self.assertEqual(plan['components']['steamgriddb']['status'], 'blocked')
        self.assertIn('maintenance leaves them unchanged', plan['components']['steamgriddb']['reason'])
        self.assertFalse(any(x.startswith(PLUGIN_ROOT) for x in plan['files']))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_retired_bundled_plugin_is_refused_and_existing_user_data_is_untouched(self):
        self.decky_and_plugin()
        plan = self.plan(['steamgriddb'])
        self.assertEqual(plan['components']['steamgriddb']['status'], 'blocked')
        self.assertFalse(any(x.startswith(PLUGIN_ROOT) for x in plan['files']))
        existing = self.write(self.root, 'home/deck/homebrew/plugins/decky-steamgriddb/custom.json', b'user data')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        plan = self.plan(['steamgriddb'])
        self.assertEqual(plan['components']['steamgriddb']['status'], 'blocked')
        self.assertIn('maintenance leaves them unchanged', plan['components']['steamgriddb']['reason'])
        self.assertFalse(any(x.startswith(PLUGIN_ROOT) for x in plan['files']))
        self.assertEqual(existing.read_bytes(), b'user data')
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_decky_conflict_requires_managed_path_evidence(self):
        self.component('decky')
        self.write(self.payload, 'plugins/decky/PluginLoader', b'\x7fELFfixture')
        relative = 'etc/systemd/system/plugin_loader.service'
        self.write(self.root, relative, b'unknown installation')
        plan = self.plan(['decky'])
        self.assertEqual(plan['components']['decky']['status'], 'blocked')
        plan = self.plan(['decky'], {'paths': {relative: {'component': 'decky'}}})
        self.assert_ready(plan, 'decky')

    def test_zip_traversal_refused_without_partial_plugin_plan(self):
        path = self.decky_and_plugin()
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('decky-steamgriddb/../../escape', b'bad')
        plan = self.plan(['steamgriddb'])
        self.assertEqual(plan['components']['steamgriddb']['status'], 'blocked')
        self.assertFalse(any(x.startswith(PLUGIN_ROOT) for x in plan['files']))

    def test_runtime_tar_traversal_and_symlink_escape_are_blocked(self):
        self.component('desktop-hdr', runtime_archive='desktop-hdr/runtime.tar')
        path = self.payload / 'integration/desktop-hdr/runtime.tar'
        path.parent.mkdir(parents=True)
        for name, link in (('../escape', None), ('lib/escape', '../../escape')):
            with tarfile.open(path, 'w') as archive:
                item = tarfile.TarInfo(name)
                if link:
                    item.type = tarfile.SYMTYPE
                    item.linkname = link
                    archive.addfile(item)
                else:
                    item.size = 3
                    archive.addfile(item, io.BytesIO(b'bad'))
            plan = self.plan(['desktop-hdr'])
            self.assertEqual(plan['components']['desktop-hdr']['status'], 'blocked')
            self.assertEqual(plan['files'], {})

    def test_gm7_is_disk_specific_and_preserves_unrelated_boot_config(self):
        self.component('gm7-resume')
        plan = self.plan(['gm7-resume'])
        self.assertEqual(plan['components']['gm7-resume']['status'], 'not_applicable')
        self.probe['target_disk']['model'] = 'Predator SSD GM7 2TB'
        self.write(self.root, 'efi/EFI/steamos/grub.cfg', b'# keep\nsteamenv_boot /boot/vmlinuz-linux quiet\n')
        plan = self.plan(['gm7-resume'])
        self.assert_ready(plan, 'gm7-resume')
        self.assertEqual(plan['files']['efi/EFI/steamos/grub.cfg']['data'], b'# keep\nsteamenv_boot /boot/vmlinuz-linux quiet nvme.noacpi=1\n')
        self.write(self.root, 'efi/EFI/steamos/grub.cfg', b'linux /boot/vmlinuz-linux nvme.quirks=7\n')
        plan = self.plan(['gm7-resume'])
        self.assertIn('Conflicting NVMe', plan['components']['gm7-resume']['reason'])

    def test_waydroid_blocks_until_package_transactions_are_supported(self):
        self.component('waydroid')
        self.write(self.payload, 'waydroid/profile.json', b'{"archive":"r2.tar"}')
        path = self.payload / 'waydroid/r2.tar'
        with tarfile.open(path, 'w') as archive:
            for number in range(5):
                item = tarfile.TarInfo('r2/packages/host' + str(number) + '.pkg.tar.zst')
                item.size = 3
                archive.addfile(item, io.BytesIO(b'pkg'))
        plan = self.plan(['waydroid'])
        self.assertEqual(plan['components']['waydroid']['status'], 'blocked')
        self.assertTrue(plan['components']['waydroid']['setup_required'])
        self.assertEqual(plan['components']['waydroid']['activation'], 'unavailable')
        self.assertEqual(plan['components']['waydroid']['units'], [])
        self.assertEqual(plan['files'], {})
        self.assertIn('transactional package journal', plan['components']['waydroid']['reason'])

    def test_waydroid_host_bundle_is_plannable_with_transactional_backend(self):
        self.component('waydroid')
        profile = {'schema': 1, 'id': 'waydroid', 'archive': 'r2.tar',
                   'system': {'version': '3.10', 'build': '20260924.1000', 'kernel': KERNEL},
                   'packages': {'glibc': 'accepted-version'}}
        self.write(self.payload, 'waydroid/profile.json', json.dumps(profile).encode())
        self.probe.update(transactional_packages=True)
        self.probe['packages']['glibc'] = 'accepted-version'
        with tarfile.open(self.payload / 'waydroid/r2.tar', 'w') as archive:
            for number in range(5):
                item = tarfile.TarInfo('r2/packages/host' + str(number) + '.pkg.tar.zst')
                item.size = 3
                archive.addfile(item, io.BytesIO(b'pkg'))
        plan = self.plan(['waydroid'])
        self.assert_ready(plan, 'waydroid')
        self.assertTrue(plan['components']['waydroid']['package_install_required'])
        self.assertTrue(plan['components']['waydroid']['setup_required'])
        self.assertEqual(len(plan['components']['waydroid']['package_files']), 5)
        self.assertEqual(plan['components']['waydroid']['activation'], 'host-packages-pending')
        self.probe['packages']['glibc'] = 'newer-version'
        plan = self.plan(['waydroid'])
        self.assertEqual(plan['components']['waydroid']['status'], 'blocked')
        self.assertEqual(plan['files'], {})

    def test_hdr_data_only_and_rejects_regressed_anchors(self):
        self.component('hdr')
        # A payload Python generator must never run, even if it would write a marker.
        self.write(self.payload, 'components/hdr/generate.py', b'raise AssertionError("payload code executed")')
        self.write(self.payload, 'components/hdr/upstream.lua', b'max_frame_average_luminance = 475')
        plan = self.plan(['hdr'])
        self.assertEqual(plan['components']['hdr']['status'], 'blocked')
        self.assertIn('accepted anchors', plan['components']['hdr']['reason'])

    def test_accepted_hdr_template_preserves_1100_472_mapping(self):
        fixture = Path(__file__).resolve().parents[2] / 'windows-installer/components/hdr/upstream.lua'
        if not fixture.is_file():
            self.skipTest('Maintained source-tree HDR fixture is unavailable')
        self.component('hdr')
        expected = fixture.read_bytes()
        self.write(self.payload, 'components/hdr/upstream.lua', expected)
        self.write(self.payload, 'components/hdr/generate.py', b'raise AssertionError("do not import payload code")')
        plan = self.plan(['hdr'])
        self.assert_ready(plan, 'hdr')
        result = plan['files']['home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua']['data']
        self.assertEqual(result, expected)
        self.assertIn(b'max_content_light_level = 1100,', result)
        self.assertIn(b'max_frame_average_luminance = 472,', result)

    def test_retired_frontend_only_plugin_is_refused_without_extracting_archive(self):
        path = self.decky_and_plugin()
        with zipfile.ZipFile(path) as archive:
            files = {entry.filename: archive.read(entry) for entry in archive.infolist() if not entry.filename.endswith('/main.py')}
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        plan = self.plan(['steamgriddb'])
        self.assertEqual(plan['components']['steamgriddb']['status'], 'blocked')
        self.assertIn('maintenance leaves them unchanged', plan['components']['steamgriddb']['reason'])
        self.assertFalse(any(x.startswith(PLUGIN_ROOT) for x in plan['files']))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_desktop_hdr_helpers_belong_to_the_desktop_user(self):
        relative = 'home/deck/.local/lib/oxp3-desktop-hdr-runtime/launch.sh'
        self.component('desktop-hdr', {relative: b'#!/bin/sh\n'})
        plan = self.plan(['desktop-hdr'])
        self.assert_ready(plan, 'desktop-hdr')
        self.assertTrue(plan['files'][relative]['user'])

    def test_windows_restart_resolves_trusted_system_executable_links(self):
        from oxp3_maintenance.components import _trusted_executable
        real = self.write(self.root, 'usr/bin/python3.14', b'python binary')
        real.chmod(0o755)
        link = self.root / 'usr/bin/python3'
        try:
            link.symlink_to('python3.14')
        except OSError:
            self.skipTest('Symlinks unavailable for the test account')
        self.assertEqual(_trusted_executable(self.root, 'usr/bin/python3'), real)
        link.unlink()
        link.symlink_to('../../../outside')
        with self.assertRaisesRegex(ValueError, 'escapes target root'):
            _trusted_executable(self.root, 'usr/bin/python3')

    def test_refind_is_explicitly_unavailable(self):
        self.component('refind')
        plan = self.plan(['refind'])
        self.assertEqual(plan['components']['refind']['status'], 'blocked')
        self.assertIn('separate boot-manager', plan['components']['refind']['reason'])


if __name__ == '__main__':
    unittest.main()
