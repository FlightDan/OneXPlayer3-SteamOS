"""Durable, bounded ownership receipts for two protected /opt runtime trees.

File snapshots remain authoritative. Unknown entries and pre-existing empty
folders are never inferred to belong to maintenance, including after a crash.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import uuid

ROOTS = ('opt/oxp3-desktop-gamma22/6.7.3-1.6', 'opt/oxp3-opti2xmx/20261005')
FIELDS = frozenset(('filesystem', 'ino', 'mode', 'uid', 'gid'))
LIMIT = 12000


def supported(path):
    return isinstance(path, str) and any(path == root or path.startswith(root + '/') for root in ROOTS)


def validate(store, value, *, intents=False):
    if not isinstance(value, dict) or len(value) > LIMIT:
        raise store._directory_error('Invalid runtime directory receipts')
    for path, receipt in value.items():
        store._path(path)
        if not supported(path):
            raise store._directory_error('Directory receipt is outside the fixed runtime roots')
        if receipt is None and intents:
            continue
        if (not isinstance(receipt, dict) or set(receipt) != FIELDS
                or not isinstance(receipt['filesystem'], str)
                or not 1 <= len(receipt['filesystem']) <= 4096
                or any(type(receipt[field]) is not int or receipt[field] < 0 for field in FIELDS - {'filesystem'})
                or receipt['mode'] > 0o7777):
            raise store._directory_error('Invalid runtime directory identity')
        if store.enforce_owner and (receipt['uid'] != 0 or receipt['mode'] & 0o022):
            raise store._directory_error('Untrusted runtime directory receipt')
    return value


def _unescape(value):
    # mountinfo uses precisely these four octal escapes, never shell quoting.
    escapes = {'040': ' ', '011': chr(9), '012': chr(10), '134': chr(92)}
    return re.sub(r'\\([0-7]{3})', lambda match: escapes[match[1]], value)


def filesystem_identity(store, handle, info):
    if not store.enforce_owner:  # Portable fixtures; production always enforces ownership.
        return 'fixture-dev:' + str(info.st_dev)
    try:
        directory = os.readlink('/proc/self/fd/' + str(handle))
        if not directory.startswith('/') or directory.endswith(' (deleted)'):
            raise ValueError('Unstable directory descriptor')
        matches = []
        with open('/proc/self/mountinfo', encoding='utf-8') as stream:
            for line in stream:
                left, right = line.rstrip(chr(10)).split(' - ', 1)
                fields, filesystem = left.split(), right.split()
                mount = _unescape(fields[4])
                if directory == mount or directory.startswith(mount.rstrip('/') + '/'):
                    matches.append((len(mount), fields, filesystem))
        _, fields, filesystem = max(matches, key=lambda item: item[0])
        kind, source = filesystem[:2]
        if kind not in ('btrfs', 'ext4') or not source.startswith('/dev/'):
            raise ValueError('Unsupported runtime filesystem')
        major, minor = map(int, fields[2].split(':'))
        if (os.major(info.st_dev), os.minor(info.st_dev)) != (major, minor):
            raise ValueError('Mount identity changed')
        device = Path(_unescape(source)).resolve(strict=True)
        if not str(device).startswith('/dev/'):
            raise ValueError('Runtime mount source escaped /dev')
        device_info = device.stat()
        if not stat.S_ISBLK(device_info.st_mode):
            raise ValueError('Runtime mount source is not a block device')
        if kind == 'ext4' and device_info.st_rdev != info.st_dev:
            raise ValueError('Runtime mount block device differs')
        cache = store._runtime_filesystem_cache
        key = (str(device), device_info.st_rdev, device_info.st_ino, kind)
        if key not in cache:
            result = subprocess.run(['/usr/bin/blkid', '-p', '-o', 'export', '--', str(device)],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True,
                                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            values = dict(line.split('=', 1) for line in result.stdout.decode('ascii').splitlines() if '=' in line)
            filesystem_uuid = values.get('UUID', '')
            if values.get('TYPE') != kind or str(uuid.UUID(filesystem_uuid)) != filesystem_uuid.lower():
                raise ValueError('Unverified runtime filesystem UUID')
            cache[key] = filesystem_uuid.lower()
        # UUID survives reboot; the mount root distinguishes subvolumes and bind
        # mounts. st_dev is checked above against the live mount, never persisted.
        return kind + ':' + cache[key] + ':' + _unescape(fields[3])
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        raise store._directory_error('Cannot establish stable runtime mount identity') from exc


def identity(store, info, handle):
    return dict(filesystem=filesystem_identity(store, handle, info), ino=info.st_ino,
                mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)


def inspect(store, path):
    # _parent authenticates every hop using O_NOFOLLOW directory descriptors.
    with store._parent(path + '/.directory-probe', user=False) as (parent, _):
        if parent is None:
            return None
        info = os.fstat(parent) if os.name == 'posix' else parent.lstat()
        return identity(store, info, parent)


def root_identity(store):
    # Only the internal nearest-existing-ancestor search reaches Store.root.
    # Do not send './...' through or relax the public target path validator.
    if os.name == 'posix':
        descriptor = os.open(store.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            store._check_dir(info, '.', False)
            return identity(store, info, descriptor)
        finally:
            os.close(descriptor)
    info = store.root.lstat()  # Portable fixtures; production requires POSIX.
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise store._directory_error('Linked transaction root')
    store._check_dir(info, '.', False)
    return identity(store, info, store.root)


def _consumes(generation, directory):
    return generation and any(path.startswith(directory + '/') for path in generation.get('paths', {}))


def plan(store, index, slot, previous, target, operations):
    generations = [record.get('current') for other, record in index['slots'].items() if other != slot]
    generations = [generation for generation in generations if generation is not None]
    current_receipts, receipts = {}, {}
    for generation in [previous] + generations + [target]:
        for path, receipt in validate(store, (generation or {}).get('runtime_directories', {})).items():
            if path in receipts and receipts[path] != receipt:
                # Historical generations can refer to an inode already removed
                # and recreated. Only a current owner's receipt is authoritative.
                if generation is target:
                    continue
                raise store._directory_error('Conflicting runtime directory receipts: ' + path)
            receipts[path] = copy.deepcopy(receipt)
            if generation is not target:
                current_receipts[path] = copy.deepcopy(receipt)
    consumers = [target] + generations
    ledger = {id(generation): {} for generation in consumers}
    cleanup = {}
    for path, receipt in receipts.items():
        owners = [generation for generation in consumers if _consumes(generation, path)]
        if owners:
            actual = inspect(store, path)
            if actual is not None:
                if actual != receipt:
                    raise store._directory_error('Runtime directory identity changed: ' + path)
                for generation in owners:
                    ledger[id(generation)][path] = copy.deepcopy(receipt)
        elif path in current_receipts:
            cleanup[path] = copy.deepcopy(receipt)
    intents, filesystems = {}, {}
    for operation in operations:
        if not operation['after']['exists']:
            continue
        for parent in reversed(PurePosixPath(operation['path']).parents):
            path = parent.as_posix()
            if supported(path) and inspect(store, path) is None:
                intents[path] = None
                ancestor = parent.parent.as_posix()
                while True:
                    if ancestor == '.':
                        actual = root_identity(store)
                    else:
                        actual = inspect(store, ancestor)
                    if actual is not None:
                        break
                    ancestor = PurePosixPath(ancestor).parent.as_posix()
                filesystems[path] = actual['filesystem']
                ledger[id(target)].pop(path, None)
    for generation in consumers:
        if ledger[id(generation)]:
            generation['runtime_directories'] = ledger[id(generation)]
        else:
            generation.pop('runtime_directories', None)
    result = {'runtime_directory_intents': intents, 'runtime_directory_cleanup': cleanup,
              'runtime_directory_filesystems': filesystems}
    if intents:
        result['runtime_directory_journal'] = uuid.uuid4().hex
    return result


def _journal_name(store, pending):
    token = pending.get('runtime_directory_journal')
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
        raise store._directory_error('Invalid runtime directory journal identity')
    return 'runtime-directories-' + token + '.json'


def _binding(pending):
    return dict(transaction=pending['runtime_directory_journal'], slot=pending['slot'],
                generation=pending['index_after']['slots'][pending['slot']]['current']['id'])


def hydrate(store, pending):
    intents = validate(store, pending.get('runtime_directory_intents', {}), intents=True)
    if not intents:
        if 'runtime_directory_journal' in pending:
            raise store._directory_error('Unexpected runtime directory journal')
        return
    filesystems = pending.get('runtime_directory_filesystems')
    if (not isinstance(filesystems, dict) or set(filesystems) != set(intents)
            or any(not isinstance(value, str) or not 1 <= len(value) <= 4096 for value in filesystems.values())):
        raise store._directory_error('Invalid runtime directory planned filesystems')
    journal = store._state_read(_journal_name(store, pending))
    if journal is None:
        return
    if (not isinstance(journal, dict) or set(journal) != {'transaction', 'slot', 'generation', 'receipts'}
            or any(journal.get(key) != value for key, value in _binding(pending).items())):
        raise store._directory_error('Runtime directory journal belongs to another transaction')
    receipts = validate(store, journal['receipts'])
    generation = pending['index_after']['slots'][pending['slot']]['current']
    for path, receipt in receipts.items():
        if path not in intents or receipt['filesystem'] != filesystems[path]:
            raise store._directory_error('Unplanned runtime directory receipt')
        if intents[path] is not None and intents[path] != receipt:
            raise store._directory_error('Runtime directory receipt changed')
        intents[path] = copy.deepcopy(receipt)
        generation.setdefault('runtime_directories', {})[path] = copy.deepcopy(receipt)


def preflight(store, pending, operations):
    intents = validate(store, pending.get('runtime_directory_intents', {}), intents=True)
    cleanup = validate(store, pending.get('runtime_directory_cleanup', {}))
    for path, receipt in intents.items():
        actual = inspect(store, path)
        if (receipt is None and actual is not None) or (receipt is not None and actual != receipt):
            raise store._directory_error('Uncertain runtime directory creation; preserve for recovery: ' + path)
    # Retained ancestors also need verification before any target file changes.
    for record in pending['index_after']['slots'].values():
        for path, receipt in validate(store, (record.get('current') or {}).get('runtime_directories', {})).items():
            if inspect(store, path) != receipt:
                raise store._directory_error('Runtime directory identity changed: ' + path)
    removed_files = {op['path'] for op in operations if not op['after']['exists']}
    for path, receipt in cleanup.items():
        actual = inspect(store, path)
        if actual is None:
            continue  # Crash after rmdir, before index commit.
        if actual != receipt:
            raise store._directory_error('Runtime directory identity changed: ' + path)
        with store._parent(path + '/.directory-probe') as (parent, _):
            for name in os.listdir(parent):
                child = path + '/' + name
                info = (os.stat(name, dir_fd=parent, follow_symlinks=False)
                        if os.name == 'posix' else (parent / name).lstat())
                if stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400:
                    if child not in cleanup:
                        raise store._directory_error('Unknown directory in runtime cleanup: ' + child)
                elif not stat.S_ISREG(info.st_mode) or child not in removed_files:
                    raise store._directory_error('Unknown file or link in runtime cleanup: ' + child)


def existing(store, path, info, handle):
    pending = store._runtime_directory_pending
    if pending is None or not supported(path):
        return
    intents = pending.get('runtime_directory_intents', {})
    if path in intents and intents[path] is None:
        # A different actor may create a planned ancestor after preflight. Only
        # our mkdir followed by its durable receipt grants ownership.
        raise store._directory_error('Uncertain runtime directory creation; preserve for recovery: ' + path)
    receipt = pending.get('runtime_directory_cleanup', {}).get(path)
    receipt = intents.get(path) or receipt
    for record in pending['index_after']['slots'].values():
        candidate = (record.get('current') or {}).get('runtime_directories', {}).get(path)
        if candidate is not None:
            receipt = candidate
    if receipt is not None and identity(store, info, handle) != receipt:
        raise store._directory_error('Runtime directory identity changed before target access: ' + path)


def before_create(store, path, parent):
    if not supported(path):
        return
    pending = store._runtime_directory_pending
    if pending is None or path not in pending.get('runtime_directory_intents', {}):
        raise store._directory_error('Unjournaled runtime directory creation: ' + path)
    if pending['runtime_directory_intents'][path] is not None:
        raise store._directory_error('Previously created runtime directory disappeared: ' + path)
    info = os.fstat(parent) if os.name == 'posix' else parent.lstat()
    if filesystem_identity(store, parent, info) != pending['runtime_directory_filesystems'][path]:
        raise store._directory_error('Runtime mount changed before directory creation: ' + path)


def created(store, path, info, handle):
    if not supported(path):
        return
    store._after_runtime_directory_create(path)
    receipt = identity(store, info, handle)
    validate(store, {path: receipt})
    pending = store._runtime_directory_pending
    if receipt['filesystem'] != pending['runtime_directory_filesystems'][path]:
        raise store._directory_error('Runtime mount changed during directory creation: ' + path)
    pending['runtime_directory_intents'][path] = receipt
    generation = pending['index_after']['slots'][pending['slot']]['current']
    generation.setdefault('runtime_directories', {})[path] = receipt
    journal = _binding(pending)
    journal['receipts'] = {path: receipt for path, receipt in pending['runtime_directory_intents'].items()
                           if receipt is not None}
    # The pending/index can exceed a GiB. Persist only this bounded small journal
    # per mkdir; pending remains a single immutable durable transaction record.
    store._state_write(_journal_name(store, pending), journal)
    store._after_runtime_directory_receipt(path)


def cleanup(store, pending):
    receipts = validate(store, pending.get('runtime_directory_cleanup', {}))
    for path in sorted(receipts, key=lambda value: (value.count('/'), value), reverse=True):
        receipt = receipts[path]
        actual = inspect(store, path)
        if actual is None:
            continue
        if actual != receipt:
            raise store._directory_error('Runtime directory identity changed before cleanup: ' + path)
        with store._parent(path) as (parent, name):
            if os.name == 'posix':
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                # inspect checked the live stable filesystem identity; _parent
                # rechecks every recorded ancestor before descriptor-relative rmdir.
                if (not stat.S_ISDIR(info.st_mode) or any(receipt[field] != value for field, value in
                        dict(ino=info.st_ino, mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid).items())):
                    raise store._directory_error('Runtime directory changed before rmdir: ' + path)
                os.rmdir(name, dir_fd=parent)  # Nonempty directories fail closed.
                os.fsync(parent)
            else:
                (parent / name).rmdir()
        store._after_runtime_directory_remove(path)


def finish(store, pending):
    # Only call after index fsync AND pending unlink/fsync. An orphan after a
    # crash is harmless; its random name and binding prevent cross-tx reuse.
    if 'runtime_directory_journal' in pending:
        try:
            (store.state / _journal_name(store, pending)).unlink()
        except FileNotFoundError:
            pass
        store._sync_state()
