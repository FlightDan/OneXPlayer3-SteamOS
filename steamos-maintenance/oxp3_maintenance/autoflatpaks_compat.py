"""Surgical repair for an already installed, pinned AutoFlatpaks 1.6.8.

No plugin archive, backend, installation logic or settings are distributed here.
The tiny polling edit matches the maintained Windows patch. Installed upstream
authorship, BSD-3-Clause LICENSE and all unrelated files remain untouched.
Call validate_transaction under the transaction lock before committing a plan.

Polling-block source: https://github.com/jurassicplayer/decky-autoflatpaks
AutoFlatpaks 1.6.8; guarded polling adapted by FlightDan, 2026.

BSD 3-Clause License

Copyright (c) 2022, Jurassicplayer
Original Copyright (c) 2022, Steam Deck Homebrew

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


COMPONENT = 'autoflatpaks-compat'
PREFIX = 'var/lib/oxp3-installer/decky/runtime/plugins/decky-autoflatpaks'
BASE_VERSION = '1.6.8'
VERSION = '1.6.8+oxp3.1'
UPSTREAM_ARCHIVE_SHA256 = '344fce82cfb4800caccb4d6c0ec46e1ad6c9594a622d5baa0bb31286baf2d1a5'
PATCHED_ARCHIVE_SHA256 = '706d2ff0b4a16ab496b38d6f43ba4435dc8937479309e0006b45dfee0bf34672'
BASE_HASHES = {
    'package.json': '999a8565513f4d66850e1e91e315f6fd43e3db4415e5c2660542fbe720b69c49',
    'dist/index.js': '2215474af4ac5ef12b670ebbb496a1a5d266a3ed52cb1626783b05bf6a25f540',
}
PATCHED_HASHES = {
    'package.json': '7280c4eded2455c99d278f558df1ca1288642b114c073e017cb967d885050f98',
    'dist/index.js': '93bba9a9b9d10a6bd549905bbd44d3180e17cefbb012c0c8732533e089cf1560',
}
WITNESSES = {
    'plugin.json': 'b6cd050ab482f467711bfaedc4eba6d73d72fbd2b317a1bdb1e4c1ad1786aab8',
    'main.py': '9806a2d328b8069d805d71ce4041a49bd53e752815bf72907736824c29802d9b',
    'LICENSE': 'dc3a1dd9bb1463083d9ff8831e85027d827a6b5ff70adda12e48d438ada7f885',
}
ORIGINAL = b'''          this.intervalID = setInterval(() => {
              // @ts-ignore
              let currentState = window.SystemPowerStore.batteryState;
              if (currentState != this.pseudoBatteryState)
                  this.setBatteryStateChange(currentState);
          }, 1000);'''
REPLACEMENT = b'''          this.intervalID = setInterval(() => {
              // OXP3 AutoFlatpaks compatibility: Steam may expose the store late.
              const currentState = window.SystemPowerStore?.batteryState;
              if (currentState == null || !Number.isFinite(currentState.eACState))
                  return;
              if (currentState != this.pseudoBatteryState)
                  this.setBatteryStateChange(currentState);
          }, 1000);'''
MAX_FILE = 1024 * 1024


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _mode(snapshot):
    mode = snapshot.get('mode')
    # Match Store's portable test representation; production runs on SteamOS.
    return 0o644 if os.name == 'nt' and mode == 0o666 else mode


def patched_bytes(package, frontend):
    """Return exactly the known two patched files; unknown/mixed states fail."""
    current = {'package.json': package, 'dist/index.js': frontend}
    hashes = {name: _hash(data) for name, data in current.items()}
    if hashes == PATCHED_HASHES:
        return current
    if hashes != BASE_HASHES:
        raise ValueError('AutoFlatpaks requires the unmodified pinned 1.6.8 or complete 1.6.8+oxp3.1; unknown or externally changed files are preserved')
    if frontend.count(ORIGINAL) != 1:
        raise ValueError('Unexpected AutoFlatpaks battery polling block')
    metadata = json.loads(package)
    metadata['version'] = VERSION
    metadata['oxp3_compatibility_patch'] = 'Defer battery polling until Steam power state is available'
    result = {'package.json': (json.dumps(metadata, indent=2) + '\n').encode(),
              'dist/index.js': frontend.replace(ORIGINAL, REPLACEMENT)}
    if {name: _hash(data) for name, data in result.items()} != PATCHED_HASHES:
        raise ValueError('AutoFlatpaks repair does not reproduce the reviewed patched files')
    return result


def _data(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('exists') is not True:
        raise ValueError('AutoFlatpaks must already be installed; this repair cannot install it')
    try:
        data = base64.b64decode(snapshot['data'], validate=True)
        mode = _mode(snapshot)
        if (type(mode) is not int or mode & 0o7022 or not mode & 0o400
                or snapshot['uid'] != 0 or snapshot['gid'] != 0 or len(data) > MAX_FILE):
            raise ValueError()
        return data
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Unsafe AutoFlatpaks installed file metadata') from exc


def _installed(read_snapshot):
    snapshots = {name: read_snapshot(PREFIX + '/' + name, user=False)
                 for name in (*BASE_HASHES, *WITNESSES)}
    data = {name: _data(snapshot) for name, snapshot in snapshots.items()}
    if any(_hash(data[name]) != expected for name, expected in WITNESSES.items()):
        raise ValueError('AutoFlatpaks identity, backend or original license differs from the reviewed release; preserve it for review')
    return snapshots, patched_bytes(data['package.json'], data['dist/index.js'])


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
            raise ValueError('Linked AutoFlatpaks installed path is unsupported')
        if path != root / relative and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Non-directory AutoFlatpaks installed path ancestor')
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise ValueError('AutoFlatpaks installed file is not a bounded single regular file')
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    return {'exists': True, 'data': base64.b64encode(data).decode(),
            'mode': stat.S_IMODE(info.st_mode) if os.name == 'posix' else 0o644,
            'uid': info.st_uid if os.name == 'posix' else 0,
            'gid': info.st_gid if os.name == 'posix' else 0}


def build_files(root):
    """Plan two existing canonical installed files; perform no system writes.

    The caller must reject conflicting ownership, including legacy autoflatpaks
    receipts. Return specs intact so the transaction preconditions
    survive planning. Frontend/backend settings and plugin installation are out
    of scope. Legacy home-directory installs require explicit adoption first.
    """
    snapshots, result = _installed(lambda path, **kwargs: _read(root, path, **kwargs))
    return {PREFIX + '/' + name: {
        'data': data, 'mode': snapshots[name]['mode'], 'component': COMPONENT,
        'user': False, 'mutable': False,
        'autoflatpaks_before_sha256': _hash(base64.b64decode(snapshots[name]['data'])),
    } for name, data in result.items()}


def _receipt(path, spec, slot=None):
    prefix = 'usr/local/lib/oxp3-maintenance/component-receipts/'
    if not path.startswith(prefix):
        return False
    parts = path[len(prefix):].split('/')
    if (len(parts) != 2 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}', parts[0])
            or parts[1] != COMPONENT + '.json' or slot is not None and parts[0] != slot):
        raise ValueError('Invalid AutoFlatpaks component receipt target')
    try:
        data = json.loads(spec.get('data', b''))
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid AutoFlatpaks component receipt') from error
    if (not isinstance(data, dict) or set(data) != {'component', 'slot', 'revision'}
            or data['component'] != COMPONENT or data['slot'] != parts[0]
            or not isinstance(data['revision'], str) or not re.fullmatch('[a-f0-9]{64}', data['revision'])
            or spec.get('mode') != 0o644 or spec.get('user') is not False
            or spec.get('mutable', False) is not False):
        raise ValueError('Invalid AutoFlatpaks component receipt')
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
        raise ValueError('AutoFlatpaks repair contains multiple slot receipts')
    if related and not selected:
        raise ValueError('AutoFlatpaks repair receipt requires the installed plugin files')
    if not selected:
        return
    if set(selected) != {PREFIX + '/' + name for name in BASE_HASHES}:
        raise ValueError('AutoFlatpaks repair must contain exactly its two existing installed files')
    snapshots, expected = _installed(read_snapshot)
    for name, data in expected.items():
        spec = selected[PREFIX + '/' + name]
        before = snapshots[name]
        validate_before(PREFIX + '/' + name, spec, before)
        if spec.get('data') != data:
            raise ValueError('AutoFlatpaks repair changed after planning; inspect the installed files again')


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
        raise ValueError('AutoFlatpaks repair target is outside the reviewed installed files')
    if (_hash(spec.get('data', b'')) != PATCHED_HASHES[name]
            or spec.get('mode') != _mode(before)
            or spec.get('user') is not False or spec.get('mutable') is not False
            or spec.get('autoflatpaks_before_sha256') != _hash(_data(before))):
        raise ValueError('AutoFlatpaks repair changed after planning; inspect the installed files again')
