import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from directory_transaction import DirectoryTransaction


class DirectoryRecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / 'code'; self.store.mkdir()
        self.destination = self.store / 'plugins' / 'selected'
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'main.py').write_bytes(b'new plugin code')
        self.transaction = DirectoryTransaction(self.root / 'state', self.destination, self.store)

    def tearDown(self): self.temporary.cleanup()

    def test_repeat_and_restore_original_directory(self):
        self.destination.mkdir(); (self.destination / 'existing.conf').write_bytes(b'original')
        (self.store / 'unrelated').mkdir(); (self.store / 'unrelated' / 'keep').write_bytes(b'keep')
        self.transaction.apply(self.source); self.transaction.apply(self.source)
        self.transaction.rollback(); self.transaction.rollback()
        self.assertEqual((self.destination / 'existing.conf').read_bytes(), b'original')
        self.assertEqual((self.store / 'unrelated' / 'keep').read_bytes(), b'keep')

    def test_restore_absent_directory(self):
        self.transaction.apply(self.source); self.transaction.rollback()
        self.assertFalse(self.destination.exists())

    def test_manual_change_is_preserved(self):
        self.transaction.apply(self.source)
        (self.destination / 'main.py').write_bytes(b'local edit')
        with self.assertRaises(RuntimeError): self.transaction.rollback()
        with self.assertRaises(RuntimeError): self.transaction.apply(self.source)
        self.assertEqual((self.destination / 'main.py').read_bytes(), b'local edit')

    def test_interrupted_swap_restores_the_original(self):
        self.destination.mkdir(); (self.destination / 'original').write_bytes(b'old')
        import directory_transaction
        real = directory_transaction.os.rename
        def interrupt(source, destination):
            if Path(source).name == 'staged': raise OSError('injected interruption')
            return real(source, destination)
        with patch('directory_transaction.os.rename', interrupt):
            with self.assertRaises(OSError): self.transaction.apply(self.source)
        self.transaction.rollback()
        self.assertEqual((self.destination / 'original').read_bytes(), b'old')

    def test_links_and_escape_are_rejected(self):
        (self.source / 'link').symlink_to(self.root / 'outside')
        with self.assertRaises(RuntimeError): self.transaction.apply(self.source)
        with self.assertRaises(RuntimeError): DirectoryTransaction(self.root / 'other-state', self.root / 'outside', self.store)
        with self.assertRaises(RuntimeError): DirectoryTransaction(self.root / 'other-state', self.store / '..' / 'outside', self.store)


if __name__ == '__main__': unittest.main()
