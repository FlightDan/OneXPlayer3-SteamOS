"""Read-only checks using the installed deck identity, including ancestor ACLs."""
import json
import os
from pathlib import Path, PurePosixPath


def require_access(root, requirements):
    """Check image-relative paths in a chrooted child after dropping root."""
    root = Path(root)
    users = [line.split(':') for line in (root/'etc/passwd').read_text().splitlines() if line.startswith('deck:')]
    if len(users) != 1 or len(users[0]) != 7 or users[0][5] != '/home/deck':
        raise RuntimeError('Expected one non-root deck account')
    uid, gid = (int(users[0][i]) for i in (2, 3))
    if uid <= 0 or gid <= 0: raise RuntimeError('Expected a non-root deck identity')
    groups = {gid}
    if (root/'etc/group').exists():
        for line in (root/'etc/group').read_text().splitlines():
            fields = line.split(':')
            if len(fields) == 4 and 'deck' in fields[3].split(','): groups.add(int(fields[2]))
    for relative in requirements:
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts: raise ValueError('Expected an image-relative path')
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(reader)
        try:
            os.chroot(root); os.chdir('/')
            os.setgroups(sorted(groups)); os.setgid(gid); os.setuid(uid)
            result = {'denied': [path for path, mode in requirements.items() if not os.access('/'+path, mode)]}
        except BaseException as error:
            result = {'error': str(error)}
        with os.fdopen(writer, 'w') as output: json.dump(result, output)
        os._exit(0)
    os.close(writer)
    with os.fdopen(reader) as source: data = source.read()
    _, status = os.waitpid(pid, 0)
    if status != 0 or not data: raise RuntimeError('Deck access check did not complete')
    result = json.loads(data)
    if result.get('error'): raise RuntimeError('Deck access check failed: '+result['error'])
    if result['denied']:
        raise RuntimeError('Deck cannot access required runtime paths: '+', '.join(result['denied'][:30]))
    return len(requirements)


def verify_runtime_access(root, components):
    root = Path(root)
    paths = {name: os.R_OK | os.X_OK for name in
             ('etc', 'usr', 'usr/bin', 'usr/lib', 'usr/share', 'var', 'var/lib', 'home', 'home/deck')}
    # Optional locations become mandatory when present in the prepared image.
    for name in ('etc/dbus-1', 'etc/dbus-1/session.d', 'home/deck/.local',
                 'home/deck/.local/bin', 'home/deck/.local/lib', 'home/deck/.local/share',
                 'home/deck/.config', 'home/deck/.cache', 'home/deck/homebrew/plugins',
                 'var/lib/oxp3-overlay-telemetry'):
        if (root/name).exists(): paths[name] = os.R_OK | os.X_OK
    # These are consumed in the user's session. Root-private journals, shadow,
    # and privileged service state intentionally are not public runtime files.
    prefixes = ('home/deck/', 'opt/oxp3-', 'etc/dbus-1/', 'usr/lib/modules/',
                'usr/local/lib/oxp3-windows-reboot/', 'usr/local/bin/oxp3-reboot-windows',
                'usr/lib/python', 'var/lib/oxp3-overlay-telemetry/',
                'var/lib/oxp3-installer/decky/runtime/plugins/')
    for component in components.values():
        if component.get('status') != 'files_installed': continue
        for name in component.get('files', []):
            if name.startswith(prefixes):
                paths[name] = os.R_OK | (os.X_OK if (root/name).stat().st_mode & 0o111 else 0)
    # depmod outputs are generated outside the component file transaction.
    for path in (root/'usr/lib/modules').glob('*/modules.*'):
        if path.is_file(): paths[path.relative_to(root).as_posix()] = os.R_OK
    return require_access(root, paths)
