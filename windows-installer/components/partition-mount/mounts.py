"""KDE data-partition mounts. Fixed destinations, UUID identities, no formatting.

Only this tool's canonical fstab block is editable. Configuration is committed
before optional activation; an activation failure never hides a saved change.
"""
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import subprocess
import sys
import tempfile

BEGIN = '# BEGIN OXP3 PARTITION MOUNTS v1\n'
END = '# END OXP3 PARTITION MOUNTS v1\n'
BASE = '/var/mnt/oxp3-volumes'
FSTAB = Path('/etc/fstab')
BACKUP = Path('/etc/fstab.oxp3-partition-mount.bak')
LOCK = '/etc/.oxp3-partition-mount.lock'
UUID = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z')
FILESYSTEMS = {'ntfs': 'ntfs3', 'exfat': 'exfat', 'ext4': 'ext4', 'vfat': 'vfat'}
DATA_TYPES = {'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7',
              '0fc63daf-8483-4772-8e79-3d69d8477de4', '0x7', '0x07', '0x83'}
FAT_TYPES = {'0x6', '0x06', '0xb', '0x0b', '0xc', '0x0c', '0xe', '0x0e'}


def command(*args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=35,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if result.returncode:
        # Commands contain fixed verbs and validated identifiers, never a shell.
        raise RuntimeError((result.stderr.strip() or 'Command failed: ' + args[0])[:1500])
    return result.stdout


def destination(uuid):
    if not isinstance(uuid, str) or not UUID.fullmatch(uuid):
        raise ValueError('Invalid filesystem UUID')
    return BASE + '/' + uuid


def row(uuid, filesystem, owner):
    target = destination(uuid)
    if filesystem not in FILESYSTEMS.values():
        raise ValueError('Unsupported filesystem')
    options = ('rw,exec,nosuid,nodev,nofail,x-systemd.automount,'
               'x-systemd.device-timeout=5s,x-systemd.mount-timeout=15s')
    if filesystem != 'ext4':
        uid, gid = owner
        if type(uid) is not int or type(gid) is not int or min(uid, gid) <= 0:
            raise ValueError('A non-root desktop owner is required')
        options += f',uid={uid},gid={gid},fmask=0022,dmask=0022'
    if filesystem == 'ntfs3':
        options += ',windows_names'
    if filesystem == 'vfat':
        options += ',utf8=1'
    return f'UUID={uuid} {target} {filesystem} {options} 0 0\n'


def parse_fstab(raw, owner):
    text = raw.decode('utf-8')
    lines = text.splitlines(keepends=True)
    markers = [(index, line) for index, line in enumerate(lines)
               if 'OXP3 PARTITION MOUNTS' in line]
    entries = {}
    if not markers:
        return lines, len(lines), len(lines), entries
    if (len(markers) != 2 or markers[0][1] != BEGIN or markers[1][1] != END
            or markers[0][0] >= markers[1][0]):
        raise RuntimeError('The managed fstab block was edited; restore it from backup or review it manually.')
    start, end = markers[0][0], markers[1][0]
    for line in lines[start + 1:end]:
        fields = line.split()
        if len(fields) != 6 or not fields[0].startswith('UUID='):
            raise RuntimeError('Unexpected managed fstab entry; manual review required.')
        uuid = fields[0][5:]
        if uuid in entries or line != row(uuid, fields[2], owner):
            raise RuntimeError('Managed mount options were edited; manual review required.')
        entries[uuid] = fields[2]
    return lines, start, end + 1, entries


def unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def conflict(lines, device):
    """Resolve all common source aliases, including LABEL and PARTUUID."""
    aliases = {device['path'], 'UUID=' + device['uuid'], '/dev/disk/by-uuid/' + device['uuid']}
    for field, prefix in (('partuuid', 'PARTUUID='), ('label', 'LABEL='), ('partlabel', 'PARTLABEL=')):
        if device.get(field): aliases.add(prefix + device[field])
    for field, directory in (('label', 'by-label'), ('partlabel', 'by-partlabel')):
        if device.get(field): aliases.add('/dev/disk/' + directory + '/' + device[field])
    if device.get('partuuid'): aliases.add('/dev/disk/by-partuuid/' + device['partuuid'])
    target = destination(device['uuid'])
    for line in lines:
        fields = line.split()
        if not fields or fields[0].startswith('#'):
            continue
        # dump/pass are optional in ordinary fstab entries. Our own block
        # remains canonical, but unrelated valid entries must be preserved.
        if not 4 <= len(fields) <= 6:
            raise RuntimeError('Malformed existing fstab; review it before making changes.')
        source, path = map(unescape, fields[:2])
        same_device = False
        if source.startswith('/dev/'):
            try:
                info = os.stat(source)
                same_device = stat.S_ISBLK(info.st_mode) and f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' == device.get('maj:min')
            except (OSError, AttributeError):
                pass
        normalized = posixpath.normpath(path)
        if normalized.startswith('/mnt/'):
            normalized = '/var' + normalized
        if same_device or source.casefold() in {alias.casefold() for alias in aliases} or (
                normalized == target or normalized.startswith(target + '/') or
                target.startswith(normalized.rstrip('/') + '/') and normalized not in ('/', '/var', '/var/mnt')):
            raise RuntimeError('This partition or mount path is already configured outside this tool; review /etc/fstab.')


def render(raw, uuid, filesystem, owner, device=None):
    lines, start, end, entries = parse_fstab(raw, owner)
    outside = lines[:start] + lines[end:]
    if filesystem is None:
        if uuid not in entries:
            raise RuntimeError('This tool does not own the selected mount.')
        del entries[uuid]
    else:
        conflict(outside, device)
        entries[uuid] = filesystem
    block = BEGIN + ''.join(row(key, value, owner) for key, value in sorted(entries.items())) + END if entries else ''
    prefix = ''.join(lines[:start])
    if block and prefix and not prefix.endswith('\n'): prefix += '\n'
    return (prefix + block + ''.join(lines[end:])).encode('utf-8')


def all_devices(tree):
    result = []
    def visit(node):
        result.append(node)
        for child in node.get('children', []): visit(child)
    for node in tree['blockdevices']: visit(node)
    return result


def devices(tree):
    return [item for item in all_devices(tree) if item.get('type') == 'part']


def exclusion_reason(device):
    if device.get('type') != 'part' or device.get('children'):
        return 'not_plain_partition'
    if device.get('fstype') not in FILESYSTEMS:
        return 'unsupported_filesystem'
    if not UUID.fullmatch(device.get('uuid') or ''):
        return 'missing_uuid'
    if device.get('ro') not in (False, 0):
        return 'readonly'
    allowed = DATA_TYPES | (FAT_TYPES if device.get('fstype') == 'vfat' else set())
    if (device.get('parttype') or '').lower() not in allowed:
        return 'protected_partition_type'
    if not re.fullmatch(r'[0-9]+:[0-9]+', device.get('maj:min') or ''):
        return 'missing_device_id'
    label = ((device.get('partlabel') or '') + ' ' + (device.get('label') or '')).lower()
    if (re.search(r'(^|[-_ ])(rootfs|root|var|home|efi|esp|reserved|recovery)([-_ ]|$)', label)
            or any(value.lower().startswith('recovery') for value in (device.get('label') or '', device.get('partlabel') or ''))):
        return 'system_label'
    target = destination(device['uuid'])
    if any(path != target and not path.startswith('/run/media/deck/')
           for path in device.get('mountpoints', []) if path):
        return 'mounted_elsewhere'
    return None


def eligible(device):
    return exclusion_reason(device) is None


def owner():
    import pwd
    account = pwd.getpwnam('deck')
    if min(account.pw_uid, account.pw_gid) <= 0:
        raise RuntimeError('Non-root deck account required')
    return account.pw_uid, account.pw_gid


def read_trusted(path):
    path = Path(path)
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
            raise RuntimeError('Untrusted configuration path: ' + str(ancestor))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError('An ordinary single-link configuration file is required')
    with path.open('rb') as stream:
        actual = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
            raise RuntimeError('Configuration changed while reading')
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024: raise RuntimeError('Configuration is too large')
    return data


def scan():
    raw = read_trusted(FSTAB)
    ownership = owner()
    _, _, _, managed = parse_fstab(raw, ownership)
    found = all_devices(json.loads(command('/usr/bin/lsblk', '--json', '--tree', '--bytes', '--paths', '--output',
        'PATH,TYPE,FSTYPE,UUID,LABEL,SIZE,MOUNTPOINTS,PARTTYPE,PARTLABEL,PARTUUID,RO,MAJ:MIN')))
    identities = {}
    for item in found:
        key = (item.get('uuid') or '').casefold()
        identities.setdefault(key, set()).add(item.get('maj:min') or item.get('path'))
    choices, excluded = [], []
    for item in found:
        reason = exclusion_reason(item)
        if reason is None and len(identities[item['uuid'].casefold()]) != 1:
            reason = 'duplicate_uuid'
        if reason is None:
            choices.append(item)
        elif item.get('type') == 'part' or item.get('fstype'):
            excluded.append(dict(item, reason=reason))
    token = hashlib.sha256(raw + json.dumps(found, sort_keys=True).encode()).hexdigest()
    return raw, ownership, managed, choices, token, excluded


def status():
    _, _, managed, choices, token, excluded = scan()
    return {'partitions': choices, 'managed': managed, 'token': token, 'excluded': excluded}


def atomic(path, data, mode=0o644):
    """Caller holds a lock in root-owned /etc; never follow an existing link."""
    path = Path(path)
    if os.path.lexists(path): read_trusted(path)
    fd, name = tempfile.mkstemp(prefix='.oxp3-mount-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, 0)
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def prepare_directory(uuid, mounted=False):
    # /var/mnt may be used through /mnt by other tools. Never follow links here.
    target = Path(destination(uuid))
    for path in reversed((target, *target.parents)):
        if not os.path.lexists(path): path.mkdir(mode=0o755)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (not (path == target and mounted)
                and (info.st_uid != 0 or info.st_mode & 0o022)):
            raise RuntimeError('Untrusted mount directory: ' + str(path))
    return target


def target_mounts(uuid):
    records = []
    for line in Path('/proc/self/mountinfo').read_text(encoding='utf-8', errors='surrogateescape').splitlines():
        fields = line.split()
        separator = fields.index('-')
        if unescape(fields[4]) == destination(uuid):
            records.append({'fstype': fields[separator + 1], 'maj:min': fields[2]})
    return records


def check_units(uuid):
    unit = command('/usr/bin/systemd-escape', '--path', '--suffix=mount', destination(uuid)).strip()
    # Reject aliases, unit files, and drop-ins before saving an entry that would
    # otherwise be silently overridden at boot. Also check runtime overrides.
    if not re.fullmatch(r'[A-Za-z0-9_\\.\-]+\.mount', unit):
        raise RuntimeError('Invalid generated mount unit name')
    for directory in ('/etc/systemd/system', '/run/systemd/system', '/etc/systemd/system.control',
                      '/run/systemd/system.control', '/run/systemd/transient',
                      '/run/systemd/generator.early',
                      '/usr/local/lib/systemd/system', '/usr/lib/systemd/system'):
        for name in (unit, unit[:-6] + '.automount'):
            stem, kind = name.rsplit('.', 1)
            overrides = [name, name + '.d', kind + '.d']
            overrides += [stem[:index + 1] + '.' + kind + '.d'
                          for index, char in enumerate(stem) if char == '-']
            for override in overrides:
                if os.path.lexists(Path(directory) / override):
                    raise RuntimeError('A custom systemd mount unit exists; review it before enabling this partition.')
    return unit


def change(action, uuid, token):
    import fcntl
    if os.geteuid() != 0: raise RuntimeError('Administrator authorization required')
    destination(uuid)
    if not re.fullmatch('[0-9a-f]{64}', token): raise ValueError('Invalid confirmation token')
    # The lock lives in trusted /etc. Other tools' locks are not borrowed.
    read_trusted(FSTAB)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
            raise RuntimeError('Untrusted mount configuration lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw, ownership, managed, choices, current, _ = scan()
        if current != token:
            raise RuntimeError('Partitions or configuration changed. Refresh the list and confirm again.')
        selected = next((item for item in choices if item['uuid'] == uuid), None)
        if action == 'enable':
            if selected is None: raise RuntimeError('Partition is unavailable, protected, or has a duplicate UUID.')
            new = render(raw, uuid, FILESYSTEMS[selected['fstype']], ownership, selected)
            unit = check_units(uuid)
            mounts = target_mounts(uuid)
            real = [item for item in mounts if item['fstype'] != 'autofs']
            if any(item['maj:min'] != selected['maj:min'] or item['fstype'] != FILESYSTEMS[selected['fstype']] for item in real):
                raise RuntimeError('The mount directory is occupied by another filesystem.')
            mounted_here = bool(real)
            path = prepare_directory(uuid, mounted_here)
            if not mounts:
                if any(path.iterdir()): raise RuntimeError('Mount directory is not empty; refusing to hide existing files.')
        elif action == 'disable':
            new = render(raw, uuid, None, ownership)
        else:
            raise ValueError('Unsupported operation')
        if new != raw:
            atomic(BACKUP, raw, 0o600)
            if read_trusted(FSTAB) != raw:
                raise RuntimeError('fstab changed concurrently. Refresh before retrying.')
            mode = stat.S_IMODE(FSTAB.stat().st_mode)
            atomic(FSTAB, new, mode)
        warning = ''
        try:
            command('/usr/bin/systemctl', 'daemon-reload')
        except Exception as error:
            warning = str(error)
        # Saving and activation are separate outcomes, including mount failures.
        mounted = False
        if action == 'enable' and not warning:
            elsewhere = [p for p in selected.get('mountpoints', []) if p and p != destination(uuid)]
            if elsewhere:
                warning = 'Already mounted by KDE. Saved for next restart; unmount in Dolphin before using the new path.'
            else:
                try:
                    # Do not let an existing custom systemd unit override fstab.
                    fragment = command('/usr/bin/systemctl', 'show', '--property=FragmentPath', '--value', unit).strip()
                    dropins = command('/usr/bin/systemctl', 'show', '--property=DropInPaths', '--value', unit).strip()
                    if fragment != '/run/systemd/generator/' + unit or dropins:
                        raise RuntimeError('The mount has a custom or missing systemd unit. Saved; activation requires review.')
                    command('/usr/bin/systemctl', 'start', unit)
                    actual = json.loads(command('/usr/bin/findmnt', '--json', '--real', '--list', '--mountpoint', destination(uuid),
                                                '--output', 'UUID,FSTYPE,TARGET,MAJ:MIN'))['filesystems']
                    if (len(actual) != 1 or actual[0].get('uuid') != uuid
                            or actual[0].get('fstype') != FILESYSTEMS[selected['fstype']]
                            or actual[0].get('target') != destination(uuid)
                            or actual[0].get('maj:min') != selected['maj:min']):
                        raise RuntimeError('Mount verification did not match the selected UUID, filesystem and path.')
                    mounted = True
                except Exception as error:
                    warning = str(error)
        return {'saved': True, 'mounted': mounted, 'path': destination(uuid), 'warning': warning,
                'action': action, 'restart_required': action == 'disable' or not mounted}
    finally:
        os.close(fd)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if args == ['status']:
            data = status()
        elif len(args) == 3 and args[0] in ('enable', 'disable'):
            data = change(*args)
        else:
            raise ValueError('Usage: status | enable UUID TOKEN | disable UUID TOKEN')
        print(json.dumps({'ok': True, 'data': data}))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
