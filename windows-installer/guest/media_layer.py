"""Track only newly created recovery UI paths; detach them from copied roots.

No content hash is used. A path/type inventory is ownership metadata, not proof
of official image authenticity. Legacy previews without this record are refused.
"""
import json
import os
from pathlib import Path, PurePosixPath
import stat

from resources import publish
from component_choice import selected

OWNED = (
    'usr/local/lib/oxp3-installer',
    'usr/local/share/oxp3-installer',
    'etc/systemd/system/oxp3-preview.target',
    'etc/systemd/system/oxp3-preview.service',
    'etc/systemd/system/oxp3-preview.target.wants',
    'usr/lib/x86_64-linux-gnu/kmscon',
)
MANIFEST = 'usr/local/share/oxp3-installer/media-layer.json'
SELECTION = 'usr/local/share/oxp3-installer/selection.json'
WANT = 'etc/systemd/system/oxp3-preview.target.wants/oxp3-preview.service'
SOURCE = {'version': '3.8.14', 'build': '20260707.10'}


def exists(path):
    return path.exists() or path.is_symlink()


def safe(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in ('.', '..') for p in parts.parts):
        raise RuntimeError('Invalid media ownership path')
    path = root
    for part in parts.parts[:-1]:
        path = path / part
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError('Media ownership parent is redirected')
    return root.joinpath(*parts.parts)


def inventory(root):
    result = []
    def visit(relative):
        path = safe(root, relative)
        if not exists(path): return
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            if relative != WANT or os.readlink(path) != '../oxp3-preview.service':
                raise RuntimeError('Unexpected symlink in owned media paths')
            result.append({'path': relative, 'kind': 'symlink', 'target': '../oxp3-preview.service'})
        elif stat.S_ISDIR(mode):
            result.append({'path': relative, 'kind': 'directory'})
            for child in sorted(path.iterdir()): visit(relative + '/' + child.name)
        elif stat.S_ISREG(mode): result.append({'path': relative, 'kind': 'file'})
        else: raise RuntimeError('Unexpected object in owned media paths')
    for relative in OWNED: visit(relative)
    return sorted(result, key=lambda item: item['path'])


def begin(root):
    # The generator can claim only absent paths; no existing component is replaced.
    for relative in OWNED:
        if exists(safe(root, relative)): raise RuntimeError('Recovery layer path already exists: ' + relative)
    file = safe(root, MANIFEST)
    file.parent.mkdir(parents=True)
    publish(file, (json.dumps({'schema': 1, 'purpose': 'oxp3-recovery-preview',
                             'source': SOURCE, 'owned_roots': list(OWNED), 'status': 'building'}) + '\n').encode())


def read(root):
    file = safe(root, MANIFEST)
    if not exists(file):
        if exists(safe(root, SELECTION)): raise RuntimeError('Legacy preview lacks a detachable recovery layer')
        return None
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 128 * 1024:
        raise RuntimeError('Invalid recovery layer record')
    data = json.loads(file.read_text())
    if (data.get('schema') != 1 or data.get('purpose') != 'oxp3-recovery-preview'
            or data.get('source') != SOURCE or data.get('owned_roots') != list(OWNED)):
        raise RuntimeError('Unknown recovery layer ownership')
    return data


def finalize(root):
    data = read(root)
    if data is None or data['status'] != 'building': raise RuntimeError('No active media generation record')
    data.update(status='ready', entries=inventory(root))
    publish(safe(root, MANIFEST), (json.dumps(data, indent=2) + '\n').encode())
    return data


def start_refresh(root):
    data = inspect(root)
    if data is None: raise RuntimeError('No owned layer to refresh')
    data.update(status='building')
    publish(safe(root, MANIFEST), (json.dumps(data, indent=2) + '\n').encode())


def inspect(root):
    data = read(root)
    if data is None: return None
    if data.get('status') != 'ready' or inventory(root) != data.get('entries'):
        raise RuntimeError('Recovery layer is incomplete or contains unexpected paths')
    choice = json.loads(safe(root, SELECTION).read_text())
    if (choice.get('schema') != 1 or choice.get('stage') != 'preview_only'
            or choice.get('allow_disk_write') is not False or choice.get('source') != SOURCE
            or choice.get('plugins')):
        raise RuntimeError('Unsupported recovery layer selection')
    try: selected(choice)
    except ValueError as error: raise RuntimeError(str(error)) from error
    return data


def detach(root, expected):
    """Validate everything before unlinking; repeated/interrupted detachment is safe."""
    if (expected.get('schema') != 1 or expected.get('owned_roots') != list(OWNED)
            or expected.get('source') != SOURCE or expected.get('status') != 'ready'):
        raise RuntimeError('Unrecognized source recovery layer')
    permitted = {item['path']: item for item in expected['entries']}
    current = inventory(root)
    if any(permitted.get(item['path']) != item for item in current):
        raise RuntimeError('Copied recovery paths contain foreign entries')
    if exists(safe(root, MANIFEST)) and read(root) != expected:
        raise RuntimeError('Copied recovery ownership record changed')
    # Keep the record until all other leaves are removed. A killed operation can
    # resume against the same source inventory without guessing ownership.
    leaves = [item for item in current if item['kind'] != 'directory' and item['path'] != MANIFEST]
    for item in leaves: safe(root, item['path']).unlink()
    if exists(safe(root, MANIFEST)): safe(root, MANIFEST).unlink()
    for item in sorted((i for i in current if i['kind'] == 'directory'), key=lambda i: len(i['path']), reverse=True):
        safe(root, item['path']).rmdir()
    return bool(current)


if __name__ == '__main__':
    import sys
    root = Path(sys.argv[2])
    {'begin': begin, 'finalize': finalize, 'inspect': inspect, 'start-refresh': start_refresh}[sys.argv[1]](root)
