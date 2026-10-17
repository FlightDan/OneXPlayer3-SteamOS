"""Emit deployment for the independent OXP3 CPU Decky plugin."""
import base64
import json
from pathlib import Path
here=Path(__file__).parent
unit='''[Unit]
Description=ONEXPLAYER3 transactional CPU EPP and frequency settings
After=systemd-udev-trigger.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 -I /var/lib/oxp3-cpu/cpu_control.py apply
ExecStop=/usr/bin/python3 -I /var/lib/oxp3-cpu/cpu_control.py restore
ExecStopPost=/usr/bin/python3 -I /var/lib/oxp3-cpu/cpu_control.py restore
TimeoutStartSec=15
TimeoutStopSec=10
RuntimeDirectory=oxp3-cpu
RuntimeDirectoryMode=0700
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ReadWritePaths=/var/lib/oxp3-cpu /sys/devices/system/cpu/cpufreq /run/lock
[Install]
WantedBy=multi-user.target
'''
files={'/var/lib/oxp3-cpu/cpu_control.py':(here/'cpu_control.py').read_bytes(),
       '/var/lib/oxp3-cpu/power_control.py':(here/'power_control.py').read_bytes(),
       '/var/lib/oxp3-cpu/test_power_control.py':(here/'test_power_control.py').read_bytes(),
       '/var/lib/oxp3-cpu/test_cpu_control.py':(here/'test_cpu_control.py').read_bytes(),
       '/etc/systemd/system/oxp3-cpu.service':unit.encode()}
plugin={'main.py':(here/'cpu-plugin-main.py').read_bytes(),'dist/index.js':(here/'cpu-plugin-index.js').read_bytes(),
        'plugin.json':json.dumps({'name':'OXP3 CPU','author':'Local OXP3 adaptation','flags':['root'],'api_version':1}).encode(),
        'package.json':json.dumps({'name':'oxp3-cpu','version':'0.2.0','type':'module'}).encode()}
print("set -eu\npython3 - <<'PY'\nfrom pathlib import Path\nimport base64,json")
print("base=Path('/var/lib/oxp3-cpu');state=Path('/var/lib/oxp3-research/cpu-connect-v1');plugin=Path('/home/deck/homebrew/plugins/OXP3-CPU');stage=Path('/home/deck/homebrew/.oxp3-cpu-stage');assert not base.exists() and not state.exists() and not plugin.exists() and not stage.exists();base.mkdir(mode=0o755);state.mkdir(mode=0o700)")
print("(base/'config.json').write_text(json.dumps({'enabled':False,'epp':'balance_performance','p_mhz':4700,'e_mhz':3600,'lp_mhz':3100}));(base/'config.json').chmod(0o600)")
print("policies=Path('/sys/devices/system/cpu/cpufreq').glob('policy*');before={str(p/n):(p/n).read_text().strip() for p in policies for n in ('scaling_max_freq','energy_performance_preference','scaling_governor')};(state/'before.json').write_text(json.dumps(before))")
for dest,data in files.items():
    print(f"p=Path({dest!r});p.write_bytes(base64.b64decode('{base64.b64encode(data).decode()}'));p.chmod(0o644)")
print("PY\nmkdir -p /run/oxp3-cpu\ncd /var/lib/oxp3-cpu\npython3 -B -m unittest -q test_cpu_control.py")
print("systemctl daemon-reload\nsystemctl enable --now oxp3-cpu.service\npython3 - <<'PY'\nfrom pathlib import Path\nimport base64")
for name,data in plugin.items():
    print(f"p=Path('/home/deck/homebrew/.oxp3-cpu-stage')/{name!r};p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode('{base64.b64encode(data).decode()}'));p.chmod(0o644)")
print("Path('/home/deck/homebrew/.oxp3-cpu-stage').rename('/home/deck/homebrew/plugins/OXP3-CPU')\nPY")
print('systemctl show oxp3-cpu -p ActiveState -p SubState\ncat /var/lib/oxp3-cpu/config.json')
