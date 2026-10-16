"""A failed first maintenance apply must return to the installed legacy state."""
import base64
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import operations as op
from oxp3_maintenance.transactions import Store, TransactionError


class InitialApplyAbortTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'root'
        self.root.mkdir()
        self.store = Store(self.root, self.base / 'state', enforce_owner=False)
        self.input = 'etc/test/input'
        self.mutable = 'etc/test/calibration'
        self.fresh = 'etc/test/waydroid'
        self.entry = 'usr/local/lib/oxp3-maintenance/entry.py'
        self.activation = 'usr/local/lib/oxp3-maintenance/activation.json'
        self.release = 'usr/local/lib/oxp3-maintenance/current-release.json'
        self.receipt = 'usr/local/lib/oxp3-maintenance/component-receipts/A/input.json'
        self.write(self.input, b'legacy-input')
        self.write(self.mutable, b'user-calibration')
        self.input_before = self.store._read(self.input)
        self.mutable_before = self.store._read(self.mutable)
        self.original = dict(self.input_before, data=base64.b64encode(b'preproject-input').decode())
        baseline = dict(self.mutable_before, data=base64.b64encode(b'legacy-calibration').decode())
        self.adopt = {
            self.input: {'component': 'input', 'original': self.original, 'applied': self.input_before},
            self.mutable: {'component': 'input', 'original': {'exists': False},
                           'applied': self.mutable_before, 'baseline': baseline, 'preserve': True}}
        self.files = {
            self.input: self.spec(b'new-input', 'input'),
            self.mutable: self.spec(b'new-calibration', 'input', mutable=True),
            self.fresh: self.spec(b'new-waydroid', 'waydroid'),
            self.receipt: self.spec(b'receipt', 'input'),
            self.entry: self.spec(b'trusted-recovery-engine', '_maintenance'),
            'home/deck/Desktop/OXP3-Maintenance.desktop': dict(
                self.spec(b'desktop-launcher', '_maintenance'), user=True),
            'home/deck/.config/systemd/user/oxp3-maintenance-check.timer': dict(
                self.spec(b'update-timer', '_maintenance'), user=True),
            self.activation: self.spec(json.dumps({'schema': 1, 'release': {'version': '0.1.4'},
                'components': {'input': {'installed_project_version': '0.1.4'}}}).encode(), '_maintenance'),
            self.release: self.spec(json.dumps({'version': '0.1.4', 'component_revisions_by_slot': {
                'A': {'input': 'new-revision'}, 'B': {'input': 'other-revision'}}}).encode(), '_maintenance')}
        self.apply()

    @staticmethod
    def spec(data, component, mutable=False):
        return {'data': data, 'mode': 0o644, 'component': component, 'user': False, 'mutable': mutable}

    def write(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def apply(self):
        return self.store.apply(copy.deepcopy(self.files), {'version': '0.1.4'},
            ['_maintenance', 'input', 'waydroid'], 'A', adopt=self.adopt, legacy_selected=['hdr'])

    def abort(self):
        return self.store.abort_apply('A', generation=1, source_generation=None)

    def assert_legacy(self):
        self.assertEqual((self.root / self.input).read_bytes(), b'legacy-input')
        self.assertEqual((self.root / self.mutable).read_bytes(), b'user-calibration')
        self.assertFalse((self.root / self.fresh).exists())
        self.assertFalse((self.root / self.receipt).exists())
        self.assertEqual((self.root / self.entry).read_bytes(), b'trusted-recovery-engine')
        self.assertEqual((self.root / 'home/deck/Desktop/OXP3-Maintenance.desktop').read_bytes(), b'desktop-launcher')
        current = self.store.status()['slots']['A']['current']
        self.assertEqual(current['selected'], ['_maintenance'])
        self.assertEqual(current['legacy_selected'], ['hdr', 'input'])
        self.assertEqual(current['release']['apply_outcome'], 'aborted_engine_retained')
        activation = json.loads((self.root / self.activation).read_bytes())
        self.assertEqual(activation['components'], {})
        release = json.loads((self.root / self.release).read_bytes())
        self.assertEqual(release['version'], '0.1.4')
        self.assertEqual(release['apply_outcome'], 'aborted_engine_retained')
        self.assertEqual(release['component_revisions_by_slot'], {'B': {'input': 'other-revision'}})

    def test_initial_adoption_abort_preserves_legacy_mutable_and_engine(self):
        result = self.abort()
        self.assertEqual(result['action'], 'abort')
        self.assert_legacy()
        self.assertEqual(self.store._index()['originals']['A:' + self.input], self.original)
        self.assertNotIn('adoption_before', self.store._index()['slots']['A']['current'])

    def test_reapply_after_abort_then_explicit_restore_uses_true_original(self):
        self.abort()
        self.apply()
        self.assertEqual((self.root / self.input).read_bytes(), b'new-input')
        self.store.restore('A', ['input'])
        self.assertEqual((self.root / self.input).read_bytes(), b'preproject-input')
        self.assertEqual((self.root / self.mutable).read_bytes(), b'user-calibration')

    def test_later_mutable_edit_survives_abort(self):
        self.write(self.mutable, b'later-user-edit')
        result = self.abort()
        self.assertIn(self.mutable, result['preserved'])
        self.assertEqual((self.root / self.mutable).read_bytes(), b'later-user-edit')

    def test_stale_generation_or_wrong_source_fails_without_writes(self):
        before = self.store.status()
        for generation, source in ((2, None), (1, 0), (1, 4), (True, None)):
            with self.subTest(generation=generation, source=source), self.assertRaises(TransactionError):
                self.store.abort_apply('A', generation=generation, source_generation=source)
        self.assertEqual(self.store.status(), before)
        self.assertEqual((self.root / self.input).read_bytes(), b'new-input')
        self.abort()
        with self.assertRaises(TransactionError):
            self.abort()
        self.assert_legacy()

    def test_immutable_drift_refuses_before_any_target_mutation(self):
        self.write(self.input, b'external-edit')
        before = self.store.status()
        with self.assertRaisesRegex(TransactionError, 'immutable file was modified'):
            self.abort()
        self.assertEqual(self.store.status(), before)
        self.assertTrue((self.root / self.fresh).exists())
        self.assertEqual((self.root / self.input).read_bytes(), b'external-edit')

    def test_interrupted_abort_rolls_forward_from_durable_journal(self):
        with mock.patch.object(self.store, '_after_write', side_effect=RuntimeError('power loss')):
            with self.assertRaisesRegex(RuntimeError, 'power loss'):
                self.abort()
        self.assertEqual(self.store.status()['pending']['action'], 'abort')
        self.assertTrue(self.store.recover('A')['recovered'])
        self.assert_legacy()

    def test_existing_generation_abort_still_restores_managed_predecessor(self):
        self.abort()
        result = self.apply()
        self.store.abort_apply('A', generation=result['generation'], source_generation=2)
        self.assert_legacy()

    def live_record(self):
        return {'slot': 'A', 'readonly': 'enabled', 'phase': 'writing', 'file_action': 'apply',
                'source_generation': None, 'file_generation': 1, 'file_components': ['input', 'waydroid'],
                'package_operation': True, 'services': {'legacy.service': {'active': True, 'enabled': 'enabled'}},
                'after_services': {'legacy.service': {'active': False, 'enabled': 'disabled'}}}

    def recover_live(self, commands):
        packages = mock.Mock()
        packages.recover.return_value = {'phase': 'restored'}
        def command(*args, **kwargs):
            commands.append(args)
            if args == ('steamos-readonly', 'status'):
                return 'enabled'
            if args[:2] == ('systemctl', 'show'):
                return 'loaded'
            if args == ('systemctl', 'start', 'legacy.service'):
                self.assert_legacy()
            return ''
        with mock.patch.object(op, 'STATE', self.store.state), \
             mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
             mock.patch.object(op.probe, 'live', return_value={'slot': {'id': 'A'}}), \
             mock.patch.object(op, 'store_for', return_value=self.store), \
             mock.patch.object(op, 'PackageStore', return_value=packages), \
             mock.patch.object(op, 'command', side_effect=command):
            op.restore(SimpleNamespace(select=[]), recovery=True)

    def test_recover_failed_first_apply_aborts_files_before_old_services(self):
        self.store._state_write('live-operation.json', self.live_record())
        commands = []
        self.recover_live(commands)
        self.assert_legacy()
        self.assertIn(('systemctl', 'start', 'legacy.service'), commands)
        self.assertFalse((self.store.state / 'live-operation.json').exists())

    def test_recovery_resumes_abort_intent_before_and_after_target_commit(self):
        live = self.live_record()
        with mock.patch.object(op, 'STATE', self.store.state), \
             mock.patch.object(self.store, '_execute', side_effect=RuntimeError('power loss')):
            with self.assertRaisesRegex(RuntimeError, 'power loss'):
                op._abort_apply(self.store, {'slot': {'id': 'A'}}, live)
        saved = self.store._state_read('live-operation.json')
        self.assertEqual(saved['file_action'], 'abort')
        self.assertEqual(saved['source_generation'], 1)
        self.assertEqual(saved['file_generation'], 2)
        # The file journal can finish before the lifecycle journal is updated.
        self.store.recover('A')
        self.recover_live([])
        self.assert_legacy()
        self.assertEqual(self.store.status()['slots']['A']['current']['id'], 2)

    def test_recovery_resumes_abort_intent_before_file_journal_exists(self):
        live = self.live_record()
        with mock.patch.object(op, 'STATE', self.store.state), \
             mock.patch.object(self.store, 'abort_apply', side_effect=RuntimeError('power loss')):
            with self.assertRaisesRegex(RuntimeError, 'power loss'):
                op._abort_apply(self.store, {'slot': {'id': 'A'}}, live)
        self.assertIsNone(self.store.status()['pending'])
        self.recover_live([])
        self.assert_legacy()

    def test_unrelated_generation_blocks_abort_lifecycle_recovery(self):
        live = self.live_record()
        with mock.patch.object(op, 'STATE', self.store.state), \
             mock.patch.object(self.store, 'abort_apply', side_effect=RuntimeError('power loss')):
            with self.assertRaisesRegex(RuntimeError, 'power loss'):
                op._abort_apply(self.store, {'slot': {'id': 'A'}}, live)
        # Simulate two unrelated committed file operations after the saved intent.
        self.store.apply({}, {'version': 'other'}, [], 'A')
        self.store.apply({}, {'version': 'unrelated'}, [], 'A')
        commands = []
        with self.assertRaisesRegex(RuntimeError, 'unrelated file generation'):
            self.recover_live(commands)
        self.assertTrue((self.store.state / 'live-operation.json').exists())
        self.assertNotIn(('systemctl', 'start', 'legacy.service'), commands)

    def test_expected_generation_number_without_abort_provenance_is_rejected(self):
        live = self.live_record()
        with mock.patch.object(op, 'STATE', self.store.state), \
             mock.patch.object(self.store, 'abort_apply', side_effect=RuntimeError('power loss')):
            with self.assertRaisesRegex(RuntimeError, 'power loss'):
                op._abort_apply(self.store, {'slot': {'id': 'A'}}, live)
        self.store.apply({}, {'version': 'unrelated'}, [], 'A')
        self.assertEqual(self.store.status()['slots']['A']['current']['id'], 2)
        commands = []
        with self.assertRaisesRegex(RuntimeError, 'unrelated file generation'):
            self.recover_live(commands)
        self.assertNotIn(('systemctl', 'start', 'legacy.service'), commands)


if __name__ == '__main__':
    unittest.main()
