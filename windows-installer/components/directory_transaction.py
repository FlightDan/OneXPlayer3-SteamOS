"""Recoverable replacement of one root-owned component directory.

Preserves an existing directory by rename. Comparisons use file bytes and
metadata directly; no digest is calculated. Runtime services must be stopped
by the caller before apply or restore.
"""
import json
import os
from pathlib import Path
import shutil
import stat
from file_transaction import atomic_write, directory_fd, snapshot, serialized
import base64


def inventory(root):
    root = Path(root)
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        info = path.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise RuntimeError('Component code must be owned and writable only by the installer user')
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            raise RuntimeError('Component tree contains a link or special file')
        relative = str(path.relative_to(root))
        result[relative] = {'directory': stat.S_ISDIR(info.st_mode), 'mode': stat.S_IMODE(info.st_mode),
                            'uid': info.st_uid, 'gid': info.st_gid}
    return result


def same_tree(current, reference, metadata):
    if not Path(current).exists(): return False
    if inventory(current) != metadata: return False
    for relative, item in metadata.items():
        if item['directory']: continue
        with open(Path(current) / relative, 'rb') as left, open(Path(reference) / relative, 'rb') as right:
            while True:
                first, second = left.read(65536), right.read(65536)
                if first != second: return False
                if not first: break
    return True


class DirectoryTransaction:
    def __init__(self, state_directory, destination, code_root):
        self.directory = Path(os.path.abspath(state_directory))
        self.destination = Path(os.path.abspath(destination))
        self.code_root = Path(os.path.abspath(code_root))
        if self.destination == self.code_root or not self.destination.is_relative_to(self.code_root):
            raise RuntimeError('Component destination must be inside the explicit code store')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeError('Private transaction directory required')
        self.state = self.directory / 'state.json'
        self.destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor = directory_fd(self.destination.parent); os.close(descriptor)
        for path in [self.destination.parent, *self.destination.parent.parents]:
            if not path.is_relative_to(self.code_root): break
            info = path.lstat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise RuntimeError('Untrusted component code ancestor')

    def save(self, value):
        atomic_write(self.state, (json.dumps(value, indent=2) + '\n').encode(), 0o600)

    def load(self):
        saved = snapshot(self.state)
        if saved['uid'] != os.geteuid() or saved['mode'] & 0o077: raise RuntimeError('Untrusted state file')
        value = json.loads(base64.b64decode(saved['data']))
        if value['destination'] != str(self.destination): raise RuntimeError('Transaction destination changed')
        return value

    @serialized
    def apply(self, source):
        source = Path(source)
        source_metadata = inventory(source)
        if self.state.exists():
            value = self.load()
            if value['phase'] != 'installed': raise RuntimeError('Restore interrupted transaction before retry')
            if not same_tree(self.destination, self.directory / 'installed', value['installed_metadata']):
                raise RuntimeError('Installed component changed; refusing to overwrite it')
            if same_tree(source, self.directory / 'installed', value['installed_metadata']): return
            raise RuntimeError('Version updates require a separate transaction after restoring this version')
        original_exists = self.destination.exists()
        original_metadata = inventory(self.destination) if original_exists else None
        if original_exists: shutil.copytree(self.destination, self.directory / 'original-reference', copy_function=shutil.copy2)
        shutil.copytree(source, self.directory / 'installed', copy_function=shutil.copy2)
        shutil.copytree(source, self.directory / 'staged', copy_function=shutil.copy2)
        value = {'destination': str(self.destination), 'phase': 'prepared', 'original_exists': original_exists,
                 'original_metadata': original_metadata, 'installed_metadata': source_metadata}
        self.save(value)
        if original_exists: os.rename(self.destination, self.directory / 'original')
        value['phase'] = 'installing'; self.save(value)
        os.rename(self.directory / 'staged', self.destination)
        value['phase'] = 'installed'; self.save(value)

    @serialized
    def rollback(self):
        value = self.load()
        if value['phase'] == 'rolled_back': return
        original = self.directory / 'original'
        if self.destination.exists():
            if value['original_exists'] and same_tree(self.destination, self.directory / 'original-reference', value['original_metadata']):
                value['phase'] = 'rolled_back'; self.save(value); return
            if not same_tree(self.destination, self.directory / 'installed', value['installed_metadata']):
                raise RuntimeError('Installed component changed; refusing to remove user changes')
            if value['original_exists'] and not original.exists(): raise RuntimeError('Original directory backup missing')
            value['phase'] = 'restoring'; self.save(value)
            # Only the exact installed tree inside the explicit code store can be removed.
            shutil.rmtree(self.destination)
        if value['original_exists']:
            if not original.exists(): raise RuntimeError('Original directory backup missing')
            os.rename(original, self.destination)
        value['phase'] = 'rolled_back'; self.save(value)
