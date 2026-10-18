"""Bounded JSON I/O for the existing, inline-snapshot state format.

The on-disk representation remains ordinary JSON understood by older runtimes.
The optional health projection validates the whole document, but retains only
the active generation and hashes its base64 payloads instead of retaining them.
"""
from __future__ import annotations

import base64
import binascii
import codecs
from dataclasses import dataclass
import hashlib
import json
import math
import re


CHUNK_SIZE = 64 * 1024
MAX_DEPTH = 64
MAX_KEYS = 100000
MAX_NODES = 2000000
MAX_METADATA = 128 * 1024 * 1024
MAX_SNAPSHOT = 256 * 1024 * 1024
MAX_BYTES = 8 * 1024 ** 3
MAX_KEY = 4096
INTERN_THRESHOLD = 4096
MAX_INTERNED = 100000
_SPECIAL = re.compile(r'["\\\x00-\x1f]')
_SPACE = re.compile(r'[ \t\r\n]*')
_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
_HEX = re.compile(r'[0-9a-fA-F]{4}\Z')
_BASE64 = re.compile(r'[A-Za-z0-9+/]*={0,2}\Z')
_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
            'n': '\n', 'r': '\r', 't': '\t'}


class StateJSONError(ValueError):
    """Invalid or excessive state JSON; messages never contain file contents."""


@dataclass(frozen=True, slots=True)
class DataDigest:
    """A parsed payload fingerprint, distinguishable from any JSON object."""
    sha256: str
    size: int


class _Base64Digest:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.size = 0
        self.tail = ''
        self.ended = False

    def feed(self, text):
        if not text:
            return
        if self.ended:
            raise StateJSONError('Invalid snapshot base64')
        try:
            text.encode('ascii')
        except UnicodeError as error:
            raise StateJSONError('Invalid snapshot base64') from error
        text = self.tail + text
        length = len(text) // 4 * 4
        self.tail = text[length:]
        if not length:
            return
        encoded = text[:length]
        if not _BASE64.fullmatch(encoded):
            raise StateJSONError('Invalid snapshot base64')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise StateJSONError('Invalid snapshot base64') from error
        if '=' in encoded:
            self.ended = True
            if self.tail:
                raise StateJSONError('Invalid snapshot base64')
        self.size += len(raw)
        if self.size > MAX_SNAPSHOT:
            raise StateJSONError('Snapshot size limit exceeded')
        self.digest.update(raw)

    def finish(self):
        if self.tail:
            raise StateJSONError('Invalid snapshot base64')
        return DataDigest(self.digest.hexdigest(), self.size)


class _Reader:
    def __init__(self, stream, slot, max_bytes, original_scopes=()):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Invalid JSON byte limit')
        if slot is not None and not isinstance(slot, str):
            raise ValueError('Invalid projection slot')
        self.original_scopes = frozenset(original_scopes)
        if (self.original_scopes and slot is None or len(self.original_scopes) > 20000
                or any(not isinstance(scope, str) or len(scope) > MAX_KEY for scope in self.original_scopes)):
            raise ValueError('Invalid original projection scopes')
        for scope in self.original_scopes:
            owner, separator, relative = scope.partition(':')
            if (owner not in ('shared', slot) or not separator or not relative
                    or '\\' in relative or ':' in relative or '\x00' in relative
                    or any(part in ('', '.', '..') for part in relative.split('/'))
                    or (owner == 'shared') != relative.startswith(('home/', 'opt/'))):
                raise ValueError('Invalid original projection scope')
        self.stream, self.slot, self.maximum = stream, slot, max_bytes
        self.buffer, self.position = '', 0
        self.eof = False
        self.binary = None
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.bytes = self.metadata = self.nodes = 0
        self.interned = {}
        self.intern_count = 0

    def error(self, message='Invalid state JSON'):
        raise StateJSONError(message)

    def budget(self, amount):
        self.metadata += amount
        if self.metadata > MAX_METADATA:
            self.error('JSON metadata limit exceeded')

    def fill(self):
        if self.eof:
            return False
        self.buffer = self.buffer[self.position:]
        self.position = 0
        raw = self.stream.read(CHUNK_SIZE)
        if not isinstance(raw, (str, bytes)):
            self.error('Invalid JSON stream')
        binary = isinstance(raw, bytes)
        if self.binary is not None and self.binary != binary:
            self.error('Inconsistent JSON stream')
        self.binary = binary
        try:
            length = len(raw) if binary else len(raw.encode('utf-8'))
            self.bytes += length
            if self.bytes > self.maximum:
                self.error('JSON byte limit exceeded')
            decoded = self.decoder.decode(raw, final=not raw) if binary else raw
        except UnicodeError as error:
            raise StateJSONError('Invalid JSON UTF-8') from error
        self.buffer += decoded
        self.eof = not raw
        return bool(raw)

    def ensure(self, count=1):
        while len(self.buffer) - self.position < count and not self.eof:
            self.fill()
        return len(self.buffer) - self.position >= count

    def peek(self):
        return self.buffer[self.position] if self.ensure() else ''

    def whitespace(self):
        while self.ensure():
            self.position = _SPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return

    def expect(self, character):
        if self.peek() != character:
            self.error()
        self.position += 1

    def retained(self, path, key):
        if self.slot is None:
            return True
        if not path:
            return key in ('format', 'slots') or key == 'originals' and bool(self.original_scopes)
        if path == ('originals',):
            return key in self.original_scopes
        if len(path) == 2 and path[0] == 'originals':
            return key in ('exists', 'mode', 'uid', 'gid', 'data')
        if path == ('slots',):
            return key == self.slot
        if path == ('slots', self.slot):
            return key == 'current'
        current = ('slots', self.slot, 'current')
        if path == current:
            return key in ('selected', 'legacy_adopted', 'paths')
        if path == current + ('paths',):
            return True
        if len(path) == 5 and path[:4] == current + ('paths',):
            return key in ('component', 'mutable', 'snapshot') or key == 'user' and bool(self.original_scopes)
        if len(path) == 6 and path[:4] == current + ('paths',) and path[-1] == 'snapshot':
            return key in ('exists', 'mode', 'uid', 'gid', 'data')
        # Keep unexpected nested structures so callers can reject their shape.
        return True

    def payload(self, path):
        return (self.slot is not None and len(path) == 3 and path[0] == 'originals'
                and path[1] in self.original_scopes and path[-1] == 'data'
                or self.slot is not None and len(path) == 7
                and path[:4] == ('slots', self.slot, 'current', 'paths')
                and path[-2:] == ('snapshot', 'data'))

    def string(self, *, keep, path=(), key=False):
        self.expect('"')
        chunks = [] if keep and not self.payload(path) else None
        sink = _Base64Digest() if keep and self.payload(path) else None
        length = 0
        high = None
        digest = hashlib.sha256() if keep and not key and sink is None else None

        def emit(text):
            nonlocal length
            if not text:
                return
            length += len(text)
            # Only the health fingerprint sink has a per-snapshot byte limit.
            # Old engines can legitimately store larger backup strings; full
            # reads and skipped projection fields use the document byte limit.
            if key and length > MAX_KEY:
                self.error('JSON string limit exceeded')
            if sink is None and (key or not path or path[-1] != 'data'
                    or self.slot is not None and keep):
                self.budget(len(text) * 2)
            if sink is not None:
                sink.feed(text)
            elif chunks is not None:
                chunks.append(text)
                if digest is not None:
                    digest.update(text.encode('utf-8', errors='surrogatepass'))

        def plain(text):
            nonlocal high
            if high is not None:
                emit(chr(high))
                high = None
            emit(text)

        while True:
            if not self.ensure():
                self.error('Unterminated JSON string')
            match = _SPECIAL.search(self.buffer, self.position)
            end = match.start() if match else len(self.buffer)
            if end > self.position:
                plain(self.buffer[self.position:end])
            self.position = end
            if match is None:
                continue
            character = self.buffer[self.position]
            self.position += 1
            if character == '"':
                if high is not None:
                    emit(chr(high))
                break
            if character != '\\':
                self.error('Unescaped JSON control character')
            escape = self.peek()
            if not escape:
                self.error('Unterminated JSON escape')
            self.position += 1
            if escape in _ESCAPES:
                plain(_ESCAPES[escape])
            elif escape == 'u':
                if not self.ensure(4):
                    self.error('Invalid JSON Unicode escape')
                digits = self.buffer[self.position:self.position + 4]
                self.position += 4
                if not _HEX.fullmatch(digits):
                    self.error('Invalid JSON Unicode escape')
                number = int(digits, 16)
                if high is not None and 0xdc00 <= number <= 0xdfff:
                    emit(chr(0x10000 + ((high - 0xd800) << 10) + number - 0xdc00))
                    high = None
                else:
                    if high is not None:
                        emit(chr(high))
                    high = number if 0xd800 <= number <= 0xdbff else None
                    if high is None:
                        emit(chr(number))
            else:
                self.error('Invalid JSON escape')
        if sink is not None:
            return sink.finish()
        if chunks is None:
            return None
        result = ''.join(chunks)
        if digest is not None and length >= INTERN_THRESHOLD:
            identity = (digest.digest(), length)
            candidates = self.interned.get(identity, ())
            for existing in candidates:
                if existing == result:
                    return existing
            if self.intern_count < MAX_INTERNED:
                self.interned.setdefault(identity, []).append(result)
                self.intern_count += 1
        return result

    def value(self, *, keep=True, path=(), depth=0):
        if depth > MAX_DEPTH:
            self.error('JSON nesting limit exceeded')
        self.nodes += 1
        self.budget(16)
        if self.nodes > MAX_NODES:
            self.error('JSON structure limit exceeded')
        self.whitespace()
        character = self.peek()
        if character == '"':
            return self.string(keep=keep, path=path)
        if character == '{':
            self.position += 1
            result, seen = ({} if keep else None), set()
            self.whitespace()
            if self.peek() == '}':
                self.position += 1
                return result
            while True:
                self.whitespace()
                if self.peek() != '"':
                    self.error()
                key = self.string(keep=True, key=True)
                if key in seen:
                    self.error('Duplicate JSON key')
                seen.add(key)
                if len(seen) > MAX_KEYS:
                    self.error('JSON object key limit exceeded')
                self.budget(32)
                self.whitespace()
                self.expect(':')
                selected = keep and self.retained(path, key)
                item = self.value(keep=selected, path=path + (key,), depth=depth + 1)
                if selected:
                    result[key] = item
                self.whitespace()
                delimiter = self.peek()
                if delimiter == '}':
                    self.position += 1
                    return result
                self.expect(',')
        if character == '[':
            self.position += 1
            result = [] if keep else None
            self.whitespace()
            if self.peek() == ']':
                self.position += 1
                return result
            number = 0
            while True:
                item = self.value(keep=keep, path=path + (number,), depth=depth + 1)
                if keep:
                    result.append(item)
                number += 1
                self.whitespace()
                if self.peek() == ']':
                    self.position += 1
                    return result
                self.expect(',')
        for literal, result in (('true', True), ('false', False), ('null', None)):
            if character and character == literal[0]:
                if not self.ensure(len(literal)) or self.buffer[self.position:self.position + len(literal)] != literal:
                    self.error()
                self.position += len(literal)
                return result if keep else None
        if character and character in '-0123456789':
            parts = []
            while self.peek() and self.peek() in '-+0123456789.eE':
                parts.append(self.peek())
                self.position += 1
                if len(parts) > 256:
                    self.error('JSON number limit exceeded')
            token = ''.join(parts)
            if not _NUMBER.fullmatch(token):
                self.error('Invalid JSON number')
            number = float(token) if any(c in token for c in '.eE') else int(token)
            if isinstance(number, float) and not math.isfinite(number):
                self.error('Nonfinite JSON number')
            return number if keep else None
        self.error()


class _JournalReader(_Reader):
    """Validate legacy JSON while fingerprinting only its file snapshots."""
    def retained(self, path, key):
        if not path:
            return key in ('phase', 'allowed', 'original', 'applied')
        if len(path) == 2 and path[0] == 'original':
            return key in ('exists', 'mode', 'uid', 'gid', 'data')
        return True

    def payload(self, path):
        return (len(path) == 2 and path[0] == 'applied'
                or len(path) == 3 and path[0] == 'original' and path[-1] == 'data')


def _load(reader):
    result = reader.value()
    reader.whitespace()
    if reader.peek():
        reader.error('Trailing JSON data')
    return result


def load(stream, *, slot=None, max_bytes=MAX_BYTES, original_scopes=()):
    """Read full state or a slot view, optionally adding selected original digests.

    Installation checks may request ``shared:home/...`` / ``shared:opt/...``
    or ``<active-slot>:<other-path>`` originals. That opt-in also retains user
    ownership flags; the default health projection stays unchanged.
    """
    return _load(_Reader(stream, slot, max_bytes, original_scopes))


def load_journal(stream, *, max_bytes=MAX_BYTES):
    """Read legacy evidence with digests; never use this view for adoption."""
    return _load(_JournalReader(stream, '', max_bytes))


def dump(value, stream):
    """Write canonical legacy JSON bytes without materializing its encoding.

    Nonfinite floats and numbers longer than 256 characters are not supported
    state values: the bounded reader deliberately rejects them as well.
    """
    active = set()
    byte_count = metadata = nodes = 0

    def budget(amount):
        nonlocal metadata
        metadata += amount
        if metadata > MAX_METADATA:
            raise StateJSONError('JSON metadata limit exceeded')

    def number_text(number):
        if isinstance(number, int):
            text = int.__repr__(number)
            if len(text) > 256:
                raise StateJSONError('JSON number limit exceeded')
            return text
        if not math.isfinite(number):
            raise StateJSONError('Nonfinite JSON number')
        return float.__repr__(number)

    def write(text):
        nonlocal byte_count
        # Text supplied here is ASCII, including every escaped Unicode value.
        for start in range(0, len(text), CHUNK_SIZE):
            raw = text[start:start + CHUNK_SIZE].encode('ascii')
            byte_count += len(raw)
            if byte_count > MAX_BYTES:
                raise StateJSONError('JSON byte limit exceeded')
            stream.write(raw)

    def string(text, *, key=False, payload=False):
        if key and len(text) > MAX_KEY:
            raise StateJSONError('JSON string limit exceeded')
        if key or not payload:
            budget(len(text) * 2)
        write('"')
        for start in range(0, len(text), 4096):
            write(json.encoder.encode_basestring_ascii(text[start:start + 4096])[1:-1])
        write('"')

    def key_text(key):
        if isinstance(key, str):
            # Normalize subclasses before duplicate detection; JSON keys use
            # their underlying string value, not custom hash/equality methods.
            return str.__str__(key)
        if key is True:
            return 'true'
        if key is False:
            return 'false'
        if key is None:
            return 'null'
        if isinstance(key, (int, float)):
            return number_text(key)
        raise TypeError('JSON object keys must be strings or scalar values')

    def visit(item, depth, path_key=None):
        nonlocal nodes
        if depth > MAX_DEPTH:
            raise StateJSONError('JSON nesting limit exceeded')
        nodes += 1
        budget(16)
        if nodes > MAX_NODES:
            raise StateJSONError('JSON structure limit exceeded')
        if isinstance(item, str):
            string(item, payload=path_key == 'data')
        elif item is None:
            write('null')
        elif item is True:
            write('true')
        elif item is False:
            write('false')
        elif isinstance(item, (int, float)):
            write(number_text(item))
        elif isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in active:
                raise ValueError('Circular reference detected')
            active.add(identity)
            try:
                if isinstance(item, dict):
                    if len(item) > MAX_KEYS:
                        raise StateJSONError('JSON object key limit exceeded')
                    write('{')
                    seen = set()
                    for number, key in enumerate(sorted(item)):
                        converted = key_text(key)
                        if converted in seen:
                            raise StateJSONError('Duplicate JSON key')
                        seen.add(converted)
                        budget(32)
                        if number:
                            write(',')
                        string(converted, key=True)
                        write(':')
                        visit(item[key], depth + 1, converted)
                    write('}')
                else:
                    write('[')
                    for number, child in enumerate(item):
                        if number:
                            write(',')
                        visit(child, depth + 1)
                    write(']')
            finally:
                active.remove(identity)
        else:
            raise TypeError('Value is not JSON serializable')

    visit(value, 0)
