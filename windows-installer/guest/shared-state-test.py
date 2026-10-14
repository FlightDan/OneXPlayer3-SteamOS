"""Actual two-slot filesystem views; no hardware compatibility emulation."""
import base64
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, '/mnt/payload/components'); sys.path.insert(0, '/mnt/payload/components/hdr')
from file_transaction import atomic_write, snapshot
from installer import ConfigurationFiles
from generate import generate

first = Path('/mnt/target'); second = Path('/mnt/shared-second-root'); second.mkdir(exist_ok=True)
subprocess.run(['mount', '-t', 'btrfs', '-o', 'ro,rescue=nologreplay', '/dev/vdd7', str(second)], check=True)
subprocess.run(['mount', '/dev/vdd9', str(second / 'var')], check=True)
subprocess.run(['mount', '/dev/vdd10', str(second / 'home')], check=True)
try:
    a = ConfigurationFiles(first); b = ConfigurationFiles(second)
    if a.directory.stat().st_ino != b.directory.stat().st_ino or a.directory.stat().st_dev != b.directory.stat().st_dev: raise RuntimeError('A/B do not share one actual state inode/device')
    target = a.target; target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): raise RuntimeError('Shared-state fixture target is not empty')
    atomic_write(target, b'shared original user configuration\n', 0o600, 1000, 1000); original = snapshot(target)
    value = a.apply((1000, 1000)); epoch = value['epoch']; journal = a.directory / epoch / 'state.json'
    original_record = json.loads(journal.read_text())['original']
    if b.apply((1000, 1000))['epoch'] != epoch or json.loads(journal.read_text())['original'] != original_record: raise RuntimeError('B replaced A original/epoch')
    if b.target.read_bytes() != generate().encode(): raise RuntimeError('B does not see A actual user configuration')
    print('OXP_SHARED_HDR=two-real-roots-one-state-inode-original-epoch-preserved', flush=True)
    fd = os.open(a.directory / '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: b.apply((1000, 1000))
        except BlockingIOError: pass
        else: raise RuntimeError('Cross-slot lock did not exclude B')
    finally: os.close(fd)
    print('OXP_SHARED_LOCK=other-slot-cannot-enter-held-operation', flush=True)
    atomic_write(target, b'cross-slot manual edit\n', 0o600, 1000, 1000)
    if b.restore()['phase'] != 'restore_conflict' or target.read_bytes() != b'cross-slot manual edit\n': raise RuntimeError('B erased later manual edit')
    atomic_write(target, generate().encode(), 0o600, 1000, 1000)
    if b.restore()['phase'] != 'rolled_back' or snapshot(target) != original or a.restore()['phase'] != 'rolled_back': raise RuntimeError('B restore did not preserve A original bytes/owner/mode')
    print('OXP_SHARED_RESTORE=B-restores-A-original-conflict-preserved-repeat-idempotent', flush=True)
    target.unlink(); fresh = a.apply((1000, 1000))
    if fresh['epoch'] == epoch: raise RuntimeError('Reinstall did not retain independent history')
    if b.restore()['phase'] != 'rolled_back' or target.exists(): raise RuntimeError('Cross-slot new-file restore lost original absence')
    legacy = second / 'var/lib/oxp3-installer/transactions/hdr'; legacy.mkdir(parents=True, mode=0o700)
    before = a.pointer.read_bytes()
    try: ConfigurationFiles(second)
    except RuntimeError as error:
        if 'Legacy per-slot' not in str(error): raise
    else: raise RuntimeError('Legacy slot journal was silently superseded')
    if a.pointer.read_bytes() != before: raise RuntimeError('Legacy refusal changed shared history')
    legacy.rmdir()
    print('OXP_SHARED_LEGACY=slot-history-refused-before-shared-overwrite', flush=True)
    base = first / 'home/.oxp3-installer'; os.chmod(base, 0o755)
    try:
        try: ConfigurationFiles(second)
        except RuntimeError as error:
            if 'Private root-owned' not in str(error): raise
        else: raise RuntimeError('Public shared state directory accepted')
    finally: os.chmod(base, 0o700)
    if a.pointer.read_bytes() != before: raise RuntimeError('Shared privacy refusal changed state')
    print('OXP_SHARED_PRIVACY=root-private-mode-required', flush=True)
finally:
    for relative in ('home', 'var', ''): subprocess.run(['umount', str(second / relative)], check=True)