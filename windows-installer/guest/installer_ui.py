#!/usr/bin/env python3
"""DRM terminal frontend with explicit review and a separately supervised worker."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import termios
import tty

from ui_backend import BootBackend
from ui_model import InstallerModel


def marker(value):
    vendor = Path('/sys/class/dmi/id/sys_vendor')
    if vendor.exists() and vendor.read_text().strip() == 'QEMU':
        try:
            with open('/dev/ttyS0', 'w') as file:
                file.write('OXP_UI_STATE=' + value + '\n')
                if value == 'home': file.write('OXP_PREVIEW_READY\n')
                file.flush()
        except OSError: pass


class Cancelled(RuntimeError): pass


def worker():
    def cancel(_signal, _frame): raise Cancelled('Installation cancelled; saved state can be reviewed for recovery.')
    signal.signal(signal.SIGTERM, cancel)
    backend = BootBackend(json.loads(Path('/usr/local/share/oxp3-installer/selection.json').read_text()))
    outcome = 0; cancelled = False
    try:
        accepted = json.loads(Path('/run/oxp3-ui-confirmation.json').read_text())
        backend.run(accepted)
        print('OXP_UI_RESULT=installed', flush=True)
    except Exception as error:
        cancelled = isinstance(error, Cancelled)
        print('OXP_UI_ERROR=' + str(error), flush=True); outcome = 1
    finally:
        backend.close()
        remaining = [line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()
                     if line.split()[4].startswith(('/mnt/oxp3-install-', '/mnt/oxp3-session-source', '/run/oxp3-ui-state'))]
        if remaining:
            print('OXP_UI_ERROR=Owned mounts remain: ' + ', '.join(remaining), flush=True); outcome = 1
        elif cancelled:
            print('OXP_UI_CANCEL_CLEANUP=worker-exited-owned-mounts-cleared', flush=True)
    return outcome


def draw(model):
    # ASCII text is deliberate: the bundled 8x16 terminal font has no CJK glyphs.
    lines = model.lines()
    print('\x1b[2J\x1b[H' + '\n'.join(line[:95] for line in lines) + '\n', end='', flush=True)
    marker(model.page)


def supervise(model, accepted):
    Path('/run/oxp3-ui-confirmation.json').write_text(json.dumps(accepted))
    os.chmod('/run/oxp3-ui-confirmation.json', 0o600)
    model.backend.close()  # The child mounts and owns persistent state itself.
    process = subprocess.Popen([sys.executable, str(Path(__file__)), '--worker'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    buffer = ''; result = False; cancelled = False; error = ''
    def log_worker(chunk):
        with open('/run/oxp3-ui-worker.log', 'a') as file: file.write(chunk)
        vendor = Path('/sys/class/dmi/id/sys_vendor')
        if vendor.exists() and vendor.read_text().strip() == 'QEMU':
            with open('/dev/ttyS0', 'w') as file: file.write(chunk); file.flush()
    draw(model)
    try:
        while process.poll() is None:
            ready, _, _ = select.select([sys.stdin, process.stdout], [], [], 0.2)
            if sys.stdin in ready:
                key = os.read(sys.stdin.fileno(), 1).decode(errors='ignore').lower()
                if key == 'c' and not cancelled:
                    cancelled = True; os.killpg(process.pid, signal.SIGTERM)
                    model.message = 'Cancelling and restoring owned mounts...'; draw(model)
            if process.stdout in ready:
                chunk = os.read(process.stdout.fileno(), 4096).decode(errors='replace')
                log_worker(chunk)
                buffer += chunk
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.startswith(('OXP_DEPLOY_', 'OXP_INSTALL_')):
                        model.message = line.split('=', 1)[-1]; draw(model)
                    if line == 'OXP_UI_RESULT=installed': result = True
                    if line.startswith('OXP_UI_ERROR='): error = line.split('=', 1)[1]
        trailing = process.stdout.read().decode(errors='replace')
        log_worker(trailing)
        if 'OXP_UI_RESULT=installed' in buffer + trailing: result = True
        if 'OXP_UI_ERROR=' in buffer + trailing: error = (buffer + trailing).split('OXP_UI_ERROR=', 1)[1].splitlines()[0]
        model.page = 'result' if result and process.returncode == 0 else 'home'
        model.message = ('SteamOS deployment completed. Boot verification is still required.' if result and process.returncode == 0
                         else error or 'Installation stopped. Review saved state before resuming.')
        draw(model)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM); process.wait()
        Path('/run/oxp3-ui-confirmation.json').unlink(missing_ok=True)


def main():
    backend = BootBackend(json.loads(Path('/usr/local/share/oxp3-installer/selection.json').read_text()))
    model = InstallerModel(backend.selection, backend)
    descriptor = sys.stdin.fileno(); original = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor); draw(model)
        while True:
            key = os.read(descriptor, 1).decode(errors='ignore').lower()
            try:
                accepted = model.action(key)
                if accepted: supervise(model, accepted)
                else: draw(model)
            except Exception as error:
                model.page = 'home'; model.accepted = None; model.message = str(error); draw(model)
    finally: termios.tcsetattr(descriptor, termios.TCSADRAIN, original); backend.close()


if __name__ == '__main__': sys.exit(worker() if '--worker' in sys.argv else main())
