"""Validate the fixed root-owned bootstrap library on the readonly media."""
import os
from pathlib import Path
import stat
import sys

RELATIVE = 'usr/local/lib/oxp3-installer/firstboot-library'
FILES = {'firstboot.py', 'firstboot_stage.py', 'file_transaction.py', 'shared_state.py',
         'hdr/installer.py', 'hdr/generate.py', 'hdr/upstream.lua', 'hdr/UPSTREAM_LICENSE'}

def library(root):
    path = Path(root) / RELATIVE
    if not path.exists() and not path.is_symlink(): return None
    for entry in [path, *path.parents]:
        info = entry.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Untrusted bootstrap library ancestor')
    found = set()
    for entry in path.rglob('*'):
        info = entry.lstat(); relative = entry.relative_to(path).as_posix()
        if info.st_uid != 0 or info.st_mode & 0o022: raise RuntimeError('Writable/non-root bootstrap source')
        if stat.S_ISDIR(info.st_mode):
            if relative != 'hdr': raise RuntimeError('Unexpected bootstrap directory')
        elif stat.S_ISREG(info.st_mode):
            if info.st_size > 1024 * 1024: raise RuntimeError('Bootstrap source too large')
            found.add(relative)
        else: raise RuntimeError('Redirected/special bootstrap source')
    if found != FILES: raise RuntimeError('Bootstrap source file set changed')
    return path

def stage(root, source_root, request):
    path = library(source_root)
    if path is None: raise RuntimeError('Selected source lacks bootstrap library')
    sys.path.insert(0, str(path))
    from firstboot_stage import stage as install
    return install(root, path, request, enable=bool(request['components']))
