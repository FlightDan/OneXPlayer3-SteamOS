import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from file_transaction import FileTransaction
import file_transaction
import fcntl


class RecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.first, self.second = self.root / 'existing.conf', self.root / 'new.conf'
        self.first.write_bytes(b'original')
        self.transaction = FileTransaction(self.root / 'state', [self.first, self.second])
        self.changes = {str(self.first): b'installed', str(self.second): b'new'}

    def tearDown(self):
        self.temporary.cleanup()

    def test_repeat_preserves_first_snapshot_and_restores_absence(self):
        self.transaction.apply(self.changes)
        self.transaction.apply(self.changes)
        self.assertEqual(self.transaction.rollback(), [])
        self.assertEqual(self.first.read_bytes(), b'original')
        self.assertFalse(self.second.exists())

    def test_partial_failure_can_restore_every_changed_file(self):
        real = file_transaction.atomic_write
        def fail_second(path, *args, **kwargs):
            if Path(path) == self.second:
                raise OSError('injected write failure')
            return real(path, *args, **kwargs)
        with patch('file_transaction.atomic_write', fail_second):
            with self.assertRaises(OSError): self.transaction.apply(self.changes)
        self.assertEqual(self.transaction.rollback(), [])
        self.assertEqual(self.first.read_bytes(), b'original')
        self.assertFalse(self.second.exists())

    def test_restore_conflict_does_not_stop_other_restorations(self):
        self.transaction.apply(self.changes)
        self.first.write_bytes(b'user edit')
        errors = self.transaction.rollback()
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.first.read_bytes(), b'user edit')
        self.assertFalse(self.second.exists())
        self.first.write_bytes(b'installed')
        self.assertEqual(self.transaction.rollback(), [])

    def test_symlink_baseline_is_rejected(self):
        if not hasattr(os, 'symlink'): self.skipTest('symlinks unavailable')
        self.second.symlink_to(self.first)
        with self.assertRaises(RuntimeError): self.transaction.apply(self.changes)
        self.assertEqual(self.first.read_bytes(), b'original')

    def test_ancestor_symlink_is_rejected(self):
        link = self.root / 'redirect'
        link.symlink_to(self.root, target_is_directory=True)
        redirected = link / self.first.name
        transaction = FileTransaction(self.root / 'other-state', [redirected])
        with self.assertRaises(OSError): transaction.apply({str(redirected): b'unsafe'})
        self.assertEqual(self.first.read_bytes(), b'original')

    def test_existing_permissions_are_preserved(self):
        self.first.chmod(0o640)
        self.transaction.apply(self.changes)
        self.assertEqual(self.first.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.transaction.rollback(), [])
        self.assertEqual(self.first.stat().st_mode & 0o777, 0o640)

    def test_concurrent_operation_is_rejected(self):
        with open(self.transaction.directory / '.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.transaction.apply(self.changes)
        self.assertEqual(self.first.read_bytes(), b'original')

    def test_retry_refuses_manual_edits_before_any_file_changes(self):
        self.transaction.apply(self.changes)
        self.second.write_bytes(b'personal change')
        with self.assertRaises(RuntimeError):
            self.transaction.apply({str(self.first): b'updated', str(self.second): b'updated too'})
        self.assertEqual(self.first.read_bytes(), b'installed')
        self.assertEqual(self.second.read_bytes(), b'personal change')

    def test_failed_update_can_restore_previous_installed_content(self):
        self.transaction.apply(self.changes)
        real = file_transaction.atomic_write
        def fail_config(path, *args, **kwargs):
            if Path(path) == self.first: raise OSError('update interrupted before write')
            return real(path, *args, **kwargs)
        with patch('file_transaction.atomic_write', fail_config):
            with self.assertRaises(OSError):
                self.transaction.apply({str(self.first): b'new version', str(self.second): b'new version too'})
        self.assertEqual(self.transaction.rollback(), [])
        self.assertEqual(self.first.read_bytes(), b'original')
        self.assertFalse(self.second.exists())

    def test_later_permission_change_is_preserved_and_other_files_restore(self):
        self.transaction.apply(self.changes)
        self.first.chmod(0o600)
        with self.assertRaises(RuntimeError): self.transaction.apply(self.changes)
        errors = self.transaction.rollback()
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.first.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.first.read_bytes(), b'installed')
        self.assertFalse(self.second.exists())


if __name__ == '__main__': unittest.main()
