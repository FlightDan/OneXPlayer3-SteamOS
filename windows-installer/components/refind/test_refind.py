"""Exercise the production transaction on a disposable mounted FAT ESP."""
import uuid
import manage as m


def run(root, payload, esp, filesystem='FAT'):
    checks=[]
    if m.load(root): m.uninstall(root)
    original={n:m.read(root,n) for n in m.FILES}
    managed={n.casefold() for n in m.FILES+[m.STATE]}
    untouched={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and str(p.relative_to(root)).casefold() not in managed}
    def check(value,name):
        if not value: raise AssertionError(name)
        checks.append(name)
        print('OXP_REFIND_CHECK='+name,flush=True)
    def install(default='SteamOS',timeout=3,**kwargs):
        return m.install(root,payload,default,timeout,esp,str(uuid.UUID(int=17)),**kwargs)
    def fault(call):
        try: call()
        except RuntimeError as e:
            if str(e)!='Injected interruption': raise
        else: raise AssertionError('Fault did not fire')
    install(); check(m.verify(root)['phase']=='installed',f'actual {filesystem} installation/readback')
    install(); check(m.verify(root)['original']=={n:m.encode(v) for n,v in original.items()},'repeat preserves original loader')
    install('Windows',0); check(m.verify(root)['default']=='Windows','Windows default and indefinite wait')
    config=m.read(root,'EFI/BOOT/refind.conf')
    m.write(root,'EFI/BOOT/refind.conf',config+b'# user edit\n')
    try: m.uninstall(root)
    except RuntimeError: checks.append('user modification refuses overwrite')
    else: raise AssertionError('Modified file overwritten')
    check(m.read(root,'EFI/BOOT/refind.conf')==config+b'# user edit\n','user edit preserved')
    m.write(root,'EFI/BOOT/refind.conf',config)
    m.uninstall(root); m.uninstall(root)
    check(all(m.read(root,n)==v for n,v in original.items()),'uninstall and repeat restore original bytes')
    for boundary in range(1,len(m.FILES)+1):
        fault(lambda:install(fault_after=boundary))
        m.resume(root); m.verify(root)
        fault(lambda:m.uninstall(root,fault_after=boundary))
        m.resume(root)
        check(all(m.read(root,n)==v for n,v in original.items()),f'install/remove recovery boundary {boundary}')
    fault(lambda:install(fault_after=4)); m.uninstall(root)
    check(all(m.read(root,n)==v for n,v in original.items()),'rollback partial install')
    install(); fault(lambda:install('Windows',6,fault_after=7)); m.resume(root)
    check(m.verify(root)['timeout']==6,'resume reconfiguration')
    m.uninstall(root)
    check(all(m.read(root,n)==v for n,v in original.items()),'reconfiguration retains first backup')
    check(all((root/n).read_bytes()==v for n,v in untouched.items()),'other ESP files preserved byte for byte')
    m.install(root,payload,'SteamOS',0,esp)
    return dict(passed=True,checks=checks,count=len(checks),scope=f'production installer on disposable {filesystem} ESP fixture; injected process interruptions, not power-loss durability')
