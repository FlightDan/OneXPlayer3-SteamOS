"""Grow only the last ext4 home partition in a session-owned raw staging image."""
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

MIB = 1024 ** 2
ROLES = ['esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home']


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def superblock(node):
    with open(node, 'rb') as filesystem:
        filesystem.seek(1024)
        value = filesystem.read(1024)
    if len(value) != 1024 or value[56:58] != b'\x53\xef' or not int.from_bytes(value[96:100], 'little') & 0x40:
        raise RuntimeError('Expected ext4 home filesystem')
    return value


def planned_home(table, selection, disk_size):
    parts = table['partitions']
    if table['label'] != 'gpt' or table['sectorsize'] != 512 or table['id'].lower() != selection['disk_id'].lower():
        raise RuntimeError('Prepared GPT identity changed')
    actual = [dict(number=int(p['node'].removeprefix('/dev/vdc')), name=p.get('name', ''),
                   start=p['start'], size=p['size'], uuid=p['uuid'].lower(), type=p['type'].lower()) for p in parts]
    if actual != selection['partitions'] or [p.get('name') for p in parts[-8:]] != ROLES:
        raise RuntimeError('Prepared partitions differ from the reviewed source')
    capacity = selection['capacity']
    if type(capacity) is not int or capacity < 64 * 1024 ** 3 or capacity % MIB:
        raise RuntimeError('Invalid selected capacity')
    home = parts[-1]
    end = parts[-8]['start'] * 512 + capacity
    if end < (home['start'] + home['size']) * 512 or end > disk_size - MIB:
        raise RuntimeError('Home expansion would shrink or exceed the staging image')
    return (end // 512) - home['start']


def expand(selection):
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
        raise RuntimeError('Managed VM required')
    if Path('/sys/class/block/vdc/ro').read_text().strip() != '0':
        raise RuntimeError('Writable staging image required')
    before = json.loads(run('sfdisk', '--json', '/dev/vdc'))['partitiontable']
    size = int(Path('/sys/class/block/vdc/size').read_text()) * 512
    sectors = planned_home(before, selection, size)
    home = before['partitions'][-1]
    node = home['node']
    uuid = superblock(node)[104:120]
    # Dump retains every partition ID, type, attribute and label. Only home size changes.
    dump = run('sfdisk', '--dump', '/dev/vdc')
    lines = []
    for line in dump.splitlines():
        if line.startswith('last-lba:'):
            continue
        if line.startswith(node + ' '):
            line, count = re.subn(r'\bsize=\s*\d+', 'size= ' + str(sectors), line)
            if count != 1:
                raise RuntimeError('Ambiguous home partition entry')
        lines.append(line)
    run('sfdisk', '/dev/vdc', input='\n'.join(lines) + '\n')
    after = json.loads(run('sfdisk', '--json', '/dev/vdc'))['partitiontable']
    expected = [dict(p) for p in before['partitions']]
    expected[-1]['size'] = sectors
    if after['id'] != before['id'] or after['partitions'] != expected:
        raise RuntimeError('Unexpected partition change during expansion')
    # mdev handles GPT reread events asynchronously and may remove /dev/vdcN
    # between fsck and resize2fs. Bind our own node to the verified kernel device.
    sysfs = Path('/sys/class/block') / Path(node).name
    deadline = time.monotonic() + 15
    while True:
        try:
            if int((sysfs / 'size').read_text()) == sectors:
                major, minor = map(int, (sysfs / 'dev').read_text().split(':'))
                break
        except FileNotFoundError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Kernel did not refresh the expanded home partition')
        time.sleep(0.1)
    node = '/tmp/oxp-capacity-home'
    os.mknod(node, stat.S_IFBLK | 0o600, os.makedev(major, minor))
    check = subprocess.run(['e2fsck', '-pf', node], check=False)
    if check.returncode not in (0, 1):
        raise RuntimeError('Home filesystem check failed')
    run('resize2fs', node)
    metadata = superblock(node)
    blocks = int.from_bytes(metadata[4:8], 'little')
    if int.from_bytes(metadata[96:100], 'little') & 0x80:
        blocks += int.from_bytes(metadata[336:340], 'little') << 32
    block_size = 1024 << int.from_bytes(metadata[24:28], 'little')
    if blocks * block_size != sectors * 512 or metadata[104:120] != uuid:
        raise RuntimeError('Expanded filesystem size or UUID differs')
    print('OXP_CAPACITY_VERIFIED=' + str(selection['capacity']), flush=True)


if __name__ == '__main__':
    expand(json.loads(Path('/mnt/payload/selection.json').read_text()))
