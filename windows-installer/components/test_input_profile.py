"""Portable fixtures; no host sysfs or hardware writes are used."""
from pathlib import Path, PurePosixPath
import os
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import input_profile as profile


TEMPLATE = ('version: 1\nkind: CompositeDevice\nname: ONEXPLAYER 3\n'
            + profile.PLACEHOLDER
            + 'source_devices:\n  - group: gamepad\n    evdev:\n'
              '      name: Microsoft X-Box 360 pad\n      handler: event*\n'
              '  - group: imu\n    iio:\n      sample_rate: 400\n'
              '      gyro_bias: [1, 2, 3]\n')
MCU = PurePosixPath('/sys/devices/pci0000:00/usb3/3-5/3-5:1.2/0003:1A86:FE00.0003')


def fixture_info(info):
    # Windows does not implement POSIX permission bits. Emulate only their
    # successful baseline; explicit refusal tests exercise real validator rules.
    kind = stat.S_IFMT(info.st_mode)
    return SimpleNamespace(st_mode=kind | (0o755 if stat.S_ISDIR(kind) else 0o644),
                           st_uid=0, st_nlink=info.st_nlink, st_size=info.st_size)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'run'; self.runtime.mkdir()
        self.templates = self.root / 'templates'; self.templates.mkdir()
        self.devices = self.root / 'devices'; self.devices.mkdir()
        self.hidraw = self.root / 'hidraw'; self.hidraw.mkdir()
        actual_lstat, actual_fstat = os.lstat, os.fstat
        self.patch('_lstat', side_effect=lambda p: fixture_info(actual_lstat(p)))
        self.patch('_fstat', side_effect=lambda fd: fixture_info(actual_fstat(fd)))

    def patch(self, name, **kwargs):
        patcher = mock.patch.object(profile, name, **kwargs)
        result = patcher.start(); self.addCleanup(patcher.stop)
        return result

    def template(self, name=profile.NAMES[1], text=TEMPLATE):
        path = self.templates / name
        path.write_text(text, encoding='utf-8', newline='')
        return path

    def output(self):
        return self.runtime / 'rootfs/usr/share/inputplumber/devices'

    def prepare(self, found=MCU):
        with mock.patch.object(profile, 'discover_mcu', return_value=found):
            return profile.prepare(runtime=self.runtime, templates=self.templates,
                                   hidraw=self.hidraw, devices=self.devices)

    def hid(self, index=0, identity='0003:00001A86:0000FE00', interface='02'):
        # Real directories avoid requiring Windows symlink privileges.
        entry = self.hidraw / ('hidraw' + str(index)); entry.mkdir()
        device = entry / 'device'; device.mkdir()
        (device / 'uevent').write_text('HID_ID=' + identity + '\n')
        (device / 'bInterfaceNumber').write_text(interface)
        return entry, device

    def discover(self):
        # Fixture hidraw/device children stand in for resolved /sys/devices.
        return profile.discover_mcu(self.hidraw, self.hidraw)

    def test_discovery_requires_unique_vendor_interface(self):
        self.assertIsNone(self.discover())
        self.hid(0, interface='01')
        self.hid(1, identity='0003:0000045E:0000028E')
        _, device = self.hid(2)
        self.assertEqual(self.discover(), device.resolve())
        self.hid(3)
        self.assertIsNone(self.discover())

    def test_discovery_rejects_escape_and_duplicate_identity(self):
        _, device = self.hid()
        self.assertIsNone(profile.discover_mcu(self.hidraw, self.devices))
        (device / 'uevent').write_text('HID_ID=0003:00001A86:0000FE00\nHID_ID=0003:00001A86:0000FE00\n')
        self.assertIsNone(self.discover())

    def test_discovery_rejects_oversized_or_malformed_sysfs(self):
        _, device = self.hid()
        (device / 'uevent').write_bytes(b'X' * 8193)
        self.assertIsNone(self.discover())
        (device / 'uevent').write_bytes(b'\xff')
        self.assertIsNone(self.discover())

    def test_generate_exact_path_and_preserve_calibration_and_original(self):
        source = self.template()
        self.assertEqual(self.prepare(), 'generated:' + source.name)
        result = (self.output() / source.name).read_text()
        self.assertIn('sys_path: "' + str(MCU) + '"', result)
        self.assertIn('vendor_id: "6790"', result)
        self.assertIn('interface_number: "2"', result)
        self.assertIn('gyro_bias: [1, 2, 3]', result)
        self.assertEqual(result.split('source_devices:', 1)[1], TEMPLATE.split('source_devices:', 1)[1])
        self.assertEqual(source.read_text(), TEMPLATE)

    def test_gyro_precedes_normal_and_removes_previous_generated_variant(self):
        normal = self.template()
        self.prepare()
        gyro = self.template(profile.NAMES[0])
        self.assertEqual(self.prepare(), 'generated:' + gyro.name)
        self.assertFalse((self.output() / normal.name).exists())
        self.assertTrue((self.output() / gyro.name).exists())

    def test_canonical_legacy_dmi_only_changes_match_block_in_runtime_copy(self):
        legacy = TEMPLATE.replace(profile.PLACEHOLDER, profile.LEGACY_MATCH)
        legacy += '# Keep per-device calibration exactly.\n'
        source = self.template(profile.NAMES[0], legacy)
        original_bytes = source.read_bytes()
        self.assertEqual(self.prepare(), 'generated:' + source.name)
        generated = (self.output() / source.name).read_bytes()
        before, after = original_bytes.split(profile.LEGACY_MATCH.encode())
        self.assertTrue(generated.startswith(before))
        self.assertTrue(generated.endswith(after))
        self.assertNotIn(b'dmi_data:', generated)
        self.assertIn(str(MCU).encode(), generated)
        self.assertEqual(source.read_bytes(), original_bytes)

    def test_custom_legacy_model_or_order_does_not_opt_in(self):
        legacy = TEMPLATE.replace(profile.PLACEHOLDER, profile.LEGACY_MATCH)
        for custom in (legacy.replace('product_name: ONEXPLAYER 3', 'product_name: Custom'),
                       legacy.replace('      product_name: ONEXPLAYER 3\n      sys_vendor: ONE-NETBOOK',
                                      '      sys_vendor: ONE-NETBOOK\n      product_name: ONEXPLAYER 3'),
                       legacy.replace('      sys_vendor: ONE-NETBOOK',
                                      '      sys_vendor: ONE-NETBOOK\n      bios_version: "5.09"')):
            with self.subTest(custom=custom):
                self.assertIsNone(profile.render_template(custom, MCU))

    def test_real_source_template_bytes_generate_without_normalizing_newlines(self):
        text = Path(__file__).with_name('input-profile.yaml').read_bytes().decode('utf-8')
        source = self.template(text=text)
        original = source.read_bytes()
        self.assertEqual(self.prepare(), 'generated:' + source.name)
        generated = (self.output() / source.name).read_bytes()
        newline = b'\r\n' if b'\r\n' in original else b'\n'
        block = profile.PLACEHOLDER.encode().replace(b'\n', newline)
        before, after = original.split(block)
        self.assertTrue(generated.startswith(before))
        self.assertTrue(generated.endswith(after))
        self.assertEqual(source.read_bytes(), original)
        if newline == b'\r\n':
            self.assertNotIn(b'\n', generated.replace(b'\r\n', b''))

    def test_crlf_legacy_calibration_bytes_survive_runtime_generation(self):
        text = (TEMPLATE.replace(profile.PLACEHOLDER, profile.LEGACY_MATCH)
                + '# calibration: 陀螺仪\n').replace('\n', '\r\n')
        source = self.template(profile.NAMES[0], text)
        original = source.read_bytes()
        self.assertEqual(self.prepare(), 'generated:' + source.name)
        generated = (self.output() / source.name).read_bytes()
        block = profile.LEGACY_MATCH.replace('\n', '\r\n').encode()
        before, after = original.split(block)
        self.assertTrue(generated.startswith(before))
        self.assertTrue(generated.endswith(after))
        self.assertNotIn(b'\n', generated.replace(b'\r\n', b''))
        self.assertEqual(source.read_bytes(), original)

    def test_absent_or_ambiguous_mcu_removes_stale_profiles(self):
        self.template(); self.prepare()
        unrelated = self.output() / 'administrator.yaml'; unrelated.write_text('keep')
        self.assertEqual(self.prepare(None), 'no-unique-mcu')
        self.assertFalse(any((self.output() / name).exists() for name in profile.NAMES))
        self.assertEqual(unrelated.read_text(), 'keep')
        self.assertEqual(self.template().read_text(), TEMPLATE)

    def test_custom_matches_are_not_rewritten_and_stale_profile_is_removed(self):
        source = self.template(); self.prepare()
        custom = TEMPLATE.replace(profile.PLACEHOLDER, 'matches:\n  - dmi_data:\n      product_name: Custom\n')
        source.write_text(custom)
        self.assertEqual(self.prepare(), 'custom-template-preserved')
        self.assertFalse((self.output() / source.name).exists())
        self.assertEqual(source.read_text(), custom)

    def test_malformed_duplicate_or_unknown_match_blocks_are_not_rewritten(self):
        for text in (TEMPLATE + profile.PLACEHOLDER,
                     TEMPLATE.replace('source_devices:', 'other_key:\nsource_devices:'),
                     TEMPLATE.replace(profile.PLACEHOLDER, 'matches: []\n'),
                     TEMPLATE.replace('matches:', 'matches :') + 'matches: []\n',
                     TEMPLATE + '"matches": []\n',
                     TEMPLATE + 'unknown_key: true\n',
                     TEMPLATE.replace('\n', '\r\n', 1),
                     TEMPLATE.replace('\n', '\r', 1),
                     TEMPLATE.replace('\n', '\r\n') + '\r'):
            with self.subTest(text=text):
                self.assertIsNone(profile.render_template(text, MCU))

    def test_reject_untrusted_file_types_permissions_owner_and_hardlinks(self):
        for mode, uid, links in ((stat.S_IFLNK | 0o777, 0, 1),
                                 (stat.S_IFIFO | 0o600, 0, 1),
                                 (stat.S_IFREG | 0o666, 0, 1),
                                 (stat.S_IFREG | 0o644, 1000, 1),
                                 (stat.S_IFREG | 0o644, 0, 2)):
            with self.subTest(mode=mode, uid=uid, links=links):
                with self.assertRaises(profile.ProfileError):
                    profile._validate_info(SimpleNamespace(st_mode=mode, st_uid=uid, st_nlink=links))

    def test_symlink_or_writable_ancestor_refuses_before_output_write(self):
        source = self.template()
        normal = profile._lstat
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFDIR | 0o777):
            def changed(path):
                return (SimpleNamespace(st_mode=mode, st_uid=0, st_nlink=1)
                        if Path(path) == self.runtime else normal(path))
            with mock.patch.object(profile, '_lstat', side_effect=changed):
                with self.assertRaises(profile.ProfileError): self.prepare()
            self.assertFalse(self.output().exists())
        self.assertEqual(source.read_text(), TEMPLATE)

    def test_reject_oversized_and_nul_templates(self):
        for data in (b'x' * (profile.MAX_TEMPLATE + 1), TEMPLATE.encode() + b'\x00'):
            source = self.template(); source.write_bytes(data)
            with self.assertRaises(profile.ProfileError): self.prepare()
            self.assertFalse((self.output() / source.name).exists())

    def test_unsafe_generated_path_or_existing_target_is_refused(self):
        with self.assertRaises(profile.ProfileError): profile.render_template(TEMPLATE, '/sys/devices/"bad')
        self.template(); self.prepare()
        normal = profile._lstat
        target = self.output() / profile.NAMES[1]
        def changed(path):
            return (SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_nlink=1)
                    if Path(path) == target else normal(path))
        with mock.patch.object(profile, '_lstat', side_effect=changed):
            with self.assertRaises(profile.ProfileError): self.prepare(None)
        self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
