"""Fixture-only transaction and restart-recovery tests; never touch a display."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import hdr_trial as hdr


class Backend:
    def __init__(self):
        self.current = {'hdr': False, 'wcg': False}
        self.saved = True
        self.fail_restore = False
        self.enables = 0
        self.restores = []

    def flags(self): return dict(self.current)
    def persisted_enabled(self): return self.saved
    def check(self): pass
    def enable(self):
        self.enables += 1
        self.current = {'hdr': True, 'wcg': True}
    def restore(self, flags):
        self.restores.append(dict(flags))
        if self.fail_restore: raise RuntimeError('compositor disconnected')
        self.current = dict(flags)


class TrialTests(unittest.TestCase):
    def test_component_removal_interlock_blocks_new_trial(self):
        with self.journal.lock():
            hdr.write_json(self.journal.directory / 'disabled.json', {'schema': 1})
        with self.assertRaisesRegex(RuntimeError, 'disabled during component restore'):
            self.trial.begin()
        self.assertEqual(self.backend.enables, 0)
        self.assertIsNone(self.journal.read())

    def test_null_journal_is_corrupt_and_preserved(self):
        with self.journal.lock():
            hdr.write_json(self.journal.path, None)
        with self.assertRaisesRegex(RuntimeError, 'Invalid HDR trial journal'):
            self.trial.begin()
        self.assertIsNone(json.loads(self.journal.path.read_text(encoding='utf8')))

    def test_null_saved_config_preserves_pending_startup_recovery(self):
        self.trial.begin()
        config = self.home / 'kwinoutputconfig.json'
        config.write_text('null', encoding='utf8')
        with self.assertRaisesRegex(RuntimeError, 'Invalid KWin output settings'):
            hdr.recover_startup(self.journal, config)
        self.assertEqual(self.journal.read()['phase'], 'armed')
        self.assertEqual(config.read_text(encoding='utf8'), 'null')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.journal = hdr.Journal(self.home / 'state')
        self.backend = Backend()
        self.now = 100.0
        self.trial = hdr.Trial(self.journal, self.backend, lambda: self.now, boot='fixture-boot')

    def visible(self):
        token = self.trial.begin()
        self.trial.arm_guard(token)
        self.trial.request_enable(token)
        self.backend.enable()
        self.trial.activated(token)
        self.trial.visible(token)
        return token

    def config(self):
        path = self.home / 'kwinoutputconfig.json'
        value = [{'name': 'outputs', 'data': [
            {'connectorName': 'eDP-1', 'highDynamicRange': True, 'wideColorGamut': True,
             'brightness': 0.6, 'scale': 1.5},
            {'connectorName': 'DP-1', 'highDynamicRange': True, 'wideColorGamut': False},
        ]}, {'name': 'other', 'data': ['keep']}]
        path.write_text(json.dumps(value), encoding='utf8')
        return path, value

    def test_confirmation_requires_detached_guard_and_first_frame(self):
        token = self.trial.begin()
        self.backend.enable()
        self.assertFalse(self.trial.guarded(token))
        self.assertFalse(self.trial.confirm(token))
        with self.assertRaisesRegex(RuntimeError, 'first HDR frame'):
            self.trial.visible(token)
        self.trial.arm_guard(token)
        self.assertTrue(self.trial.guarded(token))
        self.assertFalse(self.trial.confirm(token))
        self.trial.request_enable(token)
        self.trial.activated(token)
        self.trial.visible(token)
        self.assertTrue(self.trial.confirm(token))

    def test_confirmed_trial_survives_watchdog_and_startup(self):
        token = self.visible()
        self.assertTrue(self.trial.confirm(token))
        self.now += 20
        self.assertTrue(self.trial.rollback(token))
        config, _ = self.config()
        original = config.read_bytes()
        hdr.recover_startup(self.journal, config)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(self.journal.read()['phase'], 'confirmed')
        self.assertEqual(self.backend.restores, [])

    def test_confirmation_at_deadline_is_rejected(self):
        token = self.visible()
        self.now += 10
        self.assertFalse(self.trial.confirm(token))
        self.assertTrue(self.trial.rollback(token))
        self.assertEqual(self.backend.current, {'hdr': False, 'wcg': False})
        self.assertEqual(self.journal.read()['phase'], 'reverted')

    def test_live_on_without_persisted_settings_cannot_be_confirmed(self):
        token = self.visible()
        self.backend.saved = False
        self.assertFalse(self.trial.confirm(token))
        self.assertEqual(self.journal.read()['phase'], 'visible')

    def test_cancel_restores_original_flags_without_changing_other_settings(self):
        self.backend.current = {'hdr': False, 'wcg': True}
        token = self.visible()
        self.assertTrue(self.trial.rollback(token))
        self.assertTrue(self.trial.rollback(token))
        self.assertEqual(self.backend.restores, [{'hdr': False, 'wcg': True}])

    def test_stale_token_cannot_confirm_or_revert_a_new_trial(self):
        token = self.visible()
        self.assertFalse(self.trial.confirm('0' * 32))
        self.trial.rollback('0' * 32)
        self.assertEqual(self.journal.read()['token'], token)
        self.assertEqual(self.backend.restores, [])

    def test_pending_trial_blocks_another_start(self):
        self.visible()
        with self.assertRaisesRegex(RuntimeError, 'needs recovery'):
            self.trial.begin()

    def test_failed_rollback_stays_pending_until_startup_recovery(self):
        token = self.visible()
        self.backend.fail_restore = True
        self.assertFalse(self.trial.rollback(token))
        self.assertEqual(self.journal.read()['phase'], 'rollback_failed')
        config, original = self.config()
        hdr.recover_startup(self.journal, config)
        changed = json.loads(config.read_text(encoding='utf8'))
        original[0]['data'][0].update(highDynamicRange=False, wideColorGamut=False)
        self.assertEqual(changed, original)
        self.assertEqual(self.journal.read()['phase'], 'reverted')

    def test_startup_restores_only_internal_flags_and_is_idempotent(self):
        self.visible()
        config, expected = self.config()
        hdr.recover_startup(self.journal, config)
        expected[0]['data'][0].update(highDynamicRange=False, wideColorGamut=False)
        self.assertEqual(json.loads(config.read_text(encoding='utf8')), expected)
        data = config.read_bytes()
        hdr.recover_startup(self.journal, config)
        self.assertEqual(config.read_bytes(), data)

    def test_corrupt_output_config_is_preserved_with_pending_recovery(self):
        self.visible()
        path = self.home / 'kwinoutputconfig.json'
        path.write_text('invalid', encoding='utf8')
        with self.assertRaises(ValueError):
            hdr.recover_startup(self.journal, path)
        self.assertEqual(path.read_text(encoding='utf8'), 'invalid')
        self.assertEqual(self.journal.read()['phase'], 'visible')

    def test_missing_internal_output_is_not_silently_accepted(self):
        self.visible()
        path = self.home / 'kwinoutputconfig.json'
        path.write_text('[]', encoding='utf8')
        with self.assertRaisesRegex(RuntimeError, 'no internal output'):
            hdr.recover_startup(self.journal, path)
        self.assertEqual(self.journal.read()['phase'], 'visible')

    def test_different_boot_cannot_confirm(self):
        token = self.visible()
        self.trial.boot = 'next-boot'
        self.assertFalse(self.trial.confirm(token))

    def test_guard_start_failure_never_enables_hdr(self):
        with patch.object(hdr, 'KDE', return_value=self.backend), \
             patch.object(hdr, 'Trial', return_value=self.trial), \
             patch.object(hdr.subprocess, 'run'), \
             patch.object(hdr.time, 'sleep'), \
             patch.object(hdr, 'detached_guard', side_effect=RuntimeError('cannot arm guard')):
            with self.assertRaisesRegex(RuntimeError, 'cannot arm guard'):
                hdr.run_trial(self.home, self.journal)
        self.assertEqual(self.backend.enables, 0)
        self.assertEqual(self.journal.read()['phase'], 'reverted')

    def test_late_ui_cannot_request_activation_after_guard_expired(self):
        token = self.trial.begin()
        self.trial.arm_guard(token)
        self.now += 10
        self.trial.rollback(token)
        with self.assertRaisesRegex(RuntimeError, 'unavailable or expired'):
            self.trial.request_enable(token)
        self.assertEqual(self.backend.enables, 0)

    def test_cancel_only_requests_single_owner_restore(self):
        token = self.visible()
        self.trial.cancel(token)
        self.assertEqual(self.journal.read()['phase'], 'reverting')
        self.assertEqual(self.backend.restores, [])
        with self.assertRaisesRegex(RuntimeError, 'needs recovery'):
            self.trial.begin()
        self.trial.rollback(token)
        self.assertEqual(self.backend.restores, [{'hdr': False, 'wcg': False}])

    def test_second_guard_cannot_take_ownership(self):
        token = self.trial.begin()
        self.trial.arm_guard(token)
        with self.assertRaisesRegex(RuntimeError, 'guard token/state changed'):
            self.trial.arm_guard(token)

    def test_watchdog_restores_late_activation_before_terminal_state(self):
        token = self.trial.begin()
        arm = self.trial.arm_guard
        def ready(value):
            arm(value)
            self.trial.request_enable(value)
        def late_enable():
            self.backend.current = {'hdr': True, 'wcg': True}
            self.now += 11
        with patch.object(self.trial, 'arm_guard', side_effect=ready), \
             patch.object(self.backend, 'enable', side_effect=late_enable):
            with self.assertRaisesRegex(RuntimeError, 'cancelled or expired'):
                self.trial.watchdog(token)
        self.assertEqual(self.backend.current, {'hdr': False, 'wcg': False})
        self.assertEqual(len(self.backend.restores), 1)
        self.assertEqual(self.journal.read()['phase'], 'reverted')

    def test_watchdog_serializes_cancel_during_activation(self):
        token = self.trial.begin()
        arm = self.trial.arm_guard
        def ready(value):
            arm(value)
            self.trial.request_enable(value)
        def cancelled_enable():
            self.trial.cancel(token)
            with self.assertRaisesRegex(RuntimeError, 'needs recovery'):
                self.trial.begin()
            self.backend.current = {'hdr': True, 'wcg': True}
        with patch.object(self.trial, 'arm_guard', side_effect=ready), \
             patch.object(self.backend, 'enable', side_effect=cancelled_enable):
            with self.assertRaisesRegex(RuntimeError, 'cancelled or expired'):
                self.trial.watchdog(token)
        self.assertEqual(len(self.backend.restores), 1)
        self.assertEqual(self.backend.current, {'hdr': False, 'wcg': False})
        self.assertEqual(self.journal.read()['phase'], 'reverted')

    def test_external_output_blocks_trial_but_not_recovery_readback(self):
        value = {'outputs': [{'name': 'eDP-1', 'enabled': True, 'hdr': False, 'wcg': False},
                             {'name': 'DP-1', 'enabled': True, 'hdr': False, 'wcg': False}]}
        with self.assertRaisesRegex(RuntimeError, 'external displays'):
            hdr.output_flags(value)
        self.assertEqual(hdr.output_flags(value, False), {'hdr': False, 'wcg': False})

    def test_live_restore_without_disk_restore_stays_pending(self):
        token = self.visible()
        kde = hdr.KDE(self.home)
        with patch.object(kde, 'command'), patch.object(kde, 'flags', return_value={'hdr': False, 'wcg': False}), \
             patch.object(kde, 'persisted_matches', return_value=False), \
             patch.object(hdr.time, 'sleep'), patch.object(hdr.time, 'monotonic', side_effect=[0, 1]):
            self.trial.backend = kde
            self.assertFalse(self.trial.rollback(token))
        self.assertEqual(self.journal.read()['phase'], 'rollback_failed')

    def test_unknown_or_ambiguous_kscreen_state_is_rejected(self):
        for value in ({}, {'outputs': [{'name': 'eDP-1', 'enabled': True, 'hdr': 'true', 'wcg': False}]},
                      {'outputs': [{'name': 'eDP-1', 'enabled': False, 'hdr': False, 'wcg': False}]}):
            with self.subTest(value=value), self.assertRaises(RuntimeError): hdr.output_flags(value)

    def test_journal_symlink_is_rejected_without_touching_target(self):
        self.trial.begin()
        target = self.home / 'target.json'
        target.write_text('{}', encoding='utf8')
        self.journal.path.unlink()
        try: self.journal.path.symlink_to(target)
        except OSError as error: self.skipTest(str(error))
        with self.assertRaisesRegex(RuntimeError, 'Linked'):
            self.journal.read()
        self.assertEqual(target.read_text(encoding='utf8'), '{}')

    def test_nonfinite_deadline_is_rejected(self):
        self.trial.begin()
        value = self.journal.read()
        value['deadline'] = float('inf')
        self.journal.save(value)
        with self.assertRaisesRegex(RuntimeError, 'Invalid HDR trial journal'):
            self.journal.read()


if __name__ == '__main__': unittest.main()
