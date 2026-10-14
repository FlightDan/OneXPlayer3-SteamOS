"""Inspect actual source contents before the Windows helper opens a target for writes."""
import json
import subprocess
from pathlib import Path

def run(*args):return subprocess.check_output(args,text=True).strip()
if Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU':raise RuntimeError('Managed VM required')
if Path('/sys/class/block/vdc/ro').read_text().strip()!='1':raise RuntimeError('Source must be read-only')
table=json.loads(run('sfdisk','--json','/dev/vdc'))['partitiontable']
nodes={p.get('name'):p['node'] for p in table['partitions']}
root=Path('/mnt/readiness');root.mkdir(exist_ok=True)
for slot in ('A','B'):
    run('mount','-t','btrfs','-o','ro,rescue=nologreplay',nodes['rootfs-'+slot],str(root))
    try:
        release=dict(line.split('=',1) for line in (root/'etc/os-release').read_text().splitlines() if '=' in line)
        release={k:v.strip('"') for k,v in release.items()}
        if release.get('VERSION_ID')!='3.10' or release.get('BUILD_ID')!='20260924.1000':raise RuntimeError('Physical installation requires accepted SteamOS 3.10 build20260924.1000')
        if not (root/'usr/lib/modules/7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9').is_dir():raise RuntimeError('Kernel does not match device drivers')
        if run('btrfs','property','get','-ts',str(root),'ro')!='ro=true':raise RuntimeError('Root is not protected')
        print('OXP_PHYSICAL_SOURCE='+slot+':3.10:20260924.1000',flush=True)
    finally:run('umount',str(root))
run('mount','-t','vfat','-o','ro',nodes['esp'],str(root))
try:
    if not (root/'EFI/BOOT/BOOTX64.EFI').is_file():raise RuntimeError('Missing removable UEFI loader')
finally:run('umount',str(root))
