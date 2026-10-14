"""Independent HDR configuration lifecycle; no display/service/kernel changes.

Live apply is narrowly versioned. File-only validation on an offline test volume
uses ConfigurationFiles directly and does not claim live hardware acceptance.
Journals use one logical target, so recovery can mount the root elsewhere.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import stat
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_transaction import FileTransaction, atomic_write, directory_fd, serialized, snapshot
from generate import generate
from shared_state import directory as shared_directory

RELATIVE = 'home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua'
VERSION = '20261013-hdr-r1'
TARGET = {'ID': 'steamos', 'VERSION_ID': '3.10', 'BUILD_ID': '20260924.1000',
          'kernel': '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9',
          'gamescope': '3.16.30-1', 'vendor': 'ONE-NETBOOK', 'product': 'ONEXPLAYER 3'}


def ordinary_text(path):
    value = snapshot(path)
    if not value['exists']: raise RuntimeError('Required environment metadata missing: ' + str(path))
    return base64.b64decode(value['data']).decode('utf-8')


def live_environment():
    if os.geteuid() != 0: raise RuntimeError('HDR configuration operation requires root')
    release = {}
    for line in ordinary_text('/etc/os-release').splitlines():
        if '=' in line:
            key, value = line.split('=', 1); release[key] = value.strip('"')
    for key in ('ID', 'VERSION_ID', 'BUILD_ID'):
        if release.get(key) != TARGET[key]: raise RuntimeError('HDR system compatibility refused: ' + key)
    if os.uname().release != TARGET['kernel']: raise RuntimeError('HDR kernel compatibility refused')
    # Sysfs attributes are not ordinary on-disk files; only these fixed identity attributes are read.
    for key, name in (('vendor', 'sys_vendor'), ('product', 'product_name')):
        if Path('/sys/class/dmi/id/' + name).read_text().strip() != TARGET[key]: raise RuntimeError('HDR exact-model compatibility refused')
    database=Path('/usr/lib/holo/pacmandb/local')
    if not database.is_dir(): database=Path('/var/lib/pacman/local')
    descriptions = list(database.glob('gamescope-*/desc'))
    versions = []
    for description in descriptions:
        fields = ordinary_text(description).splitlines()
        def field(name):
            matches = [i for i, item in enumerate(fields) if item == '%' + name + '%']
            if len(matches) != 1 or matches[0] + 1 >= len(fields): raise RuntimeError('Ambiguous Gamescope package metadata')
            return fields[matches[0] + 1]
        if field('NAME') == 'gamescope': versions.append(field('VERSION'))
    if versions != [TARGET['gamescope']]: raise RuntimeError('HDR Gamescope package compatibility refused')
    drivers = [path.resolve().name for path in Path('/sys/class/drm').glob('card[0-9]*/device/driver')]
    if 'xe' not in drivers: raise RuntimeError('HDR Intel xe environment required')
    users = [line.split(':') for line in ordinary_text('/etc/passwd').splitlines() if line.startswith('deck:')]
    if len(users) != 1 or len(users[0]) != 7 or users[0][5] != '/home/deck': raise RuntimeError('Expected one deck user/home')
    owner = tuple(int(users[0][i]) for i in (2, 3))
    if any(value <= 0 for value in owner): raise RuntimeError('Non-root deck account required')
    return owner


def ensure_directory(path, mode, owner=None):
    path = Path(path)
    if path.exists() or path.is_symlink():
        fd = directory_fd(path); os.close(fd)
        return
    ensure_directory(path.parent, 0o755)
    fd = directory_fd(path.parent)
    try:
        os.mkdir(path.name, mode, dir_fd=fd)
        child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            # Like atomic_write, honor the requested mode independently of the
            # caller's umask. Do not relax permissions of existing directories.
            if owner is not None: os.fchown(child, *owner)
            os.fchmod(child, mode)
            os.fsync(child)
        finally: os.close(child)
        os.fsync(fd)
    finally: os.close(fd)


def ensure_user_directory(path, mode, owner, home):
    """Repair only explicit user-directory ancestors, never a recursive home tree."""
    path, home = Path(path).absolute(), Path(home).absolute()
    if '..' in path.parts or not path.is_relative_to(home) or len(owner) != 2 or any(type(n) is not int or n <= 0 for n in owner):
        raise RuntimeError('Expected a directory inside the non-root user home')
    ensure_directory(home, 0o755, owner)
    paths = [home]
    for part in path.relative_to(home).parts:
        paths.append(paths[-1] / part)
    for directory in paths:
        ensure_directory(directory, mode if directory == path else 0o755, owner)
        fd = directory_fd(directory)
        try:
            info = os.fstat(fd)
            if info.st_uid not in (0, owner[0]):
                raise RuntimeError('User directory belongs to another account: ' + str(directory))
            if (info.st_uid, info.st_gid) != tuple(owner):
                os.fchown(fd, *owner)
                os.fsync(fd)
            if info.st_mode & 0o700 != 0o700:
                raise RuntimeError('User directory is not owner-writable/searchable: ' + str(directory))
        finally:
            os.close(fd)


class LogicalHdrTransaction(FileTransaction):
    def __init__(self, directory, root, owner):
        self.target = Path(root) / RELATIVE
        self.owner = tuple(owner)
        super().__init__(directory, [self.target])
    def installed_metadata(self, path, original):
        if original['exists']: return super().installed_metadata(path, original)
        return {'mode': 0o644, 'uid': self.owner[0], 'gid': self.owner[1]}
    def save(self, value):
        stored = dict(value, allowed=[RELATIVE], component=VERSION, owner=list(self.owner))
        for name in ('original', 'applied', 'accepted'):
            stored[name] = {RELATIVE: value[name][str(self.target)]} if str(self.target) in value.get(name, {}) else {}
        atomic_write(self.state, (json.dumps(stored, indent=2) + '\n').encode(), 0o600)
    def load(self):
        saved = snapshot(self.state, maximum=8 * 1024 * 1024)
        if not saved['exists'] or saved['uid'] != os.geteuid() or saved['mode'] & 0o077: raise RuntimeError('Private HDR journal required')
        value = json.loads(base64.b64decode(saved['data']))
        if value.get('allowed') != [RELATIVE] or value.get('component') != VERSION or value.get('owner') != list(self.owner): raise RuntimeError('HDR logical target/owner/version changed')
        value['allowed'] = list(self.allowed)
        for name in ('original', 'applied', 'accepted'):
            if set(value.get(name, {})) - {RELATIVE}: raise RuntimeError('Unexpected HDR journal target')
            value[name] = {str(self.target): value[name][RELATIVE]} if RELATIVE in value.get(name, {}) else {}
        return value


class ConfigurationFiles:
    """File-only operation for an explicitly selected root; does not validate hardware."""
    def __init__(self, root):
        self.root = Path(os.path.abspath(root))
        fd = directory_fd(self.root); os.close(fd)
        self.target = self.root / RELATIVE
        legacy = self.root / 'var/lib/oxp3-installer/transactions/hdr'
        if legacy.exists() or legacy.is_symlink(): raise RuntimeError('Legacy per-slot HDR journal requires explicit offline migration; preserve it')
        self.directory = shared_directory(self.root, 'transactions/hdr', create=True)
        info = self.directory.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077: raise RuntimeError('Private root-owned HDR state required')
        self.pointer = self.directory / 'current.json'
    def epoch(self, create=False, owner=None):
        value = None
        if self.pointer.exists():
            saved = snapshot(self.pointer)
            if saved['uid'] != os.geteuid() or saved['mode'] & 0o077: raise RuntimeError('Untrusted HDR epoch')
            value = json.loads(base64.b64decode(saved['data']))
            if value.get('version') != VERSION or uuid.UUID(value['epoch']).hex != value['epoch'] or len(value.get('owner', [])) != 2: raise RuntimeError('Invalid HDR epoch')
        if create and (value is None or value['phase'] == 'rolled_back'):
            if owner is None or any(not isinstance(n, int) or n <= 0 for n in owner): raise RuntimeError('Explicit user ownership required')
            value = {'version': VERSION, 'epoch': uuid.uuid4().hex, 'phase': 'prepared', 'owner': list(owner), 'activation': 'session_restart_required'}
            self.publish(value)
        if value is None: raise RuntimeError('No HDR configuration operation to restore')
        journal = self.directory / value['epoch']; ensure_directory(journal, 0o700)
        return value, LogicalHdrTransaction(journal, self.root, value['owner'])
    def publish(self, value): atomic_write(self.pointer, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
    @serialized
    def apply(self, owner):
        value, transaction = self.epoch(True, owner)
        if value['owner'] != list(owner): raise RuntimeError('Selected user changed since HDR installation')
        # Create only the fixed user's configuration directories; existing file metadata is preserved.
        for relative in ('home/deck', 'home/deck/.config', 'home/deck/.config/gamescope', 'home/deck/.config/gamescope/scripts'):
            ensure_user_directory(self.root / relative, 0o755, owner, self.root / 'home/deck')
        try:
            transaction.apply({str(self.target): generate().encode()})
            value['phase'] = 'files_installed'; value.pop('error', None); self.publish(value)
        except Exception as error:
            value['phase'] = 'failed'; value['error'] = str(error); self.publish(value); raise
        return value
    @serialized
    def restore(self):
        value, transaction = self.epoch()
        if value['phase'] == 'rolled_back': return value
        errors = transaction.rollback() if transaction.state.exists() else []
        value['phase'] = 'restore_conflict' if errors else 'rolled_back'
        value['errors'] = errors; value['activation'] = 'session_restart_required'; self.publish(value)
        return value


def apply_live():
    owner = live_environment() # All live gates run before creating transaction state or target directories.
    return ConfigurationFiles('/').apply(owner)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('apply', 'restore'))
    parser.add_argument('--root', default='/')
    args = parser.parse_args()
    if args.action == 'apply':
        if args.root != '/': raise SystemExit('Live apply accepts only /. Offline file lifecycle is a separate validation path.')
        result = apply_live()
    else:
        if os.geteuid() != 0: raise SystemExit('Root required for restoring component ownership')
        result = ConfigurationFiles(args.root).restore()
    print(json.dumps(result, indent=2))
    if result.get('phase') == 'restore_conflict': raise SystemExit(1)
