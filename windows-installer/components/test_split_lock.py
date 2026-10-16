import json
import os
from pathlib import Path
import tempfile
import unittest

import split_lock


class BootChecks(unittest.TestCase):
    def test_all_entries_preserve_unrelated_options_and_idempotent(self):
        text = '# split_lock_detect=warn comment\n  steamenv_boot linux /boot/vmlinuz-linux-neptune-72 quiet nvme.noacpi=1\nlinuxefi /boot/vmlinuz-other root=UUID=abc\n'
        patched = split_lock.patch_grub(text)
        self.assertEqual(patched.count(' split_lock_detect=off'), 2)
        self.assertIn('quiet nvme.noacpi=1 split_lock_detect=off', patched)
        self.assertEqual(split_lock.patch_grub(patched), patched)
        self.assertTrue(patched.startswith('# split_lock_detect=warn comment\n'))

    def test_conflicting_or_duplicate_entries_refused(self):
        for suffix in (' split_lock_detect=warn', ' split_lock_detect=fatal',
                       ' split_lock_detect=off split_lock_detect=off'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                split_lock.patch_grub('linux /boot/vmlinuz-linux-neptune-72' + suffix + '\n')

    def test_missing_kernel_refused(self):
        with self.assertRaises(ValueError):
            split_lock.patch_grub('# untouched\n')

    def test_inline_boot_comment_refused(self):
        for suffix in (' # administrator comment', ' quiet \\', '; echo extra'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                split_lock.patch_grub('linux /boot/vmlinuz-linux-neptune-72' + suffix + '\n')

    def test_files_require_efi_and_preserve_existing_custom_dropin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                split_lock.files(root)
            grub = root / split_lock.GRUB
            grub.parent.mkdir(parents=True)
            grub.write_text('linux /boot/vmlinuz-linux-neptune-72 quiet\n')
            result = split_lock.files(root)
            self.assertIn(split_lock.DROPIN, result)
            self.assertIn(b'MIT License', result['usr/share/licenses/oxp3-split-lock/UPSTREAM_LICENSE']['data'])
            self.assertNotIn('split_lock_detect=off', grub.read_text())
            custom = root / split_lock.DROPIN
            custom.parent.mkdir(parents=True)
            custom.write_text('# administrator configuration\n')
            with self.assertRaises(ValueError):
                split_lock.files(root)

    def test_json_requires_unique_top_level_exact_type(self):
        for raw in (b'{"type":"split_lock"}', b'{"type": "split_lock", "extra": true}'):
            self.assertTrue(split_lock.is_split_report(raw))
        for raw in (b'{"type":"other","nested":{"type":"split_lock"}}',
                    b'{"type":"other","type":"split_lock"}', b'{"type":"split_lock_warn"}',
                    b'[ {"type":"split_lock"} ]', b'not json', b'{"type":"split_lock"}trailing',
                    b'{"type":"split_lock","x":NaN}', b'{"type":"split_lock","x":Infinity}'):
            self.assertFalse(split_lock.is_split_report(raw))


@unittest.skipUnless(os.name == 'posix', 'Requires Linux directory-descriptor operations')
class CleanupChecks(unittest.TestCase):
    def test_cleanup_keeps_every_non_split_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'trace'
            root.mkdir(mode=0o700)
            nested = root / 'nested'
            nested.mkdir(mode=0o700)
            (root / 'split.json').write_text('{"type":"split_lock"}')
            (nested / 'split-no-extension').write_text('{"type":"split_lock"}')
            retained = {'other.json': b'{"type":"gpu_reset","nested":{"type":"split_lock"}}',
                        'invalid.json': b'{"type":"other","type":"split_lock"}',
                        'binary': b'\x00\xff\x10split_lock', 'too-large': b'x' * (split_lock.MAX_REPORT + 1)}
            for name, data in retained.items():
                (root / name).write_bytes(data)
            outside = Path(temp) / 'outside'
            outside.write_text('{"type":"split_lock"}')
            (root / 'link').symlink_to(outside)
            (root / 'directory-link').symlink_to(Path(temp), target_is_directory=True)
            os.link(outside, root / 'hardlink')
            before = split_lock.reports(root)
            self.assertEqual(before['split_lock_files'], 2)
            deleted = split_lock.reports(root, delete=True)
            after = split_lock.reports(root)
            self.assertEqual(deleted['removed'], 2)
            self.assertEqual(before['preserved_digest'], deleted['preserved_digest'])
            self.assertEqual(before['preserved_digest'], after['preserved_digest'])
            self.assertEqual(after['split_lock_files'], 0)
            for name, data in retained.items():
                self.assertEqual((root / name).read_bytes(), data)
            self.assertTrue((root / 'link').is_symlink())
            self.assertTrue((root / 'directory-link').is_symlink())
            self.assertEqual(outside.read_text(), '{"type":"split_lock"}')

    def test_symlink_trace_ancestor_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / 'actual').mkdir()
            (base / 'alias').symlink_to(base / 'actual', target_is_directory=True)
            with self.assertRaises(OSError):
                split_lock.reports(base / 'alias', delete=True)

    def test_writable_report_directory_refuses_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o777)
            report = root / 'split'
            report.write_text('{"type":"split_lock"}')
            with self.assertRaises(ValueError):
                split_lock.reports(root, delete=True)
            self.assertTrue(report.exists())

    def test_writable_report_file_refuses_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / 'split'
            report.write_text('{"type":"split_lock"}')
            report.chmod(0o666)
            with self.assertRaises(ValueError):
                split_lock.reports(root, delete=True)
            self.assertTrue(report.exists())


if __name__ == '__main__':
    unittest.main()
