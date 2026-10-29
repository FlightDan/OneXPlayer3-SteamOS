#!/usr/bin/python3 -I
"""Order canonical OXP3 NTFS mounts after preflight, including existing v1 rows.

Runs before /home is mounted. Never imports code from /home or edits fstab.
"""
import os
from pathlib import Path
import re
import stat
import sys

BEGIN = '# BEGIN OXP3 PARTITION MOUNTS v1\n'
END = '# END OXP3 PARTITION MOUNTS v1\n'
BASE = '/var/mnt/oxp3-volumes/'
UUID = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z')
OPTIONS = re.compile(
    r'rw,exec,nosuid,nodev,nofail,x-systemd\.automount,'
    r'x-systemd\.device-timeout=5s,x-systemd\.mount-timeout=15s,'
    r'uid=([1-9][0-9]*),gid=([1-9][0-9]*),fmask=0022,dmask=0022,windows_names\Z')


def managed_ntfs(raw):
    lines = raw.decode('utf-8').splitlines(keepends=True)
    markers = [(i, line) for i, line in enumerate(lines) if 'OXP3 PARTITION MOUNTS' in line]
    if not markers:
        return {}
    if (len(markers) != 2 or markers[0][1] != BEGIN or markers[1][1] != END
            or markers[0][0] >= markers[1][0]):
        raise ValueError('Edited OXP3 partition mount block')
    result = {}
    seen = set()
    for line in lines[markers[0][0] + 1:markers[1][0]]:
        fields = line.split()
        if len(fields) != 6 or not fields[0].startswith('UUID='):
            raise ValueError('Invalid managed partition entry')
        uuid = fields[0][5:]
        if not UUID.fullmatch(uuid) or uuid in seen:
            raise ValueError('Invalid or duplicate managed UUID')
        seen.add(uuid)
        if fields[2] != 'ntfs3':
            continue
        match = OPTIONS.fullmatch(fields[3])
        expected = f'UUID={uuid} {BASE}{uuid} ntfs3 {fields[3]} 0 0\n'
        if not match or line != expected:
            raise ValueError('Edited managed NTFS options')
        result[uuid] = {'uid': int(match[1]), 'gid': int(match[2])}
    return result


def escaped_uuid(uuid):
    if not UUID.fullmatch(uuid):
        raise ValueError('Invalid filesystem UUID')
    return uuid.replace('-', r'\x2d')


def service_unit(uuid):
    return 'oxp3-ntfs-preflight@' + escaped_uuid(uuid) + '.service'


def mount_unit(uuid):
    return r'var-mnt-oxp3\x2dvolumes-' + escaped_uuid(uuid) + '.mount'


def dropin(uuid):
    unit = service_unit(uuid)
    return f'[Unit]\nRequires={unit}\nAfter={unit}\n'.encode()


def trusted_fstab(path=Path('/etc/fstab')):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Untrusted fstab')
        raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RuntimeError('fstab exceeds limit')
        return raw


def generate(output, raw):
    entries = managed_ntfs(raw)  # Validate the whole block before emitting anything.
    for uuid in entries:
        directory = Path(output) / (mount_unit(uuid) + '.d')
        directory.mkdir(mode=0o755, exist_ok=True)
        if directory.is_symlink():
            raise RuntimeError('Unsafe generator directory')
        path = directory / '50-oxp3-ntfs-preflight.conf'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(dropin(uuid))
    return entries


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4:
            raise ValueError('Expected systemd generator output directories')
        generate(sys.argv[1], trusted_fstab())
    except Exception as error:
        print('OXP3 NTFS preflight generator: ' + str(error), file=sys.stderr)
        sys.exit(1)
