"""First-boot activation. All device writes stay behind live version/model guards."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from integration import VERSION,KERNEL,release,restore,trusted_tree
from file_transaction import atomic_write,snapshot

def run(*args): return subprocess.run(args,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45).stdout

def current_slot():
    # Copied root filesystems can retain the source label in both slots. The
    # offline installer publishes an immutable slot marker in each system root.
    saved=snapshot(Path(__file__).parent/'slot')
    if not saved['exists'] or saved['uid']!=0 or saved['mode']&0o022: raise RuntimeError('Untrusted root slot marker')
    slot=base64.b64decode(saved['data']).decode().strip()
    if slot not in ('A','B'): raise RuntimeError('Unknown root slot')
    return slot

def device_guard():
    if any(release('/').get(k)!=v for k,v in VERSION.items()) or os.uname().release!=KERNEL: raise RuntimeError('Live system/kernel is not the accepted target')
    for name,value in [('sys_vendor','ONE-NETBOOK'),('product_name','ONEXPLAYER 3')]:
        if Path('/sys/class/dmi/id/'+name).read_text().strip()!=value: raise RuntimeError('Exact ONEXPLAYER 3 required')

def restore_live(component, slot):
    units={'decky':['plugin_loader.service'],'native-tdp':['oxp3-rapl.service'],'fan-driver':['oxp3-fan-module.service'],'oxp3-fan':['oxp3-fan.service','oxp3-fan-sleep.service'],'oxp3-cpu':['oxp3-cpu.service'],'charging':['oxp3-battery.service'],'overlay':['oxp3-overlay-read.service'],'gyro':['oxp3-gyro.service'],'legacy-runtime':['oxp3-volkey-fix.service','oxp3-battery-clamp.service']}
    restart_input=component=='gyro' and subprocess.run(['systemctl','is-active','--quiet','inputplumber.service']).returncode==0
    changed=False
    try:
        if component=='gyro': run('systemctl','stop','inputplumber.service')
        for unit in units.get(component,[]): run('systemctl','stop',unit)
        readonly=run('steamos-readonly','status').strip().lower()
        if not any(word in readonly for word in ('enabled','disabled')): raise RuntimeError('Unknown root protection state')
        changed='disabled' not in readonly
        if changed: run('steamos-readonly','disable')
        if component=='waydroid':
            from waydroid_setup import restore_packages
            restore_packages()
        return restore('/',slot,component)
    finally:
        try:
            if changed: run('steamos-readonly','enable')
        finally:
            run('systemctl','daemon-reload')
            if restart_input: run('systemctl','start','inputplumber.service')

def execute():
    if os.geteuid()!=0: raise RuntimeError('Root required')
    trusted_tree(Path(__file__).parent)
    slot=current_slot(); directory=Path('/home/.oxp3-installer/integration')/slot
    with os.fdopen(os.open(directory/'.activation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),'wb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        saved=snapshot(directory/'result.json',maximum=2*1024*1024)
        if saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('Untrusted activation result')
        result=json.loads(base64.b64decode(saved['data'])); installed=result['components']; activation={}
        for name,value in installed.items():
            if value['status']!='files_installed': continue
            try:
                if name in result['options']['repairs'] and name not in ('keyboard','gamescope-env','flathub-ustc'): device_guard()
                if name=='input': run('depmod','-a',KERNEL) # No live HID unbind; next boot uses the installed module.
                if name=='gyro':
                    if Path('/sys/class/dmi/id/bios_version').read_text().strip()!='5.09': raise RuntimeError('Gyro requires the accepted BIOS 5.09')
                    if run('/usr/bin/inputplumber','--version').strip()!='inputplumber 0.78.0': raise RuntimeError('Gyro requires InputPlumber 0.78.0')
                if name=='legacy-runtime':
                    run('/usr/bin/python3','-I','-B','-c','import evdev')
                if name in ('oxp3-cpu','charging','native-tdp'):
                    run('/usr/bin/python3','-I','-B','-c','import dbus; import gi')
                if name=='desktop-hdr':
                    run('runuser','-u','deck','--','/home/deck/.local/lib/oxp3-desktop-hdr-runtime/launch.sh','--check')
                if name=='waydroid':
                    from waydroid_setup import setup
                    setup()
                dependencies=json.loads((Path(__file__).parent/'options.json').read_text())
                required=next((item['dependencies'] for item in dependencies['repairs']+dependencies['plugins'] if item['id']==name),[])
                if any(activation.get(dependency,{}).get('status') not in ('ready','active') for dependency in required): raise RuntimeError('Live dependency was refused')
                activation[name]={'status':'ready','session_restart_required':name in ('input','multifunction','gyro','desktop-hdr','hdr','keyboard','kde-language','gamescope-env')}
            except Exception as error: activation[name]={'status':'refused','reason':str(error)}
        # Only services belonging to a successfully guarded component can start.
        names={'decky':['plugin_loader.service'],'native-tdp':['oxp3-rapl.service'],'fan-driver':['oxp3-fan-module.service'],
               'oxp3-fan':['oxp3-fan.service','oxp3-fan-sleep.service'],'oxp3-cpu':['oxp3-cpu.service'],
               'charging':['oxp3-battery.service'],'overlay':['oxp3-overlay-read.service'],'gyro':['oxp3-gyro.service'],
               'legacy-runtime':['oxp3-volkey-fix.service','oxp3-battery-clamp.service'],
               'input':['inputplumber.service']}
        run('systemctl','daemon-reload')
        for name,units in names.items():
            if activation.get(name,{}).get('status')!='ready': continue
            try:
                dependencies=json.loads((Path(__file__).parent/'options.json').read_text())
                required=next((item['dependencies'] for item in dependencies['repairs']+dependencies['plugins'] if item['id']==name),[])
                if any(activation.get(dependency,{}).get('status') not in ('ready','active') for dependency in required): raise RuntimeError('Dependency activation failed')
                for unit in units:
                    # A sleep hook is enabled but must not run its pre-sleep action at boot.
                    if unit!='oxp3-fan-sleep.service': run('systemctl','start',unit)
                activation[name]['status']='active'
            except Exception as error: activation[name]={'status':'failed','reason':str(error)}
        atomic_write(directory/'activation.json',(json.dumps(activation,indent=2)+'\n').encode(),0o600,0,0)
        return activation

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['run','restore','guard']); parser.add_argument('--slot',choices=['A','B']); parser.add_argument('--component'); args=parser.parse_args()
    if args.action=='guard':
        trusted_tree(Path(__file__).parent); device_guard(); print('OXP3_DEVICE_GUARD=passed')
    elif args.action=='run': print(json.dumps(execute()))
    else:
        if args.component is None: parser.error('--component required')
        errors=restore_live(args.component,args.slot or current_slot())
        print(json.dumps({'restore_errors':errors})); sys.exit(bool(errors))
