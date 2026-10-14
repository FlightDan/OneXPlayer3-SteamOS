"""Install a fixed bootstrap on an explicitly selected offline root.

Never infer an execution request from resources. Only empty/HDR requests are
accepted at present. File installation does not start any service.
"""
import json
import os
from pathlib import Path
import shutil
import stat
from file_transaction import atomic_write, directory_fd, snapshot
from firstboot import validate_request
from shared_state import directory as shared_directory

FILES = ('firstboot.py', 'file_transaction.py', 'shared_state.py', 'hdr/installer.py', 'hdr/generate.py', 'hdr/upstream.lua', 'hdr/UPSTREAM_LICENSE')
UNIT = b'''[Unit]
Description=OXP3 selected component firstboot
After=local-fs.target
Before=display-manager.service
RequiresMountsFor=/home/.oxp3-installer /home/deck
ConditionPathExists=/home/.oxp3-installer/firstboot/request.json
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I -B /usr/local/lib/oxp3-firstboot/firstboot.py run
TimeoutStartSec=120
[Install]
WantedBy=multi-user.target
'''


def stage(root, source, request, enable=False):
    root, source = Path(root).absolute(), Path(source).absolute(); validate_request(request)
    if enable and not request['components']: raise RuntimeError('Empty firstboot request must remain disabled')
    descriptor = directory_fd(root); os.close(descriptor)
    code = root / 'usr/local/lib/oxp3-firstboot'; state = root / 'home/.oxp3-installer/firstboot'
    unit = root / 'etc/systemd/system/oxp3-firstboot.service'; link = unit.parent / 'multi-user.target.wants' / unit.name
    payload = {}
    for name in FILES:
        value = snapshot(source / name)
        if not value['exists']: raise RuntimeError('Missing bootstrap source')
        import base64
        payload[name] = base64.b64decode(value['data'])
    requested = (json.dumps(request, indent=2) + '\n').encode()
    legacy = root / 'var/lib/oxp3-installer/firstboot'
    if legacy.exists() or legacy.is_symlink(): raise RuntimeError('Legacy slot firstboot state must be migrated explicitly')
    # All existing targets are checked before changing any. A retry accepts only
    # exact immutable files from this request; it never replaces later edits.
    for tree in (code, state):
        if tree.exists() or tree.is_symlink():
            fd = directory_fd(tree); os.close(fd); info = tree.lstat()
            if info.st_uid != 0 or (tree == state and info.st_mode & 0o077) or (tree == code and info.st_mode & 0o022): raise RuntimeError('Untrusted existing bootstrap tree')
    if code.exists():
        for path in code.rglob('*'):
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or info.st_uid != 0 or info.st_mode & 0o022: raise RuntimeError('Untrusted bootstrap entry')
            if path.is_file() and str(path.relative_to(code)) not in FILES: raise RuntimeError('Unexpected bootstrap code file')
    targets = {code / name: (data, 0o644) for name, data in payload.items()}
    targets.update({state / 'request.json': (requested, 0o600), unit: (UNIT, 0o644)})
    for path, (data, mode) in targets.items():
        existing = snapshot(path)
        if existing['exists']:
            import base64
            if base64.b64decode(existing['data']) != data or existing['uid'] != 0 or existing['gid'] != 0 or existing['mode'] != mode: raise RuntimeError('Existing bootstrap file/request differs; preserve it')
    for record_name in ('state.json', 'staging.json'):
        saved = snapshot(state / record_name, maximum=65536)
        if saved['exists']:
            import base64
            record = json.loads(base64.b64decode(saved['data']))
            if saved['uid'] != 0 or saved['mode'] != 0o600 or record.get('schema') != 1 or record.get('request') != request:
                raise RuntimeError('Existing bootstrap state differs; preserve it')
    if link.exists() or link.is_symlink():
        if not enable or not link.is_symlink() or os.readlink(link) != '../' + unit.name or link.lstat().st_uid != 0: raise RuntimeError('Existing bootstrap enablement differs')
    state = shared_directory(root, 'firstboot', create=True)
    code.mkdir(parents=True, exist_ok=True, mode=0o755)
    atomic_write(state / 'staging.json', (json.dumps({'schema': 1, 'request': request, 'phase': 'staging'}) + '\n').encode(), 0o600, 0, 0)
    for path, (data, mode) in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        fd = directory_fd(path.parent); os.close(fd)
        if not path.exists(): atomic_write(path, data, mode, 0, 0)
    if not (state / 'state.json').exists():
        atomic_write(state / 'state.json', (json.dumps({'schema': 1, 'request': request, 'status': 'prepared', 'components': {}}, indent=2) + '\n').encode(), 0o600, 0, 0)
    if enable and not link.is_symlink():
        link.parent.mkdir(exist_ok=True); fd = directory_fd(link.parent); os.close(fd)
        os.symlink('../' + unit.name, link)
        descriptor = os.open(link.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    result = {'schema': 1, 'request': request, 'phase': 'staged', 'enabled': enable, 'activation': 'service-not-started'}
    atomic_write(state / 'staging.json', (json.dumps(result, indent=2) + '\n').encode(), 0o600, 0, 0)
    return result