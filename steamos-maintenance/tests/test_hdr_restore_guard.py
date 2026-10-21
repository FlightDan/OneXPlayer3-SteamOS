"""HDR recovery code survives rejected generation restore and crash recovery."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import operations as op, x2mini_hdr_device as device
from oxp3_maintenance.transactions import Store


class Interrupted(Exception):
    pass


class HDRRestoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'root'
        self.root.mkdir()
        self.state = self.base / 'state'
        self.store = Store(self.root, self.state, enforce_owner=False,
                           uid=getattr(os, 'getuid', lambda: 0)(),
                           gid=getattr(os, 'getgid', lambda: 0)())
        self.hdr = 'opt/oxp3-desktop-gamma22/current/bin/kwin_wayland'
        self.input = 'etc/test-input.conf'
        self.system = {'slot': {'id': 'A'}}

    def files(self, version, *, hdr=True, hdr_path=None):
        files = {self.input: {'data': version, 'component': 'input'}}
        if hdr:
            files[hdr_path or self.hdr] = {'data': version, 'component': 'desktop-hdr'}
        return files

    def install(self, *, hdr_path=None):
        self.store.apply(self.files(b'old', hdr=False), {'version': 'old'}, ['input'], 'A')
        self.store.apply(self.files(b'new', hdr_path=hdr_path), {'version': 'new'},
                         ['input', 'desktop-hdr'], 'A')

    def queue(self, action, *, hdr_path=None):
        self.install(hdr_path=hdr_path)
        with mock.patch.object(self.store, '_execute', side_effect=Interrupted('before first write')):
            with self.assertRaises(Interrupted):
                if action == 'restore':
                    self.store.restore('A', ['desktop-hdr', 'input'])
                else:
                    self.store.rollback('A')
        self.assertTrue((self.state / 'pending.json').exists())

    def assert_recovery_blocked(self, resume, *, hdr_path=None):
        before_pending = (self.state / 'pending.json').read_bytes()
        before_index = (self.state / 'index.json').read_bytes()
        with mock.patch.object(device, 'cleanup_launchers',
                               side_effect=device.LauncherError('HDR trial recovery is pending')) as cleanup, \
             mock.patch.object(self.store, '_write', wraps=self.store._write) as write:
            with self.assertRaisesRegex(device.LauncherError, 'recovery is pending'):
                resume()
        cleanup.assert_called_once_with(self.root / 'home/deck')
        write.assert_not_called()
        self.assertEqual((self.root / (hdr_path or self.hdr)).read_bytes(), b'new')
        self.assertEqual((self.root / self.input).read_bytes(), b'new')
        self.assertEqual((self.state / 'pending.json').read_bytes(), before_pending)
        self.assertEqual((self.state / 'index.json').read_bytes(), before_index)

    def test_queued_restore_and_rollback_reject_before_any_target_write(self):
        for action in ('restore', 'rollback'):
            with self.subTest(action=action):
                if (self.state / 'pending.json').exists():
                    # Complete the preceding subcase through the same real executor.
                    with mock.patch.object(device, 'cleanup_launchers'):
                        self.store.recover(slot='A')
                    self.store.restore('A', ['input'])
                self.queue(action)
                self.assert_recovery_blocked(lambda: self.store.recover(slot='A'))
                with mock.patch.object(device, 'cleanup_launchers') as cleanup:
                    self.store.recover(slot='A')
                cleanup.assert_called_once_with(self.root / 'home/deck')
                self.assertFalse((self.root / self.hdr).exists())
                self.assertFalse((self.state / 'pending.json').exists())

    def test_component_metadata_guards_hdr_paths_outside_known_runtime_prefixes(self):
        path = 'usr/local/lib/test-hdr-recovery-helper.py'
        self.queue('restore', hdr_path=path)
        self.assert_recovery_blocked(lambda: self.store.recover(slot='A'), hdr_path=path)

    def test_implicit_ready_cannot_resume_pending_hdr_removal(self):
        self.queue('restore')
        self.assert_recovery_blocked(lambda: self.store.apply(
            {'etc/unrelated': {'data': b'update', 'component': 'other'}},
            {'version': 'later'}, ['other'], 'A'))
        self.assertFalse((self.root / 'etc/unrelated').exists())

    def test_operations_recovery_without_live_journal_checks_queued_mutations(self):
        self.queue('restore')
        self.assertFalse((self.state / 'live-operation.json').exists())
        with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
             mock.patch.object(op.probe, 'live', return_value=self.system), \
             mock.patch.object(op, 'store_for', return_value=self.store), \
             mock.patch.object(op, 'STATE', self.state), \
             mock.patch.object(op, 'command', return_value='disabled'), \
             mock.patch.object(op, 'PackageStore'):
            self.assert_recovery_blocked(lambda: op.restore(SimpleNamespace(select=[]), recovery=True))

    def test_saved_partial_rollback_scope_is_checked_before_resuming_queue(self):
        self.queue('rollback')
        (self.state / 'live-operation.json').write_text(json.dumps({
            'slot': 'A', 'readonly': 'disabled', 'services': {},
            'file_action': 'rollback', 'file_components': ['input'],
            'source_generation': 2, 'file_generation': 3}), encoding='utf8')
        with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
             mock.patch.object(op.probe, 'live', return_value=self.system), \
             mock.patch.object(op, 'store_for', return_value=self.store), \
             mock.patch.object(op, 'STATE', self.state), \
             mock.patch.object(op, 'command', return_value='disabled'), \
             mock.patch.object(op, 'PackageStore'), \
             mock.patch.object(self.store, 'recover', wraps=self.store.recover) as recover:
            self.assert_recovery_blocked(lambda: op.restore(SimpleNamespace(select=[]), recovery=True))
        recover.assert_not_called()

    def test_partial_select_rollback_persists_complete_generation_scope(self):
        self.install()
        runtime = self.base / 'runtime'
        runtime.mkdir()
        (runtime / 'activation.json').write_text(json.dumps({'components': {
            name: {'units': []} for name in ('input', 'desktop-hdr')}}), encoding='utf8')
        intents = []

        @contextmanager
        def live_write(store, system, units):
            live = {}
            yield live
            intents.append(dict(live))

        with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
             mock.patch.object(op.probe, 'live', return_value=self.system), \
             mock.patch.object(op, 'store_for', return_value=self.store), \
             mock.patch.object(op, 'STATE', self.state), mock.patch.object(op, 'RUNTIME', runtime), \
             mock.patch.object(op, '_service_history', return_value=({}, {})), \
             mock.patch.object(op, 'live_write', side_effect=live_write), \
             mock.patch.object(op, 'command'), mock.patch.object(device, 'cleanup_launchers') as cleanup:
            op.restore(SimpleNamespace(select=['input']), previous=True)
        self.assertEqual(intents[0]['file_components'], ['desktop-hdr', 'input'])
        self.assertEqual(intents[0]['file_action'], 'rollback')
        self.assertGreaterEqual(cleanup.call_count, 1)
        self.assertTrue(all(call.args == (self.root / 'home/deck',) for call in cleanup.call_args_list))
        self.assertFalse((self.root / self.hdr).exists())
        self.assertEqual((self.root / self.input).read_bytes(), b'old')

    def test_unrelated_restore_does_not_invoke_hdr_cleanup(self):
        self.store.apply(self.files(b'old', hdr=False), {'version': 'old'}, ['input'], 'A')
        with mock.patch.object(device, 'cleanup_launchers') as cleanup:
            self.store.restore('A', ['input'])
        cleanup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
