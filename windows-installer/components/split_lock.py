# SPDX-License-Identifier: MIT
# Split-lock workaround derived from kas5852's upstream PR #16 and the
# 20261015 fix pack, Copyright (c) 2026 HANA & Claude. See split-lock/UPSTREAM_LICENSE.
# OXP3 installer adaptation and conservative JSON-only cleanup: FlightDan, 2026.
"""Generate reversible boot settings; remove only explicit split_lock JSON reports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

DROPIN = 'etc/default/grub.d/oxp3-splitlock.cfg'
GRUB = 'efi/EFI/steamos/grub.cfg'
TRACE = '/var/lib/steamos-log-submitter/pending/trace'
MAX_REPORT = 1024 * 1024
DROPIN_DATA = b'''# Steam split-lock report flood workaround; upstream kas5852, PR #16.
# Copyright (c) 2026 HANA & Claude; MIT (see accompanying UPSTREAM_LICENSE).
# Revert this setting through the component transaction, then reboot.
GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} split_lock_detect=off"
'''


def patch_grub(text):
    lines = text.splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        if re.match(r'^\s*(?:steamenv_boot|linux|linuxefi)\s', line) and '/boot/vmlinuz-' in line:
            tokens = line.split()
            if any(token.startswith('#') for token in tokens) or '\\' in line or ';' in line:
                raise ValueError('Inline boot comments/continuations require manual review')
            flags = [token for token in tokens if token.startswith('split_lock_detect=')]
            if any(flag != 'split_lock_detect=off' for flag in flags) or len(flags) > 1:
                raise ValueError('Conflicting split-lock boot setting; preserve it for review')
            if not flags:
                # Preserve existing line ending and every other kernel option.
                ending = '\r\n' if line.endswith('\r\n') else '\n'
                lines[index] = line.rstrip('\r\n') + ' split_lock_detect=off' + ending
            count += 1
    if not count:
        raise ValueError('No supported Valve kernel boot entries in mounted slot EFI')
    return ''.join(lines)


def files(root):
    root = Path(root)
    # The installer/maintenance caller provides ownership, path and version checks.
    path = root / GRUB
    for candidate in (root, *list(path.parents)[:len(path.parts) - len(root.parts)], path):
        if candidate.is_symlink():
            raise ValueError('Symlinked split-lock boot path refused')
    if not path.is_file():
        raise ValueError('Split-lock repair requires mounted slot EFI grub.cfg')
    existing = root / DROPIN
    if existing.is_symlink():
        raise ValueError('Symlinked split-lock drop-in refused')
    if existing.exists() and existing.read_bytes() != DROPIN_DATA:
        raise ValueError('Existing split-lock drop-in differs; preserve it for review')
    source = Path(__file__).with_name('split-lock') / 'UPSTREAM_LICENSE'
    return {DROPIN: {'data': DROPIN_DATA}, GRUB: {'data': patch_grub(path.read_bytes().decode()).encode()},
            'usr/share/licenses/oxp3-split-lock/UPSTREAM_LICENSE': {'data': source.read_bytes()}}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate report key')
        result[key] = value
    return result


def _non_json_constant(value):
    raise ValueError('Non-JSON numeric constant: ' + value)


def is_split_report(data):
    try:
        value = json.loads(data, object_pairs_hook=_unique, parse_constant=_non_json_constant)
        return isinstance(value, dict) and value.get('type') == 'split_lock'
    except (ValueError, UnicodeError, RecursionError):
        return False


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _report_owners():
    owners = {0}
    if os.name == 'posix':
        import pwd
        try:
            service = pwd.getpwnam('steamos-log-submitter')
        except KeyError:
            return owners
        # SteamOS 3.10 uses a static, non-login system service account, not deck.
        if (0 < service.pw_uid < 1000 and service.pw_dir == '/var/lib/steamos-log-submitter'
                and service.pw_shell in ('/usr/bin/nologin', '/sbin/nologin')):
            owners.add(service.pw_uid)
    return owners


def reports(trace=TRACE, *, delete=False):
    """Never follow links or infer type from names/substrings; retain unknown files.

    Production calls use the fixed TRACE path. The caller should stop the report
    submitter during cleanup so a preservation digest can be compared afterwards.
    """
    trace = Path(trace).absolute()
    result = {'files': 0, 'split_lock_files': 0, 'removed': 0,
              'removed_allocated_bytes': 0, 'kept': 0, 'skipped': 0}
    preserved = hashlib.sha256()
    owners = _report_owners()
    # Open ancestors without following links, so a renamed ancestor cannot redirect deletion.
    fd = os.open(trace.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in trace.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        def walk(directory_fd, prefix):
            info = os.fstat(directory_fd)
            if os.name == 'posix' and (info.st_uid not in owners or info.st_mode & 0o022) and delete:
                raise ValueError('Cleanup requires root/service-owned, non-writable report directories')
            with os.scandir(directory_fd) as iterator:
                names = sorted(entry.name for entry in iterator)
            for name in names:
                relative = prefix + name
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(before.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        walk(child, relative + '/')
                    finally:
                        os.close(child)
                    continue
                result['files'] += 1
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_REPORT:
                    result['skipped'] += 1
                    preserved.update(json.dumps([relative, 'special', _identity(before)], separators=(',', ':')).encode())
                    continue
                if delete and (before.st_uid not in owners or before.st_mode & 0o022):
                    raise ValueError('Cleanup requires root/service-owned, non-writable report files')
                report_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                try:
                    opened = os.fstat(report_fd)
                    if _identity(before) != _identity(opened):
                        raise RuntimeError('Report changed while opening; cleanup stopped')
                    with os.fdopen(os.dup(report_fd), 'rb') as stream:
                        data = stream.read(MAX_REPORT + 1)
                    if _identity(opened) != _identity(os.fstat(report_fd)) or len(data) != opened.st_size:
                        raise RuntimeError('Report changed while reading; cleanup stopped')
                    split = is_split_report(data)
                    if split:
                        result['split_lock_files'] += 1
                    else:
                        result['kept'] += 1
                        preserved.update(json.dumps([relative, hashlib.sha256(data).hexdigest(), _identity(opened)], separators=(',', ':')).encode())
                    if split and delete:
                        if _identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != _identity(opened):
                            raise RuntimeError('Report changed before removal; cleanup stopped')
                        os.unlink(name, dir_fd=directory_fd)
                        result['removed'] += 1
                        result['removed_allocated_bytes'] += getattr(opened, 'st_blocks', 0) * 512
                finally:
                    os.close(report_fd)
        walk(fd, '')
    finally:
        os.close(fd)
    result['preserved_digest'] = preserved.hexdigest()
    return result


def live_guard():
    if os.geteuid() != 0:
        raise RuntimeError('Root required')
    for name, expected in (('sys_vendor', 'ONE-NETBOOK'), ('product_name', 'ONEXPLAYER 3')):
        if Path('/sys/class/dmi/id', name).read_text().strip() != expected:
            raise RuntimeError('ONEXPLAYER 3 required')
    if 'split_lock_detect=off' not in Path('/proc/cmdline').read_text().split():
        raise RuntimeError('Boot with split_lock_detect=off before cleanup')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('scan', 'cleanup'))
    args = parser.parse_args()
    if args.action == 'cleanup':
        live_guard()
    print(json.dumps(reports(delete=args.action == 'cleanup'), sort_keys=True))
