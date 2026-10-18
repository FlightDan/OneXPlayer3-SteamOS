"""File map for the optional KDE persistent partition mount utility."""
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat


TOOLS = ('python3', 'pkexec', 'kdialog', 'lsblk', 'findmnt', 'systemctl', 'systemd-escape')
ASSETS = ('mounts.py', 'desktop.py', 'oxp3-partition-mount', 'oxp3-partition-mount.desktop')


def image_tool(root, tool):
    """Resolve a tool from the target image, never from the build host."""
    root = Path(root).absolute()
    if tool not in TOOLS:
        raise ValueError('Unsupported partition mount dependency')
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != 0 or root_info.st_mode & 0o022:
        raise RuntimeError('Untrusted partition mount image root')

    logical = '/usr/bin/' + tool
    for _ in range(16):
        parts = PurePosixPath(logical).parts[1:]
        path = root
        for index, component in enumerate(parts):
            path = path / component
            try:
                info = path.lstat()
            except FileNotFoundError:
                return False
            if info.st_uid != 0:
                raise RuntimeError('Untrusted partition mount dependency: ' + str(path))
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                prefix = '/' + '/'.join(parts[:index])
                logical = posixpath.normpath(posixpath.join(prefix, target, *parts[index + 1:]))
                if not logical.startswith('/'):
                    raise RuntimeError('Invalid partition mount dependency link')
                break
            if info.st_mode & 0o022:
                raise RuntimeError('Writable partition mount dependency: ' + str(path))
            if index < len(parts) - 1:
                if not stat.S_ISDIR(info.st_mode):
                    raise RuntimeError('Unsafe partition mount dependency ancestor')
            else:
                if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
                    raise RuntimeError('Unsafe partition mount dependency target')
                return True
        else:
            raise RuntimeError('Invalid partition mount dependency link target')
    raise RuntimeError('Partition mount dependency symlink cycle')


def _validate_root_owned_targets(root, files):
    """Reject unsafe existing paths before the installer journals replacements."""
    for target, entry in files.items():
        if entry.get('user'):
            continue
        path = root / target
        for ancestor in (path, *path.parents):
            if not ancestor.is_relative_to(root):
                break
            if not os.path.lexists(ancestor):
                continue
            info = ancestor.lstat()
            if (info.st_uid != 0 or info.st_mode & 0o022 or
                    not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
                raise RuntimeError('Untrusted partition mount target: ' + str(ancestor))
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != entry['mode']:
            raise RuntimeError('Unexpected partition mount file permissions: ' + str(path))


def files(root, components):
    """Build a fixed file-only deployment; never inspect or change fstab."""
    root = Path(root).absolute()
    source = Path(components).absolute() / 'partition-mount'
    for name in ASSETS:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Partition mount source file is missing or unsafe: ' + name)
    for tool in TOOLS:
        if not image_tool(root, tool):
            raise RuntimeError('Partition mount dependency missing: /usr/bin/' + tool)

    output = {}
    for name in ('mounts.py', 'desktop.py', 'oxp3-partition-mount'):
        mode = 0o755 if name == 'oxp3-partition-mount' else 0o644
        output['home/.oxp3-partition-mount/' + name] = {
            'data': (source / name).read_bytes(), 'mode': mode}
    desktop = (source / 'oxp3-partition-mount.desktop').read_bytes()
    for target in ('home/deck/Desktop/oxp3-partition-mount.desktop',
                   'home/deck/.local/share/applications/oxp3-partition-mount.desktop'):
        output[target] = {'data': desktop, 'user': True, 'mode': 0o755}

    _validate_root_owned_targets(root, output)
    return output
