"""Partition mount safety and persistence tests; never attach a physical disk."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'partition-mount' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = load('partition_mount_backend', 'mounts.py')
desktop = load('partition_mount_desktop', 'desktop.py')
UUID = '11111111-2222-3333-4444-555555555555'
OWNER = (1000, 1000)
ORIGINAL = b'# keep this comment\nUUID=system / ext4 ro 0 1\n'


def device(**changes):
    return dict({'path': '/dev/vda3', 'type': 'part', 'uuid': UUID, 'fstype': 'ext4',
                 'parttype': '0fc63daf-8483-4772-8e79-3d69d8477de4', 'partuuid': 'data-partition',
                 'partlabel': 'Data', 'label': 'Games', 'size': 1234567890, 'ro': False,
                 'mountpoints': [None], 'maj:min': '253:3'}, **changes)


class RenderTests(unittest.TestCase):
    def test_unrelated_fstab_entries_may_omit_dump_and_pass(self):
        for suffix in ('', ' 0', ' 0 0'):
            raw = ('UUID=other /other ext4 defaults' + suffix + '\n').encode()
            saved = backend.render(raw, UUID, 'ext4', OWNER, device())
            self.assertTrue(saved.startswith(raw))
            self.assertEqual(backend.render(saved, UUID, None, OWNER), raw)
            conflict = ('UUID=' + UUID + ' /other ext4 defaults' + suffix + '\n').encode()
            with self.assertRaisesRegex(RuntimeError, 'already configured'):
                backend.render(conflict, UUID, 'ext4', OWNER, device())

    def test_unmounted_windows_volumes_and_sd_formats_are_selectable(self):
        for label in ('Windows', 'Data'):
            self.assertTrue(backend.eligible(device(label=label, fstype='ntfs',
                parttype='ebd0a0a2-b9e5-4433-87c0-68b6b72699c7', mountpoints=[])))
        for parttype in backend.FAT_TYPES | {'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'}:
            self.assertTrue(backend.eligible(device(path='/dev/mmcblk0p1', fstype='vfat',
                                                   parttype=parttype, uuid='1234-ABCD')))
        for parttype in ('c12a7328-f81f-11d2-ba4b-00a0c93ec93b', '0xef', '0x27', ''):
            self.assertFalse(backend.eligible(device(fstype='vfat', parttype=parttype)))
        self.assertFalse(backend.eligible(device(fstype='ext4', parttype='0x0c')))

    def test_vfat_persistence_uses_desktop_owner_and_round_trips(self):
        part = device(fstype='vfat', uuid='1234-ABCD', parttype='0x0c')
        saved = backend.render(ORIGINAL, part['uuid'], 'vfat', OWNER, part)
        self.assertIn(b' vfat rw,exec,nosuid,nodev,nofail,', saved)
        self.assertIn(b'uid=1000,gid=1000,fmask=0022,dmask=0022,utf8=1', saved)
        self.assertNotIn(b'windows_names', saved)
        self.assertEqual(backend.render(saved, part['uuid'], None, OWNER), ORIGINAL)

    def test_excluded_inventory_explains_missing_filesystem_and_duplicate_uuid(self):
        found = [device(), device(path='/dev/vdb3', **{'maj:min': '253:19'}),
                 device(path='/dev/vdc1', uuid=None, fstype='BitLocker')]
        with patch.object(backend, 'read_trusted', return_value=ORIGINAL), patch.object(backend, 'owner', return_value=OWNER), \
                patch.object(backend, 'command', return_value=json.dumps({'blockdevices': found})):
            result = backend.status()
        self.assertEqual(result['partitions'], [])
        self.assertEqual([item['reason'] for item in result['excluded']],
                         ['duplicate_uuid', 'duplicate_uuid', 'unsupported_filesystem'])
        with patch.object(desktop, 'ZH', False):
            self.assertIn('Not mounted', desktop.partition_label(device()))
            self.assertIn('Mounted: /run/media/deck/Games', desktop.partition_label(
                device(mountpoints=['/run/media/deck/Games'])))
            text = desktop.excluded_listing(result)
            self.assertIn('disconnect the clone', text)
            self.assertIn('encrypted volumes', text)

    def test_desktop_mounts_unmounted_selection_after_confirmation(self):
        state = {'partitions': [device()], 'managed': {}, 'token': 'a' * 64}
        response = {'saved': True, 'mounted': True, 'path': backend.destination(UUID), 'warning': ''}
        with patch.object(desktop, 'helper', side_effect=[state, response, state]) as helper, \
                patch.object(desktop, 'dialog', side_effect=['enable', UUID, '', '', None]):
            self.assertEqual(desktop.main(), 0)
        self.assertEqual(helper.call_args_list[1].args, ('enable', UUID, 'a' * 64))

    def test_persistent_uuid_and_reversible_block(self):
        saved = backend.render(ORIGINAL, UUID, 'ext4', OWNER, device())
        self.assertTrue(saved.startswith(ORIGINAL))
        self.assertIn(('UUID=' + UUID + ' /var/mnt/oxp3-volumes/' + UUID).encode(), saved)
        self.assertIn(b'nofail,x-systemd.automount,x-systemd.device-timeout=5s', saved)
        self.assertEqual(saved, backend.render(saved, UUID, 'ext4', OWNER, device()))
        self.assertEqual(backend.render(saved, UUID, None, OWNER), ORIGINAL)

    def test_ntfs_has_owner_and_no_force_or_hibernation_removal(self):
        output = backend.render(ORIGINAL, UUID, 'ntfs3', OWNER, device(fstype='ntfs'))
        self.assertIn(b'uid=1000,gid=1000', output)
        for unsafe in (b'force', b'remove_hiberfile', b'777', b'ntfs-3g'):
            self.assertNotIn(unsafe, output)
        native = backend.row(UUID, 'ext4', OWNER)
        self.assertNotIn('uid=', native)

    def test_refuses_edited_or_ambiguous_managed_entries(self):
        saved = backend.render(ORIGINAL, UUID, 'ext4', OWNER, device())
        bad = [saved.replace(b'rw,exec', b'rw,suid'), saved + backend.END.encode(),
               saved.replace(backend.END.encode(), b''), saved.replace(b' 0 0\n', b' 1 1\n'),
               saved.replace(b'UUID=' + UUID.encode(), b'/dev/vda3')]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises((ValueError, RuntimeError)):
                backend.render(raw, UUID, None, OWNER)

    def test_refuses_unmanaged_uuid_label_partuuid_and_path_aliases(self):
        for source in ('UUID=' + UUID, '/dev/vda3', 'LABEL=Games', 'PARTUUID=data-partition',
                       '/dev/disk/by-uuid/' + UUID, '/dev/disk/by-partuuid/data-partition',
                       '/dev/disk/by-label/Games', '/dev/disk/by-partlabel/Data'):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                backend.render(f'{source} /games ext4 defaults 0 0\n'.encode(), UUID, 'ext4', OWNER, device())
        for path in ('/mnt/oxp3-volumes/' + UUID, backend.destination(UUID) + '/child', '/var/mnt/oxp3-volumes'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                backend.render(f'UUID=other {path} ext4 defaults 0 0\n'.encode(), UUID, 'ext4', OWNER, device())

    def test_rejects_injection_and_unsupported_filesystems(self):
        for value in ('../bad', '/etc', 'foo bar', 'x\nUUID=bad', '-bad', '', 'bad\\x20'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.destination(value)
        with self.assertRaises(ValueError): backend.row(UUID, 'btrfs', OWNER)
        with self.assertRaises(RuntimeError): backend.render(ORIGINAL, UUID, None, OWNER)

    def test_filters_system_recovery_efi_readonly_and_encrypted_devices(self):
        self.assertTrue(backend.eligible(device()))
        self.assertTrue(backend.eligible(device(mountpoints=['/run/media/deck/Games'])))
        for changes in ({'mountpoints': ['/']}, {'mountpoints': ['/home']}, {'partlabel': 'rootfs-B'},
                        {'partlabel': 'recovery'}, {'label': 'RecoveryImages'}, {'parttype': 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'},
                        {'ro': True}, {'fstype': 'crypto_LUKS'}, {'type': 'disk'}, {'children': [{}]},
                        {'fstype': 'btrfs'}, {'mountpoints': ['/mnt/admin']}):
            with self.subTest(changes=changes): self.assertFalse(backend.eligible(device(**changes)))

    def test_duplicate_uuid_hidden_and_status_changes_invalidate_confirmation(self):
        tree = {'blockdevices': [dict(type='disk', children=[device(), device(path='/dev/vdb3', **{'maj:min': '253:19'})])]}
        with patch.object(backend, 'read_trusted', return_value=ORIGINAL), patch.object(backend, 'owner', return_value=OWNER), \
                patch.object(backend, 'command', return_value=json.dumps(tree)):
            self.assertEqual(backend.status()['partitions'], [])
            old = backend.status()['token']
            tree['blockdevices'][0]['children'].pop()
            with patch.object(backend, 'command', return_value=json.dumps(tree)):
                self.assertNotEqual(old, backend.status()['token'])

    def test_whole_disk_uuid_clone_is_also_excluded(self):
        tree = {'blockdevices': [device(), device(type='disk', path='/dev/vdb', **{'maj:min': '253:16'})]}
        with patch.object(backend, 'read_trusted', return_value=ORIGINAL), patch.object(backend, 'owner', return_value=OWNER), \
                patch.object(backend, 'command', return_value=json.dumps(tree)):
            self.assertEqual(backend.status()['partitions'], [])

    @unittest.skipUnless(hasattr(os, 'makedev'), 'Linux device identifiers')
    def test_by_id_alias_conflict_resolves_actual_block_device(self):
        from types import SimpleNamespace
        info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(253, 3))
        with patch.object(backend.os, 'stat', return_value=info), self.assertRaises(RuntimeError):
            backend.render(b'/dev/disk/by-id/some-disk-part3 /games ext4 defaults 0 0\n', UUID, 'ext4', OWNER, device())

    def test_standard_authorization_and_richtext_escaping(self):
        reply = {'ok': True, 'data': {'saved': True, 'mounted': False, 'warning': ''}}
        from types import SimpleNamespace
        with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(reply), returncode=0)) as run:
            desktop.helper('enable', UUID, 'a' * 64)
            self.assertEqual(run.call_args.args[0][:2], ['/usr/bin/pkexec', desktop.HELPER])
        self.assertEqual(desktop.rich('<img src=x>\n&'), '<qt>&lt;img src=x&gt;<br/>&amp;</qt>')

    def test_cancelled_authorization_is_reported(self):
        from types import SimpleNamespace
        with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(stdout='', returncode=126)), self.assertRaises(RuntimeError):
            desktop.helper('enable', UUID, 'a' * 64)

    def test_custom_unit_and_global_or_prefix_overrides_refused_before_save(self):
        for existing in ('/etc/systemd/system/var-mnt-oxp3\\x2dvolumes-id.mount',
                         '/etc/systemd/system/automount.d',
                         '/usr/lib/systemd/system/var-mnt-.mount.d',
                         '/run/systemd/system.control/var-mnt-oxp3\\x2dvolumes-id.automount.d',
                         '/run/systemd/generator.early/var-mnt-oxp3\\x2dvolumes-id.mount'):
            with self.subTest(existing=existing), patch.object(backend, 'command', return_value=r'var-mnt-oxp3\x2dvolumes-id.mount'), \
                    patch.object(backend.os.path, 'lexists', side_effect=lambda path: str(path).replace('\\', '/') == existing.replace('\\', '/')), self.assertRaises(RuntimeError):
                backend.check_units(UUID)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'Requires an isolated root Linux fixture')
class LinuxLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oxp3-mount-test-', dir='/root')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fstab = self.root / 'fstab'
        self.fstab.write_bytes(ORIGINAL)
        self.fstab.chmod(0o644)
        for name, value in {'FSTAB': self.fstab, 'BACKUP': self.root / 'backup',
                            'LOCK': str(self.root / 'lock'), 'BASE': str(self.root / 'volumes')}.items():
            patcher = patch.object(backend, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        self.current_device = device()
        self.command_calls = []
        self.mount_failure = False
        self.unit = 'fixture.mount'
        def commands(*args):
            self.command_calls.append(args)
            if args[0].endswith('lsblk'): return json.dumps({'blockdevices': [self.current_device]})
            if args[0].endswith('systemd-escape'): return self.unit
            if 'FragmentPath' in ' '.join(args): return '/run/systemd/generator/' + self.unit
            if args[0].endswith('findmnt'):
                return json.dumps({'filesystems': [{'uuid': UUID, 'fstype': 'ext4', 'target': backend.destination(UUID), 'maj:min': '253:3'}]})
            if 'start' in args and self.mount_failure: raise RuntimeError('fixture mount failure')
            return ''
        for patcher in (patch.object(backend, 'command', side_effect=commands), patch.object(backend, 'owner', return_value=OWNER),
                        patch.object(backend, 'target_mounts', return_value=[])):
            patcher.start(); self.addCleanup(patcher.stop)

    def enable(self):
        return backend.change('enable', UUID, backend.status()['token'])

    def test_atomic_save_repeat_disable_and_original_backup(self):
        first = self.enable()
        self.assertTrue(first['mounted'])
        self.assertEqual(backend.BACKUP.read_bytes(), ORIGINAL)
        saved = self.fstab.read_bytes()
        self.assertTrue(self.enable()['mounted'])
        self.assertEqual(self.fstab.read_bytes(), saved)
        self.assertEqual(backend.BACKUP.read_bytes(), ORIGINAL)
        self.assertEqual(stat.S_IMODE(backend.BACKUP.stat().st_mode), 0o600)
        backend.change('disable', UUID, backend.status()['token'])
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)
        self.assertFalse(any('umount' in args for args in self.command_calls))

    def test_mount_failure_keeps_saved_configuration_and_reports_partial_success(self):
        self.mount_failure = True
        result = self.enable()
        self.assertTrue(result['saved'])
        self.assertFalse(result['mounted'])
        self.assertIn('fixture mount failure', result['warning'])
        self.assertIn(UUID.encode(), self.fstab.read_bytes())

    def test_wrong_device_cannot_be_reported_as_mounted(self):
        original = backend.command
        def wrong(*args):
            result = original(*args)
            if args[0].endswith('findmnt'):
                return result.replace('253:3', '253:19')
            return result
        with patch.object(backend, 'command', side_effect=wrong):
            result = self.enable()
        self.assertTrue(result['saved'])
        self.assertFalse(result['mounted'])
        self.assertIn('verification', result['warning'])

    def test_kde_mount_is_not_double_mounted(self):
        self.current_device['mountpoints'] = ['/run/media/deck/Games']
        result = self.enable()
        self.assertTrue(result['restart_required'])
        self.assertFalse(result['mounted'])
        self.assertFalse(any('start' in args for args in self.command_calls))

    def test_existing_autofs_does_not_read_disk_contents_or_fail_idempotence(self):
        self.enable()
        target = Path(backend.destination(UUID))
        (target / 'existing-game.txt').write_text('fixture')
        with patch.object(backend, 'target_mounts', return_value=[{'fstype': 'autofs', 'maj:min': '0:42'}]):
            self.assertTrue(self.enable()['mounted'])

    def test_foreign_filesystem_at_target_refused(self):
        with patch.object(backend, 'target_mounts', return_value=[{'fstype': 'ext4', 'maj:min': '253:19'}]), self.assertRaises(RuntimeError):
            self.enable()
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)

    def test_disconnect_still_allows_disabling_saved_mount(self):
        self.enable()
        self.current_device['fstype'] = None
        backend.change('disable', UUID, backend.status()['token'])
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)

    def test_stale_confirmation_cannot_write(self):
        token = backend.status()['token']
        self.current_device['path'] = '/dev/vdb4'
        with self.assertRaises(RuntimeError): backend.change('enable', UUID, token)
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)

    def test_user_symlink_or_nonempty_mount_directory_cannot_be_overwritten(self):
        base = Path(backend.BASE); base.mkdir()
        target = base / UUID
        target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError): self.enable()
        target.unlink(); target.mkdir(); (target / 'keep.txt').write_text('keep')
        with self.assertRaises(RuntimeError): self.enable()
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)
        target.chmod(0o777)
        with self.assertRaises(RuntimeError): self.enable()

    def test_fstab_link_refused_and_backup_failure_leaves_original(self):
        self.fstab.unlink(); self.fstab.symlink_to(self.root / 'missing')
        with self.assertRaises(RuntimeError): self.enable()
        self.fstab.unlink(); self.fstab.write_bytes(ORIGINAL)
        with patch.object(backend, 'atomic', side_effect=OSError('disk full')), self.assertRaises(OSError): self.enable()
        self.assertEqual(self.fstab.read_bytes(), ORIGINAL)

    def test_unmanaged_fstab_conflict_does_not_create_backup(self):
        self.fstab.write_bytes(f'UUID={UUID} /games ext4 defaults 0 0\n'.encode())
        with self.assertRaises(RuntimeError): self.enable()
        self.assertFalse(backend.BACKUP.exists())


if __name__ == '__main__':
    unittest.main()
