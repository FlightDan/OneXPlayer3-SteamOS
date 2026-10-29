"""Partition mount installer mapping checks; never mount or edit a real filesystem."""
import os
from pathlib import Path
import tempfile
import shutil
import hashlib
import json
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
        shutil.copytree(SOURCE / 'tools', source / 'tools')
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
            'home/.oxp3-partition-mount/preflight.py',
            'home/.oxp3-partition-mount/ntfs_status.c',
            'home/.oxp3-partition-mount/ntfs-tools-build.sh',
            'home/.oxp3-partition-mount/ntfs-tools-source.json',
            'home/.oxp3-partition-mount/MUSL-COPYRIGHT',
            'etc/systemd/system-generators/oxp3-ntfs-preflight',
            'etc/systemd/system/oxp3-ntfs-preflight@.service',
            'home/deck/Desktop/oxp3-partition-mount.desktop',
            'home/deck/.local/share/applications/oxp3-partition-mount.desktop',
        }
        expected.update('home/.oxp3-partition-mount/tools/' + name
                        for name in partition_mount.RUNTIME_NAMES | {'manifest.json'})
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
        self.assertEqual(result['etc/systemd/system-generators/oxp3-ntfs-preflight']['mode'], 0o755)
        self.assertEqual(result['home/.oxp3-partition-mount/tools/ntfsfix']['mode'], 0o755)

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


class RuntimePayloadChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()
        for name in ('ntfs_status.c', 'ntfs-tools-build.sh', 'ntfs-tools-source.json'):
            shutil.copyfile(SOURCE / name, self.source / name)
        shutil.copytree(SOURCE / 'tools', self.source / 'tools')
        self.tools = self.source / 'tools'

    def test_final_runtime_is_static_and_all_corresponding_source_is_included(self):
        result = partition_mount.runtime_files(self.tools)
        self.assertEqual(set(result), {'ntfs_status', 'ntfsfix', 'COPYING', 'source.tar.gz', 'manifest.json'})
        self.assertTrue(result['ntfs_status'].startswith(b'\x7fELF'))

    def test_changed_binary_and_changed_build_source_are_rejected(self):
        binary = self.tools / 'ntfsfix'
        original = binary.read_bytes()
        binary.write_bytes(original + b'changed')
        with self.assertRaisesRegex(RuntimeError, 'hash/size mismatch'):
            partition_mount.runtime_files(self.tools)
        binary.write_bytes(original)
        (self.source / 'ntfs_status.c').write_bytes(b'changed source')
        with self.assertRaisesRegex(RuntimeError, 'Rebuild NTFS tools'):
            partition_mount.runtime_files(self.tools)

    def test_dynamic_binary_is_rejected_even_with_matching_local_hash(self):
        binary = self.tools / 'ntfsfix'
        data = bytearray(binary.read_bytes())
        import struct
        offset = struct.unpack_from('<Q', data, 32)[0]
        struct.pack_into('<I', data, offset, 3)  # PT_INTERP must never be packaged.
        binary.write_bytes(data)
        path = self.tools / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['files']['ntfsfix']['sha256'] = hashlib.sha256(data).hexdigest()
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'dynamic loader'):
            partition_mount.runtime_files(self.tools)

    def test_extra_payload_and_mismatched_pinned_source_are_rejected(self):
        extra = self.tools / 'unexpected'
        extra.write_text('not in fixed whitelist', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'unexpected NTFS tools'):
            partition_mount.runtime_files(self.tools)
        extra.unlink()
        pin = self.source / 'ntfs-tools-source.json'
        value = json.loads(pin.read_bytes())
        value['source']['sha256'] = '0' * 64
        pin.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'provenance'):
            partition_mount.runtime_files(self.tools)


if __name__ == '__main__':
    unittest.main()
