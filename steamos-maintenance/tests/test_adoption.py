"""Read-only migration fixtures for trusted legacy directory journals."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oxp3_maintenance import adoption
from oxp3_maintenance.transactions import Store, TransactionError


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.probe = {'slot': {'label': 'A'}, 'uid': 1000, 'gid': 1000}
        # Windows fixtures lack Unix ownership/modes. Every real migration still
        # validates owner/protection in _trusted before reading bytes.
        self.trust = patch.object(adoption, '_trusted')
        self.trust.start()
        self.addCleanup(self.trust.stop)

    def write(self, path, data):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def inventory(self, path):
        return {item.relative_to(path).as_posix(): {
            'directory': item.is_dir(), 'mode': stat.S_IMODE(item.stat().st_mode),
            'uid': item.stat().st_uid, 'gid': item.stat().st_gid}
            for item in [path, *path.rglob('*')]}

    def runtime(self, component='desktop-hdr', original=None):
        prefix = adoption._RUNTIMES[component]
        destination = self.root / prefix
        self.write(prefix + '/bin/tool', b'installed executable')
        self.write(prefix + '/lib/module', b'installed library')
        state = destination.parent / '.installer-state'
        state.mkdir(mode=0o700)
        shutil.copytree(destination, state / 'installed')
        original_metadata = None
        if original is not None:
            original_path = state / 'original-reference'
            original_path.mkdir()
            for relative, data in original.items():
                path = original_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            original_metadata = self.inventory(original_path)
            shutil.copytree(original_path, state / 'original')
        value = {'destination': prefix, 'phase': 'installed', 'original_exists': original is not None,
                 'original_metadata': original_metadata, 'installed_metadata': self.inventory(destination)}
        (state / 'state.json').write_text(json.dumps(value))
        return prefix, state, value

    def save(self, state, value):
        (state / 'state.json').write_text(json.dumps(value))

    def logical(self, relative, *, component='gyro', before=b'preproject', applied=b'legacy installed', current=b'user calibration'):
        path = self.write(relative, current)
        info = path.stat()
        original = {'exists': True, 'data': base64.b64encode(before).decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        value = {'phase': 'installed', 'allowed': [relative], 'original': {relative: original},
                 'applied': {relative: base64.b64encode(applied).decode()},
                 'metadata': {relative: {'user': relative.startswith('home/'), 'mode': 0o644}}}
        state = 'home/.oxp3-installer/integration/A/' + component + '/state.json'
        self.write(state, json.dumps(value).encode())
        return value

    def test_both_runtime_components_adopt_absent_original_without_mutation(self):
        first, _, _ = self.runtime()
        second, _, _ = self.runtime('opti2xmx')
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = adoption.import_originals(self.root, self.probe, ['desktop-hdr', 'opti2xmx'])
        self.assertEqual(set(result), {prefix + '/' + item for prefix in (first, second) for item in ('bin/tool', 'lib/module')})
        self.assertTrue(all(item['original'] == {'exists': False} for item in result.values()))
        self.assertEqual(base64.b64decode(result[first + '/bin/tool']['applied']['data']), b'installed executable')
        after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_existing_original_bytes_metadata_restored_after_migration(self):
        prefix, _, _ = self.runtime(original={'bin/tool': b'preproject executable'})
        adopted = adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        self.assertEqual(base64.b64decode(adopted[prefix + '/bin/tool']['original']['data']), b'preproject executable')
        store = Store(self.root, self.root.parent / 'new-state', enforce_owner=False)
        files = {path: {'data': base64.b64decode(item['applied']['data']), 'mode': 0o644,
                        'component': 'desktop-hdr', 'user': False} for path, item in adopted.items()}
        store.apply(files, {'version': '1'}, ['desktop-hdr'], 'A', adopt=adopted)
        # This fixture has runtime metadata only; user-home safety is covered by
        # test_hdr_restore_guard and the launcher helper's dropped-uid tests.
        with patch('oxp3_maintenance.x2mini_hdr_device.cleanup_launchers'):
            store.restore('A')
        self.assertEqual((self.root / prefix / 'bin/tool').read_bytes(), b'preproject executable')
        self.assertFalse((self.root / prefix / 'lib/module').exists())

    def test_original_only_file_is_refused_without_losing_backup(self):
        _, state, _ = self.runtime(original={'old-only': b'irreplaceable old file'})
        with self.assertRaisesRegex(RuntimeError, 'original-only'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        self.assertEqual((state / 'original/old-only').read_bytes(), b'irreplaceable old file')

    def test_current_and_installed_reference_bytes_must_match(self):
        prefix, state, _ = self.runtime()
        (self.root / prefix / 'bin/tool').write_bytes(b'changed code')
        with self.assertRaisesRegex(RuntimeError, 'bytes changed'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        (state / 'installed/bin/tool').write_bytes(b'changed code')
        # The journal does not have a byte hash; agreement of the protected live
        # and reference trees is the legacy authority, as in DirectoryTransaction.
        self.assertIn(prefix + '/bin/tool', adoption.import_originals(self.root, self.probe, ['desktop-hdr']))

    def test_metadata_drift_missing_extra_and_special_entries_are_refused(self):
        prefix, state, value = self.runtime()
        altered = copy.deepcopy(value)
        altered['installed_metadata']['bin/tool']['gid'] += 1
        self.save(state, altered)
        with self.assertRaisesRegex(RuntimeError, 'metadata differs'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        self.save(state, value)
        self.write(prefix + '/unmanaged', b'custom code')
        with self.assertRaisesRegex(RuntimeError, 'metadata differs'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        (self.root / prefix / 'unmanaged').unlink()
        (state / 'installed/lib/module').unlink()
        with self.assertRaisesRegex(RuntimeError, 'metadata differs'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])

    def test_original_reference_fallback_and_disagreement(self):
        _, state, _ = self.runtime(original={'bin/tool': b'preproject'})
        (state / 'original/bin/tool').write_bytes(b'changed backup')
        with self.assertRaisesRegex(RuntimeError, 'backups disagree'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        shutil.rmtree(state / 'original')
        self.assertTrue(adoption.import_originals(self.root, self.probe, ['desktop-hdr']))
        shutil.rmtree(state / 'original-reference')
        with self.assertRaisesRegex(RuntimeError, 'backup is missing'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])

    def test_interrupted_destination_mismatch_and_unsafe_metadata_refused(self):
        _, state, value = self.runtime()
        for phase in ('prepared', 'installing', 'restoring', 'unknown'):
            with self.subTest(phase=phase):
                self.save(state, dict(value, phase=phase))
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        self.save(state, dict(value, destination='opt/other'))
        with self.assertRaisesRegex(RuntimeError, 'destination'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])
        bad = copy.deepcopy(value)
        bad['installed_metadata']['../escape'] = bad['installed_metadata'].pop('bin/tool')
        self.save(state, bad)
        with self.assertRaisesRegex(RuntimeError, 'Unsafe legacy runtime path'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])

    def test_rolled_back_and_unselected_runtime_is_not_adopted(self):
        _, state, value = self.runtime()
        self.assertEqual(adoption.import_originals(self.root, self.probe, []), {})
        self.save(state, dict(value, phase='rolled_back'))
        self.assertEqual(adoption.import_originals(self.root, self.probe, ['desktop-hdr']), {})

    def test_hardlinked_current_runtime_is_refused(self):
        prefix, _, _ = self.runtime()
        os.link(self.root / prefix / 'bin/tool', self.root / 'hardlink')
        with self.assertRaisesRegex(RuntimeError, 'Unsafe legacy runtime file'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])

    def test_mutable_legacy_calibration_keeps_original_and_baseline_through_restore(self):
        relative = 'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml'
        self.logical(relative)
        adopted = adoption.import_originals(self.root, self.probe, ['gyro'])
        item = adopted[relative]
        self.assertTrue(item['preserve'])
        self.assertEqual(base64.b64decode(item['original']['data']), b'preproject')
        self.assertEqual(base64.b64decode(item['baseline']['data']), b'legacy installed')
        self.assertEqual(base64.b64decode(item['applied']['data']), b'user calibration')
        store = Store(self.root, self.root.parent / 'new-state', enforce_owner=False)
        files = {relative: {'data': b'user calibration', 'mode': 0o644, 'component': 'gyro', 'mutable': True, 'user': False}}
        result = store.apply(files, {'version': '1'}, ['gyro'], 'A', adopt=adopted)
        self.assertEqual(result['preserved'], [relative])
        result = store.restore('A')
        self.assertEqual(result['preserved'], [relative])
        self.assertEqual((self.root / relative).read_bytes(), b'user calibration')

    def test_unchanged_mutable_legacy_setting_restores_preproject_original(self):
        relative = 'etc/inputplumber/oxp3-gyro-steer.conf'
        self.logical(relative, current=b'legacy installed')
        adopted = adoption.import_originals(self.root, self.probe, ['gyro'])
        self.assertNotIn('preserve', adopted[relative])
        store = Store(self.root, self.root.parent / 'new-state', enforce_owner=False)
        files = {relative: {'data': b'legacy installed', 'mode': 0o644, 'component': 'gyro', 'mutable': True, 'user': False}}
        store.apply(files, {'version': '1'}, ['gyro'], 'A', adopt=adopted)
        store.restore('A')
        self.assertEqual((self.root / relative).read_bytes(), b'preproject')

    def test_mutable_metadata_change_and_immutable_byte_change_do_not_get_bypassed(self):
        relative = 'etc/inputplumber/oxp3-gyro-steer.conf'
        record = self.logical(relative)
        record['original'][relative]['gid'] += 1
        self.write('home/.oxp3-installer/integration/A/gyro/state.json', json.dumps(record).encode())
        with self.assertRaisesRegex(RuntimeError, 'metadata changed'):
            adoption.import_originals(self.root, self.probe, ['gyro'])
        relative = 'etc/systemd/system/oxp3-gyro.service'
        self.logical(relative)
        adopted = adoption.import_originals(self.root, self.probe, ['gyro'])
        self.assertNotIn('preserve', adopted[relative])
        store = Store(self.root, self.root.parent / 'new-state', enforce_owner=False)
        with self.assertRaisesRegex(TransactionError, 'adoption does not match'):
            store.apply({relative: {'data': b'new code', 'mode': 0o644, 'component': 'gyro', 'user': False}},
                        {}, ['gyro'], 'A', adopt=adopted)
        self.assertEqual((self.root / relative).read_bytes(), b'user calibration')

    def test_mutable_preserve_cannot_be_requested_for_immutable_or_metadata_drift(self):
        relative = 'etc/inputplumber/oxp3-gyro-steer.conf'
        self.logical(relative)
        adopted = adoption.import_originals(self.root, self.probe, ['gyro'])
        store = Store(self.root, self.root.parent / 'new-state', enforce_owner=False)
        entry = {'data': b'user calibration', 'mode': 0o644, 'component': 'gyro', 'user': False}
        with self.assertRaisesRegex(TransactionError, 'Invalid mutable installer adoption'):
            store.apply({relative: entry}, {}, ['gyro'], 'A', adopt=adopted)
        adopted[relative]['baseline']['gid'] += 1
        with self.assertRaisesRegex(TransactionError, 'Invalid mutable installer adoption'):
            store.apply({relative: dict(entry, mutable=True)}, {}, ['gyro'], 'A', adopt=adopted)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction fixture')
    def test_junction_inside_current_tree_refused_even_when_ownership_mocked(self):
        import subprocess
        prefix, _, _ = self.runtime()
        outside = self.root.parent / 'outside'
        outside.mkdir()
        link = self.root / prefix / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        with self.assertRaisesRegex(RuntimeError, 'contains a link'):
            adoption.import_originals(self.root, self.probe, ['desktop-hdr'])


if __name__ == '__main__':
    unittest.main()
