"""No device access: exercise fixed-device ownership and recovery transitions."""
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oxp3_maintenance import gyro_binding as binding


class Backend:
    def __init__(self, driver=binding.STOCK):
        self.current = driver
        self.record = None
        self.events = []
        self.fail = set()
        self.autoprobe = False

    def locked(self):
        return nullcontext()

    def guard(self, *, input_version):
        self.events.append(('guard', input_version))
        if 'guard' in self.fail:
            raise binding.BindingError('guard')

    def boot(self):
        return 'test-boot'

    def driver(self):
        return self.current

    def read(self):
        return copy.deepcopy(self.record)

    def save(self, record):
        self.record = copy.deepcopy(record)
        self.events.append(('save', record['phase']))

    def clear(self):
        self.record = None
        self.events.append(('clear',))

    def ensure_custom(self):
        self.events.append(('register',))
        if self.autoprobe and self.current is None:
            self.current = binding.CUSTOM
        if 'register' in self.fail:
            raise binding.BindingError('register')

    def unbind(self, driver):
        self.events.append(('unbind', driver))
        if 'unbind-' + driver in self.fail:
            raise binding.BindingError('unbind')
        assert self.current == driver
        self.current = None

    def bind(self, driver):
        self.events.append(('bind', driver))
        if 'bind-' + driver in self.fail:
            raise binding.BindingError('bind')
        assert self.current is None
        self.current = driver


class BindingTests(unittest.TestCase):
    def test_stock_start_repeat_and_stop_restore_only_target(self):
        backend = Backend()
        manager = binding.BindingManager(backend)
        self.assertEqual(manager.start()['status'], 'active')
        self.assertEqual(backend.current, binding.CUSTOM)
        first = list(backend.events)
        manager.start()
        self.assertEqual([event for event in backend.events[len(first):] if event[0] in ('bind', 'unbind', 'register')], [])
        manager.stop()
        self.assertEqual(backend.current, binding.STOCK)
        self.assertIsNone(backend.record)
        self.assertEqual([event for event in backend.events if event[0] in ('bind', 'unbind')],
                         [('unbind', binding.STOCK), ('bind', binding.CUSTOM),
                          ('unbind', binding.CUSTOM), ('bind', binding.STOCK)])
        self.assertEqual(manager.stop(), {'status': 'unchanged'})

    def test_unbound_autoprobe_is_journaled_and_released_on_stop(self):
        backend = Backend(None)
        backend.autoprobe = True
        manager = binding.BindingManager(backend)
        manager.start()
        self.assertLess(backend.events.index(('save', 'prepared')), backend.events.index(('register',)))
        self.assertIsNone(backend.record['previous'])
        manager.stop()
        self.assertIsNone(backend.current)

    def test_autoprobe_then_registration_error_restores_unbound_state(self):
        backend = Backend(None)
        backend.autoprobe = True
        backend.fail.add('register')
        with self.assertRaisesRegex(binding.BindingError, 'original binding restored'):
            binding.BindingManager(backend).start()
        self.assertIsNone(backend.current)
        self.assertIsNone(backend.record)

    def test_first_journal_failure_prevents_module_loading_and_autoprobe(self):
        backend = Backend(None)
        backend.autoprobe = True
        with patch.object(backend, 'save', side_effect=OSError('disk write failed')):
            with self.assertRaises(OSError):
                binding.BindingManager(backend).start()
        self.assertIsNone(backend.current)
        self.assertNotIn(('register',), backend.events)

    def test_registration_failure_does_not_unbind_stock(self):
        backend = Backend()
        backend.fail.add('register')
        with self.assertRaises(binding.BindingError):
            binding.BindingManager(backend).start()
        self.assertEqual(backend.current, binding.STOCK)
        self.assertFalse(any(event[0] == 'unbind' for event in backend.events))
        self.assertIsNone(backend.record)

    def test_bind_failure_restores_stock(self):
        backend = Backend()
        backend.fail.add('bind-' + binding.CUSTOM)
        with self.assertRaisesRegex(binding.BindingError, 'original binding restored'):
            binding.BindingManager(backend).start()
        self.assertEqual(backend.current, binding.STOCK)
        self.assertIsNone(backend.record)

    def test_failed_recovery_preserves_record_for_stop_retry(self):
        backend = Backend()
        backend.fail.update(('bind-' + binding.CUSTOM, 'bind-' + binding.STOCK))
        manager = binding.BindingManager(backend)
        with self.assertRaisesRegex(binding.BindingError, 'needs recovery'):
            manager.start()
        self.assertEqual(backend.record['phase'], 'restoring')
        self.assertIsNone(backend.current)
        backend.fail.clear()
        manager.stop()
        self.assertEqual(backend.current, binding.STOCK)
        self.assertIsNone(backend.record)

    def test_interrupted_custom_binding_becomes_active_and_restores(self):
        backend = Backend(binding.CUSTOM)
        backend.record = {'schema': 1, 'boot': backend.boot(), 'kernel': binding.KERNEL,
                          'device': binding.DEVICE, 'previous': binding.STOCK, 'phase': 'prepared'}
        manager = binding.BindingManager(backend)
        manager.start()
        self.assertEqual(backend.record['phase'], 'active')
        manager.stop()
        self.assertEqual(backend.current, binding.STOCK)

    def test_preexisting_custom_is_not_claimed_or_detached(self):
        backend = Backend(binding.CUSTOM)
        manager = binding.BindingManager(backend)
        self.assertEqual(manager.start()['status'], 'preexisting')
        manager.stop()
        self.assertIsNone(backend.record)
        self.assertEqual(backend.current, binding.CUSTOM)

    def test_unknown_driver_or_guard_failure_makes_no_binding_changes(self):
        for backend in (Backend('unrecognized'), Backend()):
            if backend.current == binding.STOCK:
                backend.fail.add('guard')
            with self.subTest(driver=backend.current), self.assertRaises(binding.BindingError):
                binding.BindingManager(backend).start()
            self.assertIsNone(backend.record)
            self.assertFalse(any(event[0] in ('bind', 'unbind', 'register') for event in backend.events))

    def test_stale_or_malformed_record_is_preserved_without_writes(self):
        for change in ({'boot': 'other'}, {'previous': 'unknown'}, {'schema': True}, {'device': 'other'}):
            backend = Backend()
            backend.record = {'schema': 1, 'boot': backend.boot(), 'kernel': binding.KERNEL,
                              'device': binding.DEVICE, 'previous': binding.STOCK, 'phase': 'active', **change}
            before = copy.deepcopy(backend.record)
            with self.subTest(change=change), self.assertRaises(binding.BindingError):
                binding.BindingManager(backend).stop()
            self.assertEqual(backend.record, before)
            self.assertEqual(backend.events, [])

    def test_stop_does_not_require_inputplumber_version(self):
        backend = Backend()
        manager = binding.BindingManager(backend)
        manager.start()
        manager.stop()
        self.assertIn(('guard', False), backend.events)

    def test_cli_does_not_accept_driver_or_sysfs_paths(self):
        for argv in ([], ['start', '/sys/other'], ['bind'], ['stop', binding.STOCK]):
            with self.subTest(argv=argv), patch.object(binding, 'SystemBackend') as backend:
                with self.assertRaises(binding.BindingError):
                    binding.main(argv)
                backend.assert_not_called()


if __name__ == '__main__':
    unittest.main()
