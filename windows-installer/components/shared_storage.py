"""Offline, reversible shared-file mounts; never opens or mounts a block device."""
import base64
import os
from pathlib import Path, PurePosixPath
import re
import stat

BEGIN = '# BEGIN OXP3 INSTALLER SHARED STORAGE\n'
END = '# END OXP3 INSTALLER SHARED STORAGE\n'
PARTUUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
MOUNT_NAME = re.compile(r'share-d(?:0|[1-9][0-9]{0,4})-p[1-9][0-9]{0,4}\Z')


def validate_mounts(mounts):
    if type(mounts) is not list or len(mounts) > 32:
        raise ValueError('Invalid shared storage selection')
    identities = set(); names = set()
    for item in mounts:
        if (type(item) is not dict or not {'partuuid', 'filesystem', 'mount_name'}.issubset(item)
                or set(item) - {'partuuid', 'filesystem', 'mount_name', 'steam_library'}):
            raise ValueError('Invalid shared storage fields')
        if any(type(item[key]) is not str for key in ('partuuid', 'filesystem', 'mount_name')):
            raise ValueError('Invalid shared storage field type')
        if ('steam_library' in item and type(item['steam_library']) is not bool or
                item.get('steam_library', False) and item['filesystem'] != 'ntfs'):
            raise ValueError('Steam directory libraries require an explicit NTFS selection')
        guid, name = item['partuuid'], item['mount_name']
        if not PARTUUID.fullmatch(guid) or guid == '00000000-0000-0000-0000-000000000000':
            raise ValueError('A canonical GPT partition identifier is required')
        if not MOUNT_NAME.fullmatch(name) or len(name) > 64:
            raise ValueError('Invalid shared storage mount name')
        if item['filesystem'] not in ('ntfs', 'exfat', 'vfat', 'ext4', 'btrfs'):
            raise ValueError('Unsupported shared storage filesystem')
        if guid in identities or name in names:
            raise ValueError('Duplicate shared storage partition or mount path')
        identities.add(guid); names.add(name)
    return mounts


def mount_path(item):
    return '/mnt/shared/' + item['mount_name']


def steam_library_path(item):
    return '/var/mnt/steam-libraries/' + item['mount_name']


def steam_bind_row(item):
    parent = _mount_alias(mount_path(item))
    return (f'{parent}/SteamLibrary {steam_library_path(item)} none '
            f'bind,exec,nosuid,nodev,nofail,x-systemd.automount,'
            f'x-systemd.requires-mounts-for={parent},x-systemd.mount-timeout=30s 0 0\n')


def _mount_alias(path):
    # SteamOS 3.10 has /mnt -> var/mnt. Treat both spellings as the same
    # destination when checking administrator-owned mounts, even on fixtures.
    normalized = '/' + str(PurePosixPath(path)).lstrip('/') if path.startswith('/') else path
    if normalized == '/mnt' or normalized.startswith('/mnt/'):
        return '/var' + normalized
    return normalized


def _unescape_fstab(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def render_fstab(original, mounts, owner, managed=False):
    """Keep every byte outside our one journal-owned block, including comments."""
    validate_mounts(mounts)
    if not mounts: return original
    if (type(owner) is not tuple or len(owner) != 2 or
            any(type(value) is not int or value <= 0 for value in owner)):
        raise ValueError('A non-root deck uid/gid is required')
    text = original.decode('utf-8')
    lines = text.splitlines(keepends=True)
    markers = [(index, line) for index, line in enumerate(lines)
               if 'OXP3 INSTALLER SHARED STORAGE' in line]
    if markers:
        if (not managed or len(markers) != 2 or markers[0][1] != BEGIN or
                markers[1][1] != END or markers[0][0] >= markers[1][0]):
            raise RuntimeError('Conflicting or unowned shared storage fstab block')
        start, end = markers[0][0], markers[1][0]
        outside = lines[:start] + lines[end + 1:]
    else:
        start = len(lines); outside = lines
    requested = {_mount_alias(mount_path(item)) for item in mounts}
    requested.update(steam_library_path(item) for item in mounts if item.get('steam_library', False))
    identities = {item['partuuid'] for item in mounts}
    for line in outside:
        fields = line.strip().split()
        if not fields or fields[0].startswith('#'): continue
        if len(fields) < 2: raise RuntimeError('Malformed existing fstab entry')
        source, destination = (_unescape_fstab(value) for value in fields[:2])
        partition = source.removeprefix('PARTUUID=') if source.startswith('PARTUUID=') else source.removeprefix('/dev/disk/by-partuuid/')
        if partition.lower() in identities:
            raise RuntimeError('Selected partition already has an unmanaged fstab mount')
        normalized = _mount_alias(destination)
        if '..' in PurePosixPath(destination).parts:
            raise RuntimeError('Ambiguous existing fstab mount path')
        if any(normalized == path or normalized.startswith(path + '/') or
               (normalized not in ('/', '/var', '/var/mnt') and path.startswith(normalized.rstrip('/') + '/'))
               for path in requested):
            raise RuntimeError('Shared storage mount path conflicts with existing fstab')
    block = BEGIN
    for item in mounts:
        filesystem = 'ntfs3' if item['filesystem'] == 'ntfs' else item['filesystem']
        # Native Linux volumes may contain Steam libraries. Keep their existing
        # ownership/modes and permit execution; shared Windows formats remain noexec.
        # Never force NTFS dirty/hibernated volumes or delete their hibernation file.
        execution = 'exec' if item['filesystem'] in ('ext4', 'btrfs') else 'noexec'
        options = (f'rw,nosuid,nodev,{execution},nofail,x-systemd.automount,'
                   'x-systemd.device-timeout=5s,x-systemd.mount-timeout=30s')
        # Linux filesystems retain their on-disk ownership and permissions.
        if item['filesystem'] not in ('ext4', 'btrfs'):
            options += f',uid={owner[0]},gid={owner[1]},fmask=0133,dmask=0022'
        if item['filesystem'] == 'ntfs': options += ',windows_names'
        block += f'PARTUUID={item["partuuid"]} {mount_path(item)} {filesystem} {options} 0 0\n'
        if item.get('steam_library', False):
            block += steam_bind_row(item)
    block += END
    if markers:
        output = ''.join(lines[:start]) + block + ''.join(lines[end + 1:])
    else:
        output = text + ('' if not text or text.endswith('\n') else '\n') + block
    return output.encode('utf-8')


def _safe_existing(root, relative):
    """Refuse links/special files and writable path ancestors before inspection."""
    path = root
    for component in Path(relative).parts:
        path = path / component
        try: info = path.lstat()
        except FileNotFoundError: return path, False
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('Unsafe shared storage path: ' + str(path))
        if os.name == 'posix' and (info.st_uid != 0 or info.st_mode & 0o022):
            raise RuntimeError('Untrusted shared storage path: ' + str(path))
    return path, True


def _check_mount_paths(root, mounts):
    relative = 'mnt'
    entry = root / 'mnt'
    try: info = entry.lstat()
    except FileNotFoundError: info = None
    if info is not None and stat.S_ISLNK(info.st_mode):
        # Verified in the official 3.10 image. Never resolve an absolute link
        # against the guest host, or allow arbitrary image symlink chains.
        if os.readlink(entry) != 'var/mnt' or (os.name == 'posix' and info.st_uid != 0):
            raise RuntimeError('Unsafe shared storage path: ' + str(entry))
        relative = 'var/mnt'
    if any(item.get('steam_library', False) for item in mounts) and relative != 'var/mnt':
        raise RuntimeError('NTFS Steam libraries require the verified SteamOS /mnt -> var/mnt layout')
    for item in mounts:
        path, exists = _safe_existing(root, relative + '/shared/' + item['mount_name'])
        if exists and (not path.is_dir() or any(path.iterdir())):
            raise RuntimeError('Shared storage mount point must be an empty ordinary directory')
        aliases = [mount_path(item), _mount_alias(mount_path(item))]
        if item.get('steam_library', False):
            library = steam_library_path(item)
            path, exists = _safe_existing(root, library.lstrip('/'))
            if exists and (not path.is_dir() or any(path.iterdir())):
                raise RuntimeError('Steam library alias must be an empty ordinary directory')
            aliases.append(library)
        directories = ['etc/systemd/system', 'usr/local/lib/systemd/system', 'usr/lib/systemd/system']
        # /lib is commonly an image-owned symlink to /usr/lib; inspect the latter.
        if (root / 'lib').exists() and not (root / 'lib').is_symlink():
            directories.append('lib/systemd/system')
        for directory in directories:
            for alias in aliases:
                escaped = alias.lstrip('/').replace('-', r'\x2d').replace('/', '-')
                for suffix in ('.mount', '.automount', '.mount.d', '.automount.d'):
                    path, exists = _safe_existing(root, directory + '/' + escaped + suffix)
                    if exists: raise RuntimeError('Conflicting shared storage systemd unit: ' + str(path))


def _require_kernel_ntfs3(root, kernel):
    from file_transaction import snapshot
    prefix = 'usr/lib/modules/' + kernel
    path, exists = _safe_existing(root, prefix + '/modules.builtin')
    if exists:
        saved = snapshot(path, maximum=8 * 1024 * 1024)
        entries = base64.b64decode(saved['data']).decode('utf-8').splitlines()
        if 'kernel/fs/ntfs3/ntfs3.ko' in entries: return
    for suffix in ('.ko', '.ko.zst', '.ko.xz', '.ko.gz'):
        path, exists = _safe_existing(root, prefix + '/kernel/fs/ntfs3/ntfs3' + suffix)
        if exists and path.is_file(): return
    raise RuntimeError('The SteamOS kernel does not provide a verified ntfs3 driver: ' + kernel)


def require_ntfs3(root):
    """Check every ordinary installed image kernel, never the host/pinned kernel."""
    root = Path(root).absolute()
    directory, exists = _safe_existing(root, 'usr/lib/modules')
    if not exists or not directory.is_dir():
        raise RuntimeError('Cannot confirm installed SteamOS kernels for ntfs3')
    kernels = []
    for entry in sorted(directory.iterdir()):
        candidate, exists = _safe_existing(root, 'usr/lib/modules/' + entry.name)
        if not candidate.is_dir() or not re.fullmatch(r'[0-9][A-Za-z0-9._+-]{0,127}', entry.name):
            raise RuntimeError('Cannot confirm ordinary installed SteamOS kernel: ' + entry.name)
        kernels.append(entry.name)
    if not kernels: raise RuntimeError('Cannot confirm installed SteamOS kernels for ntfs3')
    for kernel in kernels: _require_kernel_ntfs3(root, kernel)
    return kernels


def require_steam_interface(root, owner):
    """Do not silently enable Steam debugging or take ownership of Decky's marker."""
    path = Path(root)
    relative = 'home/deck/.local/share/Steam/.cef-enable-remote-debugging'
    for component in Path(relative).parts:
        path = path / component
        try: info = path.lstat()
        except FileNotFoundError:
            raise RuntimeError('NTFS Steam library registration requires the local Steam interface; '
                               'select Decky or provision Steam local debugging before selecting this option')
        leaf = component == '.cef-enable-remote-debugging'
        if (not (stat.S_ISREG(info.st_mode) if leaf else stat.S_ISDIR(info.st_mode))
                or os.name == 'posix' and (info.st_uid not in (0, owner[0]) or info.st_mode & 0o022)):
            raise RuntimeError('Untrusted local Steam interface marker path: ' + str(path))


def files(root, mounts, owner, managed=False):
    validate_mounts(mounts)
    if not mounts: return {}
    root = Path(root).absolute()
    _check_mount_paths(root, mounts)
    if any(item['filesystem'] == 'ntfs' for item in mounts): require_ntfs3(root)
    from file_transaction import snapshot
    saved = snapshot(root / 'etc/fstab')
    if saved['exists'] and (saved['uid'] != 0 or saved['mode'] & 0o022):
        raise RuntimeError('A trusted root-owned fstab is required')
    original = base64.b64decode(saved['data']) if saved['exists'] else b''
    output = {'etc/fstab': {'data': render_fstab(original, mounts, owner, managed)}}
    if any(item.get('steam_library', False) for item in mounts):
        require_steam_interface(root, owner)
        from ntfs_steam import runtime_files
        for relative, entry in runtime_files(mounts, owner).items():
            path, exists = _safe_existing(root, relative)
            if exists and (not path.is_file() or stat.S_IMODE(path.stat().st_mode) != entry.get('mode', 0o644)):
                raise RuntimeError('Unexpected NTFS Steam runtime target metadata: ' + str(path))
            output[relative] = entry
    return output


def verify_fstab(data, mounts, owner):
    """Independently parse installed rows; do not reproduce the renderer output."""
    validate_mounts(mounts)
    if not mounts: return
    lines = data.decode('utf-8').splitlines()
    begin = [index for index, line in enumerate(lines) if line == BEGIN.rstrip('\n')]
    end = [index for index, line in enumerate(lines) if line == END.rstrip('\n')]
    if len(begin) != 1 or len(end) != 1 or begin[0] >= end[0]:
        raise RuntimeError('Missing or ambiguous installed shared storage fstab block')
    rows = lines[begin[0]+1:end[0]]
    libraries = [item for item in mounts if item.get('steam_library', False)]
    if len(rows) != len(mounts) + len(libraries):
        raise RuntimeError('Installed shared storage count differs from selection')
    expected = {item['partuuid']: item for item in mounts}
    seen = set()
    bind_rows = []
    for line in rows:
        fields = line.split()
        if len(fields) != 6:
            raise RuntimeError('Malformed installed shared storage row')
        if not fields[0].startswith('PARTUUID='):
            bind_rows.append(fields)
            continue
        identity = fields[0][9:]
        if identity not in expected or identity in seen:
            raise RuntimeError('Installed shared storage partition differs from selection')
        seen.add(identity); selected = expected[identity]
        if fields[1] != '/mnt/shared/' + selected['mount_name'] or fields[4:] != ['0', '0']:
            raise RuntimeError('Installed shared storage destination/check policy differs from selection')
        filesystem = {'ntfs':'ntfs3', 'exfat':'exfat', 'vfat':'vfat', 'ext4':'ext4', 'btrfs':'btrfs'}[selected['filesystem']]
        if fields[2] != filesystem:
            raise RuntimeError('Installed shared storage filesystem differs from selection')
        required = {'rw', 'nosuid', 'nodev', 'nofail', 'x-systemd.automount',
                    'x-systemd.device-timeout=5s', 'x-systemd.mount-timeout=30s'}
        if filesystem in ('ext4', 'btrfs'):
            required.add('exec')
        else:
            required.add('noexec')
            required.update({'uid=' + str(owner[0]), 'gid=' + str(owner[1]), 'fmask=0133', 'dmask=0022'})
        if filesystem == 'ntfs3': required.add('windows_names')
        actual = fields[3].split(',')
        if len(actual) != len(set(actual)) or set(actual) != required:
            raise RuntimeError('Installed shared storage permission/safety options differ from selection')
    if seen != set(expected):
        raise RuntimeError('Missing installed shared storage partition')
    binds = {_mount_alias(mount_path(item)) + '/SteamLibrary': item for item in libraries}
    seen_binds = set()
    for fields in bind_rows:
        source = fields[0]
        item = binds.get(source)
        if item is None or source in seen_binds:
            raise RuntimeError('Unexpected or duplicate Steam library directory bind')
        seen_binds.add(source)
        parent = _mount_alias(mount_path(item))
        required = {'bind', 'exec', 'nosuid', 'nodev', 'nofail', 'x-systemd.automount',
                    'x-systemd.requires-mounts-for=' + parent, 'x-systemd.mount-timeout=30s'}
        flags = fields[3].split(',')
        if (fields[1] != steam_library_path(item) or fields[2] != 'none' or fields[4:] != ['0', '0']
                or len(flags) != len(set(flags)) or set(flags) != required):
            raise RuntimeError('Steam library bind scope or safety policy differs from selection')
    if seen_binds != set(binds):
        raise RuntimeError('Missing Steam library directory bind')
    # A duplicate unmanaged reference outside the block can supersede the intent.
    destinations = {_mount_alias(mount_path(item)) for item in mounts}
    destinations.update(steam_library_path(item) for item in libraries)
    for line in lines[:begin[0]] + lines[end[0]+1:]:
        fields = line.split()
        if not fields or fields[0].startswith('#') or len(fields) < 2: continue
        source = _unescape_fstab(fields[0])
        if (source.removeprefix('PARTUUID=') in expected or
                source.removeprefix('/dev/disk/by-partuuid/') in expected or
                _mount_alias(_unescape_fstab(fields[1])) in destinations):
            raise RuntimeError('Duplicate unmanaged installed shared storage reference')


def verify_steam_runtime(root, mounts, owner):
    """Verify the staged immutable runtime without mounting or registering anything."""
    validate_mounts(mounts)
    if not any(item.get('steam_library', False) for item in mounts):
        return
    from ntfs_steam import runtime_files
    from file_transaction import snapshot
    for relative, expected in runtime_files(mounts, owner).items():
        saved = snapshot(Path(root) / relative)
        if (not saved['exists'] or saved['uid'] != 0 or saved['gid'] != 0
                or saved['mode'] != expected.get('mode', 0o644)
                or base64.b64decode(saved['data']) != expected['data']):
            raise RuntimeError('Missing or changed NTFS Steam runtime file: ' + relative)
