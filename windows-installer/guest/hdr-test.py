"""File-only HDR lifecycle on owned Linux volumes; never claims display acceptance."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, '/mnt/payload/components')
sys.path.insert(0, '/mnt/payload/components/hdr')
from file_transaction import snapshot, atomic_write
from installer import ConfigurationFiles, RELATIVE
from generate import generate

root = Path('/mnt/target')
store = root / 'home/.oxp3-installer/transactions/hdr'
if store.exists(): raise RuntimeError('HDR validation requires a fresh independent overlay')
# Execute live entry against the actual deployed 3.8.14 root; this must reject
# before creating any HDR journal or user configuration, not emulate 3.10 hardware.
subprocess.run(['mkdir', '-p', str(root / 'tmp/hdr-components')], check=True)
subprocess.run(['cp', '-R', '/mnt/payload/components/.', str(root / 'tmp/hdr-components')], check=True)
negative = subprocess.run(['chroot', str(root), '/usr/bin/python3', '-I', '-B', '/tmp/hdr-components/hdr/installer.py', 'apply'], text=True, capture_output=True)
if negative.returncode == 0 or 'HDR system compatibility refused' not in negative.stderr or store.exists():
    raise RuntimeError('Actual SteamOS 3.8.14 did not reject live HDR apply before state creation: ' + negative.stderr)
print('OXP_HDR_LIVE_GATE=actual-3.8.14-refused-before-state-or-config', flush=True)

files = ConfigurationFiles(root)
parent = files.target.parent
parent.mkdir(parents=True, exist_ok=True)
os.chown(parent, 1000, 1000)
if files.target.exists(): raise RuntimeError('Unexpected existing HDR test target')
other = parent / '80-unselected-test.lua'; atomic_write(other, b'unselected configuration\n', 0o600, 1000, 1000)
original = b'original gamma22 configuration\n'; atomic_write(files.target, original, 0o600, 1000, 1000)
before = snapshot(files.target)
first = files.apply((1000, 1000)); epoch = first['epoch']
journal = store / epoch / 'state.json'; initial_journal = json.loads(journal.read_text())
if initial_journal['allowed'] != [RELATIVE] or any('/mnt/target' in key for key in initial_journal['original']): raise RuntimeError('HDR journal persisted a mount-point path')
installed = snapshot(files.target)
if base64.b64decode(installed['data']) != generate().encode() or (installed['uid'], installed['gid'], installed['mode']) != (1000, 1000, 0o600): raise RuntimeError('Existing user HDR metadata/template was not preserved')
if files.apply((1000, 1000))['epoch'] != epoch or json.loads(journal.read_text())['original'] != initial_journal['original']: raise RuntimeError('Repeat replaced the original HDR snapshot')
print('OXP_HDR_CONFIG=existing-user-file-repeat-original-and-metadata-preserved', flush=True)
# A later manual edit must survive both reinstall and restore refusals.
atomic_write(files.target, b'user manual edit\n', 0o600, 1000, 1000)
try: files.apply((1000, 1000))
except RuntimeError: pass
else: raise RuntimeError('Manual edit was overwritten by repeat')
if files.restore()['phase'] != 'restore_conflict' or files.target.read_bytes() != b'user manual edit\n': raise RuntimeError('Manual edit was overwritten by rollback')
atomic_write(files.target, generate().encode(), 0o600, 1000, 1000)
if files.restore()['phase'] != 'rolled_back' or snapshot(files.target) != before or files.restore()['phase'] != 'rolled_back': raise RuntimeError('HDR restore/repeat did not recover original bytes/metadata')
print('OXP_HDR_RESTORE=manual-conflict-refused-original-and-repeat-restored', flush=True)
# Reinstallation starts a new epoch, preserving the first history.
files.target.unlink()
new = files.apply((1000, 1000))
if new['epoch'] == epoch or snapshot(files.target)['uid'] != 1000 or snapshot(files.target)['mode'] != 0o644: raise RuntimeError('Absent configuration ownership/new epoch is incorrect')
print('OXP_HDR_NEW_CONFIG=user-owned-new-file-and-independent-epoch', flush=True)
# A real independent process exits after the target atomic write/fsync and
# before transaction commit. Recovery must release its abandoned flock and use
# the durable original/intent through a different real mount point.
if files.restore()['phase'] != 'rolled_back' or files.target.exists(): raise RuntimeError('New file did not restore original absence')
pid = os.fork()
if pid == 0:
    import file_transaction
    real_write = file_transaction.atomic_write
    def exit_after_target(path, *args, **kwargs):
        real_write(path, *args, **kwargs)
        if Path(path) == files.target: os._exit(73)
    file_transaction.atomic_write = exit_after_target
    files.apply((1000, 1000))
    os._exit(74)
_, status = os.waitpid(pid, 0)
if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 73: raise RuntimeError('Independent HDR process did not exit at the actual write boundary')
interrupted = json.loads(files.pointer.read_text())
new_journal = store / interrupted['epoch'] / 'state.json'
value = json.loads(new_journal.read_text())
if value['phase'] != 'installing' or files.target.read_bytes() != generate().encode(): raise RuntimeError('Actual interrupted configuration or durable intent missing')
print('OXP_HDR_PROCESS_EXIT=actual-child-after-target-fsync-before-commit', flush=True)
recovery = Path('/mnt/hdr-recovery'); recovery.mkdir(exist_ok=True)
subprocess.run(['mount', '--bind', str(root), str(recovery)], check=True)
# The bind is deliberately non-recursive; bind the state/home mounts explicitly.
for directory in ('var', 'home'):
    subprocess.run(['mount', '--bind', str(root / directory), str(recovery / directory)], check=True)
try:
    recovered = ConfigurationFiles(recovery).restore()
    if recovered['phase'] != 'rolled_back' or (recovery / RELATIVE).exists(): raise RuntimeError('Interrupted new HDR file was not removed from alternate root')
finally:
    for relative in ('home', 'var', ''):
        subprocess.run(['umount', str(recovery / relative)], check=True)
if other.read_bytes() != b'unselected configuration\n': raise RuntimeError('Unselected Gamescope configuration changed')
print('OXP_HDR_OFFLINE_RECOVERY=logical-path-alternate-root-interrupted-intent-and-original-absence', flush=True)
# Actual LuaJIT parsing and behavior against a supplied Gamescope API harness.
profile = root / 'tmp/hdr-generated.lua'; profile.write_text(generate())
subprocess.run(['chroot', str(root), '/usr/bin/luajit', '/tmp/hdr-components/hdr/test_profile.lua', '/tmp/hdr-generated.lua'], check=True)
print('OXP_HDR_LUA=actual-target-luajit-harness-passed-no-gamescope-display-claim', flush=True)