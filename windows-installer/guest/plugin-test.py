"""Real pinned Decky backend in the deployed SteamOS virtual root, then restore."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
sys.path.insert(0, '/mnt/payload/components')
from plugin_installer import PluginInstaller, PLUGINS

root = Path('/mnt/target')
installer = PluginInstaller(root, '/mnt/payload/plugins')
selected = ('decky', 'steamgriddb', 'protondb')
store = installer.code
unrelated = store / 'plugins/oxp3-unrelated-test'
unrelated.mkdir(parents=True, exist_ok=False)
(unrelated / 'preserve.txt').write_bytes(b'Unselected component must remain')
log_path = root / 'var/lib/oxp3-installer/transactions/plugins/backend-test.txt'
process = None
try:
    for component in selected:
        installer.apply(component)
        installer.apply(component)
        print('OXP_PLUGIN_FILES=' + component + ':repeat-passed', flush=True)
    environment = dict(os.environ, PRIVILEGED_PATH='/var/lib/oxp3-installer/decky/runtime',
                       UNPRIVILEGED_PATH='/home/deck/homebrew', UNPRIVILEGED_USER='deck',
                       PYTHONDONTWRITEBYTECODE='1', LOG_LEVEL='INFO')
    with open(log_path, 'wb') as output:
        process = subprocess.Popen(['chroot', str(root), '/var/lib/oxp3-installer/decky/runtime/services/PluginLoader'],
                                   env=environment, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 300
        loaded = set()
        request_errors = {}
        auth = None
        while time.monotonic() < deadline and process.poll() is None:
            if auth is None:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:1337/auth/token', timeout=2) as response:
                        auth = response.read().decode()
                except Exception: pass
            for plugin_id, (name, _, _) in PLUGINS.items():
                try:
                    from urllib.parse import quote
                    url = 'http://127.0.0.1:1337/plugins/' + quote(name) + '/frontend_bundle'
                    request = urllib.request.Request(url, headers={'X-Decky-Auth': auth or ''})
                    with urllib.request.urlopen(request, timeout=2) as response:
                        if response.status == 200 and len(response.read()) > 1000: loaded.add(plugin_id)
                except Exception as error: request_errors[plugin_id] = str(error)
            if loaded == set(PLUGINS): break
            time.sleep(1)
        if loaded != set(PLUGINS):
            print('OXP_PLUGIN_BACKEND_ERRORS=', flush=True)
            print('Process status: ' + str(process.poll()) + '; requests: ' + json.dumps(request_errors), flush=True)
            for line in log_path.read_text(errors='replace').splitlines()[-40:]:
                if not any(secret in line.lower() for secret in ('token', 'cookie', 'password')):
                    print(line, flush=True)
            raise RuntimeError('Decky backend did not register all selected plugins; see ' + str(log_path))
        print('OXP_PLUGIN_BACKEND=registered-and-frontend-bundles-served', flush=True)
        # This checks backend registration and JS delivery, not Steam frontend injection or live API features.
        os.killpg(process.pid, signal.SIGTERM)
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
        process = None
    for component in reversed(selected): installer.rollback(component)
    if (root / 'etc/systemd/system/plugin_loader.service').exists(): raise RuntimeError('New service unit was not removed')
    if (store / 'services').exists(): raise RuntimeError('New loader code was not removed')
    for _, _, folder in PLUGINS.values():
        if (store / 'plugins' / folder).exists(): raise RuntimeError('New selected plugin code was not removed')
    if (unrelated / 'preserve.txt').read_bytes() != b'Unselected component must remain': raise RuntimeError('Unselected plugin was changed')
    print('OXP_PLUGIN_RESTORE=passed', flush=True)
finally:
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL); process.wait()
    # Only this test's own new fixture marker is removed; deployment/restoration errors retain all component journals.
    if unrelated.exists(): (unrelated / 'preserve.txt').unlink(); unrelated.rmdir()
