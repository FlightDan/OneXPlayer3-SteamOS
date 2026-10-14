"""Root-owned, explicit first-boot requests; resource carriage is never consent.

Only the HDR adapter is currently implemented. Plugin/service activation is a
separate adapter and must not be inferred from the resource list.
"""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid

CODE = Path('/usr/local/lib/oxp3-firstboot')
STATE = Path('/home/.oxp3-installer/firstboot')

def trusted_code():
    if os.geteuid() != 0 or Path(__file__).absolute() != CODE / 'firstboot.py': raise RuntimeError('Fixed root-owned firstboot entry required')
    for path in [CODE, *CODE.rglob('*')]:
        info = path.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('Untrusted firstboot code tree')
    for parent in CODE.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022: raise RuntimeError('Untrusted firstboot code ancestor')


def modules():
    trusted_code()
    sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / 'hdr'))
    import file_transaction
    import installer
    import shared_state
    return file_transaction, installer


def private_directory(library, root):
    import shared_state
    legacy = Path(root) / 'var/lib/oxp3-installer/firstboot'
    if legacy.exists() or legacy.is_symlink(): raise RuntimeError('Legacy slot firstboot state requires explicit offline migration')
    path = shared_state.directory(root, 'firstboot')
    info = path.lstat()
    if info.st_uid != 0 or info.st_mode & 0o077: raise RuntimeError('Private firstboot directory required')
    return path


def read_private(library, path):
    value = library.snapshot(path, maximum=65536)
    if not value['exists'] or value['uid'] != 0 or value['mode'] & 0o077: raise RuntimeError('Private firstboot file required')
    return json.loads(base64.b64decode(value['data']))


def validate_request(value):
    if set(value) != {'schema', 'id', 'components', 'source', 'user'} or value['schema'] != 1 or value['user'] != 'deck': raise RuntimeError('Unsupported firstboot request')
    if not isinstance(value['id'], str) or str(uuid.UUID(value['id'])) != value['id']: raise RuntimeError('Invalid firstboot request ID')
    if not isinstance(value['components'], list) or len(set(value['components'])) != len(value['components']) or any(item != 'hdr' for item in value['components']): raise RuntimeError('Unknown/duplicate firstboot component')
    if set(value['source']) != {'version', 'build'} or any(not isinstance(v, str) or not v or len(v) > 64 for v in value['source'].values()): raise RuntimeError('Invalid firstboot source metadata')
    return value


def operating_system():
    values = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1); values[key] = value.strip('"')
    return {'version': values.get('VERSION_ID'), 'build': values.get('BUILD_ID')}


def execute():
    library, hdr = modules(); root = Path('/')
    directory = private_directory(library, root)
    with os.fdopen(os.open(directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'wb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = validate_request(read_private(library, directory / 'request.json'))
        state_path = directory / 'state.json'
        if state_path.exists():
            state = read_private(library, state_path)
            if state.get('schema') != 1 or state.get('request') != request: raise RuntimeError('Firstboot request changed; preserve previous operation')
        else: state = {'schema': 1, 'request': request, 'status': 'prepared', 'components': {}}
        def save():
            state['updated_at'] = int(time.time()); library.atomic_write(state_path, (json.dumps(state, indent=2) + '\n').encode(), 0o600)
        if operating_system() != request['source']:
            state['status'] = 'source_changed'; state['error'] = 'System update/source changed; explicit new review required'; save(); return state
        if state['status'] in ('complete', 'restored'): return state
        state['runs'] = state.get('runs', 0) + 1
        state['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        state['status'] = 'running'; save()
        for component in request['components']:
            previous = state['components'].get(component, {})
            if previous.get('status') == 'files_installed': continue
            # Probe only. A compatibility failure never constructs HDR state/config.
            try: owner = hdr.live_environment()
            except Exception as error:
                state['components'][component] = {'status': 'preflight_refused', 'error': str(error), 'files_changed': False}; save(); continue
            state['components'][component] = {'status': 'installing', 'files_changed': 'unknown'}; save()
            try:
                result = hdr.ConfigurationFiles(root).apply(owner)
                state['components'][component] = {'status': 'files_installed', 'epoch': result['epoch'], 'activation': result['activation'],
                    'restore': {'entry': str(CODE / 'firstboot.py'), 'action': 'restore', 'component': 'hdr'}}
            except Exception as error:
                state['components'][component] = {'status': 'failed', 'error': str(error), 'files_changed': 'unknown'}
            save()
        values = [value['status'] for value in state['components'].values()]
        state['status'] = 'failed' if 'failed' in values else 'completed_with_refusals' if 'preflight_refused' in values else 'complete'; save()
        return state


def restore(root):
    library, hdr = modules(); root = Path(os.path.abspath(root))
    directory = private_directory(library, root)
    with os.fdopen(os.open(directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'wb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = validate_request(read_private(library, directory / 'request.json'))
        state = read_private(library, directory / 'state.json')
        if state.get('request') != request or 'hdr' not in request['components']: raise RuntimeError('HDR was not selected by this firstboot operation')
        current = state['components'].get('hdr', {})
        if current.get('status') == 'preflight_refused': return {'status': 'not_installed', 'files_changed': False}
        if current.get('status') not in ('installing', 'files_installed', 'failed', 'restore_conflict', 'restored'): raise RuntimeError('No journaled HDR installation to restore')
        result = hdr.ConfigurationFiles(root).restore()
        state['components']['hdr'] = {'status': 'restored' if result['phase'] == 'rolled_back' else 'restore_conflict', 'epoch': result['epoch'], 'activation': result['activation'], 'errors': result.get('errors', [])}
        state['status'] = 'restored' if result['phase'] == 'rolled_back' else 'restore_conflict'
        library.atomic_write(directory / 'state.json', (json.dumps(state, indent=2) + '\n').encode(), 0o600)
        return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=('run', 'status', 'restore')); parser.add_argument('--root', default='/')
    args = parser.parse_args()
    if args.action == 'run':
        if args.root != '/': raise SystemExit('Firstboot run accepts only the actual root')
        value = execute()
    elif args.action == 'restore': value = restore(args.root)
    else:
        library, _ = modules(); value = read_private(library, private_directory(library, Path(args.root)) / 'state.json')
    print(json.dumps(value, indent=2))
    if value.get('status') in ('failed', 'source_changed', 'restore_conflict'): raise SystemExit(1)