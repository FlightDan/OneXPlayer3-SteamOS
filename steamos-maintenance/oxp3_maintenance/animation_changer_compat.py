"""Surgical path repair for already installed Animation Changer 1.3.2.

Only main.py is changed; no complete plugin or archive is distributed. Existing
settings, animations, metadata, frontend, authorship and license are preserved.
Requires exact original or prior canonical-path-patched backend and witnesses.
Source: https://github.com/TheLogicMaster/SDH-AnimationChanger
Path resolver adapted by FlightDan, 2026; original backend snippets below:

BSD 3-Clause License

Copyright (c) 2022, Justin Marentette
Original Copyright (c) 2022, SteamDeckHomebrew
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat


COMPONENT = 'animation-changer-compat'
PREFIX = 'var/lib/oxp3-installer/decky/runtime/plugins/SDH-AnimationChanger'
BASE_VERSION = '1.3.2'
UPSTREAM_ARCHIVE_SHA256 = 'f2c62b90ca60d8a80b6d0f75d8027552b1509c7a05842c6f4a24a9072846d133'
BASE_HASHES = {'main.py': '11a96a6f3108021b096e0aeb60c7d3ee3c6b2e237cf235c02f5753cf9d3382b8'}
PRIOR_HASHES = {'main.py': '86b9abdc61921ca3bc357c3063b30a7dd72276b940d5b3ed5b862c5f8720427f'}
PATCHED_HASHES = {'main.py': '18a686324b681d167c01107a07ea2027f7d317f3aa2902e1e2fc48a28b537f49'}
WITNESSES = {
    'plugin.json': 'bfe12b952650c0faa3712d3f71b0d1b4b41b9af0075bad10c7194d70c6927ebb',
    'package.json': 'bbd422d290270650bb4f6c7a0a9242f467a3cef0130478bec203127bf0b08544',
    'LICENSE': 'ef669ca78f3a52e6e50a35295c8294a6d766b9af68f06b6449721730f10f92b9',
    'dist/index.js': '9b2361a5092d006eb87e0fb004f8a1dfffc8283272506763d770bba0eca88a92',
}
ORIGINAL = b"OVERRIDE_PATH = os.path.expanduser('~/.steam/root/config/uioverrides/movies')"
CANONICAL = b"OVERRIDE_PATH = os.path.expanduser('~/.local/share/Steam/config/uioverrides/movies')"
REPLACEMENT = b'''\n\ndef get_override_path():
    steam_root = os.path.expanduser('~/.steam/root')
    # Preserve existing installations, including custom and dangling symlinks.
    # Never create the compatibility root as a directory before Steam does.
    if os.path.lexists(steam_root):
        steam_root = os.path.realpath(steam_root)
    else:
        steam_root = os.path.expanduser('~/.local/share/Steam')
    return os.path.join(steam_root, 'config', 'uioverrides', 'movies')'''
APPLY = b"    override_path = f'{OVERRIDE_PATH}/{video}'"
APPLY_REPLACEMENT = b'''    override_directory = get_override_path()
    os.makedirs(override_directory, exist_ok=True)
    override_path = os.path.join(override_directory, video)'''
STARTUP = b'            os.makedirs(OVERRIDE_PATH, exist_ok=True)'
STARTUP_REPLACEMENT = b'            os.makedirs(get_override_path(), exist_ok=True)'
MAX_FILE = 1024 * 1024


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _mode(snapshot):
    mode = snapshot.get('mode')
    # Match Store's portable test representation; production runs on SteamOS.
    return 0o644 if os.name == 'nt' and mode == 0o666 else mode


def patched_bytes(source):
    """Accept only exact reviewed backend versions, returning one repaired file."""
    hashes = {'main.py': _hash(source)}
    if hashes == PATCHED_HASHES:
        return {'main.py': source}
    if hashes not in (BASE_HASHES, PRIOR_HASHES):
        raise ValueError('Animation Changer requires exact installed 1.3.2 or its prior canonical-path patch; unknown or externally changed files are preserved')
    original = ORIGINAL if hashes == BASE_HASHES else CANONICAL
    if any(source.count(block) != 1 for block in (original, APPLY, STARTUP)):
        raise ValueError('Unexpected Animation Changer path blocks')
    result = source.replace(original, REPLACEMENT, 1).replace(
        APPLY, APPLY_REPLACEMENT, 1).replace(STARTUP, STARTUP_REPLACEMENT, 1)
    if _hash(result) != PATCHED_HASHES['main.py']:
        raise ValueError('Animation Changer repair does not reproduce the reviewed backend')
    return {'main.py': result}


def _data(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('exists') is not True:
        raise ValueError('Animation Changer must already be installed; this repair cannot install it')
    try:
        data = base64.b64decode(snapshot['data'], validate=True)
        mode = _mode(snapshot)
        if (type(mode) is not int or mode & 0o7022 or not mode & 0o400
                or snapshot['uid'] != 0 or snapshot['gid'] != 0 or len(data) > MAX_FILE):
            raise ValueError()
        return data
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Unsafe Animation Changer installed file metadata') from exc


def _installed(read_snapshot):
    snapshots = {name: read_snapshot(PREFIX + '/' + name, user=False)
                 for name in (*BASE_HASHES, *WITNESSES)}
    data = {name: _data(snapshot) for name, snapshot in snapshots.items()}
    if any(_hash(data[name]) != expected for name, expected in WITNESSES.items()):
        raise ValueError('Animation Changer identity, frontend or original license differs from the reviewed release; preserve it for review')
    return snapshots, patched_bytes(data['main.py'])


def _read(root, relative, *, user=False):
    """Planning reader; transaction validation uses Store's dirfd-safe reader."""
    root = Path(root).absolute()
    path = root
    for part in (None, *relative.split('/')):
        if part is not None:
            path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {'exists': False}
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked Animation Changer installed path is unsupported')
        if path != root / relative and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Non-directory Animation Changer installed path ancestor')
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise ValueError('Animation Changer installed file is not a bounded single regular file')
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    return {'exists': True, 'data': base64.b64encode(data).decode(),
            'mode': stat.S_IMODE(info.st_mode) if os.name == 'posix' else 0o644,
            'uid': info.st_uid if os.name == 'posix' else 0,
            'gid': info.st_gid if os.name == 'posix' else 0}


def build_files(root):
    """Plan one existing canonical installed file; perform no system writes.

    The caller must reject conflicting ownership, including legacy animation-changer
    receipts. Return specs intact so the transaction preconditions
    survive planning. Plugin settings and plugin installation are out
    of scope. Legacy home-directory installs require explicit adoption first.
    """
    snapshots, result = _installed(lambda path, **kwargs: _read(root, path, **kwargs))
    return {PREFIX + '/' + name: {
        'data': data, 'mode': snapshots[name]['mode'], 'component': COMPONENT,
        'user': False, 'mutable': False,
        'animation_changer_before_sha256': _hash(base64.b64decode(snapshots[name]['data'])),
    } for name, data in result.items()}


def _receipt(path, spec, slot=None):
    prefix = 'usr/local/lib/oxp3-maintenance/component-receipts/'
    if not path.startswith(prefix):
        return False
    parts = path[len(prefix):].split('/')
    if (len(parts) != 2 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}', parts[0])
            or parts[1] != COMPONENT + '.json' or slot is not None and parts[0] != slot):
        raise ValueError('Invalid Animation Changer component receipt target')
    try:
        data = json.loads(spec.get('data', b''))
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid Animation Changer component receipt') from error
    if (not isinstance(data, dict) or set(data) != {'component', 'slot', 'revision'}
            or data['component'] != COMPONENT or data['slot'] != parts[0]
            or not isinstance(data['revision'], str) or not re.fullmatch('[a-f0-9]{64}', data['revision'])
            or spec.get('mode') != 0o644 or spec.get('user') is not False
            or spec.get('mutable', False) is not False):
        raise ValueError('Invalid Animation Changer component receipt')
    return True


def validate_transaction(files, read_snapshot, *, slot=None):
    """Recheck installed identity and exact before-images under Store's lock.

    Run before Store constructs any pending journal. This is mandatory even for
    initially unmanaged targets; ordinary transaction originals provide restore
    and rollback once the exact existing installation has been accepted here.
    """
    related = {path: spec for path, spec in files.items() if spec.get('component') == COMPONENT}
    selected = {path: spec for path, spec in related.items() if not _receipt(path, spec, slot)}
    if len(related) - len(selected) > 1:
        raise ValueError('Animation Changer repair contains multiple slot receipts')
    if related and not selected:
        raise ValueError('Animation Changer repair receipt requires the installed plugin files')
    if not selected:
        return
    if set(selected) != {PREFIX + '/' + name for name in BASE_HASHES}:
        raise ValueError('Animation Changer repair must contain exactly its one existing installed file')
    snapshots, expected = _installed(read_snapshot)
    for name, data in expected.items():
        spec = selected[PREFIX + '/' + name]
        before = snapshots[name]
        validate_before(PREFIX + '/' + name, spec, before)
        if spec.get('data') != data:
            raise ValueError('Animation Changer repair changed after planning; inspect the installed files again')


def validate_before(path, spec, before):
    """Bind the exact before-image captured for the pending transaction.

    Store.apply must also call this immediately after capturing each target's
    ``before`` snapshot, so a change since validate_transaction cannot become
    an accepted original. Store's existing journal/recovery checks then protect
    the interval between that snapshot and replacement.
    """
    if spec.get('component') != COMPONENT:
        return
    if _receipt(path, spec):
        return
    name = path.removeprefix(PREFIX + '/')
    if name not in BASE_HASHES or path != PREFIX + '/' + name:
        raise ValueError('Animation Changer repair target is outside the reviewed installed files')
    if (_hash(spec.get('data', b'')) != PATCHED_HASHES[name]
            or spec.get('mode') != _mode(before)
            or spec.get('user') is not False or spec.get('mutable') is not False
            or spec.get('animation_changer_before_sha256') != _hash(_data(before))):
        raise ValueError('Animation Changer repair changed after planning; inspect the installed files again')
