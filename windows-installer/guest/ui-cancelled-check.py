"""Read-only evidence after cancelling the actual UI worker during root copy."""
import json
from pathlib import Path
from deployment import run, table, fs, resolve
from install_session import table_identity

target = table('/dev/vdd')
root = Path('/mnt/ui-cancel-check'); root.mkdir(exist_ok=True)
esp = next(p['node'] for p in target['partitions'] if p.get('name') == 'esp')
run('mount', '-t', 'vfat', '-o', 'ro', esp, str(root))
try: state = json.loads((root / 'oxp3/install-state.json').read_text())
finally: run('umount', str(root))
if state.get('status') != 'failed' or state.get('phase') != 'copy-rootfs-A' or state.get('configured') or state.get('copied'):
    raise RuntimeError('Cancellation did not persist the unfinished root-copy boundary')
if 'cancelled' not in state.get('error', '').lower(): raise RuntimeError('Journal did not record the cancellation')
if state.get('uuid_encoding') != 'plain_uuid_v1': raise RuntimeError('Wrong journal filesystem encoding')
if table_identity(state['selection']['target_table']) != table_identity(target):
    raise RuntimeError('Target GPT changed after UI cancellation')
choice = dict(state['selection'], target_table=target, source_table=table('/dev/vdc'))
nodes = resolve(choice, target)
expected_types = {'esp': 'vfat', 'efi-A': 'vfat', 'efi-B': 'vfat', 'var-A': 'ext4', 'var-B': 'ext4', 'home': 'ext4'}
if set(state['formatted']) != set(expected_types): raise RuntimeError('Cancellation lost a formatted filesystem role')
for role, identity in state['formatted'].items():
    if fs(nodes[role], 'UUID') != identity: raise RuntimeError('Cancellation changed a formatted filesystem UUID')
    if fs(nodes[role]) != expected_types[role]: raise RuntimeError('Cancellation changed a filesystem type')
for role in ('rootfs-B',):
    if fs(nodes[role]): raise RuntimeError('Cancellation unexpectedly started the B copy')
intent = choice['append_intent']
if state.get('append_intent_id') != intent['id']: raise RuntimeError('Append intent disappeared')
for old in intent['before']['table']['partitions']:
    actual = next(p for p in target['partitions'] if p['uuid'] == old['uuid'])
    if {k:v for k,v in old.items() if k != 'node'} != {k:v for k,v in actual.items() if k != 'node'}:
        raise RuntimeError('Protected partition metadata changed')
for node, kind, name, expected in [
    ('/dev/vdd1', 'vfat', 'preserved-efi.txt', 'Windows EFI fixture file must survive deployment.\n'),
    ('/dev/vdd2', 'ntfs-3g', 'preserved.txt', 'Windows fixture data must survive partition append.\n')]:
    run('mount', '-t', kind, '-o', 'ro', node, str(root))
    try:
        if (root / name).read_text() != expected: raise RuntimeError('Cancellation changed protected file content')
    finally: run('umount', str(root))
print('OXP_UI_CANCEL_CHECK=failed-copy-A-journal-filesystem-uuids-intent-windows-preserved', flush=True)
print('OXP_UI_FS_SNAPSHOT=' + json.dumps({'schema': 1, 'intent_id': intent['id'],
      'target': table_identity(target), 'formatted': state['formatted'], 'copied': state['copied']}), flush=True)
