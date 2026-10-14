"""Portable schema/render tests plus Linux-only isolated journal lifecycle fixtures."""
import os
from pathlib import Path
import tempfile
import shutil
import unittest

from shared_storage import BEGIN, END, validate_mounts, render_fstab, files, _check_mount_paths, verify_fstab

GUID = '11111111-2222-3333-4444-555555555555'
SELECTION = {'partuuid': GUID, 'filesystem': 'exfat', 'mount_name': 'share-d0-p4'}


class SharedStorageSchema(unittest.TestCase):
    def test_old_options_can_skip_without_changes(self):
        self.assertEqual(validate_mounts([]), [])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(files(directory, [], (1000, 1000)), {})
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(render_fstab(b'unchanged\r\n', [], (1000, 1000)), b'unchanged\r\n')

    def test_strict_schema_and_duplicate_rejection(self):
        invalid = [None, {}, [True], [dict(SELECTION, extra='bad')],
                   [dict(SELECTION, filesystem='ext4')], [dict(SELECTION, partuuid=GUID.upper())],
                   [dict(SELECTION, partuuid='{'+GUID+'}')], [dict(SELECTION, mount_name='../escape')],
                   [dict(SELECTION, mount_name='share-d00-p4')], [dict(SELECTION, mount_name='share-d0-p0')],
                   [dict(SELECTION, filesystem=True)], [SELECTION]*33,
                   [SELECTION, dict(SELECTION, mount_name='share-d1-p2')],
                   [SELECTION, dict(SELECTION, partuuid='66666666-2222-3333-4444-555555555555')]]
        # This fixture GUID uses digits; uppercase must actually change a letter.
        invalid[5] = [dict(SELECTION, partuuid='AAAAAAAA-2222-3333-4444-555555555555')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError): validate_mounts(value)

    def test_render_preserves_unrelated_bytes_and_is_idempotent(self):
        original = b'# image comment\r\nUUID=root / ext4 ro 0 1\r\n'
        output = render_fstab(original, [SELECTION], (1001, 1002))
        self.assertTrue(output.startswith(original))
        self.assertEqual(output, render_fstab(output, [SELECTION], (1001, 1002), managed=True))
        self.assertIn(b'PARTUUID='+GUID.encode()+b' /mnt/shared/share-d0-p4 exfat ', output)
        for option in (b'nofail', b'x-systemd.automount', b'x-systemd.device-timeout=5s',
                       b'x-systemd.mount-timeout=30s', b'uid=1001,gid=1002', b'nosuid,nodev,noexec'):
            self.assertIn(option, output)
        self.assertTrue(output.endswith(END.encode()))

    def test_ntfs_never_uses_destructive_options(self):
        output = render_fstab(b'', [dict(SELECTION, filesystem='ntfs')], (1000, 1000))
        self.assertIn(b' ntfs3 ', output)
        self.assertIn(b'windows_names', output)
        self.assertNotIn(b'force', output); self.assertNotIn(b'remove_hiberfile', output)
        self.assertNotIn(b'Steam', output)

    def test_independent_verification_detects_tampering_and_missing_selection(self):
        output=render_fstab(b'# unrelated\n', [SELECTION], (1000,1000))
        verify_fstab(output,[SELECTION],(1000,1000))
        changed=[output.replace(b'nofail,',b''), output.replace(b'noexec,',b'exec,'),
                 output.replace(b'uid=1000',b'uid=0'), output.replace(b'exfat',b'vfat'),
                 output.replace(GUID.encode(),b'66666666-2222-3333-4444-555555555555'),
                 output.replace(b'share-d0-p4',b'share-d0-p5'), output.replace(END.encode(),b''),
                 output.replace(b' 0 0\n',b' 0 2\n'), output.replace(b'rw,',b'rw,force,'),
                 output.replace(b'rw,',b'rw,rw,')]
        for data in changed:
            with self.subTest(data=data),self.assertRaises(RuntimeError): verify_fstab(data,[SELECTION],(1000,1000))
        with self.assertRaises(RuntimeError): verify_fstab(b'', [SELECTION], (1000,1000))
        verify_fstab(b'# old unrelated entries are preserved\n', [], (1000,1000))

    def test_unmanaged_fstab_conflicts_and_malformed_blocks_are_refused(self):
        entries = [f'PARTUUID={GUID} /elsewhere exfat defaults 0 0\n',
                   f'/dev/disk/by-partuuid/{GUID} /elsewhere exfat defaults 0 0\n',
                   'UUID=other /mnt/shared/share-d0-p4 exfat defaults 0 0\n',
                   'UUID=other /mnt/shared exfat defaults 0 0\n',
                   'UUID=other /mnt/shared/share-d0-p4/child exfat defaults 0 0\n',
                   'UUID=other //mnt/shared/share-d0-p4 exfat defaults 0 0\n',
                   'UUID=other /mnt/shared/../shared/share-d0-p4 exfat defaults 0 0\n',
                   BEGIN + END, BEGIN, END, BEGIN + END + BEGIN + END]
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(RuntimeError):
                render_fstab(entry.encode(), [SELECTION], (1000, 1000))
        with self.assertRaises(RuntimeError): render_fstab((BEGIN+BEGIN+END).encode(), [SELECTION], (1000,1000), True)

    def test_two_filesystems_and_bounded_selection(self):
        mounts = [dict(SELECTION, partuuid=f'{index:08x}-2222-3333-4444-555555555555',
                       mount_name=f'share-d{index}-p1', filesystem='vfat') for index in range(32)]
        self.assertEqual(render_fstab(b'', mounts, (1000,1000)).count(b'PARTUUID='), 32)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'Linux root fixture is required for nofollow and real FileTransaction metadata')
class SharedStorageLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='shared-storage-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'etc').mkdir(); (self.root/'etc/fstab').write_bytes(b'# original\nUUID=root / ext4 ro 0 1\n')
        self.original = (self.root/'etc/fstab').read_bytes()

    def apply(self, root, slot):
        from integration import apply_files
        state = root/'home/.oxp3-installer/integration'/slot
        selected = files(root, [SELECTION], (1000,1000), managed=(state/'shared-storage/state.json').exists())
        apply_files(root, state, 'shared-storage', selected, (1000,1000))
        return state

    def test_separate_slots_retry_and_original_restoration(self):
        from integration import LogicalFiles
        for slot in ('A','B'):
            root = self.root/slot; (root/'etc').mkdir(parents=True)
            (root/'etc/fstab').write_bytes(self.original)
            state = self.apply(root, slot)
            installed = (root/'etc/fstab').read_bytes()
            self.apply(root, slot)
            self.assertEqual((root/'etc/fstab').read_bytes(), installed)
            transaction = LogicalFiles(state/'shared-storage', root, {'etc/fstab':{}}, (1000,1000))
            self.assertEqual(transaction.rollback(), [])
            self.assertEqual((root/'etc/fstab').read_bytes(), self.original)
            self.assertFalse((root/'mnt').exists())

    def test_full_stage_only_shared_storage_preserves_update_policy_and_restores(self):
        from integration import stage, restore, VERSION
        source=Path(__file__).parent
        payload=self.root/'payload'; (payload/'components/hdr').mkdir(parents=True)
        (payload/'integration').mkdir()
        for item in source.glob('*.py'): shutil.copyfile(item,payload/'components'/item.name)
        for name in ('options.json','release.json'): shutil.copyfile(source/name,payload/'components'/name)
        for name in ('installer.py','generate.py','upstream.lua','UPSTREAM_LICENSE'):
            shutil.copyfile(source/'hdr'/name,payload/'components/hdr'/name)
        (self.root/'etc/os-release').write_text(''.join(f'{key}={value}\n' for key,value in VERSION.items()))
        (self.root/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/bash\ndeck:x:1000:1000:Deck:/home/deck:/bin/bash\n')
        options={'schema':1,'repairs':[],'plugins':[],'installer_language':'en-US',
                 'kde_language':'system','storage_mounts':[SELECTION]}
        first=stage(self.root,payload,options,'A')
        self.assertEqual(set(first['components']), {'shared-storage'})
        self.assertEqual(first['services'], [])
        self.assertEqual(stage(self.root,payload,options,'A'),first)
        self.assertFalse((self.root/'etc/systemd/system/steamos-update.service').exists())
        self.assertFalse((self.root/'home/deck/.local/share/Steam/steamapps/libraryfolders.vdf').exists())
        self.assertEqual(restore(self.root,'A','shared-storage'), [])
        self.assertEqual((self.root/'etc/fstab').read_bytes(), self.original)

    def test_manual_edit_is_preserved_on_retry_and_restore(self):
        from integration import LogicalFiles
        state = self.apply(self.root, 'A')
        path = self.root/'etc/fstab'; edited = path.read_bytes()+b'# administrator change\n'; path.write_bytes(edited)
        with self.assertRaises(RuntimeError): self.apply(self.root, 'A')
        transaction = LogicalFiles(state/'shared-storage',self.root,{'etc/fstab':{}},(1000,1000))
        self.assertTrue(transaction.rollback()); self.assertEqual(path.read_bytes(), edited)

    def test_ntfs_requires_selected_kernel_support(self):
        selection = [dict(SELECTION, filesystem='ntfs')]
        with self.assertRaisesRegex(RuntimeError, 'ntfs3'): files(self.root, selection, (1000,1000))
        metadata=self.root/'usr/lib/modules/6.1.52-valve-recovery/modules.builtin'; metadata.parent.mkdir(parents=True)
        metadata.write_text('kernel/fs/ntfs3/ntfs3.ko\n')
        self.assertIn(b' ntfs3 ', files(self.root, selection, (1000,1000))['etc/fstab']['data'])
        other=self.root/'usr/lib/modules/6.5.0-other'; other.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'ntfs3.*6.5.0-other'): files(self.root, selection, (1000,1000))
        (other/'modules.builtin').write_text('kernel/fs/ntfs3/ntfs3.ko\n')
        self.assertIn(b' ntfs3 ', files(self.root, selection, (1000,1000))['etc/fstab']['data'])
        (other/'modules.builtin').unlink(); other.rmdir(); other.symlink_to(metadata.parent, target_is_directory=True)
        with self.assertRaises(RuntimeError): files(self.root, selection, (1000,1000))

    def test_symlink_fstab_and_mount_ancestors_are_refused(self):
        outside=self.root/'outside'; outside.mkdir(); (outside/'fstab').write_bytes(b'preserve')
        (self.root/'etc/fstab').unlink(); (self.root/'etc/fstab').symlink_to(outside/'fstab')
        with self.assertRaises(RuntimeError): files(self.root,[SELECTION],(1000,1000))
        self.assertEqual((outside/'fstab').read_bytes(), b'preserve')
        (self.root/'etc/fstab').unlink(); (self.root/'etc/fstab').write_bytes(self.original)
        (self.root/'mnt').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError): files(self.root,[SELECTION],(1000,1000))

    def test_nonempty_mountpoint_and_native_unit_conflicts(self):
        mount=self.root/'mnt/shared/share-d0-p4'; mount.mkdir(parents=True); (mount/'document').write_text('preserve')
        with self.assertRaises(RuntimeError): _check_mount_paths(self.root,[SELECTION])
        (mount/'document').unlink()
        unit=self.root/r'etc/systemd/system/mnt-shared-share\x2dd0\x2dp4.mount'; unit.parent.mkdir(parents=True)
        unit.write_text('[Mount]\nWhat=UUID=other\n')
        with self.assertRaises(RuntimeError): _check_mount_paths(self.root,[SELECTION])


if __name__ == '__main__': unittest.main()
