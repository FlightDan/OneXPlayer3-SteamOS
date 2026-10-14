"""Host termination before/after append, followed by fresh Linux intent recovery."""
import json
from pathlib import Path
import sys
from deployment import run, table, fs
from intent_store import IntentStore
from install_session import review, candidate, resume_review, execute_virtual, handoff_to_esp

mode = sys.argv[1]
choice = json.loads(Path('/mnt/payload/selection.json').read_text())
journal = IntentStore(Path('/mnt/session-state/oxp3'))
if mode in ('intent', 'appended'):
    accepted = review(choice, [candidate('/dev/vdd')])
    execute_virtual(choice, '/dev/vdc', '/dev/vdd', accepted, journal=journal, fault='pause-' + mode)
    raise RuntimeError('Expected host interruption did not occur')
if mode != 'recover': raise RuntimeError('Unknown recovery mode')
record = journal.load()
if record is None or record['status'] != 'prepared': raise RuntimeError('No interrupted prepared intent')
accepted = resume_review(record, candidate('/dev/vdd'))
print('OXP_INSTALL_RECOVERY=prepared-intent-with-' + str(accepted['already_appended']) + '-owned-parts', flush=True)
if fs('/dev/vdd3'): raise RuntimeError('ESP was formatted before the interrupted boundary')
result = execute_virtual(choice, '/dev/vdc', '/dev/vdd', accepted, journal=journal)
if table('/dev/vdd')['partitions'][:2] != record['before']['table']['partitions']:
    raise RuntimeError('Protected Windows partition metadata changed')
for node, kind, name, expected in [
    ('/dev/vdd1', 'vfat', 'preserved-efi.txt', 'Windows EFI fixture file must survive deployment.\n'),
    ('/dev/vdd2', 'ntfs-3g', 'preserved.txt', 'Windows fixture data must survive partition append.\n')]:
    root = Path('/mnt/intent-check-windows'); root.mkdir(exist_ok=True)
    run('mount', '-t', kind, '-o', 'ro', node, str(root))
    try:
        if (root / name).read_text() != expected: raise RuntimeError('Protected file changed')
    finally: run('umount', str(root))
handoff_to_esp(result, journal)
if journal.load()['status'] != 'esp_journal_ready': raise RuntimeError('Intent handoff is not durable')
esp = next(p['node'] for p in table('/dev/vdd')['partitions'] if p.get('name') == 'esp')
root = Path('/mnt/intent-check-esp'); root.mkdir(exist_ok=True)
run('mount', '-t', 'vfat', '-o', 'ro', esp, str(root))
try:
    state = json.loads((root / 'oxp3/install-state.json').read_text())
    if state['append_intent_id'] != record['id'] or state['selection']['append_intent']['id'] != record['id']:
        raise RuntimeError('Original intent was not persisted in the ESP deployment journal')
    if state['copied'] or state['configured']: raise RuntimeError('This test must not copy or configure root systems')
finally: run('umount', str(root))
print('OXP_INSTALL_RECOVERY=esp-intent-windows-preserved-no-root-copy', flush=True)
