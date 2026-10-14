"""Stage both real slots with one root-owned request on the common home."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
sys.path.insert(0, '/mnt/payload/components')
from file_transaction import atomic_write
from firstboot_stage import stage

root = Path('/mnt/target'); source = Path('/mnt/payload/components')
state = root / 'home/.oxp3-installer/firstboot'; code = root / 'usr/local/lib/oxp3-firstboot'
profile = root / 'home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua'
command = ['chroot', str(root), '/usr/bin/python3', '-I', '-B', '/usr/local/lib/oxp3-firstboot/firstboot.py']
def invoke(*args, allowed=True):
    result = subprocess.run(command + list(args), text=True, capture_output=True)
    if allowed and result.returncode != 0: raise RuntimeError(result.stderr)
    if not allowed and result.returncode == 0: raise RuntimeError('Expected root-firstboot refusal')
    return result
if code.exists() or profile.exists(): raise RuntimeError('Fresh component-free slot required')
if state.exists():
    # Second slot must use the exact existing shared request, including its ID.
    request = json.loads((state / 'request.json').read_text())
    before = json.loads((state / 'state.json').read_text())
    identity = (state.stat().st_dev, state.stat().st_ino)
    stage(root, source, request, enable=True)
    if (state.stat().st_dev, state.stat().st_ino) != identity: raise RuntimeError('Second slot replaced shared state directory')
    invoke('run'); value = json.loads((state / 'state.json').read_text())
    if value['request'] != before['request'] or value['runs'] != before['runs'] + 1: raise RuntimeError('Second slot changed request or lost previous execution')
    print('OXP_FIRSTBOOT_SHARED=second-real-slot-same-request-state-inode-runs-preserved', flush=True)
else:
    request = {'schema': 1, 'id': str(uuid.uuid4()), 'components': [], 'source': {'version': '3.8.14', 'build': '20260707.10'}, 'user': 'deck'}
    for choices in (['unknown'], ['hdr', 'hdr']):
        try: stage(root, source, dict(request, components=choices))
        except RuntimeError: pass
        else: raise RuntimeError('Unknown/duplicate request was staged')
    if state.exists() or code.exists(): raise RuntimeError('Invalid request changed destination')
    print('OXP_FIRSTBOOT_REQUEST=unknown-duplicate-refused-before-staging', flush=True)
    stage(root, source, request)
    if (root / 'etc/systemd/system/multi-user.target.wants/oxp3-firstboot.service').exists(): raise RuntimeError('Empty request was enabled')
    stage(root, source, request)
    invoke('run'); before = (state / 'state.json').read_bytes(); invoke('run')
    if (state / 'state.json').read_bytes() != before or json.loads(before)['status'] != 'complete' or profile.exists(): raise RuntimeError('Empty/repeated request changed files')
    print('OXP_FIRSTBOOT_EMPTY=no-action-disabled-and-repeat-preserved', flush=True)
    state.rename(state.parent / 'firstboot-empty-test-history')
    request['id'] = str(uuid.uuid4()); request['components'] = ['hdr']
    stage(root, source, request, enable=True); stage(root, source, request, enable=True)
    invoke('run'); value = json.loads((state / 'state.json').read_text())
    if json.loads(invoke('restore').stdout)['status'] != 'not_installed' or profile.exists(): raise RuntimeError('Restoring refused component changed files')
    print('OXP_FIRSTBOOT_RESTORE=refused-component-remains-not-installed', flush=True)
    original_request = (state / 'request.json').read_bytes(); previous_state = (state / 'state.json').read_bytes()
    atomic_write(state / 'request.json', json.dumps(dict(request, id=str(uuid.uuid4()))).encode(), 0o600, 0, 0)
    invoke('run', allowed=False)
    if (state / 'state.json').read_bytes() != previous_state: raise RuntimeError('Changed request overwrote previous state')
    atomic_write(state / 'request.json', original_request, 0o600, 0, 0)
    print('OXP_FIRSTBOOT_REBIND=changed-request-refused-original-state-preserved', flush=True)
    unsafe = code / 'hdr/upstream.lua'; os.chmod(unsafe, 0o666)
    try:
        invoke('run', allowed=False)
        if (state / 'state.json').read_bytes() != previous_state: raise RuntimeError('Untrusted code altered state')
    finally: os.chmod(unsafe, 0o644)
    print('OXP_FIRSTBOOT_TRUST=writable-code-refused-before-dispatch', flush=True)
if value['status'] != 'completed_with_refusals' or value['components']['hdr']['status'] != 'preflight_refused' or profile.exists() or (root / 'home/.oxp3-installer/transactions/hdr').exists(): raise RuntimeError('Actual 3.8 adapter failed to refuse before HDR changes')
atomic_write(state / 'before-uefi.json', json.dumps({'boot_id': value['boot_id'], 'runs': value['runs'], 'request': request}).encode(), 0o600, 0, 0)
print('OXP_FIRSTBOOT_STAGED=shared-request-fixed-slot-code-no-service-start', flush=True)
