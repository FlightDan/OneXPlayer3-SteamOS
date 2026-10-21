"""Runtime directory ownership is durable and never inferred from emptiness."""
import copy
import contextlib
import os
from pathlib import Path
import tempfile
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch, mock_open, MagicMock

from oxp3_maintenance.transactions import Store, TransactionError
from oxp3_maintenance import runtime_directories as directories


PREFIX = 'opt/oxp3-desktop-gamma22/6.7.3-1.6'
PROGRAM = PREFIX + '/bin/program'
DOC = PREFIX + '/share/doc/HTML/en/index.html'


class Interrupted(Exception):
    pass


def spec(data, component='desktop-hdr'):
    return dict(data=data, component=component)


class RuntimeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'; self.root.mkdir()
        self.store = Store(self.root, Path(self.temp.name) / 'state', enforce_owner=False)
        # The independent HDR restore-guard suite exercises that boundary.
        guard = patch.object(self.store, '_guard_hdr_restore')
        guard.start(); self.addCleanup(guard.stop)
        self.runtime = self.root / PREFIX
        (self.runtime / 'bin').mkdir(parents=True)
        (self.runtime / 'legitimate-empty').mkdir()
        (self.root / PROGRAM).write_bytes(b'legacy program')
        self.store.apply({'etc/test-engine': spec(b'engine', '_maintenance')},
                         {'version': 'base'}, ['_maintenance'], 'B')
        self.original = self.tree()
        self.adopt = {PROGRAM: {'component': 'desktop-hdr', 'original': {'exists': False},
                               'applied': self.store._read(PROGRAM)}}

    def tree(self):
        return {p.relative_to(self.runtime).as_posix():
                ('directory' if p.is_dir() else p.read_bytes())
                for p in (self.runtime, *self.runtime.rglob('*'))}

    def apply(self):
        return self.store.apply({PROGRAM: spec(b'new program'), DOC: spec(b'new documentation')},
                                {'version': 'new'}, ['desktop-hdr'], 'B', adopt=self.adopt)

    def test_adopt_update_rollback_reapply_preserves_original_empty_directories(self):
        self.apply()
        owned = self.store._index()['slots']['B']['current']['runtime_directories']
        self.assertEqual(set(owned), {PREFIX + '/' + s for s in
                         ('share', 'share/doc', 'share/doc/HTML', 'share/doc/HTML/en')})
        self.store.rollback('B')
        self.assertEqual(self.tree(), self.original)
        self.assertTrue((self.runtime / 'legitimate-empty').is_dir())
        self.apply()
        self.assertEqual((self.root / DOC).read_bytes(), b'new documentation')

    def test_first_install_with_entire_opt_ancestor_missing(self):
        root = Path(self.temp.name) / 'empty-root'; root.mkdir()
        store = Store(root, Path(self.temp.name) / 'first-install-state', enforce_owner=False)
        self.assertFalse((root / 'opt').exists())
        target = 'opt/oxp3-opti2xmx/20261005/bin/program'
        store.apply({target: spec(b'first installation', 'opti2xmx')},
                    {'version': 'first'}, ['opti2xmx'], 'B')
        self.assertEqual((root / target).read_bytes(), b'first installation')
        self.assertTrue(store._index()['slots']['B']['current']['runtime_directories'])
        store.restore('B', ['opti2xmx'])
        self.assertFalse((root / 'opt/oxp3-opti2xmx/20261005').exists())
        # Ancestors outside the fixed runtime scope are never claimed or pruned.
        self.assertTrue((root / 'opt/oxp3-opti2xmx').is_dir())
        with self.assertRaises(TransactionError):
            store._path('./.directory-probe')

    def test_restore_removes_only_owned_new_empty_directories(self):
        self.apply()
        self.store.restore('B', ['desktop-hdr'])
        self.assertFalse((self.runtime / 'share').exists())
        self.assertTrue((self.runtime / 'bin').is_dir())
        self.assertTrue((self.runtime / 'legitimate-empty').is_dir())

    def test_crash_after_receipt_recovers_and_can_later_roll_back(self):
        with patch.object(self.store, '_after_runtime_directory_receipt',
                          side_effect=Interrupted('receipt saved')):
            with self.assertRaises(Interrupted): self.apply()
        self.assertTrue(self.store.recover('B')['recovered'])
        self.store.rollback('B')
        self.assertEqual(self.tree(), self.original)
        self.assertFalse(self.store.recover('B')['recovered'])

    def test_crash_before_receipt_is_not_claimed_even_when_directory_is_empty(self):
        with patch.object(self.store, '_after_runtime_directory_create',
                          side_effect=Interrupted('mkdir without receipt')):
            with self.assertRaises(Interrupted): self.apply()
        pending = self.store._state_read('pending.json')
        self.assertTrue(all(value is None for value in pending['runtime_directory_intents'].values()))
        for _ in range(2):
            with self.assertRaisesRegex(TransactionError, 'Uncertain runtime directory creation'):
                self.store.recover('B')
        self.assertTrue((self.runtime / 'share').is_dir())
        self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')
        self.assertTrue((self.store.state / 'pending.json').is_file())

    def test_crash_after_file_write_preserves_directory_receipts(self):
        def interrupt(path):
            if path == DOC: raise Interrupted('file committed')
        with patch.object(self.store, '_after_write', side_effect=interrupt):
            with self.assertRaises(Interrupted): self.apply()
        self.store.recover('B')
        self.store.rollback('B')
        self.assertEqual(self.tree(), self.original)

    def test_crash_during_deepest_first_cleanup_is_idempotent(self):
        self.apply()
        with patch.object(self.store, '_after_runtime_directory_remove',
                          side_effect=Interrupted('rmdir completed')):
            with self.assertRaises(Interrupted): self.store.rollback('B')
        self.assertTrue(self.store.recover('B')['recovered'])
        self.assertFalse(self.store.recover('B')['recovered'])
        self.assertEqual(self.tree(), self.original)

    def test_unknown_file_or_directory_blocks_before_any_file_restoration(self):
        for directory in (False, True):
            with self.subTest(directory=directory):
                self.apply()
                unknown = self.runtime / 'share' / 'unknown'
                unknown.mkdir() if directory else unknown.write_bytes(b'unknown data')
                with self.assertRaisesRegex(TransactionError, 'Unknown (file|directory)'):
                    self.store.rollback('B')
                self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')
                self.assertEqual((self.root / DOC).read_bytes(), b'new documentation')
                unknown.rmdir() if directory else unknown.unlink()  # Fixture cleanup only.
                self.store.recover('B')
                self.assertEqual(self.tree(), self.original)

    def test_changed_directory_identity_blocks_before_any_restoration(self):
        self.apply()
        # Keep the files intact while replacing just the root of the new tree.
        share = self.runtime / 'share'; moved = self.runtime / 'moved-share'
        share.rename(moved); share.mkdir()
        for child in list(moved.iterdir()): child.rename(share / child.name)
        moved.rmdir()
        with self.assertRaisesRegex(TransactionError, 'identity changed'):
            self.store.rollback('B')
        self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')

    def test_receipts_outside_fixed_runtime_roots_are_rejected(self):
        self.apply()
        index = self.store._index()
        receipt = next(iter(index['slots']['B']['current']['runtime_directories'].values()))
        for path in ('etc', PREFIX + '/../other', 'opt/other', '/opt/other'):
            with self.subTest(path=path), self.assertRaises(TransactionError):
                directories.validate(self.store, {path: copy.deepcopy(receipt)})

    def test_other_slot_files_prevent_removing_shared_owned_directories(self):
        self.apply()
        other = PREFIX + '/share/doc/HTML/en/other.html'
        self.store.apply({other: spec(b'other slot')}, {'version': 'other'}, ['desktop-hdr'], 'A')
        self.store.restore('B', ['desktop-hdr'])
        self.assertEqual((self.root / other).read_bytes(), b'other slot')
        self.assertTrue((self.runtime / 'share').is_dir())
        self.store.restore('A', ['desktop-hdr'])
        self.assertFalse((self.runtime / 'share').exists())
        for record in self.store._index()['slots'].values():
            self.assertNotIn('runtime_directories', record['current'])
        self.store.apply({DOC: spec(b'reapply')}, {'version': 'reapply'}, ['desktop-hdr'], 'B')
        self.assertEqual((self.root / DOC).read_bytes(), b'reapply')

    def test_other_slot_first_restore_also_leaves_last_owner_able_to_clean(self):
        self.apply()
        other = PREFIX + '/share/doc/HTML/en/other.html'
        self.store.apply({other: spec(b'other slot')}, {'version': 'other'}, ['desktop-hdr'], 'A')
        self.store.restore('A', ['desktop-hdr'])
        self.assertEqual((self.root / DOC).read_bytes(), b'new documentation')
        self.store.restore('B', ['desktop-hdr'])
        self.assertFalse((self.runtime / 'share').exists())
        self.assertTrue((self.runtime / 'legitimate-empty').is_dir())
        for record in self.store._index()['slots'].values():
            self.assertNotIn('runtime_directories', record['current'])

    def test_apply_abort_cleans_owned_directories_and_keeps_the_engine(self):
        source = self.store.status()['slots']['B']['current']['id']
        applied = self.apply()
        self.store.abort_apply('B', generation=applied['generation'], source_generation=source)
        self.assertEqual(self.tree(), self.original)
        self.assertEqual((self.root / 'etc/test-engine').read_bytes(), b'engine')


    def test_large_pending_is_written_once_and_receipts_are_small(self):
        # Real index_after is >1 GiB. A representative large unrelated metadata
        # value makes accidental per-mkdir rewriting measurable without that RAM.
        files = {PREFIX + '/share/doc/d' + str(i) + '/index.html': spec(b'doc') for i in range(24)}
        writes = []
        original = self.store._state_write
        def count(name, value):
            writes.append((name, len(json.dumps(value))))
            return original(name, value)
        with patch.object(self.store, '_state_write', side_effect=count):
            self.store.apply(files, {'version': 'large', 'description': 'x' * 250000}, ['desktop-hdr'], 'B')
        self.assertEqual(sum(name == 'pending.json' for name, _ in writes), 1)
        self.assertEqual(sum(name == 'index.json' for name, _ in writes), 1)
        receipts = [size for name, size in writes if name.startswith('runtime-directories-')]
        self.assertEqual(len(receipts), 26)
        self.assertLess(max(receipts), 16000)
        self.assertEqual(list(self.store.state.glob('runtime-directories-*.json')), [])

    def test_journal_cannot_be_reused_across_transactions_or_slots(self):
        with patch.object(self.store, '_after_runtime_directory_receipt', side_effect=Interrupted):
            with self.assertRaises(Interrupted): self.apply()
        pending = self.store._state_read('pending.json')
        name = 'runtime-directories-' + pending['runtime_directory_journal'] + '.json'
        original = self.store._state_read(name)
        for field, value in (('transaction', 'a' * 32), ('slot', 'A'), ('generation', 999)):
            with self.subTest(field=field):
                changed = copy.deepcopy(original); changed[field] = value
                self.store._state_write(name, changed)
                with self.assertRaisesRegex(TransactionError, 'another transaction'):
                    self.store.recover('B')
        changed = copy.deepcopy(original)
        receipt = next(iter(changed['receipts'].values()))
        changed['receipts'][PREFIX + '/unplanned'] = receipt
        self.store._state_write(name, changed)
        with self.assertRaisesRegex(TransactionError, 'Unplanned'):
            self.store.recover('B')
        self.store._state_write(name, original)
        self.assertTrue(self.store.recover('B')['recovered'])
        self.store.rollback('B')
        self.assertEqual(self.tree(), self.original)

    def test_guard_cannot_replace_owned_ancestor_before_first_file_restore(self):
        self.apply()
        def replace(*_args):
            share = self.runtime / 'share'; moved = self.runtime / 'moved-share'
            share.rename(moved); share.mkdir()
            for child in list(moved.iterdir()): child.rename(share / child.name)
            moved.rmdir()
        with patch.object(self.store, '_guard_hdr_restore', side_effect=replace):
            with self.assertRaisesRegex(TransactionError, 'identity changed'):
                self.store.rollback('B')
        self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')
        self.assertEqual((self.root / DOC).read_bytes(), b'new documentation')

    def test_external_planned_directory_after_preflight_is_not_claimed(self):
        original_write = self.store._write
        def inject(path, snapshot, **kwargs):
            if path == DOC:
                (self.runtime / 'share').mkdir()  # External actor, after final preflight.
            return original_write(path, snapshot, **kwargs)
        with patch.object(self.store, '_write', side_effect=inject):
            with self.assertRaisesRegex(TransactionError, 'Uncertain runtime directory creation'):
                self.apply()
        self.assertFalse((self.root / DOC).exists())
        self.assertTrue((self.runtime / 'share').is_dir())
        self.assertEqual(list(self.store.state.glob('runtime-directories-*.json')), [])
        # The original pending remains fail closed; emptiness grants no claim.
        with self.assertRaisesRegex(TransactionError, 'Uncertain runtime directory creation'):
            self.store.recover('B')

    def test_live_mount_device_number_is_not_persisted_in_identity(self):
        info = SimpleNamespace(st_dev=123, st_ino=91, st_mode=0o40755, st_uid=0, st_gid=0)
        with patch.object(directories, 'filesystem_identity', return_value='ext4:verified-uuid:/offload/opt'):
            first = directories.identity(self.store, info, 'fixture')
            info.st_dev = 456  # Same filesystem mounted after a different boot.
            second = directories.identity(self.store, info, 'fixture')
            self.assertEqual(first, second)
            self.assertNotIn('dev', first)
            info.st_ino += 1
            self.assertNotEqual(first, directories.identity(self.store, info, 'fixture'))

    def test_changed_stable_filesystem_identity_is_rejected_before_writes(self):
        with patch.object(directories, 'filesystem_identity', return_value='ext4:uuid-one:/opt'):
            self.apply()
        with patch.object(directories, 'filesystem_identity', return_value='ext4:uuid-two:/opt'):
            with self.assertRaisesRegex(TransactionError, 'identity changed'):
                self.store.rollback('B')
        self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')


    def test_production_mount_uuid_and_bind_root_survive_device_renumbering(self):
        # Exercise the real production parser/probe without relying on the host's
        # disk layout or weakening enforce_owner on the method under test.
        device = SimpleNamespace(st_mode=0o60660, st_rdev=2049, st_ino=5)
        info = SimpleNamespace(st_dev=2049)
        device_path = MagicMock()
        device_path.__str__.return_value = '/dev/test'
        device_path.stat.return_value = device
        production = SimpleNamespace(enforce_owner=True, _runtime_filesystem_cache={},
                                     _directory_error=TransactionError)
        mount = '31 22 8:1 /offload/opt /opt rw - ext4 /dev/test rw\n'
        probe = SimpleNamespace(stdout=b'UUID=ddf6005f-7f79-4eca-a06e-fe1def188876\nTYPE=ext4\n')
        with patch.object(directories.os, 'readlink', return_value='/opt/runtime/share'), \
                patch('builtins.open', mock_open(read_data=mount)), \
                patch.object(directories.Path, 'resolve', return_value=device_path), \
                patch.object(directories.os, 'major', return_value=8, create=True), \
                patch.object(directories.os, 'minor', return_value=1, create=True), \
                patch.object(directories.subprocess, 'run', return_value=probe) as run:
            first = directories.filesystem_identity(production, 99, info)
            self.assertEqual(first, 'ext4:ddf6005f-7f79-4eca-a06e-fe1def188876:/offload/opt')
            directories.filesystem_identity(production, 99, info)
            self.assertEqual(run.call_count, 1)  # Per-transaction physical device cache.
            args, kwargs = run.call_args
            self.assertEqual(args[0], ['/usr/bin/blkid', '-p', '-o', 'export', '--', '/dev/test'])
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['timeout'], 5)
            info.st_dev = device.st_rdev = 4097
            # Current dev/mount pair changes together after reboot; persisted
            # identity remains the disk UUID plus bind/subvolume root.
            with patch.object(directories.os, 'major', return_value=16), \
                    patch('builtins.open', mock_open(read_data=mount.replace('8:1', '16:1'))):
                self.assertEqual(directories.filesystem_identity(production, 99, info), first)
            device.st_rdev = 999
            with self.assertRaisesRegex(TransactionError, 'stable runtime mount identity'):
                directories.filesystem_identity(production, 99, info)

    def test_mount_escape_parser_preserves_kernel_bind_root(self):
        self.assertEqual(directories._unescape(r'/offload/space\040name'), '/offload/space name')


    @contextlib.contextmanager
    def production_mount(self, *, kind='ext4', source='/dev/test', resolved='/dev/test',
                         mount_root='/offload/opt', live_dev=(8, 1), physical_dev=2049,
                         probe_type=None, probe_uuid='ddf6005f-7f79-4eca-a06e-fe1def188876'):
        production = SimpleNamespace(enforce_owner=True, _runtime_filesystem_cache={},
                                     _directory_error=TransactionError)
        info = SimpleNamespace(st_dev=2049)
        device = SimpleNamespace(st_mode=0o60660, st_rdev=physical_dev, st_ino=5)
        device_path = MagicMock()
        device_path.__str__.return_value = resolved
        device_path.stat.return_value = device
        mount = ('31 22 8:1 ' + mount_root + ' /opt rw - ' + kind + ' ' + source + ' rw\n')
        output = ('UUID=' + probe_uuid + '\nTYPE=' + (probe_type or kind) + '\n').encode('ascii')
        with patch.object(directories.os, 'readlink', return_value='/opt/runtime/share'), \
                patch('builtins.open', mock_open(read_data=mount)), \
                patch.object(directories.Path, 'resolve', return_value=device_path), \
                patch.object(directories.os, 'major', return_value=live_dev[0], create=True), \
                patch.object(directories.os, 'minor', return_value=live_dev[1], create=True), \
                patch.object(directories.subprocess, 'run', return_value=SimpleNamespace(stdout=output)) as run:
            yield production, info, device, run

    def test_btrfs_anonymous_live_device_uses_physical_filesystem_uuid(self):
        # Unlike ext4, Btrfs live st_dev is an anonymous subvolume number and
        # must not be equated with the physical device rdev.
        with self.production_mount(kind='btrfs', physical_dev=999, mount_root='/@opt') as (store, info, _, run):
            self.assertEqual(directories.filesystem_identity(store, 99, info),
                             'btrfs:ddf6005f-7f79-4eca-a06e-fe1def188876:/@opt')
            self.assertEqual(run.call_count, 1)
        with self.production_mount(mount_root='/other-bind-root') as (store, info, _, _):
            self.assertTrue(directories.filesystem_identity(store, 99, info).endswith(':/other-bind-root'))

    def test_production_rejects_unverified_filesystem_sources(self):
        cases = ({'physical_dev': 999}, {'live_dev': (9, 1)}, {'kind': 'overlay'},
                 {'source': '/tmp/device'}, {'resolved': '/tmp/escaped-device'},
                 {'probe_type': 'xfs'}, {'probe_uuid': ''}, {'probe_uuid': 'not-a-uuid'},
                 {'probe_uuid': '-' * 36})
        for parameters in cases:
            with self.subTest(parameters=parameters), self.production_mount(**parameters) as (store, info, _, _):
                with self.assertRaisesRegex(TransactionError, 'stable runtime mount identity'):
                    directories.filesystem_identity(store, 99, info)

    def test_mount_probe_cache_is_reset_at_each_transaction_boundary(self):
        self.store._runtime_filesystem_cache['old-transaction'] = 'untrusted-for-next'
        self.apply()
        self.assertNotIn('old-transaction', self.store._runtime_filesystem_cache)
        self.store._runtime_filesystem_cache['finished-transaction'] = 'untrusted-for-next'
        self.store.rollback('B')
        self.assertNotIn('finished-transaction', self.store._runtime_filesystem_cache)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_symlink_in_owned_tree_is_rejected_without_deleting_targets(self):
        self.apply()
        link = self.runtime / 'share' / 'link'
        link.symlink_to(self.runtime / 'bin', target_is_directory=True)
        with self.assertRaisesRegex(TransactionError, 'Unknown file or link'):
            self.store.rollback('B')
        self.assertTrue(link.is_symlink())
        self.assertEqual((self.root / PROGRAM).read_bytes(), b'new program')


if __name__ == '__main__':
    unittest.main()
