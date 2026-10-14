"""Bundled Windows restart component, deployed through the normal file journal."""
import json
import os
from pathlib import Path
import stat


def files(root, components):
    root, components = Path(root), Path(components)
    source = components / 'windows-reboot'
    for required in ('usr/bin/python3', 'usr/bin/efibootmgr', 'usr/bin/systemctl',
                     'usr/bin/pkexec', 'usr/bin/kdialog'):
        if not (root / required).is_file():
            raise RuntimeError('Windows restart dependency is missing: /' + required)
    metadata = json.loads((source / 'plugin.json').read_text(encoding='utf-8'))
    if metadata['name'] != 'Restart into Windows' or metadata['flags'] != ['root']:
        raise RuntimeError('Unexpected Windows restart plugin identity')
    output = {}

    def add(target, relative, mode=0o644, user=False):
        output[target] = {'data': (source / relative).read_bytes(), 'mode': mode, 'user': user}

    prefix = 'var/lib/oxp3-installer/decky/runtime/plugins/oxp3-restart-windows/'
    for name in ('main.py', 'plugin.json', 'package.json', 'dist/index.js'):
        add(prefix + name, name)
    for name in ('boot.py', 'desktop.py'):
        add('usr/local/lib/oxp3-windows-reboot/' + name, name)
    add('usr/local/bin/oxp3-reboot-windows', 'oxp3-reboot-windows', 0o755)
    add('usr/share/polkit-1/actions/org.oxp3.restart-windows.policy', 'org.oxp3.restart-windows.policy')
    add('etc/polkit-1/rules.d/49-oxp3-restart-windows.rules', '49-oxp3-restart-windows.rules')
    for target in ('home/deck/Desktop/oxp3-reboot-windows.desktop',
                   'home/deck/.local/share/applications/oxp3-reboot-windows.desktop'):
        add(target, 'oxp3-reboot-windows.desktop', 0o755, True)
    # File journals preserve existing ownership and permissions. Refuse any
    # writable privileged ancestor/file rather than inheriting that metadata.
    for target, entry in output.items():
        if entry['user']:
            continue
        path = root / target
        for ancestor in (path, *path.parents):
            if not ancestor.is_relative_to(root):
                break
            if not os.path.lexists(ancestor):
                continue
            info = ancestor.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise RuntimeError('Untrusted Windows restart target: ' + str(ancestor))
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != entry['mode']:
            raise RuntimeError('Unexpected Windows restart file permissions: ' + str(path))
    return output
