"""Real file generations, fake service/sysfs backend: no live device access."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from oxp3_maintenance import operations as op
from oxp3_maintenance import gyro_binding as binding
from oxp3_maintenance.transactions import Store
from test_gyro_binding import Backend


class GyroLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.root.mkdir()
        self.state = self.base / 'state'
        self.state.mkdir()
        self.store = Store(self.root, self.state / 'files', enforce_owner=False)
        self.system = {'slot': {'id': 'A'}}
        self.unit = 'oxp3-gyro.service'
        self.prefix = 'var/lib/oxp3-gyro-v1/'
        self.backend = Backend()
        self.manager = binding.BindingManager(self.backend)
        self.calls = []
        self.active = True

    def spec(self, data):
        # Windows has no POSIX write protection: immutable 0444 fixtures let
        # the real Store retain the same safety contract on both hosts.
        return {'data': data, 'component': 'gyro', 'mode': 0o444}

    def files(self, revision=b'new helper'):
        return {self.prefix + 'binding.py': self.spec(revision),
                self.prefix + 'load.sh': self.spec(b'#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py start\n'),
                self.prefix + 'unload.sh': self.spec(b'#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py stop\n'),
                'etc/systemd/system/' + self.unit: self.spec(b'[Service]\nExecStopPost=/var/lib/oxp3-gyro-v1/unload.sh\n')}

    def install(self):
        self.store.apply(self.files(), {'version': 'new'}, ['gyro'], 'A')
        self.manager.start()

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if args == ('steamos-readonly', 'status'):
            return 'enabled'
        if args[:2] == ('systemctl', 'is-active'):
            return 'active' if self.active else 'inactive'
        if args[:2] == ('systemctl', 'is-enabled'):
            return 'enabled'
        if args[:2] == ('systemctl', 'show'):
            return 'loaded'
        if args == ('/usr/bin/python3', '-I', '-B', '/var/lib/oxp3-gyro-v1/binding.py', 'stop'):
            self.assertTrue((self.root / self.prefix / 'binding.py').is_file())
            self.manager.stop()
        if args == ('systemctl', 'stop', self.unit):
            self.manager.stop()  # ExecStopPost; second cleanup is idempotent.
            self.active = False
        if args == ('systemctl', 'start', self.unit):
            self.assertEqual(json.loads((self.state / 'live-operation.json').read_text())['phase'], 'coherent')
            if not self.active:  # Real systemd start is a no-op for active oneshot.
                self.manager.start()
                self.active = True
        return ''

    def context(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(op, 'STATE', self.state))
        stack.enter_context(patch.object(op, 'command', side_effect=self.command))
        if os.name != 'posix':
            # Windows refuses unlink of a read-only file. The POSIX Store
            # checks already ran; emulate POSIX unlink after that boundary.
            write = self.store._write
            def posix_unlink(relative, snapshot, *, user=False):
                target = self.root / relative
                if not snapshot['exists'] and target.exists():
                    target.chmod(0o666)
                return write(relative, snapshot, user=user)
            stack.enter_context(patch.object(self.store, '_write', side_effect=posix_unlink))
        return stack

    def test_update_stops_before_replacing_helper_then_restarts_desired_active(self):
        self.install()
        with self.context(), op.live_write(self.store, self.system, [self.unit]) as live:
            self.assertEqual(self.backend.current, binding.STOCK)
            self.assertIsNone(self.backend.record)
            live['after_services'] = live['services']
            self.store.apply(self.files(b'updated helper'), {'version': 'next'}, ['gyro'], 'A')
        self.assertEqual(self.backend.current, binding.CUSTOM)
        self.assertIn(('systemctl', 'stop', self.unit), self.calls)
        self.assertIn(('systemctl', 'start', self.unit), self.calls)

    def test_restore_cleans_binding_before_deleting_helper_and_does_not_start_legacy(self):
        # Original loader is intentionally unsafe to run here; it is preserved
        # as original bytes while binding cleanup uses the installed helper.
        old = self.root / self.prefix / 'unload.sh'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'rmmod oxp3_bmi260\n')
        self.install()
        with self.context(), op.live_write(self.store, self.system, [self.unit]) as live:
            self.assertEqual(self.backend.current, binding.STOCK)
            live['after_services'] = {self.unit: {'active': True, 'enabled': 'enabled'}}
            self.store.restore('A', ['gyro'])
        self.assertFalse((self.root / self.prefix / 'binding.py').exists())
        self.assertEqual(old.read_bytes(), b'rmmod oxp3_bmi260\n')
        self.assertEqual(self.backend.current, binding.STOCK)
        self.assertNotIn(('systemctl', 'start', self.unit), self.calls)

    def test_rollback_to_legacy_does_not_start_old_failed_loader(self):
        self.store.apply({self.prefix + 'unload.sh': self.spec(b'rmmod oxp3_bmi260\n')},
                         {'version': 'old'}, ['gyro'], 'A')
        self.install()
        with self.context(), op.live_write(self.store, self.system, [self.unit]) as live:
            live['after_services'] = live['services']
            self.store.rollback('A')
        self.assertEqual(self.backend.current, binding.STOCK)
        self.assertNotIn(('systemctl', 'start', self.unit), self.calls)

    def test_legacy_service_is_not_stopped(self):
        self.store.apply({self.prefix + 'unload.sh': self.spec(b'rmmod legacy\n')},
                         {'version': 'old'}, ['gyro'], 'A')
        with self.context(), op.live_write(self.store, self.system, [self.unit]):
            pass
        self.assertNotIn(('systemctl', 'stop', self.unit), self.calls)
        self.assertFalse(any(call[0] == '/usr/bin/python3' for call in self.calls))

    def test_inactive_failed_service_still_cleans_pending_binding_without_restart(self):
        self.install()
        self.active = False
        with self.context(), op.live_write(self.store, self.system, [self.unit]):
            self.assertEqual(self.backend.current, binding.STOCK)
        self.assertNotIn(('systemctl', 'start', self.unit), self.calls)

    def test_cleanup_failure_prevents_any_file_replacement(self):
        self.install()
        self.backend.fail.add('unbind-' + binding.CUSTOM)
        with self.context(), self.assertRaises(binding.BindingError):
            with op.live_write(self.store, self.system, [self.unit]):
                self.fail('file writes must not begin')
        self.assertEqual((self.root / self.prefix / 'binding.py').read_bytes(), b'new helper')
        self.assertTrue((self.state / 'live-operation.json').exists())
        self.assertIsNotNone(self.backend.record)

    def test_failed_cleanup_recover_retries_and_restores_prior_active_policy(self):
        self.install()
        # Partial failure leaves the target unbound while the oneshot remains
        # active. A plain systemctl start would be a no-op at this point.
        self.backend.fail.add('bind-' + binding.STOCK)
        with self.context(), self.assertRaises(binding.BindingError):
            with op.live_write(self.store, self.system, [self.unit]):
                self.fail('must not write')
        self.assertIsNone(self.backend.current)
        self.assertTrue(self.active)
        self.assertEqual(self.backend.record['phase'], 'restoring')
        self.backend.fail.clear()
        packages = Mock()
        packages.recover.return_value = {'phase': 'absent'}
        with self.context(), patch.object(op, 'require_root'), patch.object(op, 'trusted_code'), \
                patch.object(op.probe, 'live', return_value=self.system), \
                patch.object(op, 'store_for', return_value=self.store), \
                patch.object(op, 'PackageStore', return_value=packages):
            op.restore(SimpleNamespace(select=[]), recovery=True)
        self.assertFalse((self.state / 'live-operation.json').exists())
        self.assertEqual(self.backend.current, binding.CUSTOM)
        self.assertEqual(self.backend.record['phase'], 'active')
        self.assertIn(('systemctl', 'start', self.unit), self.calls)
        self.assertIn(('bind', binding.STOCK), self.backend.events)
        stop = self.calls.index(('systemctl', 'stop', self.unit))
        start = self.calls.index(('systemctl', 'start', self.unit))
        self.assertLess(stop, start)

    def test_restore_desired_inactive_is_preserved_with_valid_adapter(self):
        self.install()
        with self.context(), op.live_write(self.store, self.system, [self.unit]) as live:
            live['after_services'] = {self.unit: {'active': False, 'enabled': 'disabled'}}
        self.assertEqual(self.backend.current, binding.STOCK)
        self.assertIsNone(self.backend.record)
        self.assertIn(('systemctl', 'disable', self.unit), self.calls)
        self.assertNotIn(('systemctl', 'start', self.unit), self.calls)

    def test_repeated_cleanup_failure_blocks_recovery_file_writes_and_keeps_intent(self):
        self.install()
        self.backend.fail.add('bind-' + binding.STOCK)
        with self.context(), self.assertRaises(binding.BindingError):
            with op.live_write(self.store, self.system, [self.unit]):
                self.fail('must not write')
        with self.context(), patch.object(op, 'require_root'), patch.object(op, 'trusted_code'), \
                patch.object(op.probe, 'live', return_value=self.system), \
                patch.object(op, 'store_for', return_value=self.store), \
                patch.object(self.store, 'recover', wraps=self.store.recover) as recover, \
                self.assertRaises(binding.BindingError):
            op.restore(SimpleNamespace(select=[]), recovery=True)
        recover.assert_not_called()
        record = json.loads((self.state / 'live-operation.json').read_text())
        self.assertTrue(record['gyro_binding_stopped'])
        self.assertFalse(record.get('gyro_binding_quiesced', False))
        self.assertTrue((self.root / self.prefix / 'binding.py').exists())

    def test_completed_cleanup_recovery_does_not_require_removed_helper(self):
        self.install()
        with self.context(), op.live_write(self.store, self.system, [self.unit]) as live:
            self.store.restore('A', ['gyro'])
            saved = dict(live, phase='writing', file_generation=self.store.status()['slots']['A']['current']['id'])
        # Simulate the power loss after file commit and before lifecycle finish.
        (self.state / 'live-operation.json').write_text(json.dumps(saved))
        packages = Mock()
        packages.recover.return_value = {'phase': 'absent'}
        with self.context(), patch.object(op, 'require_root'), patch.object(op, 'trusted_code'), \
                patch.object(op.probe, 'live', return_value=self.system), \
                patch.object(op, 'store_for', return_value=self.store), \
                patch.object(op, 'PackageStore', return_value=packages):
            op.restore(SimpleNamespace(select=[]), recovery=True)
        self.assertFalse((self.state / 'live-operation.json').exists())
        self.assertFalse((self.root / self.prefix / 'binding.py').exists())
        self.assertEqual(self.backend.current, binding.STOCK)
        self.assertNotIn(('systemctl', 'start', self.unit), self.calls)

    def test_drifted_helper_is_not_executed(self):
        self.install()
        helper = self.root / self.prefix / 'binding.py'
        helper.chmod(0o644)
        helper.write_bytes(b'tampered')
        with self.context(), self.assertRaisesRegex(RuntimeError, 'changed'):
            with op.live_write(self.store, self.system, [self.unit]):
                self.fail('must not begin file writes')
        self.assertFalse(any(call[0] == '/usr/bin/python3' for call in self.calls))
        self.assertEqual(self.backend.current, binding.CUSTOM)


if __name__ == '__main__':
    unittest.main()
