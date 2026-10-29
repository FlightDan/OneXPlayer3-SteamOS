"""File map for the optional KDE persistent partition mount utility."""
import os
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import stat
import struct


TOOLS = ('python3', 'pkexec', 'kdialog', 'lsblk', 'findmnt', 'systemctl', 'systemd-escape', 'blkid')
ASSETS = ('mounts.py', 'desktop.py', 'oxp3-partition-mount', 'oxp3-partition-mount.desktop',
          'preflight.py', 'ntfs-generator.py', 'oxp3-ntfs-preflight@.service',
          'ntfs_status.c', 'ntfs-tools-build.sh', 'ntfs-tools-source.json', 'MUSL-COPYRIGHT')
RUNTIME_NAMES = {'ntfs_status', 'ntfsfix', 'COPYING', 'source.tar.gz'}


def _static_elf(data):
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<H', data, 18)[0] != 62:
        raise RuntimeError('NTFS tools must be little-endian x86_64 ELF binaries')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if not count or count > 128 or size != 56 or offset + size * count > len(data):
        raise RuntimeError('Invalid NTFS tool ELF program headers')
    for index in range(count):
        if struct.unpack_from('<I', data, offset + index * size)[0] in (2, 3):
            raise RuntimeError('NTFS tool has a dynamic loader or dynamic dependencies')


def runtime_files(source):
    """Accept only the pinned, freshly built static tools and corresponding source."""
    source = Path(source)
    names = RUNTIME_NAMES | {'manifest.json'}
    if source.is_symlink() or not source.is_dir() or {path.name for path in source.iterdir()} != names:
        raise RuntimeError('Missing or unexpected NTFS tools payload files')
    output = {}
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise RuntimeError('Unsafe or oversized NTFS tools payload: ' + name)
        output[name] = path.read_bytes()
    manifest = json.loads(output['manifest.json'])
    pin = json.loads((source.parent / 'ntfs-tools-source.json').read_bytes())
    if (manifest.get('schema') != 1 or manifest.get('architecture') != 'x86_64' or
            manifest.get('static') is not True or manifest.get('version') != pin['version'] or
            manifest.get('source') != pin['source'] or set(manifest.get('files', {})) != RUNTIME_NAMES):
        raise RuntimeError('NTFS tools provenance does not match the pinned source')
    for name in RUNTIME_NAMES:
        data = output[name]
        expected = manifest['files'][name]
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise RuntimeError('NTFS tools payload hash/size mismatch: ' + name)
    if hashlib.sha256(output['source.tar.gz']).hexdigest() != pin['source']['sha256']:
        raise RuntimeError('NTFS corresponding source archive mismatch')
    for name in ('ntfs_status.c', 'ntfs-tools-build.sh'):
        digest = hashlib.sha256((source.parent / name).read_bytes()).hexdigest()
        if manifest.get('build_inputs', {}).get(name) != digest:
            raise RuntimeError('Rebuild NTFS tools from current source: ' + name)
    for name in ('ntfs_status', 'ntfsfix'):
        _static_elf(output[name])
    return output


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
    """Deploy the tool and generator; preserve independent user fstab state."""
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
    for name in ('mounts.py', 'desktop.py', 'oxp3-partition-mount', 'preflight.py',
                 'ntfs_status.c', 'ntfs-tools-build.sh', 'ntfs-tools-source.json', 'MUSL-COPYRIGHT'):
        mode = 0o755 if name == 'oxp3-partition-mount' else 0o644
        output['home/.oxp3-partition-mount/' + name] = {
            'data': (source / name).read_bytes(), 'mode': mode}
    output['etc/systemd/system-generators/oxp3-ntfs-preflight'] = {
        'data': (source / 'ntfs-generator.py').read_bytes(), 'mode': 0o755}
    output['etc/systemd/system/oxp3-ntfs-preflight@.service'] = {
        'data': (source / 'oxp3-ntfs-preflight@.service').read_bytes(), 'mode': 0o644}
    for name, data in runtime_files(source / 'tools').items():
        output['home/.oxp3-partition-mount/tools/' + name] = {
            'data': data, 'mode': 0o755 if name in ('ntfs_status', 'ntfsfix') else 0o644}
    desktop = (source / 'oxp3-partition-mount.desktop').read_bytes()
    for target in ('home/deck/Desktop/oxp3-partition-mount.desktop',
                   'home/deck/.local/share/applications/oxp3-partition-mount.desktop'):
        output[target] = {'data': desktop, 'user': True, 'mode': 0o755}

    _validate_root_owned_targets(root, output)
    return output
