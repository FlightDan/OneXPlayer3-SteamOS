"""Partition mount installer mapping checks; never mount or edit a real filesystem."""
import os
from pathlib import Path
import tempfile
import unittest

import partition_mount


HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'partition-mount'


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'Target image ownership checks require Linux root')
class PartitionMountIntegrationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.components = self.root / 'payload' / 'components'
        source = self.components / 'partition-mount'
        source.mkdir(parents=True)
        for name in partition_mount.ASSETS:
            (source / name).write_bytes((SOURCE / name).read_bytes())
        bindir = self.root / 'usr' / 'bin'
        bindir.mkdir(parents=True)
        for tool in partition_mount.TOOLS:
            path = bindir / tool
            path.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            path.chmod(0o755)

    def test_builds_only_helper_and_desktop_file_map(self):
        result = partition_mount.files(self.root, self.components)
        expected = {
            'home/.oxp3-partition-mount/mounts.py',
            'home/.oxp3-partition-mount/desktop.py',
            'home/.oxp3-partition-mount/oxp3-partition-mount',
            'home/deck/Desktop/oxp3-partition-mount.desktop',
            'home/deck/.local/share/applications/oxp3-partition-mount.desktop',
        }
        self.assertEqual(set(result), expected)
        self.assertEqual(result['home/.oxp3-partition-mount/oxp3-partition-mount']['mode'], 0o755)
        self.assertEqual(result['home/.oxp3-partition-mount/mounts.py']['mode'], 0o644)
        self.assertTrue(all(result[path].get('user') for path in (
            'home/deck/Desktop/oxp3-partition-mount.desktop',
            'home/deck/.local/share/applications/oxp3-partition-mount.desktop')))
        for name in ('mounts.py', 'desktop.py', 'oxp3-partition-mount'):
            self.assertEqual(result['home/.oxp3-partition-mount/' + name]['data'],
                             (SOURCE / name).read_bytes())
        self.assertEqual(result['home/deck/Desktop/oxp3-partition-mount.desktop']['data'],
                         (SOURCE / 'oxp3-partition-mount.desktop').read_bytes())
        self.assertFalse(any('fstab' in path or 'polkit' in path for path in result))

    def test_missing_image_dependency_refuses_install(self):
        (self.root / 'usr/bin/systemd-escape').unlink()
        with self.assertRaisesRegex(RuntimeError, 'dependency missing: /usr/bin/systemd-escape'):
            partition_mount.files(self.root, self.components)

    def test_nonexecutable_image_dependency_refuses_install(self):
        (self.root / 'usr/bin/kdialog').chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'dependency target'):
            partition_mount.files(self.root, self.components)

    def test_missing_source_asset_refuses_install(self):
        (self.components / 'partition-mount/desktop.py').unlink()
        with self.assertRaisesRegex(RuntimeError, 'source file is missing or unsafe: desktop.py'):
            partition_mount.files(self.root, self.components)

    def test_dependency_link_cannot_fall_back_to_host_path(self):
        tool = self.root / 'usr/bin/lsblk'
        tool.unlink()
        tool.symlink_to('/etc/passwd')
        self.assertFalse(partition_mount.image_tool(self.root, 'lsblk'))
        with self.assertRaisesRegex(RuntimeError, 'dependency missing: /usr/bin/lsblk'):
            partition_mount.files(self.root, self.components)

    def test_dependency_cycles_and_writable_targets_are_refused(self):
        first, second = self.root / 'usr/bin/lsblk', self.root / 'usr/bin/findmnt'
        first.unlink(); second.unlink()
        first.symlink_to('findmnt'); second.symlink_to('lsblk')
        with self.assertRaisesRegex(RuntimeError, 'symlink cycle'):
            partition_mount.image_tool(self.root, 'lsblk')

        first.unlink(); second.unlink()
        for path in (first, second):
            path.write_text('tool', encoding='utf-8')
            path.chmod(0o755)
        first.chmod(0o666)
        with self.assertRaisesRegex(RuntimeError, 'Writable partition mount dependency'):
            partition_mount.image_tool(self.root, 'lsblk')

    def test_untrusted_existing_target_ancestor_is_refused(self):
        home = self.root / 'home'
        home.mkdir()
        home.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted partition mount target'):
            partition_mount.files(self.root, self.components)

    def test_existing_helper_with_unexpected_mode_is_refused(self):
        target = self.root / 'home/.oxp3-partition-mount/mounts.py'
        target.parent.mkdir(parents=True)
        target.write_text('existing', encoding='utf-8')
        target.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected partition mount file permissions'):
            partition_mount.files(self.root, self.components)


if __name__ == '__main__':
    unittest.main()
