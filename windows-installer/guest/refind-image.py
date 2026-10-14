"""Stage or test rEFInd only on the ordinary image supplied by the managed VM."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,'/mnt/payload/refind')
import manage

def run(*args): return subprocess.check_output(args,text=True).strip()
if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU': raise RuntimeError('Managed VM required')
if run('blockdev','--getro','/dev/vdc') != '0': raise RuntimeError('Independent output image must be writable')
table=json.loads(run('sfdisk','--json','/dev/vdc'))['partitiontable']
parts={p.get('name'):p for p in table['partitions']}
if not {'esp','efi-A','efi-B','rootfs-A','rootfs-B','var-A','var-B','home'}.issubset(parts): raise RuntimeError('Expected prepared SteamOS layout')
choice=json.loads(Path('/mnt/payload/selection.json').read_text())
root=Path('/mnt/refind-esp'); root.mkdir(exist_ok=True)
run('mount','-t','vfat',parts['esp']['node'],str(root))
try:
    action=choice.get('action','install')
    if action == 'install': result=manage.install(root,'/mnt/payload/refind',choice['default_system'],choice['timeout'],parts['esp']['uuid'],choice.get('windows_esp'))
    elif action == 'verify': result=manage.verify(root)
    elif action == 'uninstall': result=manage.uninstall(root)
    elif action == 'resume': result=manage.resume(root)
    elif action == 'lifecycle':
        import test_refind
        result=test_refind.run(root,Path('/mnt/payload/refind'),parts['esp']['uuid'])
    elif action == 'windows-probe':
        # Only the disposable installer fixture may receive an EFI probe.
        fixture=parts.get('Windows EFI fixture')
        if not fixture or 'Windows data fixture' not in parts: raise RuntimeError('Not the Windows test fixture')
        probe=Path('/mnt/windows-probe'); probe.mkdir(exist_ok=True)
        run('mount','-t','vfat',fixture['node'],str(probe))
        try:
            folder=probe/'EFI/Microsoft/Boot'; folder.mkdir(parents=True,exist_ok=True)
            (folder/'bootmgfw.efi').write_bytes(Path('/mnt/payload/refind/refind_x64.efi').read_bytes())
            (folder/'refind.conf').write_text('textonly\ntimeout 0\nscanfor manual\nshowtools shutdown\nmenuentry "PROBE_WINDOWS" {\n loader /EFI/Microsoft/Boot/bootmgfw.efi\n}\n')
        finally: run('sync'); run('umount',str(probe))
        result=manage.install(root,'/mnt/payload/refind','Windows',3,parts['esp']['uuid'],fixture['uuid'])
    else: raise ValueError('Unknown rEFInd action')
    print('OXP_REFIND_RESULT='+json.dumps(result if action=='lifecycle' else {k:result[k] for k in ('phase','version','esp','windows','default','timeout')}),flush=True)
finally:
    run('sync'); run('umount',str(root))
