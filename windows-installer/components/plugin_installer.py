"""Pinned offline plugin file deployment for virtual integration testing.

This module does not enable services or initialize Steam. A live installer must
separately preserve service state and validate the Steam session before using it.
Existing installations outside our managed code store are deliberately refused.
"""
import base64
import json
import os
from pathlib import Path, PurePosixPath
import stat
import uuid
import zipfile
from file_transaction import FileTransaction, atomic_write, snapshot, directory_fd, serialized
from directory_transaction import DirectoryTransaction

PLUGINS = {
    'steamgriddb': ('SteamGridDB', '1.8.1', 'decky-steamgriddb'),
    'protondb': ('ProtonDB Badges', '1.3.4', 'protondb-decky'),
}
UNIT = b'''# OXP3 managed offline Decky files; activation is a separate step.
[Unit]
Description=Decky Loader (OXP3 managed)
After=network.target
[Service]
Type=simple
User=root
Restart=on-failure
KillMode=control-group
TimeoutStopSec=15
ExecStart=/var/lib/oxp3-installer/decky/runtime/services/PluginLoader
WorkingDirectory=/var/lib/oxp3-installer/decky/runtime/services
Environment=PRIVILEGED_PATH=/var/lib/oxp3-installer/decky/runtime
Environment=UNPRIVILEGED_PATH=/home/deck/homebrew
Environment=UNPRIVILEGED_USER=deck
Environment=CHOWN_PLUGIN_PATH=0
Environment=KEEP_SYSTEMD_SERVICE=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=LOG_LEVEL=INFO
[Install]
WantedBy=multi-user.target
'''


def patch_animation_changer(files, prefix):
    """Prepare the supported upstream backend without touching its cached ZIP.

    Decky can initialize before Steam creates ~/.steam/root. Creating movies
    below that future symlink makes it a directory, breaking Steam's ln -sfn.
    Resolve an existing root (including custom/dangling symlinks) each time;
    before Steam creates it, use Steam's canonical data directory.
    The caller deploys these bytes through its existing file transaction.
    Original backend: Justin Marentette / SteamDeckHomebrew, BSD-3-Clause,
    https://github.com/TheLogicMaster/SDH-AnimationChanger. Preserve its LICENSE
    and metadata. The maintenance adapter carries the full original notice.
    """
    try:
        plugin = json.loads(files[prefix + 'plugin.json']['data'])
        package = json.loads(files[prefix + 'package.json']['data'])
        source = files[prefix + 'main.py']['data']
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError('Missing Animation Changer compatibility patch input') from error
    if (not isinstance(plugin, dict) or not isinstance(package, dict) or
            plugin.get('name') != 'Animation Changer' or
            package.get('name') != 'decky-animation-changer' or package.get('version') != '1.3.2'):
        raise RuntimeError('Unsupported Animation Changer identity or version for compatibility patch')
    original = b"OVERRIDE_PATH = os.path.expanduser('~/.steam/root/config/uioverrides/movies')"
    canonical = b"OVERRIDE_PATH = os.path.expanduser('~/.local/share/Steam/config/uioverrides/movies')"
    replacement = b'''\n\ndef get_override_path():
    steam_root = os.path.expanduser('~/.steam/root')
    # Preserve existing installations, including custom and dangling symlinks.
    # Never create the compatibility root as a directory before Steam does.
    if os.path.lexists(steam_root):
        steam_root = os.path.realpath(steam_root)
    else:
        steam_root = os.path.expanduser('~/.local/share/Steam')
    return os.path.join(steam_root, 'config', 'uioverrides', 'movies')'''
    assignment = original if isinstance(source, bytes) and original in source else canonical
    if (not isinstance(source, bytes) or source.splitlines().count(assignment) != 1
            or source.count(assignment) != 1 or b'get_override_path' in source):
        raise RuntimeError('Unsupported Animation Changer override path for compatibility patch')
    apply = b"    override_path = f'{OVERRIDE_PATH}/{video}'"
    startup = b'            os.makedirs(OVERRIDE_PATH, exist_ok=True)'
    if source.count(apply) != 1 or source.count(startup) != 1 or source.count(b'OVERRIDE_PATH') != 3:
        raise RuntimeError('Unsupported Animation Changer override path uses for compatibility patch')
    result = source.replace(assignment, replacement, 1).replace(apply, b'''    override_directory = get_override_path()
    os.makedirs(override_directory, exist_ok=True)
    override_path = os.path.join(override_directory, video)''', 1).replace(
        startup, b'            os.makedirs(get_override_path(), exist_ok=True)', 1)
    changed = dict(files)
    changed[prefix + 'main.py'] = dict(files[prefix + 'main.py'], data=result)
    return changed


def extract_plugin(archive, destination, plugin_id):
    name, version, folder = PLUGINS[plugin_id]
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 1000 or sum(entry.file_size for entry in entries) > 64 * 1024 * 1024:
            raise RuntimeError('Plugin archive exceeds supported resource limits')
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if ('\\' in entry.filename or path.is_absolute() or '..' in path.parts or not path.parts or
                path.parts[0] != folder or entry.filename in seen or stat.S_ISLNK(mode)):
                raise RuntimeError('Unsafe or unexpected plugin archive entry')
            seen.add(entry.filename)
            target = destination.joinpath(*path.parts)
            if entry.is_dir(): target.mkdir(mode=0o755, parents=True, exist_ok=True)
            else:
                if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG): raise RuntimeError('Special plugin file refused')
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                atomic_write(target, package.read(entry), 0o644)
    plugin = destination / folder
    metadata = json.loads((plugin / 'plugin.json').read_text())
    package_metadata = json.loads((plugin / 'package.json').read_text())
    if metadata['name'] != name or package_metadata['version'] != version:
        raise RuntimeError('Pinned plugin metadata does not match the selected component')
    required_files = ('main.py', 'dist/index.js')
    if plugin_id == 'protondb': required_files += ('settings.py',)
    for relative in required_files:
        if not (plugin / relative).is_file(): raise RuntimeError('Missing plugin runtime file: ' + relative)
    return plugin


class PluginInstaller:
    def __init__(self, root, resources):
        self.root = Path(os.path.abspath(root))
        self.resources = Path(resources)
        self.code = self.root / 'var/lib/oxp3-installer/decky/runtime'
        self.directory = self.root / 'var/lib/oxp3-installer/transactions/plugins'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeError('Private plugin operation directory required')
        descriptor = directory_fd(self.directory); os.close(descriptor)
        self.unit = self.root / 'etc/systemd/system/plugin_loader.service'
        self.unit.parent.mkdir(mode=0o755, parents=True, exist_ok=True)

    def epoch(self, plugin_id, create):
        if plugin_id not in ('decky', *PLUGINS): raise ValueError('Unsupported plugin id')
        pointer = self.directory / (plugin_id + '.json')
        value = None
        if pointer.exists():
            content = snapshot(pointer)
            value = json.loads(base64.b64decode(content['data']))
            if content['uid'] != os.geteuid() or content['mode'] & 0o077 or not uuid.UUID(value['epoch']).hex == value['epoch']:
                raise RuntimeError('Invalid private plugin operation record')
        if create and (value is None or value['phase'] == 'rolled_back'):
            value = {'id': plugin_id, 'epoch': uuid.uuid4().hex, 'phase': 'prepared'}
            atomic_write(pointer, (json.dumps(value) + '\n').encode(), 0o600)
        if value is None: raise RuntimeError('No previous plugin operation')
        directory = self.directory / value['epoch']; directory.mkdir(mode=0o700, exist_ok=True)
        return pointer, value, directory

    @serialized
    def apply(self, plugin_id):
        if plugin_id != 'decky':
            _, dependency, _ = self.epoch('decky', False)
            if dependency['phase'] != 'files_installed': raise RuntimeError('Decky dependency has not been deployed')
        pointer, value, journal = self.epoch(plugin_id, True)
        staging = journal / ('staging-' + uuid.uuid4().hex)
        try:
            if plugin_id == 'decky':
                current = snapshot(self.unit)
                if current['exists'] and not base64.b64decode(current['data']).startswith(b'# OXP3 managed offline Decky'):
                    raise RuntimeError('Existing Decky installation requires a separately validated migration')
                staging.mkdir(mode=0o755)
                binary = (self.resources / 'decky/PluginLoader').read_bytes()
                if len(binary) < 1024 * 1024 or not binary.startswith(b'\x7fELF'):
                    raise RuntimeError('Missing pinned Linux Decky binary')
                atomic_write(staging / 'PluginLoader', binary, 0o755)
                atomic_write(staging / 'VERSION', b'3.2.10\n', 0o644)
                DirectoryTransaction(journal / 'code', self.code / 'services', self.code).apply(staging)
                FileTransaction(journal / 'unit', [self.unit]).apply({str(self.unit): UNIT})
            else:
                name, version, folder = PLUGINS[plugin_id]
                archive = self.resources / plugin_id / (plugin_id + '-' + version + '.zip')
                plugin = extract_plugin(archive, staging, plugin_id)
                DirectoryTransaction(journal / 'code', self.code / 'plugins' / folder, self.code).apply(plugin)
            value['phase'] = 'files_installed'; value['runtime'] = 'not_validated'; value.pop('error', None)
            atomic_write(pointer, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
            return value
        except Exception as error:
            value['phase'] = 'failed'; value['error'] = str(error)
            atomic_write(pointer, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
            raise

    @serialized
    def rollback(self, plugin_id):
        if plugin_id == 'decky':
            for dependent in PLUGINS:
                try: _, status, _ = self.epoch(dependent, False)
                except RuntimeError: continue
                if status['phase'] != 'rolled_back': raise RuntimeError('Restore dependent plugin before Decky')
        pointer, value, journal = self.epoch(plugin_id, False)
        if value['phase'] == 'rolled_back': return value
        if plugin_id == 'decky':
            unit_state = journal / 'unit/state.json'
            if unit_state.exists():
                errors = FileTransaction(journal / 'unit', [self.unit]).rollback()
                if errors: raise RuntimeError('Service unit restoration has conflicts: ' + json.dumps(errors))
            destination = self.code / 'services'
        else: destination = self.code / 'plugins' / PLUGINS[plugin_id][2]
        if (journal / 'code/state.json').exists(): DirectoryTransaction(journal / 'code', destination, self.code).rollback()
        value['phase'] = 'rolled_back'; value.pop('error', None)
        atomic_write(pointer, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
        return value
