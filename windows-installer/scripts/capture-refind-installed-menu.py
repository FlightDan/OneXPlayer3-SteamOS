"""Capture the installed rEFInd menu in an owned overlay; no OS boot claim."""
import argparse
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

p=argparse.ArgumentParser(description=__doc__); p.add_argument('image',type=Path); a=p.parse_args()
root=Path(__file__).resolve().parents[1]; source=a.image.resolve(strict=True)
if not source.is_relative_to(root/'work') or source.suffix!='.img': raise ValueError('Expected owned test image')
marker=json.loads(Path(str(source)+'.refind-test.json').read_text(encoding='utf-8-sig'))
if marker.get('scope')!='disposable-refind-vm-only' or Path(marker['image'])!=source: raise ValueError('Missing ownership')
out=root/'work'/('refind-menu-'+uuid.uuid4().hex); out.mkdir()
runtime=root/'runtime/qemu-min'; overlay=out/'menu.qcow2'
subprocess.run([str(runtime/'qemu-img.exe'),'create','-f','qcow2','-F','raw','-b',str(source),str(overlay)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
shutil.copyfile(runtime/'share/edk2-i386-vars.fd',out/'vars.fd')
option=lambda path:str(path).replace('\\','/').replace(',',',,')
args=[str(runtime/'qemu-system-x86_64.exe'),'-accel','tcg','-machine','q35','-m','512','-smp','1',
      '-display','none','-monitor','none','-nic','none','-no-reboot','-vga','none','-device','virtio-gpu-pci',
      '-serial','file:'+option(out/'serial.txt'),'-qmp','stdio',
      '-drive','if=pflash,format=raw,readonly=on,file='+option(runtime/'share/edk2-x86_64-code.fd'),
      '-drive','if=pflash,format=raw,file='+option(out/'vars.fd'),
      '-drive','file='+option(overlay)+',format=qcow2,if=virtio']
process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
responses=queue.Queue(); errors=[]
def reader():
    for line in process.stdout:
        responses.put(json.loads(line))
threading.Thread(target=reader,daemon=True).start()
threading.Thread(target=lambda:errors.extend(process.stderr.readlines()),daemon=True).start()
def command(name,arguments=None):
    request=dict(execute=name,id=name)
    if arguments: request['arguments']=arguments
    process.stdin.write(json.dumps(request)+'\n'); process.stdin.flush()
    while True:
        reply=responses.get(timeout=10)
        if reply.get('id')==name:
            if 'error' in reply: raise RuntimeError(reply['error'])
            return
try:
    if 'QMP' not in responses.get(timeout=10): raise RuntimeError('No QMP greeting')
    command('qmp_capabilities'); time.sleep(20)
    command('screendump',dict(filename=str(out/'menu.png'),format='png'))
    print('MENU_CAPTURE='+str(out/'menu.png'),flush=True)
    for key,name in [('right','windows-selected'),('left','steamos-selected'),('down','tool-selected')]:
        command('send-key',dict(keys=[dict(type='qcode',data=key)])); time.sleep(.5)
        command('screendump',dict(filename=str(out/(name+'.png')),format='png'))
        print('MENU_CAPTURE='+str(out/(name+'.png')),flush=True)
finally:
    if process.poll() is None:
        try: command('quit')
        except Exception: process.kill()
    process.wait(timeout=10)
    (out/'stderr.txt').write_text(''.join(errors),encoding='utf-8')
