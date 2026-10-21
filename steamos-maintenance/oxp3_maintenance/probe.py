"""Read-only identity checks. Filesystem labels are never slot authority."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .compatibility import BASE, KERNEL, baseline_supported, device_supported


class ProbeError(RuntimeError):
    pass


def run(*args):
    result = subprocess.run(args, check=True, capture_output=True, text=True,
                            timeout=30, env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C', 'LANG': 'C.UTF-8'})
    return result.stdout.strip()


def os_release(root):
    return _release_values(Path(root) / 'etc/os-release')


def _release_values(path):
    output = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            output[key] = value.strip().strip('"').strip("'")
    return output


def _inactive_os_release(root):
    """Prefer the image's real /etc metadata without following overlay links.

    SteamOS may ship generic /usr/lib/os-release while keeping the image build
    in its regular /etc/os-release. A linked /etc must never resolve against the
    running machine; only independently safe /usr metadata can be a fallback.
    """
    for relative in ('etc/os-release', 'usr/lib/os-release'):
        try:
            path = _checked_path(root, relative)
        except ProbeError:
            continue
        if path.is_file() and path.stat().st_size <= 64 * 1024:
            return _release_values(path)
    raise ProbeError('No safe inactive SteamOS release metadata')


def packages(root):
    root = Path(root)
    database = _checked_path(root, 'usr/lib/holo/pacmandb/local')
    if not database.is_dir():
        database = _checked_path(root, 'var/lib/pacman/local')
    found = {}
    if not database.is_dir():
        return found
    for directory in database.iterdir():
        if directory.is_symlink():
            raise ProbeError('Unsafe package database directory')
        if not directory.is_dir():
            continue
        path = _checked_path(root, directory.relative_to(root).as_posix() + '/desc')
        if not path.exists():
            continue
        if not path.is_file():
            raise ProbeError('Unsafe package database record')
        lines = path.read_text().splitlines()
        try:
            name = lines[lines.index('%NAME%') + 1]
            version = lines[lines.index('%VERSION%') + 1]
        except (ValueError, IndexError):
            continue
        if name in found:
            raise ProbeError('Ambiguous package database: ' + name)
        found[name] = version
    return found


def _checked_path(root, relative):
    """Never resolve image metadata through links into the running system."""
    current = Path(root)
    def linked(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
    if linked(current):
        raise ProbeError('Unsafe image metadata root')
    for part in relative.split('/'):
        current /= part
        if linked(current):
            raise ProbeError('Unsafe image metadata symlink: ' + relative)
    return current


def _canonical_block(source):
    if (not isinstance(source, str) or not source.startswith('/dev/')
            or not re.fullmatch(r'/dev/[A-Za-z0-9_./+-]+', source)
            or any(part in ('', '.', '..') for part in source.split('/')[1:])):
        raise ProbeError('Unsupported block source; a plain /dev device is required')
    canonical = os.path.realpath(source)
    if not canonical.startswith('/dev/'):
        raise ProbeError('Root block source resolves outside /dev')
    info = os.stat(canonical)
    if not stat.S_ISBLK(info.st_mode):
        raise ProbeError('Root source is not a block device')
    return {'path': canonical, 'maj:min': str(os.major(info.st_rdev)) + ':' + str(os.minor(info.st_rdev))}


def _single_btrfs_device(filesystem_uuid, device, *, sysfs=Path('/sys/fs/btrfs')):
    """Bind a mounted Btrfs UUID to its one kernel-reported physical device."""
    if not isinstance(filesystem_uuid, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', filesystem_uuid):
        raise ProbeError('Cannot verify the mounted Btrfs filesystem UUID')
    filesystem = Path(sysfs) / filesystem_uuid.lower()
    devices = list((filesystem / 'devices').iterdir())
    if len(devices) != 1 or (devices[0] / 'dev').read_text().strip() != device['maj:min']:
        raise ProbeError('Only a verified single-device Btrfs root is supported')
    # devinfo includes missing members on kernels exposing it. Reject degraded
    # multi-device filesystems even when only one physical member is present.
    if (filesystem / 'devinfo').is_dir():
        members = list((filesystem / 'devinfo').iterdir())
        if len(members) != 1 or ((members[0] / 'missing').exists() and (members[0] / 'missing').read_text().strip() != '0'):
            raise ProbeError('Missing or additional Btrfs devices are unsupported')
    return device


def _btrfs_superblock(device, command):
    """Read the primary superblock before an inactive filesystem is mounted."""
    raw = command('btrfs', 'inspect-internal', 'dump-super', device)
    counts = re.findall(r'^num_devices\s+(\d+)\s*$', raw, re.MULTILINE)
    uuids = re.findall(r'^fsid\s+([0-9a-fA-F-]{36})\s*$', raw, re.MULTILINE)
    if counts != ['1'] or len(uuids) != 1:
        raise ProbeError('Inactive Btrfs root must have exactly one device; verify btrfs dump-super support')
    return uuids[0]


def identify_root(mount, devices, marker=None, *, verified_device=None):
    """Bind to major:minor + PARTUUID. A/B is a display label only."""
    if mount.get('fstype') == 'btrfs' and verified_device is None:
        raise ProbeError('Btrfs root requires independently verified physical source identity')
    identity = verified_device or {'maj:min': mount.get('maj:min')}
    candidates = []
    def visit(nodes, parents=()):
        for node in nodes:
            if (node.get('maj:min') == identity.get('maj:min')
                    and (verified_device is None or node.get('path') == identity.get('path'))):
                candidates.append((node, parents))
            visit(node.get('children', []), (*parents, node))
    visit(devices)
    # lsblk can repeat a block device under multiple dependency trees.
    unique = {entry[0].get('partuuid'): entry for entry in candidates
              if entry[0].get('partuuid')}
    if len(unique) != 1:
        raise ProbeError('Cannot uniquely identify the mounted SteamOS root partition')
    partuuid, (node, parents) = next(iter(unique.items()))
    if not re.fullmatch(r'[a-zA-Z0-9-]{8,64}', partuuid):
        raise ProbeError('Invalid root PARTUUID')
    disks = [p for p in parents if p.get('type') == 'disk']
    if len(disks) != 1 or node.get('type') != 'part' or len(parents) != 1:
        raise ProbeError('Unsupported root topology; expected one GPT disk partition')
    slot = {'rootfs-A': 'A', 'rootfs-B': 'B'}.get(node.get('partlabel'))
    if marker is not None and marker != slot:
        raise ProbeError('Installer slot marker disagrees with the mounted partition')
    disk = disks[0]
    return {'id': 'partuuid-' + partuuid.lower(), 'label': slot,
            'fstype': mount.get('fstype'),
            'partuuid': partuuid, 'disk': disk.get('path'),
            'device': node.get('path'),
            'target_disk': {'bus': 'NVMe' if disk.get('tran') == 'nvme' else disk.get('tran'),
                            'model': (disk.get('model') or '').strip()},
            'other_slots': [n for n in disk.get('children', [])
                            if n.get('partlabel') in ('rootfs-A', 'rootfs-B')
                            and n.get('partuuid') != partuuid]}


def inspect(root, *, kernel, dmi, bios, topology):
    root = Path(root)
    users = [line.split(':') for line in (root / 'etc/passwd').read_text().splitlines()
             if line.startswith('deck:')]
    if len(users) != 1 or len(users[0]) != 7 or users[0][5] != '/home/deck':
        raise ProbeError('Expected the non-root deck desktop account at /home/deck')
    uid, gid = int(users[0][2]), int(users[0][3])
    if min(uid, gid) <= 0:
        raise ProbeError('The desktop account must not be root')
    system = os_release(root)
    facts = {'os': system, 'kernel': kernel, 'dmi': dmi}
    compatible = baseline_supported(facts)
    return {'os': system, 'kernel': kernel, 'dmi': dmi, 'bios': bios,
            'packages': packages(root), 'uid': uid, 'gid': gid,
            'slot': topology, 'target_disk': topology['target_disk'],
            'compatible': compatible,
            'baseline_supported': compatible, 'device_supported': device_supported(facts),
            # No inactive root is mounted implicitly. The privileged operation
            # may prove an identical installer source for shared payloads.
            'shared_compatible': not topology.get('other_slots'),
            'shared_os_compatible': not topology.get('other_slots'),
            'project_updates_only': True}


def _dmi_value(name):
    # Identity is diagnostic only; absent DMI must not block SteamOS devices.
    try:
        return Path('/sys/class/dmi/id', name).read_text().strip()
    except OSError:
        return ''


def live(command=run):
    if os.name != 'posix':
        raise ProbeError('Run this tool in SteamOS Desktop Mode')
    mounts = json.loads(command('findmnt', '--json', '--target', '/', '--output',
                                'TARGET,SOURCE,MAJ:MIN,FSTYPE,UUID'))['filesystems']
    if len(mounts) != 1 or mounts[0].get('target') != '/':
        raise ProbeError('Cannot identify the active root mount')
    devices = json.loads(command('lsblk', '--json', '--tree', '--paths', '--output',
                                'PATH,TYPE,MAJ:MIN,PARTUUID,PARTLABEL,TRAN,MODEL'))['blockdevices']
    verified = None
    if mounts[0].get('fstype') == 'btrfs':
        verified = _single_btrfs_device(mounts[0].get('uuid'), _canonical_block(mounts[0].get('source')))
    marker = Path('/usr/local/lib/oxp3-integration/slot')
    saved = None
    if marker.exists():
        info = marker.lstat()
        if marker.is_symlink() or info.st_uid or info.st_mode & 0o022:
            raise ProbeError('Untrusted installer slot marker')
        saved = marker.read_text().strip()
    topology = identify_root(mounts[0], devices, saved, verified_device=verified)
    result = inspect('/', kernel=os.uname().release,
                     dmi={name: _dmi_value(name) for name in ('sys_vendor', 'product_name')},
                     bios=_dmi_value('bios_version'),
                     topology=topology)
    home = json.loads(command('findmnt', '--json', '--target', '/home', '--output',
                              'TARGET,SOURCE,OPTIONS'))['filesystems']
    if len(home) != 1 or home[0]['target'] != '/home':
        raise ProbeError('A separately mounted shared /home is required')
    if Path('/home').stat().st_uid or Path('/home').stat().st_mode & 0o022:
        raise ProbeError('The shared /home mount must be root owned and not user writable')
    return result


def _verify_shared(probe, command, *, portable):
    """Read inactive ext4/Btrfs metadata without replaying filesystem logs."""
    others = probe['slot'].get('other_slots', [])
    if not others:
        return True
    if os.geteuid() != 0:
        return False
    for partition in others:
        identifier = partition.get('partuuid', '')
        if not re.fullmatch(r'[a-zA-Z0-9-]{8,64}', identifier):
            return False
        device = '/dev/disk/by-partuuid/' + identifier
        filesystem = command('blkid', '-s', 'TYPE', '-o', 'value', device)
        if filesystem not in ('ext4', 'btrfs'):
            return False
        btrfs_device, filesystem_uuid = None, None
        if filesystem == 'btrfs':
            try:
                btrfs_device = _canonical_block(device)
                filesystem_uuid = _btrfs_superblock(device, command)
            except (ProbeError, OSError, subprocess.SubprocessError):
                return False
        with tempfile.TemporaryDirectory(prefix='oxp3-readonly-') as temporary:
            mounted = False
            try:
                options = 'ro,noload,nodev,nosuid,noexec' if filesystem == 'ext4' else 'ro,rescue=nologreplay,nodev,nosuid,noexec,subvolid=5'
                command('mount', '-t', filesystem, '-o', options, device, temporary)
                mounted = True
                if filesystem == 'btrfs':
                    _single_btrfs_device(filesystem_uuid, btrfs_device)
                root = Path(temporary)
                values = _inactive_os_release(root)
                expected = {'ID': 'steamos'} if portable else BASE
                if any(values.get(k) != v for k, v in expected.items()):
                    return False
                if portable:
                    continue
                if not _checked_path(root, 'usr/lib/modules/' + KERNEL).is_dir():
                    return False
                other = packages(root)
                slot_only = set(probe.get('verified_slot_only_packages', []))
                if any(other.get(k) != v for k, v in probe['packages'].items() if k not in slot_only):
                    return False
            except (ProbeError, OSError, subprocess.SubprocessError):
                return False
            finally:
                if mounted:
                    command('umount', temporary)
    return True


def verify_shared(probe, command=run):
    """Prove inactive slots share the exact reviewed repair baseline."""
    return _verify_shared(probe, command, portable=False)


def verify_shared_os(probe, command=run):
    """Prove inactive slots are SteamOS for reviewed portable settings only.

    This does not certify native binaries, drivers, packages or hardware fixes.
    Every inactive mount is read-only with ext4/Btrfs log replay disabled.
    """
    return _verify_shared(probe, command, portable=True)
