"""Journaled shared recovery entry survives replacement of either root image."""
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat


def image_tool(root, tool):
    """Resolve image-owned links in the target namespace, never the host /usr."""
    root = Path(root).absolute()
    if tool not in ('python3', 'pkexec', 'kdialog', 'steamos-bootconf', 'systemctl', 'busctl'):
        raise ValueError('Unsupported slot switch dependency')
    logical = '/usr/bin/' + tool
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != 0 or root_info.st_mode & 0o022:
        raise RuntimeError('Untrusted slot switch image root')
    for _ in range(16):
        parts = PurePosixPath(logical).parts[1:]
        path = root
        for index, component in enumerate(parts):
            path = path / component
            try: info = path.lstat()
            except FileNotFoundError: return False
            if info.st_uid != 0:
                raise RuntimeError('Untrusted slot switch dependency: ' + str(path))
            if stat.S_ISLNK(info.st_mode):
                # Linux link mode is always 0777, so trust its root ownership,
                # then inspect every resolved ancestor and the regular target.
                target = os.readlink(path)
                prefix = '/' + '/'.join(parts[:index])
                logical = posixpath.normpath(posixpath.join(prefix, target, *parts[index+1:]))
                if not logical.startswith('/'): raise RuntimeError('Invalid image tool link')
                break
            if info.st_mode & 0o022:
                raise RuntimeError('Writable slot switch dependency: ' + str(path))
            if index < len(parts)-1:
                if not stat.S_ISDIR(info.st_mode): raise RuntimeError('Unsafe slot switch dependency ancestor')
            else:
                if not stat.S_ISREG(info.st_mode): raise RuntimeError('Unsafe slot switch dependency target')
                return True
        else:
            raise RuntimeError('Invalid slot switch dependency link target')
    raise RuntimeError('Slot switch dependency symlink cycle')


def files(root, components):
    root, source = Path(root), Path(components) / 'slot-switch'
    for tool in ('python3', 'pkexec', 'kdialog', 'steamos-bootconf', 'systemctl', 'busctl'):
        if not image_tool(root, tool):
            raise RuntimeError('Slot switch dependency missing: /usr/bin/' + tool)
    output = {}
    for name in ('boot.py', 'desktop.py', 'oxp3-switch-slot'):
        output['home/.oxp3-slot-switch/' + name] = {
            'data': (source / name).read_bytes(), 'mode': 0o755 if name == 'oxp3-switch-slot' else 0o644}
    output['etc/polkit-1/rules.d/49-oxp3-slot-switch.rules'] = {
        'data': (source / '49-oxp3-slot-switch.rules').read_bytes()}
    for path in ('home/deck/Desktop/oxp3-slot-switch.desktop',
                 'home/deck/.local/share/applications/oxp3-slot-switch.desktop'):
        output[path] = {'data': (source / 'oxp3-slot-switch.desktop').read_bytes(), 'user': True, 'mode': 0o755}
    # Shared executable code must never inherit deck-writable permissions.
    for target, entry in output.items():
        if entry.get('user'): continue
        path = root / target
        for ancestor in (path, *path.parents):
            if not ancestor.is_relative_to(root): break
            if not os.path.lexists(ancestor): continue
            info = ancestor.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise RuntimeError('Untrusted slot switch target: ' + str(ancestor))
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != entry.get('mode', 0o644):
            raise RuntimeError('Unexpected slot switch permissions: ' + str(path))
    return output
