"""Root-owned component state on the common home filesystem, not per-slot var."""
import os
from pathlib import Path
import stat
from file_transaction import directory_fd

BASE = Path('home/.oxp3-installer')

def directory(root, relative, create=False):
    root = Path(root).absolute(); home = root / 'home'
    descriptor = directory_fd(home); os.close(descriptor)
    if not home.is_mount() or home.stat().st_dev == root.stat().st_dev: raise RuntimeError('A separately mounted shared home filesystem is required')
    if home.lstat().st_uid != 0 or home.lstat().st_mode & 0o022: raise RuntimeError('Trusted shared home mount root required')
    path = home / '.oxp3-installer'
    pieces = [path]
    for part in Path(relative).parts:
        if part in ('', '.', '..') or '/' in part or '\\' in part: raise RuntimeError('Invalid shared state relative path')
        path = path / part; pieces.append(path)
    for item in pieces:
        if not item.exists() and not item.is_symlink():
            if not create: raise RuntimeError('Shared component state is not initialized')
            parent = directory_fd(item.parent)
            try: os.mkdir(item.name, 0o700, dir_fd=parent); os.fsync(parent)
            finally: os.close(parent)
        descriptor = directory_fd(item); os.close(descriptor)
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077: raise RuntimeError('Private root-owned shared component directory required')
    return path