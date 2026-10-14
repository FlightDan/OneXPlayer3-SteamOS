"""Persistent original-file snapshots and retryable, conflict-aware restoration.

Caller supplies an explicit file allowlist and handles service/runtime state.
No command execution, device I/O, digest or fingerprint calculation is performed.
"""
import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import fcntl
from functools import wraps


def directory_fd(path):
    """Open every directory component without following ancestor symlinks."""
    path = Path(path).absolute()
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    current = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def snapshot(path, maximum=1024 * 1024):
    path = Path(path)
    try:
        directory = directory_fd(path.parent)
        metadata = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        if 'directory' in locals(): os.close(directory)
        return {'exists': False}
    if not stat.S_ISREG(metadata.st_mode):
        os.close(directory)
        raise RuntimeError('Refusing non-regular component file: ' + str(path))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        with os.fdopen(os.open(path.name, flags, dir_fd=directory), 'rb') as stream:
            actual = os.fstat(stream.fileno())
            if (metadata.st_ino, metadata.st_dev) != (actual.st_ino, actual.st_dev):
                raise RuntimeError('Component file changed during snapshot')
            data = stream.read(maximum + 1)
    finally:
        os.close(directory)
    if len(data) > maximum:
        raise RuntimeError('Component configuration is unexpectedly large')
    return {'exists': True, 'data': base64.b64encode(data).decode(),
            'mode': stat.S_IMODE(actual.st_mode), 'uid': actual.st_uid, 'gid': actual.st_gid}


def atomic_write(path, data, mode=0o644, uid=None, gid=None):
    path = Path(path)
    # Hold the directory rather than following a replacement path at rename time.
    directory = directory_fd(path.parent)
    temporary = '.oxp3-' + next(tempfile._get_candidate_names())
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(temporary, flags, mode, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            if uid is not None and hasattr(os, 'fchown'):
                os.fchown(stream.fileno(), uid, gid)
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def remove_file(path):
    path = Path(path)
    directory = directory_fd(path.parent)
    try:
        os.unlink(path.name, dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(directory)


def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        directory = directory_fd(self.directory)
        try:
            lock = os.open('.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=directory)
        finally:
            os.close(directory)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return method(self, *args, **kwargs)
        finally:
            os.close(lock)
    return run


class FileTransaction:
    def snapshot(self, path):
        return snapshot(path)
    def __init__(self, state_directory, allowed):
        self.directory = Path(state_directory)
        self.allowed = tuple(str(Path(path).absolute()) for path in allowed)
        self.state = self.directory / 'state.json'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise RuntimeError('Private transaction state directory required')

    def save(self, value):
        atomic_write(self.state, (json.dumps(value, indent=2) + '\n').encode(), 0o600)

    def installed_metadata(self, path, original):
        if original['exists']:
            return {key: original[key] for key in ('mode', 'uid', 'gid')}
        parent = Path(path).parent.stat()
        return {'mode': 0o644, 'uid': os.geteuid(),
                'gid': parent.st_gid if parent.st_mode & stat.S_ISGID else os.getegid()}

    def load(self):
        saved = snapshot(self.state, maximum=8 * 1024 * 1024)
        if not saved['exists'] or saved['uid'] != os.geteuid() or saved['mode'] & 0o077:
            raise RuntimeError('Private transaction state file required')
        value = json.loads(base64.b64decode(saved['data']))
        if value['allowed'] != list(self.allowed):
            raise RuntimeError('Transaction allowlist changed; preserve original state')
        return value

    @serialized
    def apply(self, changes):
        if set(changes) != set(self.allowed):
            raise ValueError('Changes must match the explicit component file allowlist')
        if self.state.exists():
            value = self.load()
            if value['phase'] not in ('installed', 'prepared', 'installing', 'failed'):
                raise RuntimeError('Rollback or unresolved state requires a new explicit transaction')
            # Check every file before updating any of them. Retrying an operation
            # must not silently erase a later manual edit.
            unchanged = value['phase'] == 'installed'
            for path in self.allowed:
                current = self.snapshot(path)
                encoded = current.get('data') if current['exists'] else None
                desired = base64.b64encode(changes[path]).decode() if changes[path] is not None else None
                unchanged = unchanged and encoded == desired
                original = value['original'][path]
                known = [original.get('data') if original['exists'] else None]
                known += value.get('accepted', {}).get(path, [])
                if path in value['applied']: known.append(value['applied'][path])
                if encoded not in known:
                    raise RuntimeError('Configuration changed after install; refusing to overwrite user changes')
                if current['exists'] and any(current[key] != expected for key, expected in self.installed_metadata(path, original).items()):
                    raise RuntimeError('Configuration ownership or permissions changed after install')
            if unchanged:
                return
        else:
            value = {'allowed': list(self.allowed), 'phase': 'prepared',
                     'original': {path: self.snapshot(path) for path in self.allowed}, 'applied': {}, 'accepted': {}}
            self.save(value)
        # Persist the complete intent before the first write. An unwritten file
        # still equals its original snapshot and rollback leaves it unchanged.
        # This avoids serializing every large plugin payload once per file.
        for path in self.allowed:
            encoded = base64.b64encode(changes[path]).decode() if changes[path] is not None else None
            accepted = value.setdefault('accepted', {}).setdefault(path, [])
            if path in value['applied'] and value['applied'][path] not in accepted:
                accepted.append(value['applied'][path])
            value['applied'][path] = encoded
        value['phase'] = 'installing'; self.save(value)
        try:
            for path in self.allowed:
                data = changes[path]
                if data is None:
                    try: remove_file(path)
                    except FileNotFoundError: pass
                else:
                    original = value['original'][path]
                    metadata = self.installed_metadata(path, original)
                    atomic_write(path, data, metadata['mode'], metadata['uid'], metadata['gid'])
            value['phase'] = 'installed'; self.save(value)
        except Exception:
            value['phase'] = 'failed'; self.save(value)
            raise

    @serialized
    def rollback(self):
        value = self.load(); errors = []
        for path in self.allowed:
            try:
                if path not in value['applied']:
                    continue
                current = self.snapshot(path)
                encoded = current.get('data') if current['exists'] else None
                expected = value['applied'][path]
                original = value['original'][path]
                original_encoded = original.get('data') if original['exists'] else None
                metadata_matches = not original['exists'] or all(current.get(key) == original[key] for key in ('mode', 'uid', 'gid'))
                if encoded == original_encoded and metadata_matches:
                    continue  # Already restored by a previous partial attempt.
                if encoded != expected and encoded not in value.get('accepted', {}).get(path, []):
                    raise RuntimeError('Configuration changed after install; refusing to overwrite user changes')
                if current['exists'] and any(current[key] != expected for key, expected in self.installed_metadata(path, original).items()):
                    raise RuntimeError('Configuration ownership or permissions changed after install')
                if original['exists']:
                    atomic_write(path, base64.b64decode(original['data']), original['mode'], original['uid'], original['gid'])
                else:
                    remove_file(path)
            except Exception as error:
                errors.append({'path': path, 'error': str(error)})
        value['phase'] = 'partial_restore' if errors else 'rolled_back'; value['restore_errors'] = errors; self.save(value)
        return errors
