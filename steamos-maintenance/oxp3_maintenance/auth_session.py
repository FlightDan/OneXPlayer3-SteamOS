"""Window-scoped authorization over inherited anonymous pipes.

The installed root helper accepts a small maintenance protocol, never Python,
shell commands or executable paths. Passwords remain entirely inside polkit.
"""
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading

ENTRY = Path('/usr/local/lib/oxp3-maintenance/entry.py')
PROTOCOL = 1
MAX_REQUEST = 64 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
MAX_SEQUENCE = 1000000
ACTIONS = frozenset(('status', 'logs', 'plan', 'apply', 'rollback', 'restore',
                     'recover', 'health', 'installation-status'))
_COMPONENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,79}\Z')
_VERSION = re.compile(r'[0-9A-Za-z.+-]{1,128}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class SessionUnavailable(RuntimeError):
    """The protected engine must be installed/upgraded before session use."""


def _trusted_runtime():
    """Check the fixed installed Python import surface without following links."""
    for path in reversed((ENTRY.parent, *ENTRY.parent.parents)):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o022):
            raise SessionUnavailable('Untrusted installed maintenance directory')
    def regular(path, maximum=None):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_nlink != 1 or info.st_uid or info.st_mode & 0o022
                or maximum is not None and info.st_size > maximum):
            raise SessionUnavailable('Untrusted installed maintenance program file')
        return info
    regular(ENTRY, 64 * 1024)
    runtime = ENTRY.parent
    with ENTRY.open('rb') as stream:
        wrapper = stream.read(64 * 1024 + 1)
    template = ('#!/usr/bin/python3\nimport runpy\nrunpy.run_path('
                + repr(str(ENTRY.parent / 'releases' / '__RUNTIME__' / 'entry.py'))
                + ', run_name="__main__")\n').encode()
    pattern = re.escape(template).replace(b'__RUNTIME__', rb'(?P<name>[A-Za-z0-9][A-Za-z0-9.+-]{0,159})')
    generation = re.fullmatch(pattern, wrapper)
    if generation is not None:
        name = generation['name'].decode('ascii')
        runtime = ENTRY.parent / 'releases' / name
        for path in (runtime.parent, runtime):
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_uid or info.st_mode & 0o022):
                raise SessionUnavailable('Untrusted installed maintenance generation')
        regular(runtime / 'entry.py', 64 * 1024)
    elif b'runpy.run_path' in wrapper or b'import runpy' in wrapper:
        raise SessionUnavailable('Invalid installed maintenance generation wrapper')
    package = runtime / 'oxp3_maintenance'
    info = package.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o022):
        raise SessionUnavailable('Untrusted installed maintenance package')
    # entry.py inserts the runtime itself in sys.path. Protect all importable
    # surfaces, including top-level module shadows and existing bytecode caches.
    count = 0
    for parent, directories, files in os.walk(runtime, followlinks=False):
        for name in directories + files:
            count += 1
            if count > 4096:
                raise SessionUnavailable('Installed maintenance file limit exceeded')
            path = Path(parent) / name
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or info.st_uid or info.st_mode & 0o022
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise SessionUnavailable('Untrusted installed maintenance program path')
    return runtime


def trusted_entry():
    try:
        _trusted_runtime()
    except FileNotFoundError as error:
        raise SessionUnavailable('Install the latest maintenance engine first; window authorization needs a protected installation') from error
    return ENTRY


def supported():
    """A missing helper in an older protected installation is upgrade-only."""
    trusted_entry()
    return (_trusted_runtime() / 'oxp3_maintenance/auth_session.py').is_file()


def _unique(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError('Duplicate session JSON key')
        result[key] = item
    return result


def _decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid session number')))


def _line(stream, maximum):
    raw = stream.readline(maximum + 1)
    if not raw:
        return None
    if len(raw) > maximum or not raw.endswith(b'\n'):
        raise ValueError('Session message limit or incomplete message')
    return _decode(raw)


def _send(stream, value, maximum):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(raw) > maximum:
        raise ValueError('Session response limit exceeded')
    pending = memoryview(raw)
    while pending:
        written = stream.write(pending)
        if not isinstance(written, int) or written < 1:
            raise BrokenPipeError('Maintenance session pipe closed')
        pending = pending[written:]
    stream.flush()


def validate_request(value, sequence):
    if (not isinstance(value, dict) or set(value) != {'protocol', 'sequence', 'action', 'params'}
            or type(value['protocol']) is not int or value['protocol'] != PROTOCOL
            or type(value['sequence']) is not int or value['sequence'] != sequence
            or not 1 <= sequence <= MAX_SEQUENCE or not isinstance(value['action'], str)
            or value['action'] not in ACTIONS
            or not isinstance(value['params'], dict)):
        raise ValueError('Invalid maintenance session request')
    action, params = value['action'], value['params']
    allowed = {'selected'} if action in ('restore', 'installation-status') else set()
    if action in ('plan', 'apply'):
        allowed = {'bundle', 'bundle_dir', 'selected', 'all_components', 'tool_only',
                   'expected_version', 'expected_manifest'}
    if set(params) - allowed:
        raise ValueError('Unsupported maintenance session parameters')
    selected = params.get('selected', [])
    if (not isinstance(selected, list) or len(selected) > 128
            or any(not isinstance(name, str) or not _COMPONENT.fullmatch(name) for name in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('Invalid session component selection')
    if action == 'restore' and not selected:
        raise ValueError('Choose components to restore first')
    for flag in ('all_components', 'tool_only'):
        if flag in params and type(params[flag]) is not bool:
            raise ValueError('Invalid session flag')
    if action in ('plan', 'apply'):
        if ('bundle' in params) == ('bundle_dir' in params):
            raise ValueError('Choose one signed maintenance bundle')
        source = params.get('bundle', params.get('bundle_dir'))
        if (not isinstance(source, str) or not source.startswith('/') or len(source) > 4096
                or any(ord(character) < 32 for character in source)
                or '\\' in source or any(part in ('.', '..') for part in source.split('/'))):
            raise ValueError('Invalid session bundle path')
        version, digest = params.get('expected_version'), params.get('expected_manifest')
        if 'expected_version' in params and (not isinstance(version, str) or not _VERSION.fullmatch(version)):
            raise ValueError('Invalid session reviewed version')
        if 'expected_manifest' in params and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise ValueError('Invalid session reviewed manifest')
        if params.get('tool_only') and selected:
            raise ValueError('Tool-only session request cannot select components')
        if params.get('tool_only') and params.get('all_components'):
            raise ValueError('Tool-only session request cannot include all components')
        if action == 'apply' and (version is None or digest is None or params.get('all_components')):
            raise ValueError('Apply requires the exact reviewed version and manifest')
    return action, {key: value for key, value in params.items()
                    if not (key in ('all_components', 'tool_only') and value is False
                            or key == 'selected' and not value)}


def command(action, params):
    result = ['/usr/bin/python3', '-I', '-B', str(ENTRY), action, '--json']
    for name in ('bundle', 'bundle_dir', 'expected_version', 'expected_manifest'):
        if name in params:
            result.extend(('--' + name.replace('_', '-'), params[name]))
    if action in ('plan', 'apply'):
        result.append('--selected-only')
    if params.get('selected'):
        result.extend(('--select', *params['selected']))
    for name in ('all_components', 'tool_only'):
        if params.get(name):
            result.append('--' + name.replace('_', '-'))
    return result


def run_backend(action, params):
    """Drain both pipes concurrently, retaining bounded output, never kill writes."""
    trusted_entry()  # Recheck after every possible engine replacement.
    process = subprocess.Popen(command(action, params), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               close_fds=True, cwd='/', env=_environment())
    output = [bytearray(), bytearray()]
    excessive = threading.Event()
    def drain(index, stream):
        with stream:
            while raw := stream.read(64 * 1024):
                remaining = MAX_RESPONSE - len(output[index])
                output[index].extend(raw[:remaining])
                if len(raw) > remaining:
                    excessive.set()
    threads = [threading.Thread(target=drain, args=(i, stream), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    returncode = process.wait()
    for thread in threads:
        thread.join()
    if excessive.is_set():
        raise RuntimeError('Maintenance output exceeded the session limit; inspect operation status before retrying')
    if returncode in (0, 2):
        value = _decode(bytes(output[0]))
        if not isinstance(value, dict) or returncode == 2 and value.get('status') != 'preflight_refused':
            raise RuntimeError('Invalid maintenance result')
        return value
    try:
        error = _decode(bytes(output[1])).get('error')
    except (ValueError, AttributeError):
        error = None
    raise RuntimeError(error[:2000] if isinstance(error, str) else 'Maintenance action failed')


def _environment():
    # Commands still need the normal OS utility path; no caller-controlled
    # Python, loader, shell or lookup environment crosses this boundary.
    return {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root',
            'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}


def serve(incoming=None, outgoing=None):
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Maintenance session service requires administrator authorization')
    runtime = _trusted_runtime()
    if Path(__file__).absolute() != runtime / 'oxp3_maintenance/auth_session.py':
        raise RuntimeError('Maintenance session service must use the installed protected engine')
    incoming = sys.stdin.buffer if incoming is None else incoming
    outgoing = sys.stdout.buffer if outgoing is None else outgoing
    for stream in (incoming, outgoing):
        descriptor = stream.fileno()
        if (not stat.S_ISFIFO(os.fstat(descriptor).st_mode)
                or not os.readlink('/proc/self/fd/' + str(descriptor)).startswith('pipe:[')):
            raise RuntimeError('Maintenance session requires private anonymous pipes')
    return _serve(incoming, outgoing)


def _serve(incoming, outgoing):
    """Protocol loop separated from the installed-entry/descriptor gate for tests."""
    _send(outgoing, {'protocol': PROTOCOL, 'status': 'authorized'}, MAX_RESPONSE)
    sequence, review = 1, None
    while True:
        value = _line(incoming, MAX_REQUEST)
        if value is None:
            return None
        action, params = validate_request(value, sequence)
        try:
            if action == 'apply':
                previous, review = review, None  # Never replay a consumed review.
                if previous != params:
                    raise RuntimeError('Review the changes again before applying')
            elif action == 'plan':
                review = None
            result = run_backend(action, params)
            if action == 'plan' and result.get('can_apply') and not params.get('all_components'):
                review = dict(params, expected_version=result['release']['version'],
                              expected_manifest=result['manifest_digest'])
                review.pop('all_components', None)
            _send(outgoing, {'protocol': PROTOCOL, 'sequence': sequence, 'result': result}, MAX_RESPONSE)
        except BrokenPipeError:
            return None  # The operation already finished before writing its response.
        except Exception as error:
            try:
                _send(outgoing, {'protocol': PROTOCOL, 'sequence': sequence, 'error': str(error)[:2000]}, MAX_RESPONSE)
            except BrokenPipeError:
                return None
        sequence += 1


class Client:
    def __init__(self):
        self.process = None
        self.sequence = 0
        self.closed = False
        self.lock = threading.Lock()

    def _start(self):
        if self.closed:
            raise RuntimeError('Maintenance authorization session is closed; reopen the window')
        if self.process is not None:
            if self.process.poll() is not None:
                raise RuntimeError('Maintenance authorization session ended; reopen the window')
            return
        if not supported():
            raise SessionUnavailable('Update tool only first; the installed engine does not support window authorization')
        process = subprocess.Popen(['/usr/bin/pkexec', '/usr/bin/python3', '-I', '-B', str(ENTRY), 'session-service'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   bufsize=0, close_fds=True, start_new_session=True)
        process.stdout = io.BufferedReader(process.stdout, 64 * 1024)
        try:
            hello = _line(process.stdout, MAX_REQUEST)
            if (hello != {'protocol': PROTOCOL, 'status': 'authorized'}
                    or type(hello.get('protocol')) is not int):
                raise RuntimeError('Authentication cancelled or maintenance session could not start')
        except BaseException:
            process.stdin.close()
            process.stdout.close()
            threading.Thread(target=process.wait, daemon=True).start()
            raise
        if self.closed:
            process.stdin.close()
            threading.Thread(target=process.wait, daemon=True).start()
            raise RuntimeError('Maintenance authorization session is closed')
        self.process = process

    def authorize(self):
        with self.lock:
            self._start()
        return {'status': 'authorized'}

    def request(self, action, params):
        with self.lock:
            request = dict(protocol=PROTOCOL, sequence=self.sequence + 1, action=action, params=params)
            validate_request(request, self.sequence + 1)
            self._start()
            self.sequence += 1
            try:
                _send(self.process.stdin, request, MAX_REQUEST)
                response = _line(self.process.stdout, MAX_RESPONSE)
                if (not isinstance(response, dict) or type(response.get('protocol')) is not int
                        or response.get('protocol') != PROTOCOL
                        or type(response.get('sequence')) is not int or response['sequence'] != self.sequence
                        or set(response) not in ({'protocol', 'sequence', 'result'}, {'protocol', 'sequence', 'error'})):
                    raise ValueError('Invalid maintenance session response; inspect status before retrying')
            except BaseException:
                self.close()
                raise
            if 'error' in response:
                if not isinstance(response['error'], str) or len(response['error']) > 2000:
                    self.close()
                    raise ValueError('Invalid maintenance session error')
                raise RuntimeError(response['error'])
            if not isinstance(response['result'], dict):
                self.close()
                raise ValueError('Invalid maintenance session result')
            return response['result']

    def close(self):
        # No request lock: closing the window must not wait for a transaction.
        # EOF is observed after its current child exits. Never terminate it.
        self.closed = True
        process = self.process
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            threading.Thread(target=process.wait, daemon=True).start()
