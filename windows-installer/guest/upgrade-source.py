"""Compose a recovery disk from the fixed official root image, in an isolated VM."""
import json
import subprocess
from pathlib import Path

def run(*args): return subprocess.check_output(args,text=True).strip()
if Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU': raise RuntimeError('Managed VM required')
if Path('/sys/class/block/vdd/ro').read_text().strip()!='1': raise RuntimeError('Update must be read-only')
table=json.loads(run('sfdisk','--json','/dev/vdc'))['partitiontable']
if [p.get('name') for p in table['partitions']]!=['esp','efi-A','rootfs-A','var-A','home']: raise RuntimeError('Unexpected recovery layout')
part=table['partitions'][2]
if part['size']*512<int(run('blockdev','--getsize64','/dev/vdd')): raise RuntimeError('Root update does not fit')
root=Path('/mnt/update-root');root.mkdir(exist_ok=True)
run('mount','-t','btrfs','-o','ro,rescue=nologreplay','/dev/vdd',str(root))
try:
    release=dict(line.split('=',1) for line in (root/'etc/os-release').read_text().splitlines() if '=' in line)
    release={k:v.strip('"') for k,v in release.items()}
    if release.get('VERSION_ID') not in ('3.10','3.10.0') or release.get('BUILD_ID')!='20260924.1000': raise RuntimeError('Unexpected official root version')
    if not (root/'usr/lib/modules/7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9').is_dir(): raise RuntimeError('Unexpected kernel')
    print('OXP_UPDATE_SOURCE='+json.dumps(release),flush=True)
finally:run('umount',str(root))
run('dd','if=/dev/vdd','of='+part['node'],'bs=4M','conv=fsync')
run('mount','-t','btrfs','-o','ro,rescue=nologreplay',part['node'],str(root))
try:
    if '20260924.1000' not in (root/'etc/os-release').read_text(): raise RuntimeError('Written root version differs')
    print('OXP_UPDATE_ROOT=3.10:20260924.1000',flush=True)
finally:run('umount',str(root))
