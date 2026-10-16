"""Package maintained public repair payloads without device snapshots or secrets."""
from pathlib import Path
import json
import hashlib
import shutil
import tarfile
import runpy
from pathlib import PurePosixPath
import argparse
from opti_payload import read_plugin_tree, validate_runtime

root = Path(__file__).resolve().parents[1]
research = root.parent / 'research'
controls = root / 'components/controls'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root / 'cache/integration')
parser.add_argument('--opti-source', type=Path, default=root / 'components/opti2xmx')
arguments = parser.parse_args()
store = arguments.output
store.mkdir(parents=True, exist_ok=True)
manifest = {}

def component(name, files, units=(), packages=None):
    folder = store / name; folder.mkdir(exist_ok=True)
    targets = []
    for index, (target, data) in enumerate(files.items()):
        if target.startswith('/etc/systemd/system/') and target.endswith('.service') and b'[Service]\n' in data:
            data=data.replace(b'[Service]\n',b'[Service]\nExecCondition=/usr/bin/python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py guard\n',1)
        source = f'{index:03d}.bin'
        (folder / source).write_bytes(data)
        targets.append({'target': target.lstrip('/'), 'source': name + '/' + source,
                        'mode': 0o755 if target.endswith(('.sh', '/steamos-manager', '/steamosctl')) else 0o644,
                        'user': target.startswith('/home/deck/')})
    manifest[name] = {'files': targets, 'units': list(units), 'packages': packages or {}, 'missing': []}

def emitted_definitions(path):
    # Maintained deployment generators define a file map before emitting shell.
    code = path.read_text().split('print(', 1)[0]
    scope = {'__file__': str(path)}
    exec(compile(code, str(path), 'exec'), scope)
    return scope

opti=arguments.opti_source
opti_records=read_plugin_tree(opti)
component('opti2xmx', {
    **{'/home/deck/homebrew/plugins/opti2xmx/'+name:data for name,data in opti_records.items()},
    '/home/deck/.local/share/opti2xmx/runtime.json':(json.dumps({'package':'/opt/oxp3-opti2xmx/20261005/runtime','sr':'/opt/oxp3-opti2xmx/20261005/sdk/libxess.dll'})+'\n').encode()})
for item in manifest['opti2xmx']['files']:
    if '/homebrew/plugins/' in item['target']:item['user']=False
manifest['opti2xmx']['runtime_archive']='opti2xmx/runtime.tar.gz'
if not (store/'opti2xmx/runtime.tar.gz').is_file():manifest['opti2xmx']['missing']=['Run prepare-opti2xmx.py to stage the public runtime']
else: validate_runtime(store/'opti2xmx/runtime.tar.gz')

def plugin_files(name, values):
    return {f'/home/deck/homebrew/plugins/{name}/{key}': data for key, data in values.items()}

fan = emitted_definitions(research / 'overlay/deploy-fan.py')
cache_command=runpy.run_path(str(research/'overlay/update-layout.py'))['cache_command']
for which in ('domains','limits','fan'):
    if fan['presets'].count('exec='+cache_command(which))!=3:
        raise RuntimeError('Overlay presets must contain three current cached readers: '+which)
component('oxp3-fan', {**{p:d for p,d in fan['files'].items() if p not in ('/home/deck/.config/MangoHud/presets.conf','/var/lib/oxp3-overlay-telemetry/telemetry.py','/var/lib/oxp3-fan/load-fan-module.py','/etc/systemd/system/oxp3-fan-module.service')}, **plugin_files('OXP3-Fan',fan['plugin'])}, ['oxp3-fan.service','oxp3-fan-sleep.service'])
fan_sleep=store/'oxp3-fan/sleep-target.conf'; fan_sleep.write_bytes(b'[Unit]\nWants=oxp3-fan-sleep.service\n')
manifest['oxp3-fan']['files'].append({'target':'etc/systemd/system/sleep.target.d/90-oxp3-fan.conf','source':'oxp3-fan/sleep-target.conf','mode':0o644,'user':False})
cpu = emitted_definitions(controls / 'cpu/deploy-cpu.py')
component('oxp3-cpu', {**cpu['files'], **plugin_files('OXP3-CPU',cpu['plugin'])}, ['oxp3-cpu.service'])
battery = emitted_definitions(research / 'charging/deploy-battery.py')
component('charging', {**battery['files'], **plugin_files('OXP3-battery',battery['plugin'])}, ['oxp3-battery.service'], {'steamos-manager':'26.4.1-2'})
def light_plugin_files(directory):
    # Explicit recursive paths keep tests and Python caches out of the runtime.
    names = ('main.py', 'light_control.py', 'plugin.json', 'package.json',
             'dist/index.js', 'LICENSE', 'LICENSE-HHD', 'LICENSE-HueSync',
             'THIRD_PARTY_NOTICES.md', 'README.md')
    return plugin_files('OXP3-Light', {name: (directory / name).read_bytes() for name in names})

component('oxp3-light', light_plugin_files(root / 'components/light'))
for item in manifest['oxp3-light']['files']:
    item['user'] = False
component('fan-driver', {
    '/var/lib/oxp3-fan/oxpec.ko':(research/'charging/module/oxpec.ko').read_bytes(),
    '/usr/lib/modules/7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9/updates/oxpec.ko':(research/'charging/module/oxpec.ko').read_bytes(),
    '/var/lib/oxp3-fan/load-fan-module.py':(research/'overlay/load-fan-module.py').read_bytes(),
    '/etc/systemd/system/oxp3-fan-module.service':fan['files']['/etc/systemd/system/oxp3-fan-module.service']}, ['oxp3-fan-module.service'])
component('native-tdp', { '/var/lib/oxp3-rapl/provider.py':(controls/'rapl/provider.py').read_bytes(),
    '/etc/systemd/system/oxp3-rapl.service':(research/'rapl/oxp3-rapl.service').read_bytes(),
    '/etc/steamos-manager/remotes.d/oxp3-rapl.toml':(research/'rapl/oxp3-rapl.toml').read_bytes(),
    '/etc/dbus-1/system.d/org.onexplayer.SteamOSManager.PowerControl.conf':(research/'rapl/org.onexplayer.SteamOSManager.PowerControl.conf').read_bytes()}, ['oxp3-rapl.service'], {'steamos-manager':'26.4.1-2'})
component('overlay', {
    '/var/lib/oxp3-overlay-telemetry/telemetry.py':(research/'overlay/telemetry.py').read_bytes(),
    '/var/lib/oxp3-overlay-telemetry/allow-read.py':(research/'overlay/allow-read.py').read_bytes(),
    '/home/deck/.config/MangoHud/presets.conf':fan['presets'].encode(),
    '/etc/systemd/system/oxp3-overlay-read.service':b'[Unit]\nDescription=OXP3 read-only energy counters\nAfter=systemd-udev-trigger.service\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I -B /var/lib/oxp3-overlay-telemetry/allow-read.py\nRemainAfterExit=yes\n[Install]\nWantedBy=multi-user.target\n',
    '/home/deck/.config/systemd/user/oxp3-overlay-telemetry.service':b'[Unit]\nDescription=OXP3 overlay telemetry\n[Service]\nExecStart=/usr/bin/python3 -I -B /var/lib/oxp3-overlay-telemetry/telemetry.py collect\nRestart=on-failure\n[Install]\nWantedBy=default.target\n'}, ['oxp3-overlay-read.service'], {'mangohud':'0.8.3.rc1.r24.g33c2c7dd-4'})
overlay_target=store/'overlay/user-default-target.conf'; overlay_target.write_bytes(b'[Unit]\nWants=oxp3-overlay-telemetry.service\n')
overlay_sources=store/'sources/overlay'; overlay_sources.mkdir(parents=True,exist_ok=True)
for name in ('telemetry.py','update-layout.py','test-layout-device.py'):
    shutil.copyfile(research/'overlay'/name,overlay_sources/name)
manifest['overlay']['files'].append({'target':'home/deck/.config/systemd/user/default.target.d/90-oxp3-overlay.conf','source':'overlay/user-default-target.conf','mode':0o644,'user':True})
# Include both transport variants of this exact Bluetooth family; retain c106.
firmware_store=root/'cache/be201-firmware'
firmware_manifest=json.loads((firmware_store/'provenance.json').read_text())
firmware_files={}
for entry in firmware_manifest['files']:
    data=(firmware_store/entry['target']).read_bytes()
    if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
        raise RuntimeError('Firmware cache differs from pinned provenance: '+entry['target'])
    if entry['target'].startswith('licenses/'):
        target=store/'sources/be201'/entry['target']; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
    else: firmware_files['/usr/lib/firmware/'+entry['target']]=data
accepted='iwlwifi-sc-a0-fm-c0-c106.ucode'
if firmware_files['/usr/lib/firmware/'+accepted]!=(research/'wifi/candidate'/accepted).read_bytes():
    raise RuntimeError('Accepted c106 must remain unchanged')
component('wifi', firmware_files)
for entry in manifest['wifi']['files']:
    entry['missing_only']=not entry['target'].endswith('/'+accepted)
shutil.copyfile(firmware_store/'provenance.json',store/'sources/be201/provenance.json')
component('xe-dsb', {'/etc/modprobe.d/xe-oxp3.conf':b'# OXP3 accepted display workaround. Re-enabling DSB is a separate later hardware trial.\noptions xe enable_dsb=0\n'})
component('gm7-resume', {})
component('gamescope-env', {'/home/deck/.config/systemd/user/gamescope-session.service.d/90-oxp3-desktop-env-isolation.conf':(research/'desktop-hdr/90-oxp3-desktop-env-isolation.conf').read_bytes()})
input_map=(research/'input/20261013-oxp3-capability-before.yaml').read_text()
input_map='\n'.join(line for line in input_map.splitlines() if not line.startswith('#'))+'\n'
input_map=input_map.replace('id: oxp3\n','id: oxp3-installer\n')
home_start=input_map.index('  - name: Home key'); home_end=input_map.index('  - name: Console key',home_start)
home_block=input_map[home_start:home_end]
if home_block.count('button: Guide')!=1: raise RuntimeError('Unexpected accepted Home mapping')
input_map=input_map[:home_start]+home_block.replace('button: Guide','button: LeftPaddle2')+input_map[home_end:]
component('input', {
    '/usr/lib/modules/7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9/updates/hid-oxp.ko':(research/'input/hid-build-v1/hid-oxp.ko').read_bytes(),
    '/etc/inputplumber/devices.d/50-onexplayer_3.yaml':(root/'components/input-profile.yaml').read_bytes(),
    '/usr/share/inputplumber/capability_maps/oxp3-installer.yaml':input_map.encode()})
gyro_profile=(root/'components/input-profile.yaml').read_text()
needle='      name: "{i2c-BMI0160:00,bmi260,bmi160}"'
if gyro_profile.count(needle)!=1: raise RuntimeError('Unexpected input profile for gyro')
gyro_profile=gyro_profile.replace(needle,needle+'\n      sample_rate: 400\n      gyro_bias: [0, 0, 0]\n      gyro_auto_calibrate: false\n      mount_matrix:\n        x: [0, -1, 0]\n        y: [-1, 0, 0]\n        z: [0, 0, -1]\n      accel_bias: [0, 0, 0]')
component('gyro', {
    '/var/lib/oxp3-gyro-v1/oxp3_bmi260.ko':(research/'gyro/oxp3_bmi260.ko').read_bytes(),
    '/var/lib/oxp3-gyro-v1/inputplumber':(root/'cache/gyro/inputplumber').read_bytes(),
    **{'/var/lib/oxp3-gyro-v1/'+name:(root/'components/gyro'/name).read_bytes() for name in ('load.sh','unload.sh','launch.sh')},
    '/etc/systemd/system/oxp3-gyro.service':(root/'components/gyro/oxp3-gyro.service').read_bytes(),
    '/etc/systemd/system/inputplumber.service.d/oxp3-gyro-v1.conf':(root/'components/gyro/inputplumber.conf').read_bytes(),
    '/etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml':gyro_profile.encode(),
    '/etc/inputplumber/oxp3-gyro-steer.conf':b'# Preserve physical angular velocity; calibrate each device separately.\nenabled=0\n'}, ['oxp3-gyro.service'])
for entry in manifest['gyro']['files']:
    if entry['target'].endswith('/inputplumber'):entry['mode']=0o755
gyro_sources=store/'sources/gyro';gyro_sources.mkdir(parents=True,exist_ok=True)
for name in ('oxp3_bmi260.c','bmi270.h','onexplayer3-bmi260.patch','Makefile'):
    shutil.copyfile(research/'gyro'/name,gyro_sources/name)
shutil.copyfile(root/'docs/GYRO_INTEGRATION.md',gyro_sources/'README.md')
shutil.copyfile(root.parent/'onexplayer3-steamos-setup/gyro/inputplumber-0.78.0-oxp3-gyro.patch',gyro_sources/'inputplumber-0.78.0-oxp3-gyro.patch')
shutil.copyfile(research/'input/LICENSE',gyro_sources/'InputPlumber-LICENSE')
component('legacy-runtime', {
    '/var/lib/oxp3-runtime-hardened/volume.py':(research/'runtime_hardening/volume.py').read_bytes(),
    '/var/lib/oxp3-runtime-hardened/battery.sh':(research/'runtime_hardening/battery.sh').read_bytes(),
    '/etc/systemd/system/oxp3-volkey-fix.service':b'[Unit]\nDescription=OXP3 volume keys\n[Service]\nType=notify\nNotifyAccess=main\nTimeoutStartSec=30\nExecStart=/usr/bin/python3 -I -B /var/lib/oxp3-runtime-hardened/volume.py\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n',
    '/etc/systemd/system/oxp3-battery-clamp.service':b'[Unit]\nDescription=OXP3 battery display\n[Service]\nExecStart=/bin/bash /var/lib/oxp3-runtime-hardened/battery.sh\nExecStopPost=/bin/bash /var/lib/oxp3-runtime-hardened/battery.sh --stop\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n'}, ['oxp3-volkey-fix.service','oxp3-battery-clamp.service'])
component('manager', {}, packages={'steamos-manager':'26.4.1-2'})
for name in ('steamos-manager','steamosctl'):
    artifact = research / 'manager/source/target/release' / name
    if artifact.is_file():
        folder = store/'manager'; shutil.copyfile(artifact,folder/name)
        manifest['manager']['files'].append({'target':'usr/bin/'+name,'source':'manager/'+name,'mode':0o755,'user':False})
    else: manifest['manager']['missing'].append('Compatible built artifact: '+name)
component('desktop-hdr', {}, packages={'kwin':'6.7.3-1.6','qt6-base':'6.11.0-1','qt6-declarative':'6.11.0-1'})
# Exact package requirements are taken from the accepted launcher, not guessed.
manifest['desktop-hdr']['packages'] = dict(line.split() for line in (research/'desktop-hdr/compatible-packages.txt').read_text().splitlines())
desktop = store/'desktop-hdr/source'; desktop.mkdir(parents=True, exist_ok=True)
for source in (research/'desktop-hdr').iterdir():
    if source.is_file() and source.suffix in ('.cpp','.h','.py','.sh','.txt','.md'): shutil.copyfile(source,desktop/source.name)
shutil.copyfile(research/'display-source/kwin-6.7.3-1.6.src.tar.gz',desktop/'kwin-6.7.3-1.6.src.tar.gz')
manifest['desktop-hdr']['missing'] = ['Accepted fixed-prefix KWin binary bundle (not present in the local workspace)']
runtime = store/'desktop-hdr/accepted-runtime.tar'
if runtime.is_file():
    files={}
    with tarfile.open(runtime) as archive:
        members={m.name.removeprefix('./'):m for m in archive.getmembers() if m.name not in ('.','./')}
        for name, item in members.items():
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name: raise RuntimeError('Unsafe runtime archive')
            if item.isdir(): continue
            visited=set(); resolved=item
            while resolved.issym():
                if resolved.name in visited: raise RuntimeError('Cyclic runtime link')
                visited.add(resolved.name)
                link=PurePosixPath(resolved.linkname)
                if link.is_absolute() or '..' in link.parts: raise RuntimeError('External runtime link')
                resolved=members[str(PurePosixPath(resolved.name.removeprefix('./')).parent/link)]
            if not resolved.isfile(): raise RuntimeError('Special runtime entry')
            files['/opt/oxp3-desktop-gamma22/6.7.3-1.6/'+name]=archive.extractfile(resolved).read()
    files['/home/deck/.local/lib/oxp3-desktop-hdr-runtime/launch.sh']=(research/'desktop-hdr/launch-stable.sh').read_bytes()
    files['/home/deck/.local/lib/oxp3-desktop-hdr-runtime/disable-hdr.py']=(research/'desktop-hdr/disable-hdr.py').read_bytes()
    files['/home/deck/.config/systemd/user/plasma-kwin_wayland.service.d/90-oxp3-gamma22.conf']=b'[Service]\nUnsetEnvironment=LD_LIBRARY_PATH KWIN_OXP3_GAMMA22_HDR\nExecStart=\nExecStart=/home/deck/.local/lib/oxp3-desktop-hdr-runtime/launch.sh\n'
    files['/home/deck/.local/share/applications/oxp3-mapped-hdr.desktop']=b'[Desktop Entry]\nType=Application\nName=Mapped Desktop HDR\nName[zh_CN]=\xe6\xa1\x8c\xe9\x9d\xa2\xe6\x98\xa0\xe5\xb0\x84 HDR\nExec=/opt/oxp3-desktop-gamma22/6.7.3-1.6/bin/oxp3-mapped-hdr-control\nIcon=video-display\nCategories=Settings;\n'
    requirements=manifest['desktop-hdr']['packages']
    component('desktop-hdr',files,packages=requirements)
    for entry in manifest['desktop-hdr']['files']:
        target=entry['target']
        if target.startswith('opt/'):
            original=members.get(target.split('6.7.3-1.6/',1)[1])
            if original and original.mode & 0o111: entry['mode']=0o755
        if target.startswith('home/deck/.local/lib/'): entry['user']=False
    # Read the large compositor as one archive in the guest; thousands of FAT
    # payload lookups made the first full lifecycle run exceed its old timeout.
    manifest['desktop-hdr']['runtime_archive']='desktop-hdr/accepted-runtime.tar'
    discarded=[x for x in manifest['desktop-hdr']['files'] if x['target'].startswith('opt/')]
    manifest['desktop-hdr']['files']=[x for x in manifest['desktop-hdr']['files'] if x not in discarded]
    for item in discarded:
        source=(store/item['source']).resolve()
        if not source.is_relative_to(store.resolve()): raise RuntimeError('Out-of-store payload')
        source.unlink()
# Source and license material stays alongside executable payloads.
for directory, names in [('charging/module',['oxpec.c','oxpec.upstream.c','onexplayer3-dmi.patch','oxpec-acpi-lock-release.patch','README.md']),('input/hid-build-v1',['hid-oxp.patched.c','hid-ids.h','onexplayer3-button-format.patch','BUILD_STATUS.md']),('manager',['tdp-error-propagation.patch','tdp-live-state-cache.patch','BUILD_RESULTS.md']),('wifi/candidate',['provenance.json'])]:
    target=store/'sources'/directory; target.mkdir(parents=True,exist_ok=True)
    for name in names:
        source=research/directory/name
        if source.exists(): shutil.copyfile(source,target/name)
for source in (research/'wifi/candidate').glob('*LICEN*'): shutil.copyfile(source,store/'sources'/source.name)
for name in ('LICENSE','LICENSES/LICENCE.iwlwifi_firmware'):
    source=research/'wifi/candidate'/name
    if source.is_file(): shutil.copyfile(source,store/'sources'/Path(name).name)
(store/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'components':list(manifest),'missing':{k:v['missing'] for k,v in manifest.items() if v['missing']}},indent=2))
