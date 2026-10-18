"""Persistence optimizations keep the original transaction disk protocol."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oxp3_maintenance.transactions import Store, TransactionError
from oxp3_maintenance import state_io


class StoreRecordIO(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'root'
        self.root.mkdir()
        self.state = base / 'state'
        self.store = Store(self.root, self.state, enforce_owner=False)

    def test_saved_records_remain_byte_compatible_with_legacy_json(self):
        value = {'format': 1, 'slots': {}, 'originals': {}, 'next_generation': 1,
                 'unicode': '\u4e2d\u6587\U0001f600', 'escaped': '\n\\"',
                 'data': base64.b64encode(bytes(range(256)) * 1024).decode()}
        expected = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        with self.store.lock():
            self.store._state_write('index.json', value)
            self.assertEqual((self.state / 'index.json').read_bytes(), expected)
            # This is exactly the old reader protocol, including full backups.
            with (self.state / 'index.json').open(encoding='utf-8') as stream:
                self.assertEqual(json.load(stream), value)
            self.assertEqual(self.store._state_read('index.json'), value)

    def test_long_identical_snapshot_strings_share_read_memory(self):
        data = base64.b64encode(b'snapshot bytes' * 8192).decode()
        value = {'current': {'data': data}, 'previous': {'data': data},
                 'original': {'data': data}}
        with self.store.lock():
            self.store._state_write('index.json', value)
            result = self.store._state_read('index.json')
        self.assertEqual(result, value)
        self.assertIs(result['current']['data'], result['previous']['data'])
        self.assertIs(result['current']['data'], result['original']['data'])

    def test_duplicate_keys_in_existing_record_fail_closed(self):
        with self.store.lock():
            (self.state / 'index.json').write_bytes(b'{"format":1,"slots":{},"slots":{}}')
            with self.assertRaises(TransactionError):
                self.store._state_read('index.json')
        self.assertFalse((self.state / 'pending.json').exists())

    def test_partial_serialization_failure_preserves_old_record(self):
        before = {'format': 1, 'safe': 'old record'}
        with self.store.lock():
            self.store._state_write('index.json', before)
            def fail(value, stream):
                stream.write(b'{"unfinished":')
                raise OSError('injected write failure')
            with patch('oxp3_maintenance.state_io.dump', fail):
                with self.assertRaises(OSError):
                    self.store._state_write('index.json', {'new': 'value'})
            self.assertEqual(self.store._state_read('index.json'), before)
        self.assertFalse(list(self.state.glob('.tmp-*')))

    def test_whole_document_dumps_is_not_used_for_persistence(self):
        with self.store.lock(), patch('json.dumps', side_effect=AssertionError('whole record encoding')):
            self.store._state_write('pending.json', {'format': 1, 'data': 'A' * 200000})
        self.assertEqual(json.loads((self.state / 'pending.json').read_bytes())['format'], 1)

    def test_pending_budget_rejection_keeps_target_and_previous_backups(self):
        relative = 'etc/record-test'
        original = self.root / relative
        original.parent.mkdir()
        original.write_bytes(b'original')
        def spec(data):
            return {'data': data, 'component': 'fixture', 'mode': 0o644}
        self.store.apply({relative: spec(b'first')}, {'version':'1'}, ['fixture'], 'A')
        baseline = (self.state / 'index.json').read_bytes()
        real_dump = state_io.dump
        for limit in ('MAX_BYTES', 'MAX_METADATA'):
            def limited_dump(value, stream):
                with patch.object(state_io, limit, 128):
                    real_dump(value, stream)
            with self.subTest(limit=limit), patch.object(state_io, 'dump', limited_dump):
                with self.assertRaises(ValueError):
                    self.store.apply({relative: spec(b'second')}, {'version':'2'}, ['fixture'], 'A')
            self.assertEqual(original.read_bytes(), b'first')
            self.assertEqual((self.state / 'index.json').read_bytes(), baseline)
            self.assertFalse((self.state / 'pending.json').exists())
            self.assertFalse(list(self.state.glob('.tmp-*')))
        self.store.restore('A')
        self.assertEqual(original.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
