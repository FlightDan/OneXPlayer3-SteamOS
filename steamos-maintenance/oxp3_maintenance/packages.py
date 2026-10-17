"""Durable, narrowly scoped Waydroid host-package installation and recovery.

The caller owns the maintenance operation lock and root-protection state. This
module never initializes Android, removes Android data, upgrades existing host
packages, imports bundle code, or invokes bundle shell scripts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid


NAMES = frozenset(('libgbinder', 'libglibutil', 'python-gbinder',
                   'steamos-waydroid-binder', 'waydroid'))
PHASES = frozenset(('prepared', 'installing', 'installed', 'rolling_back',
                    'rollback_failed', 'rollback_conflict', 'restored'))


class PackageError(RuntimeError):
    pass


def _command(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=300,
                            env={**os.environ, 'LC_ALL': 'C', 'PATH': '/usr/bin:/usr/sbin'})
    if check and result.returncode:
        raise PackageError('Command failed: ' + args[0] + ': ' + result.stderr.strip()[:1000])
    return result.stdout.strip()


class PackageStore:
    """One slot's private package journal; callers must serialize all methods.

    ``command(*args, check=True) -> str`` may be injected for orchestration and
    fixture tests. ``enforce_owner=False`` is exclusively for nonprivileged
    fixtures. Production requires root-owned files and a 0700 state directory.
    """
    def __init__(self, state: Path, slot: str, command=None, *, enforce_owner=True):
        if not isinstance(slot, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', slot) or slot in ('.', '..'):
            raise PackageError('Unknown SteamOS package slot')
        self.state = Path(os.path.abspath(state))
        self.slot = slot
        self.command = command or _command
        self.enforce_owner = enforce_owner
        self.path = self.state / ('packages-' + slot + '.json')
        if enforce_owner and os.name != 'posix':
            raise PackageError('Package ownership enforcement requires Linux/POSIX')

    @staticmethod
    def _link(info):
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)

    def _state_directory(self):
        for path in reversed((self.state, *self.state.parents)):
            try:
                info = path.lstat()
            except FileNotFoundError:
                path.mkdir(mode=0o700)
                info = path.lstat()
            if self._link(info) or not stat.S_ISDIR(info.st_mode):
                raise PackageError('Unsafe package journal ancestor: ' + str(path))
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o022):
                raise PackageError('Untrusted package journal ancestor: ' + str(path))
        if self.enforce_owner and stat.S_IMODE(self.state.stat().st_mode) != 0o700:
            raise PackageError('Package journal directory must have mode 0700')

    def _read(self):
        self._state_directory()
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return None
        if self._link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PackageError('Unsafe package journal file')
        if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o077):
            raise PackageError('Package journal must be private and root-owned')
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or opened.st_size > 256 * 1024:
                raise PackageError('Package journal changed or is oversized')
            try:
                value = json.load(stream)
            except (ValueError, UnicodeError) as error:
                raise PackageError('Corrupt package journal') from error
        self._validate(value)
        return value

    def _save(self, value):
        self._validate(value)
        self._state_directory()
        if os.path.lexists(self.path):
            info = self.path.lstat()
            if self._link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PackageError('Unsafe package journal destination')
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o077):
                raise PackageError('Untrusted package journal destination')
        temporary = self.state / ('.packages-' + uuid.uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write((json.dumps(value, sort_keys=True) + '\n').encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name == 'posix':
                descriptor = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _validate(self, value):
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('slot') != self.slot or value.get('phase') not in PHASES:
            raise PackageError('Invalid package journal schema or slot')
        entries = value.get('packages')
        if not isinstance(entries, list) or len(entries) != 5 or {x.get('name') for x in entries if isinstance(x, dict)} != NAMES:
            raise PackageError('Package journal must contain the exact five Waydroid host packages')
        for entry in entries:
            if (not isinstance(entry.get('version'), str) or not re.fullmatch(r'[^\s\x00]+', entry['version'])
                    or type(entry.get('original_installed')) is not bool
                    or not isinstance(entry.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])
                    or not isinstance(entry.get('path'), str) or not Path(entry['path']).is_absolute()):
                raise PackageError('Invalid package journal entry')

    def _package_file(self, path):
        path = Path(os.path.abspath(path))
        for ancestor in reversed(path.parents):
            info = ancestor.lstat()
            if self._link(info) or not stat.S_ISDIR(info.st_mode):
                raise PackageError('Unsafe package source ancestor: ' + str(ancestor))
            # Root's sticky /tmp is permitted for the authenticated private
            # staging directory created by the caller.
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise PackageError('Untrusted package source ancestor: ' + str(ancestor))
        info = path.lstat()
        if self._link(info) or not stat.S_ISREG(info.st_mode) or info.st_size > 256 * 1024 * 1024:
            raise PackageError('Expected a regular staged package file: ' + str(path))
        if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o022):
            raise PackageError('Staged package must be protected and root-owned')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        digest = hashlib.sha256()
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
                raise PackageError('Staged package changed before reading')
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return path, digest.hexdigest()

    @staticmethod
    def _parse(output):
        if not isinstance(output, str):
            raise PackageError('Unexpected package command output')
        entries = {}
        for line in output.splitlines():
            words = line.split()
            if len(words) != 2 or words[0] in entries:
                raise PackageError('Malformed or duplicate package database entry')
            entries[words[0]] = words[1]
        return entries

    def _installed(self):
        # A successful full query distinguishes absence from a broken database;
        # an empty result from `pacman -Q NAME` with check=False cannot do that.
        return self._parse(self.command('pacman', '-Q'))

    def _verify_installed(self, value):
        installed = self._installed()
        conflicts = [entry['name'] for entry in value['packages'] if installed.get(entry['name']) != entry['version']]
        if conflicts:
            raise PackageError('Managed host package is missing or changed: ' + ', '.join(conflicts))
        return value

    def _preflight_transaction(self, entries):
        """Resolve the actual archive transaction without changing the host.

        ``pacman -U`` can add or upgrade repository dependencies implicitly.
        They are outside this journal's ownership and must never be installed.
        Print mode resolves dependencies, but does not prove signature validity:
        the authenticated project bundle and pacman's normal signature policy
        remain separate checks. In particular, Optional local signatures do not
        require us to initialize or change the system keyring.
        """
        if not entries:
            return
        output = self.command('pacman', '-U', '--print', '--print-format',
                              '%n\t%v\t%l', '--noconfirm',
                              *(entry['path'] for entry in entries))
        if not isinstance(output, str):
            raise PackageError('Unexpected package transaction output')
        expected = {entry['name']: (entry['version'], entry['path']) for entry in entries}
        resolved = {}
        for line in output.splitlines():
            words = line.split('\t')
            if len(words) != 3 or any(not word or '\x00' in word for word in words) or words[0] in resolved:
                raise PackageError('Malformed or duplicate package transaction entry')
            name, version, location = words
            resolved[name] = (version, location)
        if resolved != expected:
            unexpected = sorted(name for name, identity in resolved.items()
                                if expected.get(name) != identity)
            missing = sorted(set(expected) - set(resolved))
            details = []
            if unexpected:
                details.append('unexpected packages or archive sources: ' + ', '.join(unexpected))
            if missing:
                details.append('missing packages: ' + ', '.join(missing))
            raise PackageError('Host package transaction exceeds the exact staged package set; '
                               + '; '.join(details))

    def prepare(self, package_paths: list[Path]) -> dict:
        if not isinstance(package_paths, list) or len(package_paths) != 5:
            raise PackageError('Exactly five staged Waydroid package files are required')
        entries, seen_paths = [], set()
        installed = self._installed()
        for supplied in package_paths:
            path, digest = self._package_file(supplied)
            if str(path) in seen_paths:
                raise PackageError('Duplicate staged package file')
            seen_paths.add(str(path))
            info = self._parse(self.command('pacman', '-Qp', str(path)))
            if len(info) != 1:
                raise PackageError('Staged package must identify exactly one package')
            name, version = next(iter(info.items()))
            if name not in NAMES:
                raise PackageError('Unexpected Waydroid host package: ' + name)
            if name in installed and installed[name] != version:
                raise PackageError('Existing host package differs; upgrades are refused: ' + name)
            entries.append({'name': name, 'version': version, 'path': str(path), 'sha256': digest,
                            'original_installed': name in installed})
        value = {'schema': 1, 'slot': self.slot, 'phase': 'prepared', 'packages': sorted(entries, key=lambda x: x['name'])}
        self._validate(value)
        self._preflight_transaction([entry for entry in value['packages'] if not entry['original_installed']])
        previous = self._read()
        if previous is not None and previous['phase'] != 'restored':
            before = [(x['name'], x['version'], x['sha256']) for x in previous['packages']]
            after = [(x['name'], x['version'], x['sha256']) for x in value['packages']]
            if before != after:
                raise PackageError('Package generation changed; restore the current package operation first')
            if previous['phase'] not in ('prepared', 'installed'):
                raise PackageError('Pending package operation requires recover() before preparing again')
            if previous['phase'] == 'installed':
                self._verify_installed(previous)
            # Refresh temporary source paths while retaining the first original
            # ownership record, including after a later repeat installation.
            for old, new in zip(previous['packages'], value['packages']):
                old['path'] = new['path']
            value = previous
        self._save(value)
        return value

    def install(self) -> dict:
        value = self._read()
        if value is None:
            raise PackageError('Prepare the staged host package operation first')
        if value['phase'] == 'installed':
            return self._verify_installed(value)
        if value['phase'] != 'prepared':
            raise PackageError('Package operation is pending or restored; recover and prepare first')
        current = self._installed()
        for entry in value['packages']:
            actual = current.get(entry['name'])
            expected = entry['version'] if entry['original_installed'] else None
            if actual != expected:
                raise PackageError('Host package changed after preparation: ' + entry['name'])
            path, digest = self._package_file(entry['path'])
            if digest != entry['sha256'] or self._parse(self.command('pacman', '-Qp', str(path))) != {entry['name']: entry['version']}:
                raise PackageError('Staged package changed after preparation: ' + entry['name'])
        pending = [entry for entry in value['packages'] if not entry['original_installed']]
        self._preflight_transaction(pending)
        value['phase'] = 'installing'
        self._save(value)  # Intent must be durable before pacman can mutate.
        try:
            paths = [entry['path'] for entry in pending]
            if paths:
                self.command('pacman', '-U', '--noconfirm', *paths)
            self._verify_installed(value)
            self.command('depmod', '-a')
            value['phase'] = 'installed'
            self._save(value)
            return value
        except Exception as error:
            value['install_error'] = str(error)[:4000]
            self._save(value)
            try:
                self._rollback(value)
            except Exception as rollback_error:
                raise PackageError('Host package installation failed: ' + str(error)
                                   + '; recovery requires attention: ' + str(rollback_error)) from error
            raise PackageError('Host package installation failed; added packages were rolled back: ' + str(error)) from error

    def _rollback(self, value):
        current = self._installed()
        conflicts, remove = [], []
        for entry in value['packages']:
            actual = current.get(entry['name'])
            if entry['original_installed']:
                if actual != entry['version']:
                    conflicts.append(entry['name'])
            elif actual is not None:
                if actual != entry['version']:
                    conflicts.append(entry['name'])
                else:
                    remove.append(entry['name'])
        if conflicts:
            value.update(phase='rollback_conflict', error='Host packages changed; preserving: ' + ', '.join(conflicts))
            self._save(value)
            raise PackageError(value['error'])
        # A killed pacman can unpack files before its database registration.
        # Database absence alone therefore does not prove a clean rollback.
        # Register the exact protected archives first, without --overwrite;
        # any filesystem conflict or unavailable archive remains actionable.
        uncertain_install = (value['phase'] in ('installing', 'rolling_back', 'rollback_failed', 'rollback_conflict')
                             and value.get('rollback_stage') != 'remove')
        if uncertain_install:
            missing = [entry for entry in value['packages'] if not entry['original_installed'] and entry['name'] not in current]
            if missing:
                value.update(phase='rolling_back', rollback_stage='complete-install')
                self._save(value)
                try:
                    paths = []
                    for entry in missing:
                        path, digest = self._package_file(entry['path'])
                        if digest != entry['sha256'] or self._parse(self.command('pacman', '-Qp', str(path))) != {entry['name']: entry['version']}:
                            raise PackageError('Recovery archive changed: ' + entry['name'])
                        paths.append(str(path))
                    self._preflight_transaction(missing)
                    try:
                        self.command('pacman', '-U', '--noconfirm', *paths)
                    except Exception as install_error:
                        value['recovery_install_error'] = str(install_error)[:4000]
                        self._save(value)
                        # Hooks may fail after registration. Complete verified
                        # registration is enough to remove this exact file set.
                        try:
                            self._verify_installed(value)
                        except Exception as verification_error:
                            value['recovery_verification_error'] = str(verification_error)[:4000]
                            self._save(value)
                            raise PackageError(str(install_error) + '; registration verification failed: '
                                               + str(verification_error)) from install_error
                    self._verify_installed(value)
                    remove = [entry['name'] for entry in value['packages'] if not entry['original_installed']]
                except Exception as error:
                    value.update(phase='rollback_failed', error='Unregistered package files may remain; exact archive completion failed: ' + str(error))
                    self._save(value)
                    raise PackageError(value['error']) from error
        value.update(phase='rolling_back')
        value['rollback_stage'] = 'remove'
        value.pop('error', None)
        self._save(value)
        try:
            if remove:
                # No recursive dependency removal and no deletion of Android
                # images/data: only our originally-absent exact packages.
                self.command('pacman', '-R', '--noconfirm', *remove)
            remaining = self._installed()
            for entry in value['packages']:
                expected = entry['version'] if entry['original_installed'] else None
                if remaining.get(entry['name']) != expected:
                    raise PackageError('Package rollback could not verify: ' + entry['name'])
            self.command('depmod', '-a')
            value.update(phase='restored')
            self._save(value)
            return value
        except Exception as error:
            value.update(phase='rollback_failed', error=str(error))
            self._save(value)
            raise PackageError('Package rollback is incomplete: ' + str(error)) from error

    def recover(self) -> dict:
        value = self._read()
        if value is None:
            return {'phase': 'absent', 'slot': self.slot}
        if value['phase'] == 'installed':
            return self._verify_installed(value)
        if value['phase'] in ('prepared', 'restored'):
            return value
        return self._rollback(value)

    def rollback(self) -> dict:
        value = self._read()
        if value is None:
            return {'phase': 'absent', 'slot': self.slot}
        if value['phase'] == 'restored':
            return value
        if value['phase'] == 'prepared':
            # No installation intent was recorded, so do not remove packages
            # independently installed since the read-only preparation step.
            value['phase'] = 'restored'
            self._save(value)
            return value
        return self._rollback(value)

    def restore(self) -> dict:
        return self.rollback()
