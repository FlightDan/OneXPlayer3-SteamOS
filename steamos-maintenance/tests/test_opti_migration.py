"""Narrow Opti runtime split: retained bytes, originals, ownership and rollback."""
import base64
import copy
import json
import shutil
import stat
import unittest
from unittest import mock

from oxp3_maintenance import adoption
from oxp3_maintenance.opti_migration import PLUGIN, RUNTIME, RUNTIME_CONFIG, RUNTIME_PREFIX
from oxp3_maintenance.transactions import TransactionError
import test_transactions


class OptiMigrationTests(unittest.TestCase):
    setUp = test_transactions.Transactions.setUp
    tearDown = test_transactions.Transactions.tearDown
    write = test_transactions.Transactions.write
    apply = test_transactions.Transactions.apply
    binary = RUNTIME_PREFIX + 'bin/tool'
    plugin = 'var/lib/oxp3-installer/decky/runtime/plugins/Opti2XMX/main.py'

    def spec(self, data=b'runtime', component=PLUGIN, *, config=False):
        return test_transactions.spec(data, component=component, mutable=config, user=config)

    def old_files(self):
        return {self.binary: self.spec(), RUNTIME_CONFIG: self.spec(b'config', config=True),
                self.plugin: self.spec(b'old plugin')}

    def current(self, slot='A'):
        return self.store._index()['slots'][slot]['current']

    def test_plugin_only_update_keeps_legacy_runtime_and_originals(self):
        self.write(self.binary, b'preproject executable')
        self.apply(self.old_files(), selected=[PLUGIN])
        before = copy.deepcopy(self.store._index()['originals'])
        self.apply({self.plugin: self.spec(b'new plugin')}, '2', selected=[PLUGIN])
        self.assertEqual((self.root / self.binary).read_bytes(), b'runtime')
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'config')
        self.assertEqual(self.current()['paths'][self.binary]['component'], PLUGIN)
        self.assertEqual(self.store._index()['originals'], before)
        self.store.rollback('A')
        self.assertEqual((self.root / self.plugin).read_bytes(), b'old plugin')
        self.store.restore('A', [PLUGIN])
        self.assertEqual((self.root / self.binary).read_bytes(), b'preproject executable')

    def test_explicit_runtime_transfer_preserves_originals_and_can_rollback(self):
        self.write(self.binary, b'preproject executable')
        self.apply(self.old_files(), selected=[PLUGIN])
        original = copy.deepcopy(self.store._index()['originals'])
        files = {self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME),
                 RUNTIME_CONFIG: self.spec(b'new config', RUNTIME, config=True)}
        self.apply(files, '2', selected=[PLUGIN, RUNTIME])
        self.assertEqual(self.current()['paths'][self.binary]['component'], RUNTIME)
        self.assertEqual(self.store._index()['originals'], original)
        self.store.rollback('A')
        self.assertEqual(self.current()['paths'][self.binary]['component'], PLUGIN)
        self.assertEqual((self.root / self.binary).read_bytes(), b'runtime')
        self.store.rollback('A')
        self.store.restore('A', [PLUGIN])
        self.assertTrue((self.root / self.binary).is_file())
        self.store.restore('A', [RUNTIME])
        self.assertEqual((self.root / self.binary).read_bytes(), b'preproject executable')

    def test_edited_runtime_config_survives_transfer_with_new_owner(self):
        self.apply(self.old_files(), selected=[PLUGIN])
        self.write(RUNTIME_CONFIG, b'user setting')
        self.apply({self.binary: self.spec(b'new runtime', RUNTIME),
                    RUNTIME_CONFIG: self.spec(b'new config', RUNTIME, config=True)},
                   '2', selected=[PLUGIN, RUNTIME])
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user setting')
        self.assertEqual(self.current()['paths'][RUNTIME_CONFIG]['component'], RUNTIME)
        self.store.restore('A', [PLUGIN])
        self.assertTrue((self.root / RUNTIME_CONFIG).exists())
        self.store.restore('A', [RUNTIME])
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user setting')

    def test_rollback_of_edited_runtime_config_restores_owner_and_plugin_restore_scope(self):
        self.write(RUNTIME_CONFIG, b'preproject config')
        self.apply(self.old_files(), selected=[PLUGIN])
        originals = copy.deepcopy(self.store._index()['originals'])
        self.write(RUNTIME_CONFIG, b'user setting')
        self.apply({self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME),
                    RUNTIME_CONFIG: self.spec(b'new config', RUNTIME, config=True)},
                   '2', selected=[PLUGIN, RUNTIME])
        for expected_owner in (PLUGIN, RUNTIME, PLUGIN):
            self.store.rollback('A')
            self.assertEqual(self.current()['paths'][RUNTIME_CONFIG]['component'], expected_owner)
            self.assertIn(expected_owner, self.current()['selected'])
            self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user setting')
            self.assertEqual(self.store._index()['originals'], originals)
        self.store.restore('A', [PLUGIN])
        self.assertNotIn(RUNTIME_CONFIG, self.current()['paths'])
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user setting')

    def test_transfer_requires_explicit_runtime_and_exact_legacy_scope(self):
        for path, owner, selection in (
                (self.binary, PLUGIN, [PLUGIN]),
                (self.plugin, PLUGIN, [PLUGIN, RUNTIME]),
                ('opt/oxp3-opti2xmx/20261006/bin/tool', PLUGIN, [PLUGIN, RUNTIME]),
                (self.binary, 'unrelated', [PLUGIN, RUNTIME])):
            with self.subTest(path=path, owner=owner):
                # Each case uses a fresh state and filesystem target.
                state = self.state / str(len(list(self.state.glob('*'))) if self.state.exists() else 0)
                store = type(self.store)(self.root, state, enforce_owner=False)
                store.apply({path: self.spec(component=owner)}, {'version': '1'}, [owner], 'A')
                with self.assertRaisesRegex(TransactionError, 'transfer'):
                    store.apply({path: self.spec(b'changed', RUNTIME)}, {'version': '2'}, selection, 'A')
                self.assertIsNone(store.status()['pending'])
                self.assertEqual((self.root / path).read_bytes(), b'runtime')

    def test_changed_runtime_cannot_overwrite_another_slots_owner(self):
        self.apply(self.old_files(), selected=[PLUGIN])
        self.apply(self.old_files(), slot='B', selected=[PLUGIN])
        with self.assertRaisesRegex(TransactionError, 'owned by slot B'):
            self.apply({self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME),
                        RUNTIME_CONFIG: self.spec(b'config', RUNTIME, config=True)},
                       '2', selected=[PLUGIN, RUNTIME])
        self.assertEqual((self.root / self.plugin).read_bytes(), b'old plugin')
        self.assertEqual(self.current()['paths'][self.binary]['component'], PLUGIN)
        self.assertIsNone(self.store.status()['pending'])

    def test_missing_managed_original_blocks_before_plugin_write(self):
        self.apply(self.old_files(), selected=[PLUGIN])
        index = self.store._index()
        del index['originals'][self.store._scope('A', self.binary)]
        self.store._state_write('index.json', index)
        with self.assertRaisesRegex(TransactionError, 'original is missing'):
            self.apply({self.plugin: self.spec(b'new plugin')}, '2', selected=[PLUGIN])
        self.assertEqual((self.root / self.plugin).read_bytes(), b'old plugin')
        self.assertIsNone(self.store.status()['pending'])

    def test_runtime_transfer_recovery_keeps_original_and_new_owner(self):
        self.write(self.binary, b'preproject executable')
        self.apply(self.old_files(), selected=[PLUGIN])
        def power_loss(path):
            raise RuntimeError('power loss')
        self.store._after_write = power_loss
        with self.assertRaisesRegex(RuntimeError, 'power loss'):
            self.apply({self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME),
                        RUNTIME_CONFIG: self.spec(b'new config', RUNTIME, config=True)},
                       '2', selected=[PLUGIN, RUNTIME])
        fresh = type(self.store)(self.root, self.state, uid=self.store.uid, gid=self.store.gid, enforce_owner=False)
        fresh.recover('A')
        self.assertEqual(fresh._index()['slots']['A']['current']['paths'][self.binary]['component'], RUNTIME)
        fresh.restore('A', [RUNTIME])
        self.assertEqual((self.root / self.binary).read_bytes(), b'preproject executable')

    def legacy_runtime(self):
        """Produce the old protected directory journal, including original bytes."""
        destination = self.root / RUNTIME_PREFIX.rstrip('/')
        self.write(self.binary, b'legacy runtime')
        state = destination.parent / '.installer-state'
        state.mkdir(mode=0o700)
        shutil.copytree(destination, state / 'installed')
        original = state / 'original-reference'
        (original / 'bin').mkdir(parents=True)
        (original / 'bin/tool').write_bytes(b'preproject executable')
        shutil.copytree(original, state / 'original')
        def inventory(root):
            return {path.relative_to(root).as_posix(): {
                'directory': path.is_dir(), 'mode': stat.S_IMODE(path.stat().st_mode),
                'uid': path.stat().st_uid, 'gid': path.stat().st_gid}
                for path in [root, *root.rglob('*')]}
        metadata = {'destination': RUNTIME_PREFIX.rstrip('/'), 'phase': 'installed',
                    'original_exists': True, 'original_metadata': inventory(original),
                    'installed_metadata': inventory(destination)}
        (state / 'state.json').write_text(json.dumps(metadata))
        return state

    def legacy_originals(self):
        probe = {'slot': {'label': 'A'}, 'uid': self.store.uid, 'gid': self.store.gid}
        # Windows lacks POSIX protection metadata; production checks remain on.
        with mock.patch.object(adoption, '_trusted'):
            return adoption.validate_current(self.root,
                adoption.import_originals(self.root, probe, [PLUGIN]), probe)

    def legacy_config(self):
        path = self.write(RUNTIME_CONFIG, b'user runtime config')
        info = path.stat()
        original = {'exists': True, 'data': base64.b64encode(b'preproject config').decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        state = {'phase': 'installed', 'allowed': [RUNTIME_CONFIG],
                 'original': {RUNTIME_CONFIG: original},
                 'applied': {RUNTIME_CONFIG: base64.b64encode(b'legacy config').decode()}}
        self.write('home/.oxp3-installer/integration/A/opti2xmx/state.json', json.dumps(state).encode())

    def test_legacy_plugin_only_adopts_retained_runtime_true_originals(self):
        self.legacy_runtime()
        originals = self.legacy_originals()
        self.apply({self.plugin: self.spec(b'new plugin')}, selected=[PLUGIN], adopt=originals)
        self.assertEqual((self.root / self.binary).read_bytes(), b'legacy runtime')
        self.assertEqual(self.current()['paths'][self.binary]['component'], PLUGIN)
        self.store.restore('A', [PLUGIN])
        self.assertEqual((self.root / self.binary).read_bytes(), b'preproject executable')

    def test_legacy_direct_runtime_upgrade_preserves_original_for_restore(self):
        self.legacy_runtime()
        self.apply({self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME)},
                   selected=[PLUGIN, RUNTIME], adopt=self.legacy_originals())
        self.assertEqual(self.current()['paths'][self.binary]['component'], RUNTIME)
        self.store.restore('A', [RUNTIME])
        self.assertEqual((self.root / self.binary).read_bytes(), b'preproject executable')

    def test_legacy_custom_config_remains_mutable_through_adoption_and_transfer(self):
        self.legacy_runtime()
        self.legacy_config()
        self.apply({self.plugin: self.spec(b'new plugin')}, selected=[PLUGIN], adopt=self.legacy_originals())
        self.assertEqual(self.current()['paths'][RUNTIME_CONFIG]['component'], PLUGIN)
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user runtime config')
        self.apply({self.plugin: self.spec(b'new plugin'), self.binary: self.spec(b'new runtime', RUNTIME),
                    RUNTIME_CONFIG: self.spec(b'new config', RUNTIME, config=True)},
                   '2', selected=[PLUGIN, RUNTIME])
        self.assertEqual(self.current()['paths'][RUNTIME_CONFIG]['component'], RUNTIME)
        self.store.restore('A', [RUNTIME])
        self.assertEqual((self.root / RUNTIME_CONFIG).read_bytes(), b'user runtime config')

    def test_unknown_or_changed_legacy_original_fails_before_plugin_writes(self):
        state = self.legacy_runtime()
        (state / 'original-reference/bin/tool').write_bytes(b'changed original')
        with self.assertRaisesRegex(RuntimeError, 'disagree'):
            self.legacy_originals()
        self.assertFalse((self.root / self.plugin).exists())
        self.assertFalse((self.state / 'index.json').exists())


if __name__ == '__main__':
    unittest.main()
