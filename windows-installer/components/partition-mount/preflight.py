"""Bounded repair of explicitly selected, dirty, unmounted, non-hibernated NTFS.

The read-only native checker is the sole source of repair eligibility. Unknown
metadata errors never become a dirty indication. No forced mounts are used.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

HOME = Path('/home/.oxp3-partition-mount')
GENERATOR = Path('/etc/systemd/system-generators/oxp3-ntfs-preflight')
FSTAB = Path('/etc/fstab')
LOCKS = Path('/run/lock')
UUID = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z')
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}


def trusted(path, executable=False):
    for part in (path, *path.parents):
        info = part.lstat()
        if (info.st_uid != 0 or info.st_mode & 0o022 or
                not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
            raise RuntimeError('Untrusted NTFS preflight path: ' + str(part))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or executable and not info.st_mode & 0o111:
        raise RuntimeError('Missing NTFS preflight executable: ' + str(path))


def policy():
    trusted(GENERATOR)
    loader = importlib.machinery.SourceFileLoader('oxp3_ntfs_policy', str(GENERATOR))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def runtime():
    path = HOME / 'tools/manifest.json'
    trusted(path)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if (manifest.get('schema') != 1 or manifest.get('architecture') != 'x86_64'
            or manifest.get('static') is not True):
        raise RuntimeError('Invalid NTFS tools manifest')
    for name in ('ntfs_status', 'ntfsfix'):
        binary = HOME / 'tools' / name
        trusted(binary, executable=True)
        data = binary.read_bytes()
        pin = manifest['files'][name]
        if len(data) != pin['size'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
            raise RuntimeError('NTFS tool integrity mismatch: ' + name)
    return HOME / 'tools/ntfs_status', HOME / 'tools/ntfsfix'


def run(args, timeout=15):
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=timeout, env=ENV)


def identity(uuid):
    device = Path('/dev/disk/by-uuid') / uuid
    info = device.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise RuntimeError('Selected UUID is not a block device')
    result = run(['/usr/bin/blkid', '-p', '-o', 'export', str(device)])
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or values.get('UUID') != uuid or values.get('TYPE') != 'ntfs':
        raise RuntimeError('Selected NTFS identity changed')
    return device, info.st_rdev


def unmounted(number):
    expected = f'{os.major(number)}:{os.minor(number)}'
    # system service runs in the host mount namespace; the native checker and
    # ntfsfix also refuse mounted volumes. Do not access the automount directory.
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        if line.split()[2] == expected:
            raise RuntimeError('Selected NTFS volume is already mounted')


def state(checker, device):
    result = run([str(checker), str(device)])
    try:
        value = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError('NTFS read-only check returned invalid output') from error
    if (result.returncode or value.get('schema') != 1 or
            value.get('status') not in ('clean', 'dirty', 'hibernated')):
        raise RuntimeError('NTFS state is unknown: ' + str(value.get('error') or 'check failed'))
    if value['status'] == 'hibernated':
        raise RuntimeError('NTFS is hibernated; resume Windows and fully shut it down')
    return value['status']


def preflight(uuid):
    import fcntl
    if os.geteuid() != 0:
        raise RuntimeError('NTFS preflight requires root')
    if not UUID.fullmatch(uuid):
        raise ValueError('Invalid filesystem UUID')
    selected = policy()
    if uuid not in selected.managed_ntfs(selected.trusted_fstab(FSTAB)):
        raise RuntimeError('NTFS UUID is not selected in the managed fstab block')
    trusted(HOME / 'preflight.py')
    checker, repair = runtime()
    descriptor = os.open(LOCKS / ('oxp3-ntfs-' + uuid + '.lock'),
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                info.st_mode & 0o077 or info.st_nlink != 1):
            raise RuntimeError('Untrusted NTFS preflight lock')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        device, number = identity(uuid)
        unmounted(number)
        before = state(checker, device)
        if before == 'clean':
            return {'schema': 1, 'uuid': uuid, 'status': 'clean', 'repaired': False}
        # Recheck selection and device immediately before the one permitted write.
        if uuid not in selected.managed_ntfs(selected.trusted_fstab(FSTAB)):
            raise RuntimeError('NTFS selection changed before repair')
        if identity(uuid)[1] != number:
            raise RuntimeError('NTFS block device changed before repair')
        unmounted(number)
        result = run([str(repair), '--clear-dirty', str(device)], timeout=90)
        if result.returncode:
            raise RuntimeError('NTFS limited repair failed: ' + result.stderr[-1500:])
        unmounted(number)
        result = run([str(repair), '--no-action', str(device)], timeout=25)
        if result.returncode or identity(uuid)[1] != number or state(checker, device) != 'clean':
            raise RuntimeError('NTFS repair verification failed; use Windows chkdsk')
        return {'schema': 1, 'uuid': uuid, 'status': 'clean', 'repaired': True}
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Expected one selected filesystem UUID')
        print(json.dumps(preflight(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'schema': 1, 'status': 'blocked', 'error': str(error)}))
        sys.exit(1)
