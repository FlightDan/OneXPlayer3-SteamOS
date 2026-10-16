import json
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from contextlib import nullcontext
from unittest import mock

from oxp3_maintenance import probe


class ProbeTests(unittest.TestCase):
    def topology(self, label='rootfs-A'):
        disk = {'path': '/dev/nvme0n1', 'type': 'disk', 'tran': 'nvme', 'model': 'Predator GM7',
                'children': [{'path': '/dev/nvme0n1p4', 'type': 'part', 'maj:min': '259:4',
                              'partuuid': '00000000-0000-0000-0000-000000000004', 'partlabel': label},
                             {'path': '/dev/nvme0n1p5', 'type': 'part', 'maj:min': '259:5',
                              'partuuid': '00000000-0000-0000-0000-000000000005', 'partlabel': 'rootfs-B'}]}
        return {'target': '/', 'maj:min': '259:4'}, [disk]

    def test_identity_comes_from_mounted_partition_not_filesystem_label(self):
        mount, disks = self.topology()
        disks[0]['children'][0]['label'] = 'rootfs-B'
        result = probe.identify_root(mount, disks, 'A')
        self.assertEqual(result['label'], 'A')
        self.assertTrue(result['id'].endswith('000000000004'))
        self.assertEqual(result['target_disk']['bus'], 'NVMe')
        with self.assertRaises(probe.ProbeError):
            probe.identify_root(mount, disks, 'B')

    def test_ambiguous_or_mapper_topology_refuses(self):
        mount, disks = self.topology()
        disks[0]['children'][1]['maj:min'] = '259:4'
        with self.assertRaises(probe.ProbeError):
            probe.identify_root(mount, disks)
        with self.assertRaises(probe.ProbeError):
            probe.identify_root({'maj:min': '0:1'}, disks)

    def test_unknown_label_does_not_invent_slot_a(self):
        mount, disks = self.topology('installed-by-other-tool')
        self.assertIsNone(probe.identify_root(mount, disks)['label'])

    def test_btrfs_pseudo_mount_number_requires_verified_block_source(self):
        mount, disks = self.topology()
        mount.update(fstype='btrfs', source='/dev/nvme0n1p4', **{'maj:min': '0:28'})
        with self.assertRaises(probe.ProbeError):
            probe.identify_root(mount, disks)
        verified = {'path': '/dev/nvme0n1p4', 'maj:min': '259:4'}
        result = probe.identify_root(mount, disks, verified_device=verified)
        self.assertEqual(result['device'], '/dev/nvme0n1p4')
        self.assertEqual(result['label'], 'A')
        with self.assertRaises(probe.ProbeError):
            probe.identify_root(mount, disks, verified_device=dict(verified, path='/dev/other'))
        with self.assertRaises(probe.ProbeError):
            probe.identify_root(mount, disks[0]['children'], verified_device=verified)

    def test_canonical_source_requires_real_block_device_under_dev(self):
        fake_os = SimpleNamespace(path=SimpleNamespace(realpath=lambda path: '/dev/nvme0n1p4'),
                                  stat=lambda path: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=123),
                                  major=lambda number: 259, minor=lambda number: 4)
        with mock.patch.object(probe, 'os', fake_os):
            self.assertEqual(probe._canonical_block('/dev/disk/by-partuuid/abcd'),
                             {'path': '/dev/nvme0n1p4', 'maj:min': '259:4'})
            for source in ('/etc/passwd', '/dev/../etc/passwd', '/dev/nvme0n1p4[/@]', 'UUID=arbitrary'):
                with self.subTest(source=source), self.assertRaises(probe.ProbeError):
                    probe._canonical_block(source)
            fake_os.stat = lambda path: SimpleNamespace(st_mode=stat.S_IFREG, st_rdev=123)
            with self.assertRaises(probe.ProbeError):
                probe._canonical_block('/dev/not-a-device')
            fake_os.path.realpath = lambda path: '/outside/device'
            with self.assertRaises(probe.ProbeError):
                probe._canonical_block('/dev/redirected')

    def test_btrfs_kernel_identity_rejects_multiple_missing_or_wrong_devices(self):
        uuid = '11111111-2222-3333-4444-555555555555'
        with tempfile.TemporaryDirectory() as temporary:
            sysfs = Path(temporary)
            device = sysfs / uuid / 'devices/nvme0n1p4'
            device.mkdir(parents=True)
            (device / 'dev').write_text('259:4\n')
            expected = {'path': '/dev/nvme0n1p4', 'maj:min': '259:4'}
            self.assertEqual(probe._single_btrfs_device(uuid, expected, sysfs=sysfs), expected)
            with self.assertRaises(probe.ProbeError):
                probe._single_btrfs_device(uuid, dict(expected, **{'maj:min': '259:9'}), sysfs=sysfs)
            other = sysfs / uuid / 'devices/other'
            other.mkdir()
            with self.assertRaises(probe.ProbeError):
                probe._single_btrfs_device(uuid, expected, sysfs=sysfs)
            other.rmdir()
            missing = sysfs / uuid / 'devinfo/1'
            missing.mkdir(parents=True)
            (missing / 'missing').write_text('1\n')
            with self.assertRaises(probe.ProbeError):
                probe._single_btrfs_device(uuid, expected, sysfs=sysfs)

    def test_live_requests_tree_and_verifies_btrfs_physical_identity(self):
        mount, disks = self.topology()
        mount.update(fstype='btrfs', uuid='11111111-2222-3333-4444-555555555555', source='/dev/nvme0n1p4', **{'maj:min': '0:28'})
        calls = []
        def command(*args):
            calls.append(args)
            if args[0] == 'lsblk':
                return json.dumps({'blockdevices': disks})
            return json.dumps({'filesystems': [mount if args[3] == '/' else {'target': '/home'}]})
        fake_path = SimpleNamespace(exists=lambda: False, read_text=lambda: 'fixture',
                                    stat=lambda: SimpleNamespace(st_uid=0, st_mode=0o755))
        fake_os = SimpleNamespace(name='posix', uname=lambda: SimpleNamespace(release='fixture-kernel'))
        verified = {'path': '/dev/nvme0n1p4', 'maj:min': '259:4'}
        with mock.patch.object(probe, 'os', fake_os), \
             mock.patch.object(probe, 'Path', return_value=fake_path), \
             mock.patch.object(probe, '_canonical_block', return_value=verified), \
             mock.patch.object(probe, '_single_btrfs_device', return_value=verified) as check, \
             mock.patch.object(probe, 'inspect', return_value={}) as inspect:
            probe.live(command)
        self.assertIn('--tree', next(args for args in calls if args[0] == 'lsblk'))
        self.assertIn('TARGET,SOURCE,MAJ:MIN,FSTYPE,UUID', calls[0])
        self.assertEqual(check.call_args.args, (mount['uuid'], verified))
        self.assertEqual(inspect.call_args.kwargs['topology']['label'], 'A')

    def test_inspection_reads_versions_without_running_system_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'etc').mkdir()
            (root / 'etc/os-release').write_text('ID=steamos\nVERSION_ID="3.10"\nBUILD_ID=20260924.1000\n')
            (root / 'etc/passwd').write_text('deck:x:1000:1000::/home/deck:/bin/bash\n')
            metadata = root / 'usr/lib/holo/pacmandb/local/gamescope-3.16.30-1'
            metadata.mkdir(parents=True)
            (metadata / 'desc').write_text('%NAME%\ngamescope\n\n%VERSION%\n3.16.30-1\n')
            topology = probe.identify_root(*self.topology())
            result = probe.inspect(root, kernel=probe.KERNEL,
                                   dmi={'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'},
                                   bios='5.09', topology=topology)
            self.assertTrue(result['compatible'])
            self.assertTrue(result['baseline_supported'])
            self.assertTrue(result['device_supported'])
            self.assertFalse(result['shared_compatible'])
            self.assertEqual(result['packages']['gamescope'], '3.16.30-1')
            self.assertTrue(result['project_updates_only'])
            older = probe.inspect(root, kernel='old-kernel',
                                  dmi=result['dmi'], bios='5.08', topology=topology)
            self.assertTrue(older['device_supported'])
            self.assertFalse(older['baseline_supported'])
            self.assertFalse(older['compatible'])

    def test_tool_managed_slot_packages_do_not_block_the_next_project_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib/modules' / probe.KERNEL).mkdir(parents=True)
            (root / 'usr/lib/os-release').write_text('ID=steamos\nVERSION_ID=3.10\nBUILD_ID=20260924.1000\n')
            system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]},
                      'packages': {'gamescope': '3.16.30-1', 'waydroid': '1.5.0-1'}}
            def command(*args):
                return 'ext4' if args[0] == 'blkid' else ''
            with mock.patch.object(probe.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(probe.tempfile, 'TemporaryDirectory', return_value=nullcontext(temporary)), \
                 mock.patch.object(probe, 'packages', return_value={'gamescope': '3.16.30-1'}):
                self.assertFalse(probe.verify_shared(system, command))
                system['verified_slot_only_packages'] = ['waydroid']
                self.assertTrue(probe.verify_shared(system, command))

    def test_portable_shared_check_accepts_other_steamos_without_certifying_patches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib').mkdir(parents=True)
            release = root / 'usr/lib/os-release'
            release.write_text('ID=steamos\nVERSION_ID=3.7\nBUILD_ID=older\n')
            system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]},
                      'packages': {}}
            calls = []
            def command(*args):
                calls.append(args)
                return 'ext4' if args[0] == 'blkid' else ''
            with mock.patch.object(probe.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(probe.tempfile, 'TemporaryDirectory', return_value=nullcontext(temporary)):
                self.assertTrue(probe.verify_shared_os(system, command))
                self.assertFalse(probe.verify_shared(system, command))
                release.write_text('ID=arch\n')
                self.assertFalse(probe.verify_shared_os(system, command))
            mounts = [args for args in calls if args[0] == 'mount']
            self.assertTrue(mounts)
            self.assertTrue(all('ro,noload,nodev,nosuid,noexec' in args for args in mounts))
            self.assertEqual(len(mounts), len([args for args in calls if args[0] == 'umount']))

    def test_portable_shared_check_requires_privilege_for_inactive_slots(self):
        system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]}}
        with mock.patch.object(probe.os, 'geteuid', return_value=1000, create=True):
            self.assertFalse(probe.verify_shared_os(system, mock.Mock(side_effect=AssertionError('mounted'))))

    def test_inactive_regular_etc_build_metadata_takes_precedence_over_generic_usr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'etc').mkdir()
            (root / 'etc/os-release').write_text('ID=steamos\nVERSION_ID=3.10\nBUILD_ID=20260924.1000\n')
            (root / 'usr/lib/modules' / probe.KERNEL).mkdir(parents=True)
            (root / 'usr/lib/os-release').write_text('ID=steamos\nNAME=SteamOS\n')
            system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]},
                      'packages': {'gamescope': '3.16.30-1'}}
            def command(*args):
                return 'ext4' if args[0] == 'blkid' else ''
            with mock.patch.object(probe.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(probe.tempfile, 'TemporaryDirectory', return_value=nullcontext(temporary)), \
                 mock.patch.object(probe, 'packages', return_value=dict(system['packages'])):
                self.assertTrue(probe.verify_shared(system, command))
                (root / 'etc/os-release').write_text('ID=steamos\nVERSION_ID=3.9\nBUILD_ID=other\n')
                self.assertFalse(probe.verify_shared(system, command))
            self.assertEqual(probe._inactive_os_release(root)['VERSION_ID'], '3.9')

    def test_unsafe_etc_is_skipped_without_following_link_to_running_system(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib').mkdir(parents=True)
            (root / 'usr/lib/os-release').write_text('ID=steamos\n')
            original = probe._checked_path
            checked = []
            def checked_path(root, relative):
                checked.append(relative)
                if relative == 'etc/os-release':
                    raise probe.ProbeError('Unsafe image metadata symlink')
                return original(root, relative)
            with mock.patch.object(probe, '_checked_path', side_effect=checked_path):
                self.assertEqual(probe._inactive_os_release(root), {'ID': 'steamos'})
            self.assertEqual(checked, ['etc/os-release', 'usr/lib/os-release'])

    def test_inactive_btrfs_mount_never_replays_log_and_always_unmounts(self):
        uuid = '11111111-2222-3333-4444-555555555555'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/lib').mkdir(parents=True)
            (root / 'usr/lib/os-release').write_text('ID=steamos\nVERSION_ID=3.7\n')
            system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]}}
            calls = []
            def command(*args):
                calls.append(args)
                if args[0] == 'blkid':
                    return 'btrfs'
                if args[0] == 'btrfs':
                    return 'fsid\t' + uuid + '\nnum_devices\t1\n'
                return ''
            with mock.patch.object(probe.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(probe.tempfile, 'TemporaryDirectory', return_value=nullcontext(temporary)), \
                 mock.patch.object(probe, '_canonical_block', return_value={'path': '/dev/test', 'maj:min': '259:5'}), \
                 mock.patch.object(probe, '_single_btrfs_device') as check:
                self.assertTrue(probe.verify_shared_os(system, command))
                check.side_effect = probe.ProbeError('changed or multiple device filesystem')
                self.assertFalse(probe.verify_shared_os(system, command))
            mounts = [args for args in calls if args[0] == 'mount']
            self.assertEqual(len(mounts), 2)
            self.assertTrue(all('ro,rescue=nologreplay,nodev,nosuid,noexec,subvolid=5' in args for args in mounts))
            self.assertEqual(len([args for args in calls if args[0] == 'umount']), 2)

    def test_multidevice_btrfs_is_rejected_before_mounting(self):
        system = {'slot': {'other_slots': [{'partuuid': '00000000-0000-0000-0000-000000000005'}]}}
        calls = []
        def command(*args):
            calls.append(args)
            return 'btrfs' if args[0] == 'blkid' else 'fsid\t11111111-2222-3333-4444-555555555555\nnum_devices\t2\n'
        with mock.patch.object(probe.os, 'geteuid', return_value=0, create=True), \
             mock.patch.object(probe, '_canonical_block', return_value={'path': '/dev/test', 'maj:min': '259:5'}):
            self.assertFalse(probe.verify_shared_os(system, command))
        self.assertFalse(any(args[0] == 'mount' for args in calls))

    def test_package_metadata_symlink_is_never_followed_into_live_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, outside = Path(temporary) / 'root', Path(temporary) / 'outside'
            (root / 'usr/lib/holo/pacmandb').mkdir(parents=True)
            outside.mkdir()
            try:
                (root / 'usr/lib/holo/pacmandb/local').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaises(probe.ProbeError):
                probe.packages(root)


if __name__ == '__main__':
    unittest.main()
