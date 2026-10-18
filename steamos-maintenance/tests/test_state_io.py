import base64
import hashlib
import io
import json
import math
import random
import tracemalloc
import unittest
from unittest import mock

from oxp3_maintenance import state_io


class BoundedReader(io.BytesIO):
    def __init__(self, data, step=state_io.CHUNK_SIZE):
        super().__init__(data)
        self.step = step
        self.calls = 0

    def read(self, amount=-1):
        if not 0 <= amount <= state_io.CHUNK_SIZE:
            raise AssertionError('unbounded read')
        self.calls += 1
        return super().read(min(amount, self.step))


class BoundedWriter(io.BytesIO):
    def write(self, data):
        if not isinstance(data, bytes) or len(data) > state_io.CHUNK_SIZE:
            raise AssertionError('unbounded or nonbinary write')
        return super().write(data)


def document(payload='YQ==', **extra):
    snapshot = {'exists': True, 'data': payload, 'mode': 420, 'uid': 0, 'gid': 0}
    current = {'selected': ['one'], 'legacy_adopted': ['old'],
               'paths': {'etc/example': {'component': 'one', 'mutable': False,
                                         'snapshot': snapshot, 'user': False}},
               'release': {'version': 'example'}}
    result = {'format': 1, 'slots': {'B': {'current': current, 'previous': None}},
              'originals': {}, 'next_generation': 2}
    result.update(extra)
    return result


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class StateIOTests(unittest.TestCase):
    def test_full_load_matches_standard_decoder_with_bounded_binary_reads(self):
        value = document(base64.b64encode(bytes(range(256)) * 1024).decode())
        value['extra'] = ['quote"slash\\\n', '中文 😀', 0, -3, 1.25, True, False, None]
        for step in (1, 7, 4093, state_io.CHUNK_SIZE):
            with self.subTest(step=step):
                stream = BoundedReader(encoded(value), step)
                self.assertEqual(state_io.load(stream), value)
                self.assertGreater(stream.calls, 1)

    def test_text_stream_and_raw_utf8_cross_boundaries(self):
        text = '{"values":["中文😀","a\\tb\\/c","\\ud834\\udd1e"]}'
        self.assertEqual(state_io.load(io.StringIO(text)), json.loads(text))
        for step in range(1, 9):
            self.assertEqual(state_io.load(BoundedReader(text.encode(), step)), json.loads(text))

    def test_surrogate_escape_combinations_match_standard_decoder(self):
        values = [r'"\ud800"', r'"\udc00"', r'"\ud800\udc00"',
                  r'"\ud800\ud801\udc00"', r'"\ud800x\udc00"',
                  r'"\ud800\n\udc00"', r'"\ud800\u0061"']
        for text in values:
            for step in (1, 3, 5, 7):
                with self.subTest(text=text, step=step):
                    self.assertEqual(state_io.load(BoundedReader(text.encode(), step)), json.loads(text))

    def test_large_strings_are_interned_only_after_actual_equality(self):
        blob = base64.b64encode(bytes(range(256)) * 1024).decode()
        result = state_io.load(io.BytesIO(encoded({'before': {'data': blob},
                                                   'after': {'data': blob},
                                                   'different': {'data': blob[:-4] + 'YWJj'}})))
        self.assertIs(result['before']['data'], result['after']['data'])
        self.assertIsNot(result['before']['data'], result['different']['data'])
        # Even a hash collision cannot substitute a different backup string.
        class Collision:
            def update(self, data):
                pass
            def digest(self):
                return b'x' * 32
        with mock.patch.object(state_io.hashlib, 'sha256', Collision):
            values = state_io.load(io.BytesIO(encoded(['a' * 5000, 'b' * 5000, 'a' * 5000])))
        self.assertEqual(values, ['a' * 5000, 'b' * 5000, 'a' * 5000])
        self.assertIs(values[0], values[2])
        self.assertIsNot(values[0], values[1])

    def test_interner_has_an_entry_bound(self):
        with mock.patch.object(state_io, 'MAX_INTERNED', 1):
            reader = state_io._Reader(io.BytesIO(encoded(['a' * 5000, 'b' * 5000,
                                                          'a' * 5000])), None, 100000)
            value = reader.value()
        self.assertEqual(reader.intern_count, 1)
        self.assertEqual(len(reader.interned), 1)
        self.assertIs(value[0], value[2])

    def test_health_projection_hashes_only_active_current_snapshots(self):
        raw = bytes(range(256)) * 1000
        value = document(base64.b64encode(raw).decode())
        value['originals'] = {'old': {'exists': True, 'data': 'not-base64'}}
        value['slots']['A'] = {'current': document('not-base64')['slots']['B']['current']}
        value['slots']['B']['previous'] = document('not-base64')['slots']['B']['current']
        projected = state_io.load(BoundedReader(encoded(value), 17), slot='B')
        current = projected['slots']['B']['current']
        snapshot = current['paths']['etc/example']['snapshot']
        self.assertEqual(snapshot['data'], state_io.DataDigest(hashlib.sha256(raw).hexdigest(), len(raw)))
        self.assertEqual(set(projected), {'format', 'slots'})
        self.assertEqual(set(projected['slots']), {'B'})
        self.assertEqual(set(projected['slots']['B']), {'current'})
        self.assertEqual(set(current), {'selected', 'legacy_adopted', 'paths'})
        self.assertEqual(set(current['paths']['etc/example']), {'component', 'mutable', 'snapshot'})

    def test_legacy_journal_projection_hashes_original_and_applied_in_bounded_reads(self):
        raw = b'legacy bytes' * 1000
        blob = base64.b64encode(raw).decode()
        value = {'phase': 'installed', 'allowed': ['etc/example'],
                 'original': {'etc/example': {'exists': True, 'mode': 420, 'uid': 0, 'gid': 0, 'data': blob}},
                 'applied': {'etc/example': blob}, 'private': {'data': 'not retained'}}
        for step in (1, 7, state_io.CHUNK_SIZE):
            projected = state_io.load_journal(BoundedReader(encoded(value), step))
            digest = state_io.DataDigest(hashlib.sha256(raw).hexdigest(), len(raw))
            self.assertEqual(projected['original']['etc/example']['data'], digest)
            self.assertEqual(projected['applied']['etc/example'], digest)
            self.assertNotIn('private', projected)
        self.assertEqual(state_io.load(io.BytesIO(encoded(value))), value)

    def test_installation_projection_retains_only_requested_original_digests_and_users(self):
        value = document()
        original = value['slots']['B']['current']['paths']['etc/example']['snapshot']
        value['originals'] = {'B:etc/example': original, 'A:etc/example': {'data': 'not-base64'},
                              'shared:opt/unrelated': {'data': 'not-base64'}}
        for step in (1, 7, state_io.CHUNK_SIZE):
            projected = state_io.load(BoundedReader(encoded(value), step), slot='B',
                                      original_scopes={'B:etc/example'})
            self.assertEqual(set(projected['originals']), {'B:etc/example'})
            self.assertEqual(projected['originals']['B:etc/example']['data'],
                             state_io.DataDigest(hashlib.sha256(b'a').hexdigest(), 1))
            self.assertIs(projected['slots']['B']['current']['paths']['etc/example']['user'], False)
        value['originals']['B:etc/example']['data'] = 'not-base64'
        with self.assertRaises(ValueError):
            state_io.load(io.BytesIO(encoded(value)), slot='B', original_scopes={'B:etc/example'})
        for scope in ('A:etc/example', 'shared:etc/example', 'B:home/deck/config',
                      'B:../outside', 'B:/absolute', 'B:etc\\example'):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                state_io.load(io.BytesIO(encoded(document())), slot='B', original_scopes={scope})

    def test_legacy_projection_does_not_materialize_payloads(self):
        blob = base64.b64encode(b'x' * (4 * 1024 * 1024)).decode()
        wire = encoded({'original': {'etc/example': {'data': blob}}, 'applied': {'etc/example': blob}})
        tracemalloc.start()
        try:
            value = state_io.load_journal(BoundedReader(wire))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(value['applied']['etc/example'].size, 4 * 1024 * 1024)
        self.assertLess(peak, 2 * 1024 * 1024)

    def test_legacy_projection_rejects_invalid_payloads_and_skipped_json(self):
        for wire in (b'{"applied":{"etc/example":"YQ==AAAA"}}',
                     b'{"original":{"etc/example":{"data":"!"}}}',
                     b'{"private":{"x":1,"x":2}}'):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                state_io.load_journal(BoundedReader(wire, 1))
        with mock.patch.object(state_io, 'MAX_METADATA', 4096), self.assertRaisesRegex(ValueError, 'metadata limit'):
            state_io.load_journal(io.BytesIO(encoded({'allowed': [{'data': 'x' * 5000}]})))

    def test_json_object_cannot_forge_a_data_digest(self):
        value = document({'sha256': 'a' * 64, 'size': 1})
        result = state_io.load(io.BytesIO(encoded(value)), slot='B')
        data = result['slots']['B']['current']['paths']['etc/example']['snapshot']['data']
        self.assertIsInstance(data, dict)
        self.assertNotIsInstance(data, state_io.DataDigest)

    def test_projection_nested_data_cannot_bypass_metadata_budget(self):
        value = document({'data': 'A' * 5000000})
        with mock.patch.object(state_io, 'MAX_METADATA', 4096):
            with self.assertRaisesRegex(ValueError, 'metadata limit'):
                state_io.load(io.BytesIO(encoded(value)), slot='B')
        value = document('YQ==')
        value['slots']['B']['current']['selected'] = [{'data': 'A' * 5000000}]
        with mock.patch.object(state_io, 'MAX_METADATA', 4096):
            with self.assertRaisesRegex(ValueError, 'metadata limit'):
                state_io.load(io.BytesIO(encoded(value)), slot='B')

    def test_projection_does_not_materialize_large_payload_or_skipped_strings(self):
        # Allocate the fixture before tracemalloc: the projection itself must
        # retain neither its 8 MiB payload nor its previous-generation copy.
        blob = base64.b64encode(b'abcd' * (2 * 1024 * 1024)).decode()
        value = document(blob)
        value['originals'] = {'source': {'data': blob}}
        value['slots']['B']['previous'] = value['slots']['B']['current']
        wire = encoded(value)
        tracemalloc.start()
        try:
            result = state_io.load(BoundedReader(wire), slot='B')
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        data = result['slots']['B']['current']['paths']['etc/example']['snapshot']['data']
        self.assertEqual(data.size, 8 * 1024 * 1024)
        self.assertLess(peak, 2 * 1024 * 1024)

    def test_strict_base64_at_every_chunk_boundary(self):
        for count in range(20):
            raw = bytes(range(count))
            wire = encoded(document(base64.b64encode(raw).decode()))
            for step in (1, 2, 3, 7, 31):
                result = state_io.load(BoundedReader(wire, step), slot='B')
                digest = result['slots']['B']['current']['paths']['etc/example']['snapshot']['data']
                self.assertEqual(digest, state_io.DataDigest(hashlib.sha256(raw).hexdigest(), count))
        for payload in ('a', 'abc', '=AAA', 'YQ=', 'YQ===', 'YQ==AAAA', 'AAAA====',
                        'Y Q=', 'YQ==\n', '中文', 'YQ--'):
            for step in (1, 3, state_io.CHUNK_SIZE):
                with self.subTest(payload=payload, step=step), self.assertRaises(ValueError):
                    state_io.load(BoundedReader(encoded(document(payload)), step), slot='B')

    def test_base64_limit_is_incremental(self):
        with mock.patch.object(state_io, 'MAX_SNAPSHOT', 3):
            with self.assertRaisesRegex(ValueError, 'Snapshot size limit'):
                state_io.load(BoundedReader(encoded(document('YWJjZA==')), 1), slot='B')

    def test_invalid_json_is_rejected_including_skipped_fields(self):
        invalid = [b'', b'\xef\xbb\xbf{}', b'{}{}', b'{} trailing', b'{"x":1,}', b'[1,]',
                   b'{"x":1,"x":2}', b'{"x":1,"\\u0078":2}',
                   b'{"skipped":{"x":1,"x":2}}', b'{"skipped":"bad\\x"}',
                   b'{"skipped":"\x00"}', b'{"skipped":"\\u1x23"}',
                   b'"unterminated', b'"bad\\', b'"\xc0\x80"', b'"\xed\xa0\x80"',
                   b'"\xf0\x9f\x98"', b'01', b'-01', b'+1', b'.5', b'1.', b'1e',
                   b'NaN', b'Infinity', b'1e999', b'truex', b'[false null]']
        for wire in invalid:
            for slot in (None, 'B'):
                with self.subTest(wire=wire, slot=slot), self.assertRaises(ValueError):
                    state_io.load(BoundedReader(wire, 1), slot=slot)

    def test_structure_and_input_budgets(self):
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            state_io.load(BoundedReader(b'{"hello":1}', 1), max_bytes=10)
        self.assertEqual(state_io.load(io.BytesIO(b'{}'), max_bytes=2), {})
        with mock.patch.object(state_io, 'MAX_DEPTH', 2):
            with self.assertRaisesRegex(ValueError, 'nesting limit'):
                state_io.load(io.BytesIO(b'[[[0]]]'))
        with mock.patch.object(state_io, 'MAX_KEYS', 1):
            with self.assertRaisesRegex(ValueError, 'key limit'):
                state_io.load(io.BytesIO(b'{"skip":{"a":0,"b":0}}'), slot='B')
        with mock.patch.object(state_io, 'MAX_NODES', 2):
            with self.assertRaisesRegex(ValueError, 'structure limit'):
                state_io.load(io.BytesIO(b'[0,1]'))
        with mock.patch.object(state_io, 'MAX_METADATA', 40):
            with self.assertRaisesRegex(ValueError, 'metadata limit'):
                state_io.load(io.BytesIO(b'{"hello":"world"}'))
        with mock.patch.object(state_io, 'MAX_KEY', 4):
            with self.assertRaisesRegex(ValueError, 'string limit'):
                state_io.load(io.BytesIO(b'{"longer":"skip"}'), slot='B')

    def test_full_payloads_do_not_consume_the_metadata_budget(self):
        wire = encoded({'data': 'a' * 200000})
        with mock.patch.object(state_io, 'MAX_METADATA', 100):
            self.assertEqual(state_io.load(io.BytesIO(wire)), {'data': 'a' * 200000})

    def test_only_projected_current_data_has_the_health_snapshot_limit(self):
        value = document('YQ==')
        value['originals'] = {'source': {'data': 'legacy backup larger than health limit'}}
        value['slots']['B']['previous'] = document('legacy backup larger than health limit')['slots']['B']['current']
        with mock.patch.object(state_io, 'MAX_SNAPSHOT', 1):
            self.assertEqual(state_io.load(io.BytesIO(encoded(value))), value)
            result = state_io.load(io.BytesIO(encoded(value)), slot='B')
            data = result['slots']['B']['current']['paths']['etc/example']['snapshot']['data']
            self.assertEqual(data.size, 1)

    def test_dump_matches_existing_canonical_bytes_and_bounds_writes(self):
        values = [document(), {'中文': ['😀', '\ud800', '\udc00', '"\\\b\f\n\r\t/']},
                  [0, -1, 1.0, -0.0, 1e-20, 1e30, True, False, None],
                  {3: 'three', 1: 'one'}, ('tuple',),
                  ['中文😀\n\\"' * 100000]]
        for value in values:
            with self.subTest(kind=type(value).__name__):
                stream = BoundedWriter()
                expected = encoded(value)
                with mock.patch.object(state_io.json, 'dumps', side_effect=AssertionError('whole document serialization')):
                    state_io.dump(value, stream)
                self.assertEqual(stream.getvalue(), expected)

    def test_dump_detects_cycles_and_rejects_unsupported_values(self):
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(ValueError, 'Circular'):
            state_io.dump(cyclic, io.BytesIO())
        with self.assertRaises(TypeError):
            state_io.dump({'digest': state_io.DataDigest('a' * 64, 1)}, io.BytesIO())

    def test_dump_rejects_numbers_that_the_state_reader_cannot_accept(self):
        for value in (math.inf, -math.inf, math.nan, 10 ** 256, -(10 ** 255)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                state_io.dump(value, io.BytesIO())
        stream = io.BytesIO()
        state_io.dump(10 ** 255, stream)
        self.assertEqual(state_io.load(io.BytesIO(stream.getvalue())), 10 ** 255)

    def test_dump_budgets_match_reader_and_fail_before_a_complete_document(self):
        cases = [('MAX_DEPTH', 1, {'one': {'two': 1}}, 'nesting'),
                 ('MAX_KEYS', 1, {'one': 1, 'two': 2}, 'key limit'),
                 ('MAX_NODES', 2, [1, 2], 'structure'),
                 ('MAX_KEY', 3, {'long': 1}, 'string'),
                 ('MAX_METADATA', 40, {'hello': 'world'}, 'metadata')]
        for limit, maximum, value, reason in cases:
            with self.subTest(limit=limit), mock.patch.object(state_io, limit, maximum):
                with self.assertRaisesRegex(ValueError, reason):
                    state_io.dump(value, io.BytesIO())
                with self.assertRaisesRegex(ValueError, reason):
                    state_io.load(io.BytesIO(encoded(value)))
        with mock.patch.object(state_io, 'MAX_BYTES', 12):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                state_io.dump({'data': 'too long'}, io.BytesIO())
        # String subclasses can be distinct Python keys but encode identically.
        class OddString(str):
            __hash__ = object.__hash__
        duplicate = {OddString('same'): 1, OddString('same'): 2}
        self.assertEqual(len(duplicate), 2)
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            state_io.dump(duplicate, io.BytesIO())

    def test_random_small_documents_round_trip_like_json(self):
        rng = random.Random(712)
        alphabet = 'ab中文😀"\\\n\t'
        for _ in range(100):
            value = {str(i): [''.join(rng.choice(alphabet) for _ in range(rng.randrange(30))),
                               rng.randint(-100000, 100000), rng.random()]
                     for i in range(rng.randrange(10))}
            stream = BoundedWriter()
            state_io.dump(value, stream)
            self.assertEqual(stream.getvalue(), encoded(value))
            self.assertEqual(state_io.load(BoundedReader(stream.getvalue(), rng.randrange(1, 30))), value)


if __name__ == '__main__':
    unittest.main()
