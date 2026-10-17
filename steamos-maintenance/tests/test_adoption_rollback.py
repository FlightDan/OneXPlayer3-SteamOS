"""First legacy adoption has distinct rollback and original-restore images."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import transactions
from oxp3_maintenance.transactions import Store, TransactionError


class AdoptionRollbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'root'
        self.root.mkdir()
        self.store = Store(self.root, Path(temporary.name) / 'state', enforce_owner=False)
        self.relative = 'etc/test/input'
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'legacy-installed')
        self.applied = self.store._read(self.relative)
        self.original = dict(self.applied, data=base64.b64encode(b'preproject-image').decode())
        self.engine = {'usr/local/lib/oxp3-maintenance/entry.py': self.spec(b'engine', '_maintenance')}
        self.store.apply(self.engine, {'version': '1'}, ['_maintenance'], 'A', legacy_selected=['input'])

    @staticmethod
    def spec(data, component='input', mutable=False):
        return {'data': data, 'mode': 0o644, 'component': component, 'user': False, 'mutable': mutable}

    def current(self):
        return self.store._index()['slots']['A']['current']

    def adopt(self, *, mutable=False, applied=None, preserve=False):
        record = {'component': 'input', 'original': self.original,
                  'applied': applied or self.applied}
        if preserve:
            record.update(preserve=True, baseline=self.applied)
        files = dict(self.engine, **{self.relative: self.spec(b'maintained-input', mutable=mutable)})
        return self.store.apply(files, {'version': '2'}, ['_maintenance', 'input'], 'A',
                                adopt={self.relative: record}, legacy_selected=[])

    def test_rollback_returns_legacy_bytes_and_selection_then_toggles_back(self):
        self.adopt()
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.assertEqual(self.current()['adoption_before'][self.relative], self.applied)
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')
        self.assertEqual(self.current()['legacy_selected'], ['input'])
        self.assertNotIn('input', self.store.managed()['components'])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.assertEqual(self.current()['legacy_selected'], [])
        self.assertIn('input', self.store.managed()['components'])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')

    def test_explicit_restore_still_returns_true_preproject_original(self):
        self.adopt()
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'preproject-image')
        self.assertNotIn('input', self.store.managed()['components'])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'preproject-image')

    def test_normal_reapplication_after_rollback_accepts_verified_legacy_image(self):
        self.adopt()
        self.store.rollback('A')
        self.adopt()
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'preproject-image')

    def test_reapplication_cannot_replace_existing_true_original(self):
        self.adopt()
        self.store.rollback('A')
        self.original = dict(self.original, data=base64.b64encode(b'wrong-backup').decode())
        with self.assertRaisesRegex(TransactionError, 'Previously restored target changed externally'):
            self.adopt()
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')

    def test_tampered_legacy_before_image_blocks_reentry_without_writes(self):
        self.adopt()
        self.store.rollback('A')
        self.path.write_bytes(b'external modification')
        before = self.store.status()
        with self.assertRaisesRegex(TransactionError, 'Rollback target changed externally'):
            self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'external modification')
        self.assertEqual(self.store.status(), before)

    def test_before_images_are_private_and_not_inherited_by_later_apply(self):
        self.adopt()
        public = json.dumps({'status': self.store.status(), 'managed': self.store.managed()})
        self.assertNotIn('adoption_before', public)
        self.assertNotIn('adoption_preserved', public)
        self.assertNotIn(base64.b64encode(b'legacy-installed').decode(), public)
        files = dict(self.engine, **{self.relative: self.spec(b'later-maintained-input')})
        self.store.apply(files, {'version': '3'}, ['_maintenance', 'input'], 'A', legacy_selected=[])
        self.assertNotIn('adoption_before', self.current())
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.assertEqual(self.current()['adoption_before'][self.relative], self.applied)
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'later-maintained-input')

    def test_fresh_component_rollback_behavior_is_unchanged(self):
        fresh = 'etc/test/fresh'
        files = dict(self.engine, **{fresh: self.spec(b'fresh-component', 'fresh')})
        self.store.apply(files, {'version': '2'}, ['_maintenance', 'fresh'], 'A', legacy_selected=['input'])
        self.assertNotIn('adoption_before', self.current())
        self.store.rollback('A')
        self.assertFalse((self.root / fresh).exists())
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')
        self.store.rollback('A')
        self.assertEqual((self.root / fresh).read_bytes(), b'fresh-component')
        self.store.restore('A', ['fresh'])
        self.assertFalse((self.root / fresh).exists())

    def test_absent_legacy_before_image_rolls_back_toggles_and_restores_original(self):
        # The Store snapshot contract also covers an earlier legacy removal.
        # Adoption may install a replacement while retaining its true original.
        self.path.unlink()
        self.adopt(applied={'exists': False})
        self.assertEqual(self.current()['adoption_before'][self.relative], {'exists': False})
        self.store.rollback('A')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.current()['legacy_selected'], ['input'])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'preproject-image')

    def test_mutable_calibration_edits_remain_preserved(self):
        self.path.write_bytes(b'user-calibration')
        calibration = self.store._read(self.relative)
        self.adopt(mutable=True, applied=calibration, preserve=True)
        self.assertEqual(self.path.read_bytes(), b'user-calibration')
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'user-calibration')
        self.path.write_bytes(b'later-user-calibration')
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'later-user-calibration')
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'later-user-calibration')

    def test_mutable_calibration_immediate_toggle_preserves_custom_bytes(self):
        self.path.write_bytes(b'user-calibration')
        calibration = self.store._read(self.relative)
        self.adopt(mutable=True, applied=calibration, preserve=True)
        self.assertEqual(self.current()['adoption_preserved'], [self.relative])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'user-calibration')
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'user-calibration')
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'user-calibration')

    def test_older_adoption_generation_conservatively_preserves_custom_bytes(self):
        self.path.write_bytes(b'user-calibration')
        self.adopt(mutable=True, applied=self.store._read(self.relative), preserve=True)
        index = self.store._index()
        del index['slots']['A']['current']['adoption_preserved']
        self.store._state_write('index.json', index)
        self.store.rollback('A')
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'user-calibration')

    def test_unedited_mutable_adoption_toggle_applies_desired_bytes(self):
        self.adopt(mutable=True)
        self.assertEqual(self.current()['adoption_preserved'], [])
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')
        self.store.rollback('A')
        self.assertEqual(self.path.read_bytes(), b'maintained-input')

    def test_reapply_matching_restored_custom_settings_keeps_them_on_later_restore(self):
        self.adopt(mutable=True)
        self.store.restore('A', ['input'])
        self.assertEqual(self.path.read_bytes(), b'preproject-image')
        self.path.write_bytes(b'custom-after-restore')
        files = dict(self.engine, **{self.relative: self.spec(b'custom-after-restore', mutable=True)})
        result = self.store.apply(files, {'version': '3'}, ['_maintenance', 'input'], 'A', legacy_selected=[])
        self.assertIn(self.relative, result['preserved'])
        # Even when a merge produces exactly the custom live bytes, ownership
        # must retain a distinct baseline so later restore recognizes the edit.
        result = self.store.restore('A', ['input'])
        self.assertIn(self.relative, result['preserved'])
        self.assertEqual(self.path.read_bytes(), b'custom-after-restore')

    def test_reapply_matching_custom_settings_keeps_absent_original_distinct(self):
        relative = 'etc/test/new-settings'
        files = dict(self.engine, **{relative: self.spec(b'installed-settings', 'settings', mutable=True)})
        self.store.apply(files, {'version': '2'}, ['_maintenance', 'settings'], 'A', legacy_selected=['input'])
        self.store.restore('A', ['settings'])
        path = self.root / relative
        self.assertFalse(path.exists())
        path.write_bytes(b'custom-after-restore')
        files[relative] = self.spec(b'custom-after-restore', 'settings', mutable=True)
        result = self.store.apply(files, {'version': '3'}, ['_maintenance', 'settings'], 'A', legacy_selected=['input'])
        self.assertIn(relative, result['preserved'])
        result = self.store.restore('A', ['settings'])
        self.assertIn(relative, result['preserved'])
        self.assertEqual(path.read_bytes(), b'custom-after-restore')

    def test_invalid_preserved_adoption_paths_are_rejected(self):
        self.adopt()
        index = self.store._index()
        for value in ('not-a-list', [3], [self.relative, self.relative], ['../escape'], ['etc/unknown']):
            with self.subTest(value=value):
                altered = copy.deepcopy(index)
                altered['slots']['A']['current']['adoption_preserved'] = value
                self.store._state_write('index.json', altered)
                with self.assertRaises(TransactionError):
                    self.store.status()
                self.assertEqual(self.path.read_bytes(), b'maintained-input')

    def test_invalid_before_image_metadata_is_rejected(self):
        self.adopt()
        index = self.store._index()
        invalid = [[], {'../escape': self.applied}, {'etc/passwd': self.applied},
                   {self.relative: {'exists': False, 'data': 'unexpected'}},
                   {self.relative: dict(self.applied, mode=True)},
                   {self.relative: dict(self.applied, data='not-base64')},
                   {self.relative: dict(self.applied, extra='unexpected')}]
        for value in invalid:
            with self.subTest(value=value):
                altered = copy.deepcopy(index)
                altered['slots']['A']['current']['adoption_before'] = value
                self.store._state_write('index.json', altered)
                with self.assertRaises(TransactionError):
                    self.store.status()
                self.assertEqual(self.path.read_bytes(), b'maintained-input')
        self.store._state_write('index.json', index)
        with mock.patch.object(transactions, '_MAX_ADOPTION_FILE', 2):
            with self.assertRaisesRegex(TransactionError, 'adoption rollback snapshot'):
                self.store.status()

    def test_recovery_rejects_invalid_before_images_before_target_writes(self):
        with mock.patch.object(self.store, '_execute', side_effect=RuntimeError('simulated interruption')):
            with self.assertRaisesRegex(RuntimeError, 'simulated interruption'):
                self.adopt()
        pending = self.store._state_read('pending.json')
        pending['index_after']['slots']['A']['current']['adoption_before'] = {'../escape': self.applied}
        self.store._state_write('pending.json', pending)
        with self.assertRaises(TransactionError):
            self.store.recover('A')
        self.assertEqual(self.path.read_bytes(), b'legacy-installed')


if __name__ == '__main__':
    unittest.main()
