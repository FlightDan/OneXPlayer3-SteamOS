"""OXP3 standard battery controls. No startup or unload policy writes."""
import fcntl
from pathlib import Path

BAT=Path('/sys/class/power_supply/BAT0')
MODES=('auto','inhibit-charge-awake','inhibit-charge')

def guard():
    # Require the battery interfaces used below, regardless of DMI model.
    if not all((BAT/name).is_file() for name in ('charge_control_end_threshold', 'charge_behaviour')):
        raise RuntimeError('Battery charge-control interfaces are unavailable')

def read(name):
    return (BAT/name).read_text().strip()

def mode():
    text=read('charge_behaviour')
    selected=[x[1:-1] for x in text.split() if x.startswith('[') and x.endswith(']')]
    if len(selected)!=1 or selected[0] not in MODES:
        raise RuntimeError('Unknown charging behaviour')
    return selected[0]

def status():
    guard()
    result={'limit':int(read('charge_control_end_threshold')),'mode':mode()}
    for name in ('capacity','status','power_now','energy_now','energy_full'):
        try: result[name]=read(name)
        except OSError: result[name]=None
    result['ac']=any(p.read_text().strip()=='1' for p in Path('/sys/class/power_supply').glob('*/online'))
    return result

def set_value(name,value):
    guard()
    if name=='charge_control_end_threshold':
        if type(value)!=int or not 60<=value<=100:
            raise ValueError('Charge limit must be an integer from 60 to 100')
        expected=str(value)
    elif name=='charge_behaviour':
        if value not in MODES or value not in read(name).replace('[','').replace(']','').split():
            raise ValueError('Unsupported charging mode')
        expected=value
    else: raise ValueError('Unsupported attribute')
    with open('/run/lock/oxp3-battery.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous=read(name) if name=='charge_control_end_threshold' else mode()
        try:
            with (BAT/name).open('w') as output: output.write(expected+'\n')
            actual=read(name) if name=='charge_control_end_threshold' else mode()
            if actual!=expected: raise RuntimeError('Hardware readback did not match requested setting')
        except Exception as error:
            # Behaviour getter is lossy for firmware raw state 2: do not claim
            # exact restoration or issue a guessed second behaviour write.
            if name=='charge_control_end_threshold':
                with (BAT/name).open('w') as output: output.write(previous+'\n')
                if read(name)!=previous: raise RuntimeError('Threshold rollback failed') from error
            raise
    return status()
