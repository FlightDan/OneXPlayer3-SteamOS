"""Independent read-only checks after the actual boot UI worker exits."""
import json
import stat
from pathlib import Path
from deployment import run, table, fs, resolve
from media_layer import OWNED
from install_session import table_identity

target = table('/dev/vdd')
if [p.get('name') for p in target['partitions']] != ['Windows EFI fixture', 'Windows data fixture', 'esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home']:
    raise RuntimeError('Unexpected post-UI installation partition table')
root = Path('/mnt/ui-result-check'); root.mkdir(exist_ok=True)
esp = next(p['node'] for p in target['partitions'] if p.get('name') == 'esp')
run('mount', '-t', 'vfat', '-o', 'ro', esp, str(root))
try: state = json.loads((root / 'oxp3/install-state.json').read_text())
finally: run('umount', str(root))
if state.get('status') != 'complete' or state.get('configured') != ['A', 'B'] or state.get('uuid_encoding') != 'plain_uuid_v1':
    raise RuntimeError('UI worker did not persist a completed typed-UUID installation')
source_table = table('/dev/vdc')
if table_identity(state['selection']['target_table']) != table_identity(target) or table_identity(state['selection']['source_table']) != table_identity(source_table):
    raise RuntimeError('Boot UI disk metadata changed between VM adapters')
selection = dict(state['selection'], source_table=source_table, target_table=target)
nodes = resolve(selection, target)
expected_types = {'esp': 'vfat', 'efi-A': 'vfat', 'efi-B': 'vfat', 'var-A': 'ext4', 'var-B': 'ext4', 'home': 'ext4'}
if set(state['formatted']) != set(expected_types) or set(state['copied']) != {'rootfs-A', 'rootfs-B'}:
    raise RuntimeError('Completed journal lacks the exact filesystem roles')
for field in ('formatted', 'copied'):
    for role, identity in state[field].items():
        if fs(nodes[role], 'UUID') != identity: raise RuntimeError('Completed filesystem UUID changed: ' + role)
        if fs(nodes[role]) != expected_types.get(role, 'btrfs'): raise RuntimeError('Completed filesystem type changed: ' + role)
if len(set(state['copied'].values())) != 2 or fs('/dev/vdc3', 'UUID') in state['copied'].values():
    raise RuntimeError('Root UUIDs are not distinct from each other and source')
bootstrap_views = []
for slot in ('A', 'B'):
    run('mount', '-t', 'btrfs', '-o', 'ro,rescue=nologreplay', nodes['rootfs-' + slot], str(root))
    try:
        if run('btrfs', 'property', 'get', '-ts', str(root), 'ro', capture=True).strip() != 'ro=true':
            raise RuntimeError('UI installation root is unprotected')
        if any((root / name).exists() or (root / name).is_symlink() for name in OWNED):
            raise RuntimeError('UI/preview recovery layer leaked into installed system')
        if 'VERSION_ID=3.8.14' not in (root / 'etc/os-release').read_text(): raise RuntimeError('Installed version differs')
        if 'component_request' in state:
            request = state['component_request']
            if request['id'] != state['selection']['append_intent']['id'] or request['components'] != [] or state.get('bootstrap_staged') != ['A','B']:
                raise RuntimeError('Bootstrap choice is not the confirmed empty request from this install')
            run('mount', '-t', 'ext4', '-o', 'ro,noload', nodes['var-' + slot], str(root / 'var'))
            run('mount', '-t', 'ext4', '-o', 'ro,noload', nodes['home'], str(root / 'home'))
            try:
                directory = root / 'home/.oxp3-installer/firstboot'
                for name in ('request.json','state.json','staging.json'):
                    info = (directory / name).lstat()
                    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600: raise RuntimeError('Non-private staged bootstrap record')
                if json.loads((directory / 'request.json').read_text()) != request: raise RuntimeError('Root view lost shared request')
                status = json.loads((directory / 'state.json').read_text())
                staging = json.loads((directory / 'staging.json').read_text())
                if status['request'] != request or status['status'] != 'prepared' or status['components'] != {} or status.get('runs',0) != 0:
                    raise RuntimeError('Passive resources caused component dispatch')
                if staging['request'] != request or staging['phase'] != 'staged' or staging['enabled'] is not False: raise RuntimeError('Empty bootstrap enabled service')
                if (root / 'etc/systemd/system/multi-user.target.wants/oxp3-firstboot.service').exists() or (root / 'etc/systemd/system/multi-user.target.wants/oxp3-firstboot.service').is_symlink():
                    raise RuntimeError('Empty component request unexpectedly enabled')
                for name in ('firstboot.py','file_transaction.py','shared_state.py','hdr/installer.py','hdr/generate.py','hdr/upstream.lua','hdr/UPSTREAM_LICENSE'):
                    path = root / 'usr/local/lib/oxp3-firstboot' / name; info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022: raise RuntimeError('Missing/untrusted installed bootstrap code')
                if (root / 'home/.oxp3-installer/transactions/hdr').exists() or (root / 'home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua').exists(): raise RuntimeError('Carried HDR resource activated')
                bootstrap_views.append([directory.stat().st_dev,directory.stat().st_ino,request['id']])
            finally:
                for name in ('home','var'): run('umount',str(root/name))
    finally: run('umount', str(root))
if 'component_request' in state:
    if len(bootstrap_views) != 2 or bootstrap_views[0] != bootstrap_views[1]: raise RuntimeError('Both slots do not share one request inode')
    print('OXP_UI_FIRSTBOOT=normal-install-same-request-id-shared-state-root-code-carriage-not-enabled', flush=True)
for node, kind, name, expected in [
    ('/dev/vdd1', 'vfat', 'preserved-efi.txt', 'Windows EFI fixture file must survive deployment.\n'),
    ('/dev/vdd2', 'ntfs-3g', 'preserved.txt', 'Windows fixture data must survive partition append.\n')]:
    run('mount', '-t', kind, '-o', 'ro', node, str(root))
    try:
        if (root / name).read_text() != expected: raise RuntimeError('Protected Windows file changed')
    finally: run('umount', str(root))
intent = selection.get('append_intent')
if intent is None or state.get('append_intent_id') != intent['id']:
    raise RuntimeError('UI installation lacks durable append-intent handoff')
for old in intent['before']['table']['partitions']:
    actual = next(p for p in target['partitions'] if p['uuid'] == old['uuid'])
    if {k:v for k,v in actual.items() if k != 'node'} != {k:v for k,v in old.items() if k != 'node'}:
        raise RuntimeError('Protected partition metadata changed')
run('mount', '-t', 'ext4', '-o', 'ro,noload', nodes['home'], str(root))
try:
    for resource in intent['selection'].get('resources', []):
        directory = root / 'oxp3-resources' / resource
        profile = json.loads((directory / 'profile.json').read_text())
        if not (directory / profile['archive']).is_file(): raise RuntimeError('Chosen resource was not carried')
finally: run('umount', str(root))
print('OXP_UI_INSTALL_CHECK=typed-uuid-protected-roots-preview-detached-intent-resources-windows-preserved', flush=True)
print('OXP_UI_FS_SNAPSHOT=' + json.dumps({'schema': 1, 'intent_id': intent['id'],
      'target': table_identity(target), 'formatted': state['formatted'], 'copied': state['copied']}), flush=True)
