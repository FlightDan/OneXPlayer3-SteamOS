"""Isolated OS-update policy tests; no service commands or device access."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import system_update_policy as policy

if os.name == 'posix':
    from file_transaction import FileTransaction


class PolicyChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Permit non-root developers to exercise isolated fixture roots. The
        # production root-ownership constant remains zero.
        fixture_uid = os.geteuid() if hasattr(os, 'geteuid') else 0
        self.uid_guard = patch.object(policy, '_ROOT_UID', fixture_uid)
        self.uid_guard.start()
        self.addCleanup(self.uid_guard.stop)
        for service in policy.SERVICES:
            self.put('usr/lib/systemd/system/' + service,
                     ('[Service]\nExecStart=/usr/bin/' + service[:-8] + '\n').encode())

    def put(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def stage(self):
        output = policy.files(self.root)
        for relative, entry in output.items():
            self.put(relative, entry['data'])
        return output

    def link(self, relative, target, directory=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest('Fixture symlinks unavailable: ' + str(error))
        return path

    def test_policy_is_only_two_os_masks_and_marker(self):
        sentinel = {
            'usr/bin/steam': b'steam client executable',
            'home/deck/.steam/steam/config/config.vdf': b'client update config',
            'home/deck/.steam/steam/steamapps/appmanifest_10.acf': b'game update config',
        }
        for relative, data in sentinel.items():
            self.put(relative, data)
        output = policy.files(self.root)
        self.assertEqual(set(output), {
            'etc/systemd/system/atomupd.service',
            'etc/systemd/system/rauc.service', policy.MARKER})
        for service in policy.SERVICES:
            self.assertEqual(output['etc/systemd/system/' + service],
                             {'data': b'', 'mode': 0o644})
        marker = json.loads(output[policy.MARKER]['data'])
        self.assertEqual(marker['services'], list(policy.SERVICES))
        self.assertEqual(marker['steam_client_updates'], 'unchanged')
        self.assertEqual(marker['steam_game_updates'], 'unchanged')
        for relative, data in sentinel.items():
            self.assertEqual((self.root / relative).read_bytes(), data)
        self.assertFalse((self.root / 'etc/systemd/system/atomupd.service').exists())
        self.assertFalse((self.root / policy.MARKER).exists())

    def test_staged_policy_verifies_and_retry_is_deterministic(self):
        output = self.stage()
        result = policy.verify(self.root)
        self.assertTrue(result['paused'])
        self.assertTrue(result['recorded'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(policy.files(self.root), output)

    def test_missing_vendor_service_fails_before_mutation(self):
        (self.root / 'usr/lib/systemd/system/rauc.service').unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing: rauc.service'):
            policy.files(self.root)
        self.assertFalse((self.root / 'etc').exists())

    def test_empty_vendor_unit_is_not_a_supported_update_service(self):
        self.put('usr/lib/systemd/system/atomupd.service', b'')
        with self.assertRaisesRegex(RuntimeError, 'missing: atomupd.service'):
            policy.files(self.root)

    def test_existing_custom_override_is_preserved(self):
        path = self.put('etc/systemd/system/rauc.service', b'[Service]\nExecStart=/custom\n')
        with self.assertRaisesRegex(RuntimeError, 'Conflicting'):
            policy.files(self.root)
        self.assertEqual(path.read_bytes(), b'[Service]\nExecStart=/custom\n')
        self.assertFalse((self.root / 'etc/systemd/system/atomupd.service').exists())

    def test_existing_regular_empty_masks_are_accepted(self):
        for service in policy.SERVICES:
            self.put('etc/systemd/system/' + service, b'')
        self.assertEqual(len(policy.files(self.root)), 3)

    def test_directory_instead_of_unit_is_refused(self):
        (self.root / 'etc/systemd/system/atomupd.service').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'Conflicting'):
            policy.files(self.root)

    def test_existing_marker_conflict_is_preserved(self):
        path = self.put(policy.MARKER, b'{"policy": "personal"}\n')
        with self.assertRaisesRegex(RuntimeError, 'Conflicting.*marker'):
            policy.files(self.root)
        self.assertEqual(path.read_bytes(), b'{"policy": "personal"}\n')

    def test_status_reports_partial_mask_without_claiming_pause(self):
        self.put('etc/systemd/system/atomupd.service', b'')
        result = policy.status(self.root)
        self.assertFalse(result['paused'])
        self.assertTrue(result['services']['atomupd.service']['masked'])
        self.assertFalse(result['services']['rauc.service']['masked'])
        self.assertFalse(result['recorded'])
        with self.assertRaisesRegex(RuntimeError, 'rauc.service'):
            policy.verify(self.root)

    def test_changed_mask_is_detected_without_writing(self):
        self.stage()
        path = self.put('etc/systemd/system/rauc.service', b'[Service]\n')
        result = policy.status(self.root)
        self.assertFalse(result['paused'])
        self.assertFalse(result['services']['rauc.service']['masked'])
        self.assertEqual(path.read_bytes(), b'[Service]\n')

    def test_changed_marker_is_detected(self):
        self.stage()
        self.put(policy.MARKER, b'{"schema": 1}\n')
        self.assertFalse(policy.status(self.root)['recorded'])
        with self.assertRaisesRegex(RuntimeError, 'marker'):
            policy.verify(self.root)

    def test_missing_vendor_after_staging_is_not_verified(self):
        self.stage()
        (self.root / 'usr/lib/systemd/system/rauc.service').unlink()
        result = policy.status(self.root)
        self.assertFalse(result['paused'])
        self.assertIn('SteamOS OS update service is missing: rauc.service', result['errors'])

    def test_vendor_symlink_is_refused(self):
        path = self.root / 'usr/lib/systemd/system/atomupd.service'
        path.unlink()
        self.link('usr/lib/systemd/system/atomupd.service', 'rauc.service')
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
            policy.files(self.root)

    def test_mask_symlink_is_refused_without_changing_target(self):
        target = self.put('sentinel', b'untouched')
        self.link('etc/systemd/system/atomupd.service', target)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
            policy.files(self.root)
        self.assertEqual(target.read_bytes(), b'untouched')

    def test_symlink_ancestor_is_refused_by_generation_and_status(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        self.link('etc', target, directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
            policy.files(self.root)
        self.assertFalse(policy.status(self.root)['paused'])
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'Unix permissions required')
    def test_writable_privileged_ancestor_is_refused(self):
        directory = self.root / 'etc/systemd/system'
        directory.mkdir(parents=True)
        directory.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'permissions'):
            policy.files(self.root)

    @unittest.skipUnless(os.name == 'posix', 'Unix ownership required')
    def test_wrong_owner_is_refused(self):
        with patch.object(policy, '_ROOT_UID', os.geteuid() + 1):
            with self.assertRaisesRegex(RuntimeError, 'permissions'):
                policy.files(self.root)

    @unittest.skipUnless(os.name == 'posix', 'Linux journal requires fcntl')
    def test_journal_restores_absence_and_retains_preexisting_mask(self):
        existing = self.put('etc/systemd/system/atomupd.service', b'')
        existing.chmod(0o640)
        output = policy.files(self.root)
        for relative in output:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        transaction = FileTransaction(self.root / 'journal',
                                      [self.root / relative for relative in output])
        changes = {str(self.root / relative): entry['data'] for relative, entry in output.items()}
        transaction.apply(changes)
        transaction.apply(changes)
        policy.verify(self.root)
        self.assertEqual(transaction.rollback(), [])
        self.assertEqual(existing.read_bytes(), b'')
        self.assertEqual(existing.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.root / 'etc/systemd/system/rauc.service').exists())
        self.assertFalse((self.root / policy.MARKER).exists())
        self.assertFalse(policy.status(self.root)['paused'])

    @unittest.skipUnless(os.name == 'posix', 'Linux journal requires fcntl')
    def test_journal_restore_preserves_later_manual_edits(self):
        output = policy.files(self.root)
        for relative in output:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        transaction = FileTransaction(self.root / 'journal',
                                      [self.root / relative for relative in output])
        transaction.apply({str(self.root / relative): entry['data']
                           for relative, entry in output.items()})
        changed = self.put('etc/systemd/system/rauc.service', b'[Service]\nExecStart=/personal\n')
        errors = transaction.rollback()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['path'], str(changed))
        self.assertEqual(changed.read_bytes(), b'[Service]\nExecStart=/personal\n')
        self.assertFalse((self.root / 'etc/systemd/system/atomupd.service').exists())


if __name__ == '__main__':
    unittest.main()
