"""Read-only conflict checks for live files proposed for legacy adoption."""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import adoption


class AdoptionDriftTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'root'
        self.root.mkdir()
        self.probe = {'uid': 1000, 'gid': 1000, 'slot': {'label': 'A'}}
        # Actual metadata and link checks remain active in _file; these fixtures
        # run on Windows without Unix ownership for the temporary ancestors.
        trusted = mock.patch.object(adoption, '_trusted')
        self.trusted = trusted.start()
        self.addCleanup(trusted.stop)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def imported(self, relative='etc/systemd/system/oxp3-gyro.service', data=b'installed unit'):
        path = self.write(relative, data)
        info = path.stat()
        applied = {'exists': True, 'data': base64.b64encode(data).decode(),
                   'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        return {relative: {'component': 'gyro', 'original': {'exists': False}, 'applied': applied}}

    def test_matching_immutable_snapshot_is_read_only(self):
        originals = self.imported()
        before = copy.deepcopy(originals)
        path = self.root / next(iter(originals))
        self.assertIs(adoption.validate_current(self.root, originals, self.probe), originals)
        self.assertEqual(originals, before)
        self.assertEqual(path.read_bytes(), b'installed unit')

    def test_immutable_byte_drift_is_reported_with_target(self):
        originals = self.imported()
        relative = next(iter(originals))
        self.write(relative, b'locally changed unit')
        before = copy.deepcopy(originals)
        with self.assertRaisesRegex(RuntimeError, 'changed after installation: ' + relative):
            adoption.validate_current(self.root, originals, self.probe)
        self.assertEqual(originals, before)
        self.assertEqual((self.root / relative).read_bytes(), b'locally changed unit')

    def test_missing_and_metadata_drift_are_reported_before_adoption(self):
        originals = self.imported()
        relative = next(iter(originals))
        originals[relative]['applied']['gid'] += 1
        with self.assertRaisesRegex(RuntimeError, 'changed after installation'):
            adoption.validate_current(self.root, originals, self.probe)
        (self.root / relative).unlink()
        with self.assertRaisesRegex(RuntimeError, 'cannot be verified: ' + relative):
            adoption.validate_current(self.root, originals, self.probe)

    def test_preserved_mutable_calibration_keeps_original_and_baseline(self):
        relative = 'etc/inputplumber/oxp3-gyro-steer.conf'
        originals = self.imported(relative, b'user calibration')
        applied = originals[relative]['applied']
        original = dict(applied, data=base64.b64encode(b'preproject setting').decode())
        journal = {'phase': 'installed', 'allowed': [relative], 'original': {relative: original},
                   'applied': {relative: base64.b64encode(b'legacy calibration').decode()},
                   'metadata': {relative: {'user': False, 'mode': applied['mode']}}}
        self.write('home/.oxp3-installer/integration/A/gyro/state.json', json.dumps(journal).encode())
        originals = adoption.import_originals(self.root, self.probe, ['gyro'])
        self.assertTrue(originals[relative]['preserve'])
        before = copy.deepcopy(originals)
        adoption.validate_current(self.root, originals, self.probe)
        self.assertEqual(originals, before)
        self.assertEqual(base64.b64decode(originals[relative]['original']['data']), b'preproject setting')
        self.assertEqual(base64.b64decode(originals[relative]['baseline']['data']), b'legacy calibration')
        self.assertEqual(base64.b64decode(originals[relative]['applied']['data']), b'user calibration')
        self.write(relative, b'newer calibration after import')
        with self.assertRaisesRegex(RuntimeError, 'changed after installation'):
            adoption.validate_current(self.root, originals, self.probe)
        self.assertEqual(originals, before)

    def test_home_targets_allow_deck_owned_ancestors_through_safe_reader(self):
        originals = self.imported('home/deck/.config/kwinrc')
        adoption.validate_current(self.root, originals, self.probe)
        self.trusted.assert_called_once_with(self.root / 'home/deck/.config/kwinrc',
                                             self.root, user_uid=1000)

    def test_hardlinked_target_is_refused_without_modification(self):
        originals = self.imported()
        path = self.root / next(iter(originals))
        link = self.root / 'linked-unit'
        os.link(path, link)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe legacy runtime file'):
            adoption.validate_current(self.root, originals, self.probe)
        self.assertEqual(link.read_bytes(), b'installed unit')

    def test_hardlink_created_between_path_check_and_open_is_refused(self):
        originals = self.imported()
        path = self.root / next(iter(originals))
        real_open = os.open
        linked = False

        def open_with_race(*args, **kwargs):
            nonlocal linked
            if not linked:
                os.link(path, self.root / 'racing-hardlink')
                linked = True
            return real_open(*args, **kwargs)

        with mock.patch.object(adoption.os, 'open', side_effect=open_with_race):
            with self.assertRaisesRegex(RuntimeError, 'changed during reading'):
                adoption.validate_current(self.root, originals, self.probe)
        self.assertEqual(path.read_bytes(), b'installed unit')

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_linked_target_or_ancestor_is_refused(self):
        originals = self.imported()
        relative = next(iter(originals))
        path = self.root / relative
        outside = self.write('outside-unit', b'installed unit')
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe legacy runtime file'):
            adoption.validate_current(self.root, originals, self.probe)
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(outside.parent, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'cannot be verified'):
            adoption.validate_current(self.root, originals, self.probe)

    def test_oversized_snapshots_and_unsafe_paths_are_rejected(self):
        originals = self.imported(data=b'abc')
        with mock.patch.object(adoption, '_MAX_FILE', 2):
            with self.assertRaisesRegex(RuntimeError, 'Oversized legacy adoption targets'):
                adoption.validate_current(self.root, originals, self.probe)
        originals.update(self.imported('etc/second-unit', b'abc'))
        with mock.patch.object(adoption, '_MAX_TREE', 5):
            with self.assertRaisesRegex(RuntimeError, 'Oversized legacy adoption targets'):
                adoption.validate_current(self.root, originals, self.probe)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe legacy runtime path'):
            adoption.validate_current(self.root, {'../escape': next(iter(originals.values()))}, self.probe)


if __name__ == '__main__':
    unittest.main()
