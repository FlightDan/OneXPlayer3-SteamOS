"""Import trusted installer originals without executing the old activation loop."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import re

_RUNTIMES = {
    'desktop-hdr': 'opt/oxp3-desktop-gamma22/6.7.3-1.6',
    'opti2xmx': 'opt/oxp3-opti2xmx/20261005',
}
_MAX_FILE = 256 * 1024 * 1024
_MAX_TREE = 1024 * 1024 * 1024
_FAN_WRITERS = {
    'var/lib/oxp3-fan/fan.py': '5ed6af94055a22454ad28a43feff257383918c21804460da5287658399ab9f9c',
    'var/lib/oxp3-installer/decky/runtime/plugins/OXP3-Fan/main.py': '147cc10a5448d36de7c3a88ccfeb4007174d732121177d0c750805d778689b4d',
}
_MUTABLE_SETTINGS = {
    'input': {'etc/inputplumber/devices.d/50-onexplayer_3.yaml'},
    'gyro': {'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml', 'etc/inputplumber/oxp3-gyro-steer.conf'},
    'multifunction': {'etc/inputplumber/capability_maps.d/oxp3-installer.yaml'},
    'keyboard': {'home/deck/.config/kwinrc'},
    'overlay': {'home/deck/.config/MangoHud/presets.conf'},
    'opti2xmx': {'home/deck/.local/share/opti2xmx/runtime.json'},
    'oxp3-fan': {'var/lib/oxp3-fan/config.json'},
    'oxp3-cpu': {'var/lib/oxp3-cpu/config.json'},
    'flathub-ustc': {'etc/flatpak/remotes.d/flathub.flatpakrepo', 'var/lib/flatpak/repo/config'},
    'gm7-resume': {'efi/EFI/steamos/grub.cfg'},
}


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _trusted(path, boundary, *, directory=False, user_uid=None):
    path, boundary = Path(path), Path(boundary)
    current = path
    while True:
        info = current.lstat()
        permitted = (0, user_uid) if user_uid is not None and current.is_relative_to(boundary / 'home/deck') else (0,)
        if _linked(info) or info.st_uid not in permitted or info.st_mode & 0o022:
            raise RuntimeError('Untrusted installer journal: ' + str(current))
        if current == boundary:
            break
        if not current.is_relative_to(boundary):
            raise RuntimeError('Installer journal escaped state directory')
        current = current.parent
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('Invalid installer runtime directory')
    elif not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE or info.st_nlink != 1:
        raise RuntimeError('Invalid installer journal')


def _relative(value, *, directory=False):
    if value == '.' and directory:
        return value
    if (not isinstance(value, str) or not value or value.startswith('/')
            or '\\' in value or ':' in value or '\x00' in value
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise RuntimeError('Unsafe legacy runtime path')
    return value


def _metadata(value):
    if not isinstance(value, dict) or '.' not in value or len(value) > 12000:
        raise RuntimeError('Invalid legacy runtime metadata')
    normalized = {}
    for relative, item in value.items():
        if not isinstance(item, dict) or type(item.get('directory')) is not bool:
            raise RuntimeError('Invalid legacy runtime metadata entry')
        _relative(relative, directory=item['directory'])
        if any(type(item.get(key)) is not int or item[key] < 0 for key in ('mode', 'uid', 'gid')) or item['mode'] > 0o7777:
            raise RuntimeError('Invalid legacy runtime metadata values')
        normalized[relative] = {key: item[key] for key in ('directory', 'mode', 'uid', 'gid')}
    if not normalized['.']['directory']:
        raise RuntimeError('Legacy runtime root must be a directory')
    for relative in normalized:
        if relative == '.':
            continue
        for parent in PurePosixPath(relative).parents:
            if parent.as_posix() not in normalized or not normalized[parent.as_posix()]['directory']:
                raise RuntimeError('Incomplete legacy runtime directory metadata')
    return normalized


def _file(path, boundary, *, user_uid=None):
    """Read one protected regular file without accepting a changed inode."""
    _trusted(path, boundary, user_uid=user_uid)
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_FILE:
        raise RuntimeError('Unsafe legacy runtime file: ' + str(path))
    if os.name == 'posix':
        # Mutable home ancestors may be renamed by deck. Hold each directory
        # descriptor and never traverse a replacement symlink while opening.
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
    else:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mode, opened.st_uid, opened.st_gid, opened.st_nlink) != (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid, info.st_gid, 1):
            raise RuntimeError('Legacy runtime file changed during reading')
        data = stream.read(_MAX_FILE + 1)
        after = os.fstat(stream.fileno())
        if len(data) > _MAX_FILE or after.st_nlink != 1 or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise RuntimeError('Legacy runtime file changed during reading')
    return {'exists': True, 'data': base64.b64encode(data).decode(),
            'mode': stat.S_IMODE(opened.st_mode), 'uid': opened.st_uid, 'gid': opened.st_gid}


def _mountinfo_text():
    return Path('/proc/self/mountinfo').read_text()


def _mount_stat(path):
    return path.stat()


def _mount_device(major, minor):
    return os.makedev(major, minor)


def _gm7_vfat_metadata(root, relative, installed, current):
    """Recognize only the live SteamOS EFI mask, not arbitrary chmod drift."""
    if (relative != 'efi/EFI/steamos/grub.cfg'
            or {key: installed[key] for key in ('mode', 'uid', 'gid')} != {'mode': 0o755, 'uid': 0, 'gid': 0}
            or {key: current[key] for key in ('mode', 'uid', 'gid')} != {'mode': 0o700, 'uid': 0, 'gid': 0}):
        return None
    root = Path(root).absolute()
    target, efi = root / relative, root / 'efi'
    try:
        target_info, efi_info = _mount_stat(target), _mount_stat(efi)
        def unescape(value):
            return re.sub(r'\\(040|011|012|134)', lambda match: chr(int(match[1], 8)), value)
        candidates = []
        for line in _mountinfo_text().splitlines():
            left, right = line.split(' - ', 1)
            fields, filesystem = left.split(), right.split()
            if Path(unescape(fields[4])) != efi or filesystem[0] != 'vfat' or fields[3] != '/':
                continue
            major, minor = (int(value) for value in fields[2].split(':'))
            device = _mount_device(major, minor)
            if target_info.st_dev != device or efi_info.st_dev != device:
                continue
            source = unescape(filesystem[1])
            if not source.startswith('/dev/') or '..' in PurePosixPath(source).parts:
                continue
            source_info = _mount_stat(Path(source))
            if not stat.S_ISBLK(source_info.st_mode) or source_info.st_rdev != device:
                continue
            options = {}
            for option in (fields[5] + ',' + filesystem[2]).split(','):
                key, _, value = option.partition('=')
                if key in options and options[key] != value:
                    raise ValueError('Conflicting EFI mount options')
                options[key] = value
            if ('rw' not in options or 'ro' in options or 'showexec' in options
                    or options.get('uid', '0') != '0' or options.get('gid', '0') != '0'
                    or not all(re.fullmatch(r'0?[0-7]{3}', options.get(key, '')) for key in ('fmask', 'dmask'))):
                continue
            file_mode = 0o777 & ~int(options['fmask'], 8)
            directory_mode = 0o777 & ~int(options['dmask'], 8)
            if (file_mode != current['mode'] or directory_mode != 0o700
                    or (stat.S_IMODE(target_info.st_mode), target_info.st_uid, target_info.st_gid) != (file_mode, 0, 0)
                    or not stat.S_ISREG(target_info.st_mode) or not stat.S_ISDIR(efi_info.st_mode)
                    or (stat.S_IMODE(efi_info.st_mode), efi_info.st_uid, efi_info.st_gid) != (directory_mode, 0, 0)):
                continue
            candidates.append({'filesystem': 'vfat', 'mountpoint': str(efi), 'device': fields[2],
                               'source': source, 'fmask': options['fmask'], 'dmask': options['dmask'],
                               'mode': file_mode, 'uid': 0, 'gid': 0})
        return candidates[0] if len(candidates) == 1 else None
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def _fan_writer_metadata(root, relative, record, installed, current):
    # Public0.1.3 Plugin.configure/_unload call fan.atomic(CONFIG), whose
    # explicit chmod(0644) differs from the installer's initial 0600 snapshot.
    if (relative != 'var/lib/oxp3-fan/config.json'
            or {key: installed[key] for key in ('mode', 'uid', 'gid')} != {'mode': 0o600, 'uid': 0, 'gid': 0}
            or {key: current[key] for key in ('mode', 'uid', 'gid')} != {'mode': 0o644, 'uid': 0, 'gid': 0}):
        return None
    for path, expected in _FAN_WRITERS.items():
        encoded = record.get('applied', {}).get(path)
        if not isinstance(encoded, str) or hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest() != expected:
            return None
        writer = _file(Path(root) / path, Path(root))
        if (writer['uid'] or writer['gid'] or writer['mode'] != 0o644
                or hashlib.sha256(base64.b64decode(writer['data'], validate=True)).hexdigest() != expected):
            return None
    return {'writer': 'public0.1.3-fan.atomic(CONFIG)', 'sha256': dict(_FAN_WRITERS),
            'mode': 0o644, 'uid': 0, 'gid': 0}


def validate_current(root, originals, probe):
    """Read-only preflight of imported targets; return the same adoption mapping.

    Compare against ``applied``, which import_originals already updates for
    permitted mutable edits. Never change originals, calibration baselines or
    preserve flags here. The transaction must still repeat its live comparison
    immediately before accepting adoption; this check is advisory preflight.
    """
    root = Path(root).absolute()
    if not isinstance(originals, dict) or len(originals) > 20000:
        raise RuntimeError('Invalid or oversized legacy adoption mapping')
    total = 0
    for relative, record in originals.items():
        _relative(relative)
        applied = record.get('applied') if isinstance(record, dict) else None
        if (not isinstance(applied, dict) or applied.get('exists') is not True
                or not isinstance(applied.get('data'), str)
                or len(applied['data']) > ((_MAX_FILE + 2) // 3) * 4
                or any(type(applied.get(key)) is not int or applied[key] < 0
                       for key in ('mode', 'uid', 'gid'))
                or applied['mode'] > 0o7777):
            raise RuntimeError('Invalid legacy applied snapshot: ' + relative)
        try:
            data = base64.b64decode(applied['data'], validate=True)
        except ValueError as error:
            raise RuntimeError('Invalid legacy applied bytes: ' + relative) from error
        total += len(data)
        if len(data) > _MAX_FILE or total > _MAX_TREE:
            raise RuntimeError('Oversized legacy adoption targets: ' + relative)
        expected = {key: applied[key] for key in ('exists', 'mode', 'uid', 'gid')}
        expected['data'] = base64.b64encode(data).decode()
        try:
            current = _file(root / relative, root,
                            user_uid=probe['uid'] if relative.startswith('home/deck/') else None)
        except (OSError, RuntimeError) as error:
            raise RuntimeError('Legacy installed target cannot be verified: ' + relative + ': ' + str(error)) from error
        if current != expected:
            raise RuntimeError('Legacy installed target changed after installation: ' + relative)
    return originals


def _tree(path, expected, boundary):
    expected = _metadata(expected)
    actual, files, total = {}, {}, 0
    def visit(directory, relative):
        nonlocal total
        _trusted(directory, boundary, directory=True)
        info = directory.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('Unsafe legacy runtime directory')
        actual[relative] = {'directory': True, 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        for child in sorted(directory.iterdir()):
            child_relative = child.name if relative == '.' else relative + '/' + child.name
            _relative(child_relative)
            if len(actual) >= 12000:
                raise RuntimeError('Oversized legacy runtime tree')
            info = child.lstat()
            if _linked(info):
                raise RuntimeError('Legacy runtime contains a link')
            if stat.S_ISDIR(info.st_mode):
                visit(child, child_relative)
            elif stat.S_ISREG(info.st_mode):
                snapshot = _file(child, boundary)
                total += info.st_size
                if total > _MAX_TREE:
                    raise RuntimeError('Oversized legacy runtime tree')
                files[child_relative] = snapshot
                actual[child_relative] = {'directory': False, **{key: snapshot[key] for key in ('mode', 'uid', 'gid')}}
            else:
                raise RuntimeError('Legacy runtime contains a special file')
    visit(path, '.')
    if actual != expected:
        raise RuntimeError('Legacy runtime metadata differs from installer journal: ' + str(path))
    return files


def _directory_originals(root, component):
    prefix = _RUNTIMES[component]
    destination = root / prefix
    state = destination.parent / '.installer-state'
    journal = state / 'state.json'
    if not os.path.lexists(journal):
        return {}
    _trusted(journal, root / 'opt')
    record = json.loads(journal.read_bytes())
    if record.get('destination') != prefix:
        raise RuntimeError('Legacy runtime destination does not match component: ' + component)
    if record.get('phase') == 'rolled_back':
        return {}
    if record.get('phase') != 'installed' or type(record.get('original_exists')) is not bool:
        raise RuntimeError('Recover interrupted legacy runtime before migration: ' + component)
    installed = _tree(state / 'installed', record.get('installed_metadata'), root / 'opt')
    current = _tree(destination, record.get('installed_metadata'), root / 'opt')
    if current != installed:
        raise RuntimeError('Legacy runtime bytes changed after install: ' + component)
    original = {}
    backups = [state / name for name in ('original-reference', 'original') if os.path.lexists(state / name)]
    if record['original_exists']:
        if not backups:
            raise RuntimeError('Original legacy runtime backup is missing: ' + component)
        for backup in backups:
            candidate = _tree(backup, record.get('original_metadata'), root / 'opt')
            if original and candidate != original:
                raise RuntimeError('Original legacy runtime backups disagree: ' + component)
            original = candidate
        missing = set(original) - set(installed)
        if missing:
            raise RuntimeError('Cannot migrate runtime with original-only files; restore the old component first: ' + component + ': ' + ', '.join(sorted(missing)))
    elif record.get('original_metadata') is not None or backups:
        raise RuntimeError('Unexpected original legacy runtime backup: ' + component)
    return {prefix + '/' + relative: {'original': original.get(relative, {'exists': False}),
                                     'applied': snapshot, 'component': component}
            for relative, snapshot in installed.items()}


def import_originals(root, probe, selected):
    """Return originals + installed snapshots; unknown/custom data is a conflict."""
    root = Path(root)
    label = probe['slot'].get('label')
    base = root / 'home/.oxp3-installer/integration'
    output = {}
    for group in ((label, 'shared') if label in ('A', 'B') else ('shared',)):
        for component in selected:
            if component in ('system-update-policy', 'refind'):
                continue
            path = base / group / component / 'state.json'
            if not os.path.lexists(path):
                continue
            _trusted(path, root / 'home')
            record = json.loads(path.read_text())
            if record.get('phase') == 'rolled_back':
                continue
            for relative in record['allowed']:
                _relative(relative)
                original = record['original'][relative]
                metadata = record.get('metadata', {}).get(relative, {})
                installed = dict(original, exists=True, data=record['applied'][relative])
                if not original.get('exists'):
                    user = metadata.get('user', False)
                    installed.update(mode=metadata.get('mode', 0o644),
                                     uid=probe['uid'] if user else 0,
                                     gid=probe['gid'] if user else 0)
                # Decode now to reject malformed state before proposing adoption.
                base64.b64decode(installed['data'], validate=True)
                if relative in output:
                    raise RuntimeError('Overlapping legacy component ownership: ' + relative)
                output[relative] = {'original': original, 'applied': installed,
                                    'component': component}
                if record.get('phase') == 'installed' and relative in _MUTABLE_SETTINGS.get(component, ()):
                    current = _file(root / relative, root, user_uid=probe['uid'] if relative.startswith('home/deck/') else None)
                    if any(current[key] != installed[key] for key in ('mode', 'uid', 'gid')):
                        provenance = (_gm7_vfat_metadata(root, relative, installed, current) if component == 'gm7-resume'
                                      else _fan_writer_metadata(root, relative, record, installed, current) if component == 'oxp3-fan' else None)
                        if provenance is None:
                            raise RuntimeError('Legacy mutable file metadata changed: ' + relative)
                        output[relative]['legacy_metadata'] = {'applied': installed, 'original': original,
                                                               'effective_metadata_source': provenance}
                        installed = dict(installed, **{key: current[key] for key in ('mode', 'uid', 'gid')})
                        output[relative]['applied'] = installed
                        if component == 'gm7-resume' and original.get('exists'):
                            if any(original.get(key) != value for key, value in {'mode': 0o755, 'uid': 0, 'gid': 0}.items()):
                                raise RuntimeError('Unsupported legacy EFI original metadata: ' + relative)
                            # VFAT cannot represent the offline mount's mode;
                            # retain it above while giving Store a restorable
                            # effective snapshot. The old journal is untouched.
                            output[relative]['original'] = dict(original, **{key: current[key] for key in ('mode', 'uid', 'gid')})
                    if current['data'] != installed['data']:
                        output[relative].update(applied=current, preserve=True, baseline=installed)
    for component in sorted(set(selected) & _RUNTIMES.keys()):
        runtime = _directory_originals(root, component)
        if set(output) & set(runtime):
            raise RuntimeError('Overlapping legacy directory and file ownership: ' + component)
        output.update(runtime)
    return output
