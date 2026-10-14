import json
import os
import subprocess
from pathlib import Path

def run(*args):
    return subprocess.check_output(args, text=True).strip()

if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
    raise RuntimeError('Managed VM required')
if Path('/sys/class/block/vdc/ro').read_text().strip() != '1':
    raise RuntimeError('Read-only source required')
parts = json.loads(run('sfdisk', '--json', '/dev/vdc'))['partitiontable']['partitions']
mountpoint = Path('/mnt/capacity-check')
mountpoint.mkdir(exist_ok=True)
for part in parts:
    name = part.get('name', '')
    if name not in ('esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home'):
        continue
    opts = 'ro,rescue=nologreplay' if name.startswith('rootfs-') else 'ro,noload' if name in ('var-A', 'var-B', 'home') else 'ro'
    run('mount', '-o', opts, part['node'], str(mountpoint))
    try:
        usage = os.statvfs(mountpoint)
        row = dict(name=name, partition_bytes=part['size'] * 512,
                   filesystem_bytes=usage.f_blocks * usage.f_frsize,
                   used_bytes=(usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                   available_bytes=usage.f_bavail * usage.f_frsize,
                   du=run('du', '-sk', str(mountpoint)))
        if name.startswith('rootfs-'):
            row['btrfs_usage'] = run('btrfs', 'filesystem', 'usage', '-b', str(mountpoint))
        print('OXP_CAPACITY=' + json.dumps(row), flush=True)
    finally:
        run('umount', str(mountpoint))
