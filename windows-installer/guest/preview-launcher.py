#!/usr/bin/env python3
"""Run one read-only preview inside a DRM terminal, with no login or shell."""
import os
from pathlib import Path

base = '/usr/local/lib/oxp3-installer'
environment = dict(os.environ)
environment['LD_LIBRARY_PATH'] = base + '/console'
vendor = Path('/sys/class/dmi/id/sys_vendor')
if vendor.exists() and vendor.read_text().strip() == 'QEMU':
    # Preserve console startup errors in the isolated VM probe's serial log.
    with open('/dev/ttyS0', 'w') as serial:
        os.dup2(serial.fileno(), 2)
os.execve(base + '/console/kmscon', [base + '/console/kmscon',
    '--vt=1', '--switchvt', '--seats=seat0', '--no-hwaccel', '--drm',
    # kmscon reserves one dummy session, leaving one slot for the preview.
    '--font-engine=8x16', '--render-engine=bbulk', '--session-max=2',
    '--no-session-control', '--configdir=' + base + '/console',
    '--login', '--', '/usr/bin/python3', base + '/installer_ui.py'], environment)
