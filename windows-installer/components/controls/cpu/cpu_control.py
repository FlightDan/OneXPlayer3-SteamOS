"""Transactional OXP3 EPP and per-core-group frequency control."""
import fcntl
import json
from pathlib import Path
import platform
import sys

CONFIG=Path('/var/lib/oxp3-cpu/config.json')
STATE=Path('/run/oxp3-cpu/state.json')
POLICIES=Path('/sys/devices/system/cpu/cpufreq')
EPPS=('performance','balance_performance','balance_power','power')

def atomic(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.chmod(0o600);tmp.replace(p)

def groups():
    policies=sorted(POLICIES.glob('policy*'),key=lambda p:int(p.name[6:]))
    by_max={}
    for p in policies:
        if (p/'scaling_driver').read_text().strip()!='intel_pstate':
            raise RuntimeError('intel_pstate required')
        maximum=int((p/'cpuinfo_max_freq').read_text())
        by_max.setdefault(maximum,[]).append(p)
    maxima=sorted(by_max,reverse=True)
    if len(maxima)!=3 or [len(by_max[v]) for v in maxima]!=[2,8,4]:
        raise RuntimeError('Unexpected G3E core topology; refusing writes')
    return dict(zip(('p','e','lp'),(by_max[v] for v in maxima)))

def status():
    info={}
    for key,paths in groups().items():
        info[key]={'count':len(paths),'cpus':[int(p.name[6:]) for p in paths],
                   'hardware_max_mhz':min(int((p/'cpuinfo_max_freq').read_text())//1000 for p in paths),
                   'limit_mhz':[int((p/'scaling_max_freq').read_text())//1000 for p in paths],
                   'epp':[(p/'energy_performance_preference').read_text().strip() for p in paths]}
    ibc={'manual_available':False,'enabled':None,'balancer':None,'ia_limit':None}
    try:
        raw=Path('/sys/kernel/debug/dri/0000:00:02.0/gt0/uc/guc_pc').read_text()
        for line in raw.splitlines():
            for prefix,key in [('IBC enabled:','enabled'),('Balancer enabled:','balancer'),('Balancer IA LMT enabled:','ia_limit')]:
                if line.strip().startswith(prefix):
                    ibc[key]=line.rsplit(':',1)[1].strip()=='yes'
    except OSError:
        pass
    ibc['message']='由驱动与 GuC 固件自动分配；当前没有手动比例接口。'
    return {'groups':info,'kernel':platform.release(),'epp_choices':list(EPPS),
            'ibc':ibc,
            'config':json.loads(CONFIG.read_text()) if CONFIG.exists() else {'enabled':False}}

def targets(config):
    if type(config.get('enabled')) is not bool:
        raise ValueError('enabled must be boolean')
    if not config['enabled']:
        return {}
    if config.get('epp') not in EPPS:
        raise ValueError('Invalid EPP')
    result={}
    for key,paths in groups().items():
        cap=config.get(key+'_mhz')
        if type(cap) is not int:
            raise ValueError('Frequency must be integer MHz')
        for p in paths:
            minimum=int((p/'scaling_min_freq').read_text())
            maximum=int((p/'cpuinfo_max_freq').read_text())
            if not minimum<=cap*1000<=maximum or cap%100:
                raise ValueError(f'{key}: invalid frequency limit')
            choices=(p/'energy_performance_available_preferences').read_text().split()
            if config['epp'] not in choices:
                raise ValueError('EPP not available')
            if (p/'scaling_governor').read_text().strip()=='performance' and config['epp']!='performance':
                raise ValueError('Current performance governor rejects this EPP')
            result[str(p/'scaling_max_freq')]=str(cap*1000)
            result[str(p/'energy_performance_preference')]=config['epp']
    return result

def write_verified(name,value):
    p=Path(name);p.write_text(value+'\n')
    actual=p.read_text().strip()
    if actual!=value:
        raise RuntimeError(f'{name}: readback {actual} != {value}')

def restore_locked():
    if not STATE.exists():
        return {'restored':True,'external_changes':[]}
    state=json.loads(STATE.read_text());errors=[];external=[]
    for name,value in state['before'].items():
        try:
            actual=Path(name).read_text().strip()
            if actual==value:
                continue
            if actual not in state['owned'].get(name,[]):
                external.append(name)
                continue
            write_verified(name,value)
        except Exception as e:
            errors.append(str(e))
    if errors:
        raise RuntimeError('CPU restoration incomplete: '+'; '.join(errors))
    STATE.unlink()
    return {'restored':True,'external_changes':external}

def apply(config):
    desired=targets(config)
    with open('/run/lock/oxp3-cpu.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not desired:
            result=restore_locked();atomic(CONFIG,{'enabled':False});return result
        old={name:Path(name).read_text().strip() for name in desired}
        previous=json.loads(STATE.read_text()) if STATE.exists() else None
        before=previous['before'] if previous else old
        owned={name:list(set((previous or {}).get('owned',{}).get(name,[])+[old[name],value])) for name,value in desired.items()}
        atomic(STATE,{'before':before,'owned':owned})
        try:
            for name,value in desired.items():
                write_verified(name,value)
            for name,value in desired.items():
                if Path(name).read_text().strip()!=value:
                    raise RuntimeError('CPU settings changed during transaction')
        except Exception as error:
            errors=[]
            for name,value in old.items():
                try:
                    write_verified(name,value)
                except Exception as e:
                    errors.append(str(e))
            if not errors:
                if previous:
                    atomic(STATE,previous)
                else:
                    STATE.unlink()
            raise RuntimeError(f'{error}; rollback='+('verified' if not errors else '; '.join(errors))) from error
        atomic(STATE,{'before':before,'owned':{name:[value] for name,value in desired.items()}})
        atomic(CONFIG,config)
        return status()

def restore():
    with open('/run/lock/oxp3-cpu.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return restore_locked()

if __name__=='__main__':
    if sys.argv[1:] == ['restore']:
        print(json.dumps(restore()))
    elif sys.argv[1:] == ['apply']:
        print(json.dumps(apply(json.loads(CONFIG.read_text()))))
    else:
        print(json.dumps(status()))
