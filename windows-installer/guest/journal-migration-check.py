"""Verify a legacy completed fixture journal on a private overlay; no recopy."""
import json
from pathlib import Path
from deployment import Deployment, run, table, fs
from fs_metadata import normalize_uuid

choice = json.loads(Path('/mnt/payload/selection.json').read_text())
selection = {'schema': 1, 'mode': 'virtual_install', 'source_table': table('/dev/vdc'),
             'target_table': table('/dev/vdd'), 'range': {'start': choice['target']['Start'], 'size': choice['target']['Size']}}
probe = Deployment(selection)
root = Path('/mnt/journal-before'); root.mkdir(exist_ok=True)
run('mount', '-t', 'vfat', '-o', 'ro', probe.nodes['esp'], str(root))
try:
    before_bytes = (root / 'oxp3/install-state.json').read_bytes()
    before = json.loads(before_bytes)
finally: run('umount', str(root))
if before.get('uuid_encoding') is not None or before['status'] != 'complete':
    raise RuntimeError('This probe requires a completed legacy UUID-encoding baseline')
if not all(value.startswith('/dev/') for field in ('formatted', 'copied') for value in before[field].values()):
    raise RuntimeError('Legacy baseline does not contain the known BusyBox descriptors')
try:
    probe.preflight(); probe.open_state()
    if probe.state['uuid_encoding'] != 'plain_uuid_v1' or probe.state['status'] != before['status']:
        raise RuntimeError('Journal migration did not preserve completion')
    for field in ('formatted', 'copied'):
        for role, old in before[field].items():
            if probe.state[field][role] != normalize_uuid(old, probe.nodes[role]) or probe.state[field][role] != fs(probe.nodes[role], 'UUID'):
                raise RuntimeError('Migration accepted a filesystem UUID mismatch')
    for field in ('configured', 'selection', 'phase'):
        if probe.state[field] != before[field]: raise RuntimeError('Migration changed existing deployment work')
finally: probe.cleanup()

# A foreign saved UUID must be rejected without overwriting the journal.
run('mount', '-t', 'vfat', probe.nodes['esp'], str(root))
try:
    current_bytes = (root / 'oxp3/install-state.json').read_bytes()
    altered = json.loads(current_bytes); altered['copied']['rootfs-A'] = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
    (root / 'oxp3/install-state.json').write_text(json.dumps(altered)); run('sync')
    corrupt_bytes = (root / 'oxp3/install-state.json').read_bytes()
finally: run('umount', str(root))
failed = False
try: Deployment(selection).apply()
except RuntimeError as error:
    if 'Journal filesystem identity changed' not in str(error): raise
    failed = True
if not failed: raise RuntimeError('Foreign journal UUID was accepted')
run('mount', '-t', 'vfat', probe.nodes['esp'], str(root))
try:
    if (root / 'oxp3/install-state.json').read_bytes() != corrupt_bytes:
        raise RuntimeError('Rejected journal was overwritten')
    (root / 'oxp3/install-state.json').write_bytes(current_bytes); run('sync')
finally: run('umount', str(root))
for node, kind, name, expected in [
    ('/dev/vdd1', 'vfat', 'preserved-efi.txt', 'Windows EFI fixture file must survive deployment.\n'),
    ('/dev/vdd2', 'ntfs-3g', 'preserved.txt', 'Windows fixture data must survive partition append.\n'),
    (probe.nodes['home'], 'ext4', 'retry-preserved.txt', 'Already formatted home must survive retry.\n')]:
    run('mount', '-t', kind, '-o', 'ro', node, str(root))
    try:
        if (root / name).read_text() != expected: raise RuntimeError('Existing content changed')
    finally: run('umount', str(root))
print('OXP_JOURNAL_MIGRATION=actual-uuid-types-distinct-roots-and-preserved-files', flush=True)
print('OXP_JOURNAL_MIGRATION=foreign-uuid-refused-with-journal-bytes-preserved', flush=True)
