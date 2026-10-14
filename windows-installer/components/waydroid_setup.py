"""Install the selected r2 host packages on the exact target after first boot.

Android initialization is explicit and separate because the Android images are
not included in this development archive. No existing package is upgraded.
"""
import json
import os
from pathlib import Path
import subprocess
import tarfile
from integration_runtime import device_guard,current_slot
from file_transaction import atomic_write, snapshot
import base64

def command(*args, check=True):
    return subprocess.run(args,check=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)

def setup():
    device_guard()
    if os.geteuid()!=0: raise RuntimeError('Root required')
    directory=Path('/home/.oxp3-installer/waydroid')/current_slot(); directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=directory.lstat()
    if info.st_uid!=0 or info.st_mode&0o077: raise RuntimeError('Untrusted Waydroid record')
    packages=sorted(Path('/usr/local/lib/oxp3-waydroid/packages').glob('*.pkg.tar.zst'))
    if len(packages)!=5: raise RuntimeError('The complete five-package r2 host bundle is required')
    record=directory/'packages.json'
    if record.exists():
        saved=snapshot(record)
        if saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('Untrusted Waydroid package state')
        state=json.loads(base64.b64decode(saved['data']))
    else:
        planned=[]
        for package in packages:
            name,version=command('pacman','-Qp',str(package)).stdout.strip().split()
            previous=command('pacman','-Q',name,check=False)
            if previous.returncode==0 and previous.stdout.strip()!=name+' '+version: raise RuntimeError('Existing Waydroid package differs; preserve it: '+name)
            planned.append({'name':name,'version':version,'file':str(package),'originally_installed':previous.returncode==0})
        state={'schema':1,'phase':'prepared','packages':planned}
        atomic_write(record,(json.dumps(state)+'\n').encode(),0o600,0,0)
    if state['phase']=='installed': return state
    if state['phase'] not in ('prepared','failed'): raise RuntimeError('Waydroid operation must be restored before reuse')
    readonly=command('steamos-readonly','status').stdout.strip().lower()
    if not any(word in readonly for word in ('enabled','disabled')): raise RuntimeError('Unknown root protection state')
    changed='disabled' not in readonly
    if changed: command('steamos-readonly','disable')
    try:
        state['phase']='installing'; atomic_write(record,(json.dumps(state)+'\n').encode(),0o600,0,0)
        command('pacman','-U','--noconfirm',*[x['file'] for x in state['packages']])
        command('depmod','-a')
        state['phase']='installed'; state['android']='image-download-and-initialization-required'
    except Exception as error:
        state['phase']='failed'; state['error']=str(error); raise
    finally:
        atomic_write(record,(json.dumps(state)+'\n').encode(),0o600,0,0)
        if changed: command('steamos-readonly','enable')
    return state

def restore_packages():
    device_guard()
    record=Path('/home/.oxp3-installer/waydroid')/current_slot()/'packages.json'
    if not record.exists(): return {'status':'not_installed'}
    saved=snapshot(record)
    if saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('Untrusted Waydroid package state')
    state=json.loads(base64.b64decode(saved['data']))
    if state['phase']=='restored': return state
    remove=[]
    for item in state['packages']:
        if item['originally_installed']: continue
        current=command('pacman','-Q',item['name'],check=False)
        if current.returncode: continue
        if current.stdout.strip()!=item['name']+' '+item['version']: raise RuntimeError('Waydroid package was changed; preserve it')
        remove.append(item['name'])
    # Pacman preserves changed package configuration as .pacsave. Android
    # images, applications and user data under /var/lib/waydroid are retained.
    if remove: command('pacman','-R','--noconfirm',*remove)
    state['phase']='restored'; atomic_write(record,(json.dumps(state)+'\n').encode(),0o600,0,0)
    return state

if __name__=='__main__': print(json.dumps(setup()))
