"""Live X2 Mini DMI gate and user-owned KDE launcher management.

The local evidence has an ``oxpec.ko`` modalias containing the normalized
``ONEXPLAYERX2MiniPRO`` token, but no raw X2 Mini sysfs capture. The accepted
product spellings below are therefore an explicit, fail-closed allowlist; the
board name is returned for diagnostics and never substitutes for product_name.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping


DMI_ROOT = Path('/sys/class/dmi/id')
SCRIPT_RELATIVE = PurePosixPath('.local/lib/oxp3-desktop-hdr-runtime/hdr_trial.py')
STATE_RELATIVE = PurePosixPath('.local/state/x2mini-hdr/launchers.json')
REMOVAL_RELATIVE = PurePosixPath('.local/state/x2mini-hdr/disabled.json')
APPLICATION_RELATIVE = PurePosixPath('.local/share/applications/x2mini-hdr.desktop')
LAUNCHER_NAME = 'x2mini-hdr.desktop'
_MAX_STATE_BYTES = 32 * 1024
_MAX_LAUNCHER_BYTES = 16 * 1024
_MAX_SCRIPT_BYTES = 32 * 1024 * 1024
_MAX_TRUSTED_SOURCE_BYTES = 64 * 1024
_ACCEPTED_PRODUCTS = frozenset(('ONEXPLAYERX2MINI', 'ONEXPLAYERX2MINIPRO'))
_TRIAL_ACTIVE_PHASES = frozenset(('armed', 'enabled', 'visible', 'reverting', 'rollback_failed'))
_TRIAL_TERMINAL_PHASES = frozenset(('confirmed', 'reverted'))
_TRIAL_PROFILE = 'X2MINI_HDR_TRIAL_475_700_V1'


class LauncherError(RuntimeError):
    """A safe install or cleanup could not be completed."""


class LauncherConflictError(LauncherError):
    """An unmanaged or user-edited launcher would otherwise be overwritten."""


def _normalize(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    normalized: list[str] = []
    for char in value:
        if char.isascii() and char.isalnum():
            normalized.append(char.upper())
        elif char in ' \t\r\n\v\f_-':
            continue
        else:
            return ''
    return ''.join(normalized)


def read_device() -> dict[str, str]:
    """Read the live DMI vendor, product, and board strings from sysfs."""
    result: dict[str, str] = {}
    for field in ('sys_vendor', 'product_name', 'board_name'):
        try:
            result[field] = (DMI_ROOT / field).read_text(encoding='utf-8').strip().strip('\x00')
        except (OSError, UnicodeError):
            result[field] = ''
    return result


def device_matches(fields: Mapping[str, Any]) -> bool:
    """Return true only for an exact allowlisted X2 Mini vendor/product pair."""
    if not isinstance(fields, Mapping):
        return False
    vendor = _normalize(fields.get('sys_vendor'))
    product = _normalize(fields.get('product_name'))
    return vendor == 'ONENETBOOK' and product in _ACCEPTED_PRODUCTS


def is_x2mini() -> bool:
    """Test the current machine, using live sysfs rather than staged-image data."""
    return device_matches(read_device())


def _has_reparse_point(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, 'st_file_attributes', 0)
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return bool(attributes & reparse)


def _absolute(path: os.PathLike[str] | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _check_chain(path: Path, *, allow_missing: bool) -> None:
    """Reject symlinks, reparse points, and non-directory ancestors."""
    if not path.is_absolute():
        raise LauncherError('Managed paths must be absolute')
    cursor = Path(path.anchor)
    parts = path.parts[1:]
    missing = False
    for index, part in enumerate(parts):
        if part in ('', '.', '..'):
            raise LauncherError('Non-canonical managed path')
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if not allow_missing:
                raise LauncherError('Required path is missing: ' + str(cursor))
            missing = True
            continue
        except OSError as error:
            raise LauncherError('Cannot inspect managed path: ' + str(cursor)) from error
        if missing:
            raise LauncherError('Path exists below a missing ancestor: ' + str(cursor))
        if _has_reparse_point(info):
            raise LauncherError('Symlink or reparse point in managed path: ' + str(cursor))
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LauncherError('Managed path ancestor is not a directory: ' + str(cursor))


def _effective_uid() -> int | None:
    getter = getattr(os, 'geteuid', None)
    return getter() if callable(getter) else None


def _check_owner(info: os.stat_result, owner: tuple[int, int], description: str) -> None:
    if os.name == 'posix' and (info.st_uid != owner[0] or info.st_gid != owner[1]):
        raise LauncherError(description + ' is not owned by the target user')


def _home_info(home: os.PathLike[str] | str, *, allow_root: bool) -> tuple[Path, tuple[int, int]]:
    path = _absolute(home)
    _check_chain(path, allow_missing=False)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise LauncherError('Target home is not a directory')
    owner = (info.st_uid, info.st_gid)
    if os.name == 'posix':
        if info.st_uid == 0:
            raise LauncherError('Target home must belong to a non-root user')
        current = _effective_uid()
        if current == 0 and not allow_root:
            raise LauncherError('Launcher installation must run as the target non-root user')
        if current not in ((0, info.st_uid) if allow_root else (info.st_uid,)):
            raise LauncherError('Caller is outside the target user scope')
    return path, owner


def _relative_parts(home: Path, path: Path) -> tuple[str, ...]:
    try:
        relative = path.relative_to(home)
    except ValueError as error:
        raise LauncherError('Managed path must stay below the target home') from error
    parts = relative.parts
    if not parts or any(part in ('', '.', '..') for part in parts):
        raise LauncherError('Unsafe home-relative path')
    return parts


def _relative_text(home: Path, path: Path) -> str:
    return PurePosixPath(*_relative_parts(home, path)).as_posix()


def _desktop_dir_from_config(home: Path) -> Path | None:
    config = home / '.config' / 'user-dirs.dirs'
    try:
        _check_chain(config, allow_missing=True)
        info = config.lstat()
    except FileNotFoundError:
        return None
    except LauncherError:
        return None
    if _has_reparse_point(info) or not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_STATE_BYTES:
        return None
    try:
        home_info = home.stat()
        _check_owner(info, (home_info.st_uid, home_info.st_gid), 'XDG user directories configuration')
    except (LauncherError, OSError):
        return None
    if os.name == 'posix' and stat.S_IMODE(info.st_mode) & 0o022:
        return None
    try:
        content = config.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None
    lines = [line for line in content.splitlines() if re.match(r'^\s*XDG_DESKTOP_DIR\s*=', line)]
    if len(lines) != 1:
        return None
    try:
        values = shlex.split(lines[0].split('=', 1)[1].strip(), comments=True, posix=True)
    except ValueError:
        return None
    if len(values) != 1:
        return None
    value = values[0]
    if value.startswith('$HOME/'):
        suffix = value[len('$HOME/'):]
        if '$' in suffix or '~' in suffix:
            return None
        candidate = home.joinpath(*PurePosixPath(suffix).parts)
    elif value.startswith('${HOME}/'):
        suffix = value[len('${HOME}/'):]
        if '$' in suffix or '~' in suffix:
            return None
        candidate = home.joinpath(*PurePosixPath(suffix).parts)
    else:
        if '$' in value or '~' in value:
            return None
        raw = Path(value)
        if not raw.is_absolute():
            return None
        candidate = _absolute(raw)
    if '..' in PurePosixPath(value.replace('\\', '/')).parts:
        return None
    candidate = _absolute(candidate)
    try:
        parts = _relative_parts(home, candidate)
        if not parts:
            return None
        _check_chain(candidate, allow_missing=True)
    except LauncherError:
        return None
    return candidate


def _desktop_dir(home: Path, desktop_path: os.PathLike[str] | str | None) -> Path:
    if desktop_path is None:
        candidate = _desktop_dir_from_config(home) or (home / 'Desktop')
    else:
        supplied = Path(desktop_path)
        if any(part == '..' for part in supplied.parts):
            raise LauncherError('Desktop path cannot contain parent traversal')
        candidate = supplied if supplied.is_absolute() else home / supplied
    candidate = _absolute(candidate)
    _relative_parts(home, candidate)
    if candidate == home / APPLICATION_RELATIVE.parent:
        raise LauncherError('Desktop path cannot be the applications directory')
    _check_chain(candidate, allow_missing=True)
    return candidate


def _expected_script(home: Path, script_path: os.PathLike[str] | str) -> Path:
    expected = home.joinpath(*SCRIPT_RELATIVE.parts)
    supplied = Path(script_path)
    if supplied.is_absolute():
        matches = os.path.normcase(os.path.abspath(os.fspath(supplied))) == os.path.normcase(str(expected))
    else:
        raw = os.fspath(script_path).replace('\\', '/')
        matches = PurePosixPath(raw).as_posix() == SCRIPT_RELATIVE.as_posix()
    if not matches:
        raise LauncherError('Trial script must use the fixed home-relative runtime path')
    _check_chain(expected, allow_missing=False)
    return expected


def _snapshot_file(path: Path, owner: tuple[int, int], maximum: int) -> dict[str, Any] | None:
    _check_chain(path, allow_missing=True)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if _has_reparse_point(before) or not stat.S_ISREG(before.st_mode):
        raise LauncherError('Managed target is not a regular file: ' + str(path))
    _check_owner(before, owner, 'Managed file')
    if before.st_size > maximum:
        raise LauncherError('Managed file is oversized: ' + str(path))
    try:
        data = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise LauncherError('Cannot read managed file: ' + str(path)) from error
    if (_has_reparse_point(after) or not stat.S_ISREG(after.st_mode)
            or before.st_dev != after.st_dev or before.st_ino != after.st_ino
            or before.st_size != after.st_size or len(data) != before.st_size):
        raise LauncherError('Managed file changed while being read: ' + str(path))
    if before.st_uid != after.st_uid or before.st_gid != after.st_gid or before.st_nlink != after.st_nlink:
        raise LauncherError('Managed file ownership changed while being read: ' + str(path))
    return {'data': data, 'mode': stat.S_IMODE(after.st_mode), 'uid': after.st_uid,
            'gid': after.st_gid, 'nlink': after.st_nlink}


def _same_snapshot(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is right
    return left['data'] == right['data'] and left['mode'] == right['mode']


def _record_for(relative: str, data: bytes, mode: int) -> dict[str, Any]:
    return {'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'mode': mode}


def _validate_relative_launcher(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value or ':' in value:
        raise LauncherError('Invalid launcher path in ownership state')
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in ('', '.', '..') for part in path.parts):
        raise LauncherError('Unsafe launcher path in ownership state')
    if path.name != LAUNCHER_NAME:
        raise LauncherError('Unexpected launcher name in ownership state')
    if role == 'applications' and value != APPLICATION_RELATIVE.as_posix():
        raise LauncherError('Unexpected applications launcher path in ownership state')
    if role == 'desktop' and value == APPLICATION_RELATIVE.as_posix():
        raise LauncherError('Duplicate launcher path in ownership state')
    if value.startswith('.local/state/x2mini-hdr/'):
        raise LauncherError('Launcher path overlaps ownership state')
    return value


def _validate_state(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {'schema', 'launchers'} or value.get('schema') != 1:
        raise LauncherError('Invalid launcher ownership state')
    launchers = value['launchers']
    if not isinstance(launchers, dict) or set(launchers) != {'applications', 'desktop'}:
        raise LauncherError('Invalid launcher ownership records')
    normalized: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    for role in ('applications', 'desktop'):
        record = launchers[role]
        if not isinstance(record, dict) or set(record) != {'path', 'sha256', 'mode'}:
            raise LauncherError('Invalid launcher ownership record')
        relative = _validate_relative_launcher(record['path'], role)
        digest = record['sha256']
        mode = record['mode']
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise LauncherError('Invalid launcher hash in ownership state')
        if type(mode) is not int or mode != 0o755:
            raise LauncherError('Invalid launcher mode in ownership state')
        if relative in used:
            raise LauncherError('Duplicate launcher path in ownership state')
        used.add(relative)
        normalized[role] = {'path': relative, 'sha256': digest, 'mode': mode}
    return normalized


def _read_state(home: Path, owner: tuple[int, int]) -> tuple[Path, dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    path = home.joinpath(*STATE_RELATIVE.parts)
    snapshot = _snapshot_file(path, owner, _MAX_STATE_BYTES)
    if snapshot is None:
        return path, None, None
    if os.name == 'posix' and snapshot['mode'] != 0o600:
        raise LauncherError('Launcher ownership state must have mode 0600')
    if snapshot['nlink'] != 1:
        raise LauncherError('Launcher ownership state must not have hard links')
    try:
        value = json.loads(snapshot['data'].decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise LauncherError('Invalid launcher ownership state') from error
    return path, _validate_state(value), snapshot


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _ensure_directories(home: Path, owner: tuple[int, int], targets: list[Path]) -> None:
    for target in targets:
        _relative_parts(home, target)
        parent = target
        if target.suffix:
            parent = target.parent
        _check_chain(parent, allow_missing=True)
        parts = _relative_parts(home, parent)
        current = home
        for part in parts:
            current = current / part
            try:
                info = current.lstat()
                created = False
            except FileNotFoundError:
                try:
                    current.mkdir(mode=0o700 if current == home.joinpath(*STATE_RELATIVE.parts[:-1]) else 0o755)
                except FileExistsError:
                    pass
                info = current.lstat()
                created = True
            if _has_reparse_point(info) or not stat.S_ISDIR(info.st_mode):
                raise LauncherError('Managed directory is unsafe: ' + str(current))
            _check_owner(info, owner, 'Managed directory')
            mode = 0o700 if current == home.joinpath(*STATE_RELATIVE.parts[:-1]) else 0o755
            if created:
                if os.name == 'posix' and _effective_uid() == 0:
                    os.chown(current, owner[0], owner[1])
                os.chmod(current, mode)
            else:
                existing_mode = stat.S_IMODE(info.st_mode)
                if os.name == 'posix' and existing_mode & 0o022:
                    raise LauncherError('Managed directory is writable by other users: ' + str(current))
                if (os.name == 'posix'
                        and current == home.joinpath(*STATE_RELATIVE.parts[:-1])
                        and existing_mode != 0o700):
                    raise LauncherError('Launcher state directory must be private')


def _desktop_quote(argument: str) -> str:
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in argument):
        raise LauncherError('Desktop command path contains control characters')
    escaped = argument.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + escaped + '"'


def _launcher_bytes(script: Path) -> bytes:
    command = '/usr/bin/python3 -I -B ' + _desktop_quote(str(script))
    text = ('[Desktop Entry]\n'
            'Type=Application\n'
            'Name=X2 Mini KDE HDR Trial\n'
            'Name[zh_CN]=ONEXPLAYER X2 Mini KDE HDR 试用\n'
            'Comment=Open the X2 Mini KDE HDR trial controls\n'
            'Comment[zh_CN]=打开 X2 Mini KDE HDR 试用控制界面\n'
            'Exec=' + command + '\n'
            'Icon=video-display\n'
            'Terminal=false\n'
            'Categories=Utility;\n')
    data = text.encode('utf-8')
    if len(data) > _MAX_LAUNCHER_BYTES:
        raise LauncherError('Generated launcher is oversized')
    return data


def _atomic_write(path: Path, data: bytes, mode: int, owner: tuple[int, int],
                  expected: dict[str, Any] | None, maximum: int) -> None:
    parent = path.parent
    _check_chain(parent, allow_missing=False)
    current = _snapshot_file(path, owner, maximum)
    if not _same_snapshot(current, expected):
        raise LauncherConflictError('Managed file changed before atomic update: ' + str(path))
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(parent))
    try:
        if os.name == 'posix' and _effective_uid() == 0:
            os.fchown(descriptor, owner[0], owner[1])
        if os.name == 'posix' and hasattr(os, 'fchmod'):
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _check_chain(parent, allow_missing=False)
        current = _snapshot_file(path, owner, maximum)
        if not _same_snapshot(current, expected):
            raise LauncherConflictError('Managed file changed during atomic update: ' + str(path))
        os.replace(temporary, path)
        try:
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _launcher_content_matches(snapshot: dict[str, Any] | None, record: dict[str, Any]) -> bool:
    return (snapshot is not None and (os.name != 'posix' or snapshot['mode'] == record['mode'])
            and hashlib.sha256(snapshot['data']).hexdigest() == record['sha256'])


def _install_launchers_unlocked(home: os.PathLike[str] | str, script_path: os.PathLike[str] | str,
                      desktop_path: os.PathLike[str] | str | None = None) -> tuple[str, ...]:
    """Install or refresh the menu/Desktop launcher only on an exact live X2 Mini.

    Returns the two managed absolute launcher paths. A non-matching or unknown
    live DMI returns an empty tuple without creating files or directories.
    """
    if not is_x2mini():
        return ()
    home_path, owner = _home_info(home, allow_root=False)
    script = _expected_script(home_path, script_path)
    script_snapshot = _snapshot_file(script, owner, _MAX_SCRIPT_BYTES)
    if script_snapshot is None:
        raise LauncherError('HDR trial script is missing from its fixed runtime path')
    app_path = home_path.joinpath(*APPLICATION_RELATIVE.parts)
    desktop_directory = _desktop_dir(home_path, desktop_path)
    desktop_target = desktop_directory / LAUNCHER_NAME
    paths = {'applications': app_path, 'desktop': desktop_target}
    relative = {role: _relative_text(home_path, path) for role, path in paths.items()}
    if len(set(relative.values())) != 2:
        raise LauncherError('Applications and Desktop launcher paths must be distinct')
    for path in paths.values():
        _check_chain(path, allow_missing=True)

    state_path, old_records, state_snapshot = _read_state(home_path, owner)
    if old_records is not None and old_records['desktop']['path'] != relative['desktop']:
        raise LauncherConflictError('XDG Desktop path changed; clean up existing launchers before reinstalling')

    data = _launcher_bytes(script)
    new_records = {role: _record_for(relative[role], data, 0o755) for role in paths}
    launcher_snapshots: dict[str, dict[str, Any] | None] = {}
    pending: list[str] = []
    for role, path in paths.items():
        snapshot = _snapshot_file(path, owner, _MAX_LAUNCHER_BYTES)
        launcher_snapshots[role] = snapshot
        old_record = old_records.get(role) if old_records is not None else None
        if snapshot is not None:
            if old_record is None:
                raise LauncherConflictError('Unmanaged launcher already exists: ' + str(path))
            if not _launcher_content_matches(snapshot, old_record):
                raise LauncherConflictError('Launcher was edited by the user; preserving it: ' + str(path))
        if (snapshot is None or snapshot['data'] != data
                or (os.name == 'posix' and snapshot['mode'] != 0o755)):
            pending.append(role)

    state_data = (json.dumps({'schema': 1, 'launchers': new_records}, sort_keys=True,
                             separators=(',', ':')) + '\n').encode('utf-8')
    state_current = state_snapshot
    if state_current is not None and state_current['data'] != state_data:
        # A valid prior state is owned and may be refreshed atomically.
        pass
    _ensure_directories(home_path, owner, [*paths.values(), state_path])

    # Write the ownership record first. A crash after this point is recoverable:
    # missing files are safe to recreate or harmless for cleanup.
    _atomic_write(state_path, state_data, 0o600, owner, state_current, _MAX_STATE_BYTES)
    for role in pending:
        _atomic_write(paths[role], data, 0o755, owner, launcher_snapshots[role], _MAX_LAUNCHER_BYTES)
    return tuple(str(paths[role]) for role in ('applications', 'desktop'))


def _unlink_if_unchanged(path: Path, expected: dict[str, Any], owner: tuple[int, int], maximum: int) -> bool:
    current = _snapshot_file(path, owner, maximum)
    if current is None:
        return False
    if not _same_snapshot(current, expected):
        raise LauncherConflictError('Managed file changed before removal: ' + str(path))
    path.unlink()
    return True


def _verify_root_trusted_path(path: Path, description: str) -> os.stat_result:
    """Verify a root-owned file and every ancestor before root uses it."""
    if os.name != 'posix' or not path.is_absolute() or not hasattr(os, 'O_NOFOLLOW'):
        raise LauncherError(description + ' cannot be verified as trusted')
    cursor = Path(path.anchor)
    parts = path.parts[1:]
    leaf_info: os.stat_result | None = None
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as error:
            raise LauncherError(description + ' path cannot be inspected') from error
        if _has_reparse_point(info) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise LauncherError(description + ' path is not root-owned and protected')
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LauncherError(description + ' path has a non-directory ancestor')
        leaf_info = info
    if leaf_info is None or not stat.S_ISREG(leaf_info.st_mode):
        raise LauncherError(description + ' is not a regular file')
    return leaf_info


def _root_trusted_file(path: Path, description: str, maximum: int) -> bytes:
    """Read a bounded root-owned file only through its protected path."""
    leaf_info = _verify_root_trusted_path(path, description)
    if leaf_info.st_size > maximum:
        raise LauncherError(description + ' is oversized')

    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0
                or stat.S_IMODE(opened.st_mode) & 0o022
                or opened.st_dev != leaf_info.st_dev or opened.st_ino != leaf_info.st_ino
                or opened.st_size > maximum):
            raise LauncherError(description + ' changed while being opened')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = -1
            data = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if (len(data) > maximum or len(data) != opened.st_size
                or after.st_dev != opened.st_dev or after.st_ino != opened.st_ino
                or after.st_size != opened.st_size):
            raise LauncherError(description + ' changed while being read')
        return data
    except OSError as error:
        raise LauncherError(description + ' could not be read safely') from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _trusted_module_source() -> tuple[Path, str]:
    """Load only this module from its protected runtime installation path."""
    if _effective_uid() != 0:
        raise LauncherError('Trusted cleanup source can only be read by root')
    source_path = Path(__file__)
    if (not source_path.is_absolute() or source_path.name not in ('x2mini_device.py', 'x2mini_hdr_device.py')
            or str(source_path) != os.path.normpath(os.fspath(source_path))):
        raise LauncherError('Canonical cleanup source path is invalid')
    source_bytes = _root_trusted_file(source_path, 'Canonical cleanup source', _MAX_TRUSTED_SOURCE_BYTES)
    try:
        return source_path, source_bytes.decode('utf-8')
    except UnicodeError as error:
        raise LauncherError('Canonical cleanup source is not UTF-8') from error


def _trusted_python_executable() -> str:
    executable = Path(sys.executable)
    if not executable.is_absolute():
        raise LauncherError('System Python path is not absolute')
    resolved = Path(os.path.realpath(executable))
    info = _verify_root_trusted_path(resolved, 'System Python executable')
    if not info.st_mode & 0o111:
        raise LauncherError('System Python executable is not executable')
    return str(resolved)


def _should_delegate_root_cleanup() -> bool:
    return os.name == 'posix' and _effective_uid() == 0


def _cleanup_as_home_user(home: Path, owner: tuple[int, int], *, reset: bool = False) -> tuple[str, ...]:
    source_path, source = _trusted_module_source()
    python = _trusted_python_executable()
    worker = (
        'import json, sys\n'
        'source = ' + repr(source) + '\n'
        'namespace = {"__name__": "_x2mini_cleanup_worker", "__file__": '
        + repr(str(source_path)) + '}\n'
        'exec(compile(source, namespace["__file__"], "exec"), namespace)\n'
        'removed = namespace["' + ('reset_after_install' if reset else 'cleanup_launchers') + '"](sys.argv[1])\n'
        'print(json.dumps({"removed": list(removed)}, ensure_ascii=True, separators=(",", ":")))\n'
    )
    environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}
    try:
        completed = subprocess.run(
            [python, '-I', '-B', '-c', worker, str(home)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='strict',
            cwd='/',
            env=environment,
            timeout=30,
            check=False,
            user=owner[0],
            group=owner[1],
            extra_groups=[],
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise LauncherError('Could not run launcher cleanup as the target user') from error
    if completed.returncode != 0:
        raise LauncherError('Launcher cleanup as the target user failed')
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise LauncherError('Launcher cleanup returned an invalid result') from error
    if (not isinstance(result, dict) or set(result) != {'removed'}
            or not isinstance(result['removed'], list)
            or any(not isinstance(path, str) for path in result['removed'])):
        raise LauncherError('Launcher cleanup returned an invalid result')
    return tuple(result['removed'])


def _read_guard_json(path: Path, owner: tuple[int, int], *, private: bool) -> Any | None:
    snapshot = _snapshot_file(path, owner, 1024 * 1024)
    if snapshot is None:
        return None
    if snapshot['nlink'] != 1:
        raise LauncherError('HDR recovery/configuration file must not have hard links: ' + str(path))
    mode = snapshot['mode']
    if os.name == 'posix' and (mode & (0o077 if private else 0o022)):
        raise LauncherError('HDR recovery/configuration file permissions are unsafe: ' + str(path))
    try:
        return json.loads(snapshot['data'].decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise LauncherError('HDR recovery/configuration file is corrupt: ' + str(path)) from error


def _assert_trial_is_terminal(home: Path, owner: tuple[int, int]) -> None:
    trial_path = home.joinpath(*STATE_RELATIVE.parent.parts, 'trial.json')
    trial = _read_guard_json(trial_path, owner, private=True)
    if trial is None and not trial_path.exists():
        return
    if (not isinstance(trial, dict) or trial.get('profile') != _TRIAL_PROFILE
            or trial.get('phase') not in _TRIAL_ACTIVE_PHASES | _TRIAL_TERMINAL_PHASES
            or not isinstance(trial.get('token'), str)
            or not re.fullmatch(r'[0-9a-f]{32}', trial['token'])
            or type(trial.get('deadline')) not in (int, float)
            or not math.isfinite(trial['deadline'])
            or not isinstance(trial.get('original'), dict)
            or set(trial['original']) != {'hdr', 'wcg'}
            or any(type(flag) is not bool for flag in trial['original'].values())
            or not isinstance(trial.get('boot'), str)):
        raise LauncherError('HDR trial state is corrupt; preserve it for recovery')
    if trial['phase'] in _TRIAL_ACTIVE_PHASES:
        raise LauncherError('HDR trial recovery is pending; preserve the launcher runtime')


def _assert_persisted_hdr_is_off(home: Path, owner: tuple[int, int]) -> None:
    config_path = home / '.config' / 'kwinoutputconfig.json'
    config = _read_guard_json(config_path, owner, private=False)
    if config is None and not config_path.exists():
        return
    if not isinstance(config, list):
        raise LauncherError('KWin output configuration is corrupt; preserve the launcher runtime')
    for group in config:
        if not isinstance(group, dict):
            raise LauncherError('KWin output configuration is corrupt; preserve the launcher runtime')
        if group.get('name') != 'outputs':
            continue
        outputs = group.get('data', [])
        if not isinstance(outputs, list):
            raise LauncherError('KWin output configuration is corrupt; preserve the launcher runtime')
        for output in outputs:
            if not isinstance(output, dict):
                raise LauncherError('KWin output configuration is corrupt; preserve the launcher runtime')
            if output.get('connectorName') != 'eDP-1':
                continue
            for field in ('highDynamicRange', 'wideColorGamut'):
                value = output.get(field)
                if value is not None and type(value) is not bool:
                    raise LauncherError('KWin HDR/WCG state is unknown; preserve the launcher runtime')
                if value is True:
                    raise LauncherError('KWin still has HDR or WCG enabled; turn it off before restoring')


@contextmanager
def _trial_lock(home: Path, owner: tuple[int, int]):
    """Use the exact same lock as hdr_trial.Journal for removal/start exclusion."""
    path = home.joinpath(*STATE_RELATIVE.parent.parts, 'trial.lock')
    _ensure_directories(home, owner, [path])
    _check_chain(path, allow_missing=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if (_has_reparse_point(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or os.name == 'posix' and (info.st_uid != owner[0] or info.st_gid != owner[1]
                                            or stat.S_IMODE(info.st_mode) & 0o077)):
            raise LauncherError('Unsafe HDR trial lock')
        if os.name == 'posix':
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        else:
            import msvcrt
            if info.st_size == 0:
                os.write(descriptor, b'0')
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        yield
    finally:
        os.close(descriptor)


def _removal_interlock(home: Path, owner: tuple[int, int]) -> bool:
    path = home.joinpath(*REMOVAL_RELATIVE.parts)
    value = _read_guard_json(path, owner, private=True)
    if value is None:
        if not path.exists():
            return False
        raise LauncherError('HDR removal interlock is corrupt; preserve it for recovery')
    if value != {'schema': 1, 'state': 'disabled_for_removal'}:
        raise LauncherError('HDR removal interlock is corrupt; preserve it for recovery')
    return True


def assert_trial_available(home: os.PathLike[str] | str) -> None:
    """Reject a durable removal interlock; caller must hold Journal's trial.lock."""
    home_path, owner = _home_info(home, allow_root=False)
    if _removal_interlock(home_path, owner):
        raise LauncherError('HDR runtime removal is pending; reinstall the component before another trial')


def install_launchers(home: os.PathLike[str] | str, script_path: os.PathLike[str] | str,
                      desktop_path: os.PathLike[str] | str | None = None) -> tuple[str, ...]:
    """Startup may refresh icons, but must never lift a removal interlock."""
    if not is_x2mini():
        return ()
    home_path, owner = _home_info(home, allow_root=False)
    with _trial_lock(home_path, owner):
        assert_trial_available(home_path)
        return _install_launchers_unlocked(home_path, script_path, desktop_path)


def reset_after_install(home: os.PathLike[str] | str) -> tuple[str, ...]:
    """Canonical deployment-only hook, after a complete successful runtime install.

    Never expose this operation through the user runtime command line or call it
    from compositor startup. Root delegates protected source to the home owner.
    """
    home_path, owner = _home_info(home, allow_root=True)
    if _should_delegate_root_cleanup():
        return _cleanup_as_home_user(home_path, owner, reset=True)
    with _trial_lock(home_path, owner):
        if not _removal_interlock(home_path, owner):
            return ()
        _assert_trial_is_terminal(home_path, owner)
        _assert_persisted_hdr_is_off(home_path, owner)
        path = home_path.joinpath(*REMOVAL_RELATIVE.parts)
        path.unlink()
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    return ()


def cleanup_launchers(home: os.PathLike[str] | str) -> tuple[str, ...]:
    """Remove unchanged launchers from the private state record, without running target code."""
    home_path, owner = _home_info(home, allow_root=True)
    if _should_delegate_root_cleanup():
        return _cleanup_as_home_user(home_path, owner)
    with _trial_lock(home_path, owner):
        return _cleanup_launchers_locked(home_path, owner)


def _cleanup_launchers_locked(home_path: Path, owner: tuple[int, int]) -> tuple[str, ...]:
    # Safety does not depend on successful icon installation: the generic HDR
    # control can also start a trial when a launcher write conflicted.
    _assert_trial_is_terminal(home_path, owner)
    _assert_persisted_hdr_is_off(home_path, owner)
    # This outlives the dropped-uid worker and guards the entire subsequent root
    # transaction, including a crash or an already-running launcher's delay.
    if not _removal_interlock(home_path, owner):
        path = home_path.joinpath(*REMOVAL_RELATIVE.parts)
        data = b'{"schema":1,"state":"disabled_for_removal"}\n'
        _atomic_write(path, data, 0o600, owner, None, _MAX_STATE_BYTES)
    state_path, records, state_snapshot = _read_state(home_path, owner)
    if records is None or state_snapshot is None:
        return ()

    planned: list[tuple[Path, dict[str, Any], dict[str, Any] | None]] = []
    for role in ('applications', 'desktop'):
        record = records[role]
        relative = _validate_relative_launcher(record['path'], role)
        path = home_path.joinpath(*PurePosixPath(relative).parts)
        _check_chain(path, allow_missing=True)
        current = _snapshot_file(path, owner, _MAX_LAUNCHER_BYTES)
        planned.append((path, record, current))

    removed: list[str] = []
    preserved_edit = False
    for path, record, current in planned:
        if current is None:
            continue
        if not _launcher_content_matches(current, record):
            preserved_edit = True
            continue
        if _unlink_if_unchanged(path, current, owner, _MAX_LAUNCHER_BYTES):
            removed.append(str(path))

    if not preserved_edit:
        current_state = _snapshot_file(state_path, owner, _MAX_STATE_BYTES)
        if not _same_snapshot(current_state, state_snapshot):
            raise LauncherConflictError('Launcher ownership state changed before cleanup')
        state_path.unlink()
    return tuple(removed)


__all__ = ('LauncherConflictError', 'LauncherError', 'assert_trial_available', 'cleanup_launchers',
           'device_matches', 'install_launchers', 'is_x2mini', 'read_device', 'reset_after_install')
