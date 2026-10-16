"""Selected NTFS Steam libraries: root mounts, deck uses Steam's native API.

No raw-device writes, repair, forced mounting, or Steam configuration-file editing.
The offline caller validates its selection before calling runtime_files().
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

CODE = Path('/usr/local/lib/oxp3-ntfs-steam')
CONFIG = CODE / 'config.json'
CONFIG_RELATIVE = 'usr/local/lib/oxp3-ntfs-steam/config.json'
STATUS = Path('/run/oxp3-ntfs-steam/status.json')
NAME = re.compile(r'share-d(?:0|[1-9][0-9]{0,4})-p[1-9][0-9]{0,4}\Z')
GUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
MAXIMUM = 1024 * 1024


class MountPending(RuntimeError):
    pass


def entry(item):
    name, guid = item['mount_name'], item['partuuid']
    if not isinstance(name, str) or not NAME.fullmatch(name): raise ValueError('Invalid mount name')
    if not isinstance(guid, str) or not GUID.fullmatch(guid) or guid == '00000000-0000-0000-0000-000000000000': raise ValueError('Invalid partition identifier')
    parent = '/var/mnt/shared/' + name
    return {'partuuid': guid, 'mount_name': name, 'parent': parent,
            'source': parent + '/SteamLibrary', 'alias': '/var/mnt/steam-libraries/' + name}


def validate_config(value):
    if type(value) is not dict or set(value) != {'schema', 'user', 'uid', 'gid', 'mounts'} or value['schema'] != 1 or value['user'] != 'deck': raise ValueError('Invalid runtime configuration')
    if any(type(value[key]) is not int or value[key] <= 0 for key in ('uid', 'gid')): raise ValueError('Invalid deck identity')
    mounts = value['mounts']
    if type(mounts) is not list or not 1 <= len(mounts) <= 32: raise ValueError('Invalid runtime selection')
    identities, names = set(), set()
    for item in mounts:
        if type(item) is not dict or set(item) != {'partuuid', 'mount_name', 'parent', 'source', 'alias'} or item != entry(item): raise ValueError('Invalid derived library path')
        if item['partuuid'] in identities or item['mount_name'] in names: raise ValueError('Duplicate runtime selection')
        identities.add(item['partuuid']); names.add(item['mount_name'])
    return value


def runtime_files(mounts, owner):
    selected = [entry(item) for item in mounts if item.get('steam_library', False)]
    if not selected: return {}
    config = validate_config({'schema': 1, 'user': 'deck', 'uid': owner[0], 'gid': owner[1], 'mounts': selected})
    prefix = 'usr/local/lib/oxp3-ntfs-steam/'
    files = {prefix + 'ntfs_steam.py': {'data': Path(__file__).read_bytes()},
             prefix + 'config.json': {'data': (json.dumps(config, indent=2) + '\n').encode()}}
    command = '/usr/bin/python3 -I -B /' + prefix + 'ntfs_steam.py'
    files['etc/systemd/system/oxp3-ntfs-steam-prepare.service'] = {'data': (
        '[Unit]\nDescription=Prepare selected NTFS Steam libraries\nAfter=local-fs.target\nRequiresMountsFor=/home\n'
        '[Service]\nType=oneshot\nExecStart=' + command + ' prepare\nTimeoutStartSec=120\n').encode()}
    files['etc/systemd/system/oxp3-ntfs-steam-prepare.timer'] = {'data': (
        '[Unit]\nDescription=Retry selected NTFS Steam library preparation\n[Timer]\nOnBootSec=15\nOnUnitInactiveSec=60\nUnit=oxp3-ntfs-steam-prepare.service\n').encode()}
    files['etc/systemd/system/multi-user.target.d/90-oxp3-ntfs-steam.conf'] = {'data': b'[Unit]\nWants=oxp3-ntfs-steam-prepare.timer\n'}
    files['etc/systemd/user/oxp3-ntfs-steam-register.service'] = {'data': (
        '[Unit]\nDescription=Register prepared NTFS libraries with Steam\nConditionUser=deck\n'
        '[Service]\nType=oneshot\nExecStart=' + command + ' register\nTimeoutStartSec=40\n').encode()}
    files['etc/systemd/user/oxp3-ntfs-steam-register.timer'] = {'data': (
        '[Unit]\nDescription=Retry Steam library registration\nConditionUser=deck\n[Timer]\nOnStartupSec=20\nOnUnitInactiveSec=60\nUnit=oxp3-ntfs-steam-register.service\n').encode()}
    files['etc/systemd/user/default.target.d/90-oxp3-ntfs-steam.conf'] = {'data': b'[Unit]\nWants=oxp3-ntfs-steam-register.timer\n'}
    return files


def trusted(path, directory=False):
    """Inspect every ancestor without following links or writable components."""
    path = Path(path)
    for current in [*reversed(path.parents), path]:
        info = current.lstat()
        kind = stat.S_ISDIR(info.st_mode) if current != path or directory else stat.S_ISREG(info.st_mode)
        if not kind or info.st_uid != 0 or info.st_mode & 0o022: raise RuntimeError('Untrusted runtime path: ' + str(current))
    return path


def read_json(path, maximum=MAXIMUM):
    trusted(path)
    with open(path, 'rb') as source:
        data = source.read(maximum + 1)
    if len(data) > maximum: raise RuntimeError('Runtime file exceeds limit')
    return json.loads(data)


def load_config():
    trusted(CODE / 'ntfs_steam.py')
    value = validate_config(read_json(CONFIG))
    import pwd
    user = pwd.getpwnam('deck')
    if (user.pw_uid, user.pw_gid, user.pw_dir) != (value['uid'], value['gid'], '/home/deck'): raise RuntimeError('Deck account changed')
    return value


def run(args, timeout=30):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def unit(path):
    return path.lstrip('/').replace('-', r'\x2d').replace('/', '-') + '.mount'


def visible_mount_id(path):
    """An O_PATH descriptor identifies the layer processes actually see."""
    if os.name != 'posix': return None  # Offline Windows tests cannot inspect Linux mounts.
    descriptor = os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with open('/proc/self/fdinfo/' + str(descriptor), encoding='ascii') as source:
            values = [line.split(':', 1)[1].strip() for line in source if line.startswith('mnt_id:')]
        if len(values) != 1 or not values[0].isdigit(): raise RuntimeError('Cannot confirm visible mount identity')
        return int(values[0])
    finally: os.close(descriptor)


def find_mount(path, runner=run):
    reply = runner(['findmnt', '--json', '--mountpoint', path, '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,FSROOT,MAJ:MIN,ID'])
    rows = []
    def flatten(items):
        for row in items:
            if type(row) is not dict or row.get('target') != path: raise RuntimeError('Unexpected mount tree at: ' + path)
            rows.append(row)
            flatten(row.get('children', []))
    flatten(json.loads(reply.stdout).get('filesystems', []))
    ntfs = [row for row in rows if row.get('fstype') == 'ntfs3']
    automount = [row for row in rows if row.get('fstype') == 'autofs' and row.get('source') == 'systemd-1' and
                 row.get('fsroot') == '/' and 'direct' in row.get('options', '').split(',')]
    if not ntfs and len(automount) <= 1 and len(automount) == len(rows): raise MountPending('NTFS mount is not ready: ' + path)
    if len(ntfs) != 1 or len(automount) > 1 or len(ntfs) + len(automount) != len(rows): raise RuntimeError('Unexpected or covering mount at: ' + path)
    current_id = visible_mount_id(path)
    if current_id is not None and ntfs[0].get('id') != current_id: raise RuntimeError('NTFS mount is not the visible mount: ' + path)
    return ntfs[0]


def options(row):
    return set(row['options'].split(','))


def parent_policy(row, config):
    opts = options(row)
    if row['fstype'] != 'ntfs3' or row.get('fsroot') != '/' or not {'rw', 'noexec', 'nosuid', 'nodev', 'windows_names'} <= opts or opts & {'exec', 'force', 'remove_hiberfile'}: raise RuntimeError('Parent NTFS safety policy changed')
    pairs = dict(item.split('=', 1) for item in opts if '=' in item)
    if (pairs.get('uid') != str(config['uid']) or pairs.get('gid') != str(config['gid']) or
            int(pairs.get('fmask', '-1'), 8) != 0o133 or int(pairs.get('dmask', '-1'), 8) != 0o22): raise RuntimeError('Parent NTFS ownership/mask changed')


def check_device(item, runner=run):
    text = runner(['blkid', '-s', 'PARTUUID', '-s', 'TYPE', '-o', 'export', '/dev/disk/by-partuuid/' + item['partuuid']]).stdout
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    if values.get('PARTUUID') != item['partuuid'] or values.get('TYPE') != 'ntfs': raise RuntimeError('Selected device identity/filesystem changed')


def device_number(item):
    info = os.stat('/dev/disk/by-partuuid/' + item['partuuid'])
    if not stat.S_ISBLK(info.st_mode): raise RuntimeError('Selected partition is not a block device')
    return str(os.major(info.st_rdev)) + ':' + str(os.minor(info.st_rdev))


def same_mount(first, second):
    return all(first.get(key) == second.get(key) for key in ('target', 'source', 'fstype', 'fsroot', 'maj:min', 'options', 'id'))


def alias_policy(row, parent):
    if (row['fstype'] != 'ntfs3' or row.get('fsroot') != '/SteamLibrary' or
            row.get('maj:min') != parent.get('maj:min') or not {'rw', 'nosuid', 'nodev'} <= options(row) or 'noexec' in options(row)):
        raise RuntimeError('Steam library bind identity/safety policy changed')


def make_directory(item):
    descriptor = os.open(item['parent'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try: os.mkdir('SteamLibrary', 0o755, dir_fd=descriptor)
        except FileExistsError: pass
        info = os.stat('SteamLibrary', dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode): raise RuntimeError('SteamLibrary is not an ordinary directory')
    finally: os.close(descriptor)


def alias_directory(path):
    for directory in (Path('/var/mnt'), Path('/var/mnt/steam-libraries'), Path(path)):
        try: directory.mkdir(mode=0o755)
        except FileExistsError: pass
        trusted(directory, directory=True)
    if any(Path(path).iterdir()): raise RuntimeError('Uncovered alias directory is not empty')


def probe(item):
    """Only chmod/execute/remove our new random file, never existing game files."""
    descriptor, filename = tempfile.mkstemp(prefix='.oxp3-exec-', dir=item['alias'])
    try:
        os.write(descriptor, b'#!/bin/sh\nexit 0\n'); os.fchmod(descriptor, 0o755); os.fsync(descriptor)
        os.close(descriptor); descriptor = None
        subprocess.run([filename], check=True, timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        original = item['source'] + '/' + Path(filename).name
        try: subprocess.run([original], check=False, timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except PermissionError: pass
        else: raise RuntimeError('Original parent unexpectedly permits direct execution')
    finally:
        if descriptor is not None: os.close(descriptor)
        os.unlink(filename)


def as_deck(action, item, runner=run):
    return runner(['runuser', '-u', 'deck', '--', '/usr/bin/python3', '-I', '-B', str(CODE / 'ntfs_steam.py'), action, '--partuuid', item['partuuid']], timeout=15)


def uncovered_alias(item, runner):
    # An idle autofs mount obscures its underlying directory. Stop only that
    # selected automount, then refuse inspection if any mount still covers it.
    runner(['systemctl', 'stop', unit(item['alias']).removesuffix('.mount') + '.automount'])
    try:
        reply = runner(['findmnt', '--json', '--mountpoint', item['alias'], '--output', 'TARGET,FSTYPE'])
    except subprocess.CalledProcessError as error:
        if error.returncode != 1: raise
    else:
        if json.loads(reply.stdout).get('filesystems'): raise RuntimeError('Alias remains mounted; retry preparation')
    alias_directory(item['alias'])


def prepare_one(item, config, runner=run, previous=None):
    check_device(item, runner)
    runner(['systemctl', 'start', '--no-block', unit(item['parent'])])
    parent = find_mount(item['parent'], runner); parent_policy(parent, config)
    if parent.get('maj:min') != device_number(item): raise RuntimeError('Parent mount is not the selected partition')
    as_deck('make-directory', item, runner)
    newly_requested = False
    try:
        # Existing prepared mounts need no empty underlying-directory inspection.
        try: alias = find_mount(item['alias'], runner)
        except (subprocess.CalledProcessError, RuntimeError):
            uncovered_alias(item, runner)
            check_device(item, runner)
            fresh = find_mount(item['parent'], runner); parent_policy(fresh, config)
            if not same_mount(parent, fresh): raise RuntimeError('Parent mount changed before bind')
            info = os.lstat(item['source'])
            if not stat.S_ISDIR(info.st_mode): raise RuntimeError('SteamLibrary changed before bind')
            runner(['systemctl', 'start', '--no-block', unit(item['alias'])])
            newly_requested = True
            alias = find_mount(item['alias'], runner)
        alias_policy(alias, parent)
        if not same_mount(parent, find_mount(item['parent'], runner)): raise RuntimeError('Parent mount changed while binding')
        mount_id = alias.get('id')
        if not (previous and previous.get('status') == 'prepared' and mount_id is not None and
                previous.get('mount_id') == mount_id and previous.get('device') == parent['maj:min']):
            as_deck('probe', item, runner)
        return {'status': 'prepared', 'alias': item['alias'], 'parent': item['parent'], 'device': parent['maj:min'], 'mount_id': mount_id}
    except Exception as error:
        pending = isinstance(error, MountPending) or (isinstance(error, subprocess.CalledProcessError) and
                  error.returncode == 1 and error.cmd[0] == 'findmnt')
        if newly_requested and not pending:
            try: runner(['systemctl', 'stop', unit(item['alias'])])
            except Exception: pass  # Preserve the original validation refusal.
        raise


def write_status(value):
    directory = STATUS.parent
    try: directory.mkdir(mode=0o755)
    except FileExistsError: pass
    trusted(directory, directory=True)
    fd, temporary = tempfile.mkstemp(prefix='.status-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o644); json.dump(value, output); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, STATUS)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def prepare(config, runner=run, writer=write_status, previous=None):
    if os.geteuid() != 0: raise RuntimeError('Root preparation required')
    if previous is None:
        try: previous = read_json(STATUS)
        except (OSError, ValueError, RuntimeError): previous = {}
    if previous.get('config') != config: previous = {}
    result = {'schema': 1, 'config': config, 'mounts': {item['partuuid']: {'status': 'pending'} for item in config['mounts']}}
    writer(result)
    for item in config['mounts']:
        try: value = prepare_one(item, config, runner, previous.get('mounts', {}).get(item['partuuid']))
        except Exception as error: value = {'status': 'pending', 'reason': str(error)[:512]}
        result['mounts'][item['partuuid']] = value
        writer(result)
    return result


def stop(config, runner=run):
    """Explicit restore only: stop our retries/binds, preserve parents and games."""
    if os.geteuid() != 0: raise RuntimeError('Root restoration required')
    runner(['systemctl', 'stop', 'oxp3-ntfs-steam-prepare.timer', 'oxp3-ntfs-steam-prepare.service'])
    runtime = '/run/user/' + str(config['uid'])
    if Path(runtime + '/bus').is_socket():
        runner(['runuser', '-u', 'deck', '--', 'env', 'XDG_RUNTIME_DIR=' + runtime,
                'DBUS_SESSION_BUS_ADDRESS=unix:path=' + runtime + '/bus', 'systemctl', '--user', 'stop',
                'oxp3-ntfs-steam-register.timer', 'oxp3-ntfs-steam-register.service'])
    for item in reversed(config['mounts']):
        # Stop only selected child units. A busy bind aborts restoration.
        runner(['systemctl', 'stop', unit(item['alias']).removesuffix('.mount') + '.automount', unit(item['alias'])])
    if STATUS.exists():
        trusted(STATUS); STATUS.unlink()
    return {'status': 'stopped', 'steam_registration': 'preserved', 'library_data': 'preserved'}


class WebSocket:
    """Small bounded localhost CDP transport, with handshake verification."""
    def __init__(self, url, deadline):
        parsed = urlsplit(url)
        if parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1' or parsed.port != 8080 or parsed.username or parsed.password or parsed.fragment or not parsed.path.startswith('/devtools/') or any(c in url for c in '\r\n'): raise RuntimeError('Invalid local Steam debugger URL')
        self.deadline, self.buffer = deadline, b''
        self.socket = socket.create_connection(('127.0.0.1', 8080), timeout=self.remaining())
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            target = parsed.path + ('?' + parsed.query if parsed.query else '')
            self.socket.sendall((f'GET {target} HTTP/1.1\r\nHost: 127.0.0.1:8080\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            while b'\r\n\r\n' not in self.buffer:
                self.socket.settimeout(self.remaining()); chunk = self.socket.recv(4096)
                if not chunk or len(self.buffer) + len(chunk) > 16384: raise RuntimeError('Invalid debugger handshake')
                self.buffer += chunk
            header, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
            lines = header.decode('ascii').split('\r\n'); headers = {name.lower(): value for line in lines[1:] if ':' in line for name, value in [line.split(':', 1)]}
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if ' 101 ' not in lines[0] or headers.get('sec-websocket-accept', '').strip() != expected: raise RuntimeError('Debugger handshake verification failed')
        except BaseException:
            self.socket.close(); raise

    def remaining(self):
        value = self.deadline - time.monotonic()
        if value <= 0: raise TimeoutError('Steam query deadline exceeded')
        return min(value, 5)

    def read(self, size):
        if size > MAXIMUM: raise RuntimeError('Debugger message exceeds limit')
        while len(self.buffer) < size:
            self.socket.settimeout(self.remaining()); chunk = self.socket.recv(min(65536, size - len(self.buffer)))
            if not chunk: raise RuntimeError('Debugger connection closed')
            self.buffer += chunk
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def send(self, data, opcode=1):
        mask = os.urandom(4); size = len(data)
        if size > MAXIMUM: raise RuntimeError('Debugger request exceeds limit')
        header = bytes([128 | opcode, 128 | size]) if size < 126 else bytes([128 | opcode, 254]) + struct.pack('>H', size)
        self.socket.settimeout(self.remaining()); self.socket.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        data = b''
        while True:
            first, second = self.read(2); size = second & 127; opcode = first & 15
            if first & 112 or second & 128: raise RuntimeError('Invalid debugger frame')
            if size == 126: size = struct.unpack('>H', self.read(2))[0]
            elif size == 127: size = struct.unpack('>Q', self.read(8))[0]
            if size + len(data) > MAXIMUM: raise RuntimeError('Debugger message exceeds limit')
            chunk = self.read(size)
            if opcode == 8: raise RuntimeError('Debugger connection closed')
            if opcode == 9:
                if size > 125: raise RuntimeError('Invalid debugger ping')
                self.send(chunk, 10); continue
            if opcode == 10: continue
            if opcode not in (0, 1): raise RuntimeError('Unexpected debugger frame')
            data += chunk
            if first & 128: return data.decode('utf-8')


def steam_query(expression):
    deadline = time.monotonic() + 25
    connection = http.client.HTTPConnection('127.0.0.1', 8080, timeout=5)
    try:
        connection.request('GET', '/json'); response = connection.getresponse()
        if response.status != 200: raise RuntimeError('Steam debugger is unavailable')
        data = b''
        while True:
            if time.monotonic() >= deadline: raise TimeoutError('Steam target list deadline exceeded')
            chunk = response.read1(min(65536, MAXIMUM + 1 - len(data)))
            if not chunk: break
            data += chunk
            if len(data) > MAXIMUM: raise RuntimeError('Steam target list exceeds limit')
        targets = json.loads(data)
    finally: connection.close()
    matches = [target for target in targets if target.get('title') == 'SharedJSContext' and target.get('type') == 'page' and urlsplit(target.get('url', '')).hostname == 'steamloopback.host']
    if len(matches) != 1: raise RuntimeError('Steam SharedJSContext is unavailable')
    websocket = WebSocket(matches[0]['webSocketDebuggerUrl'], deadline)
    try:
        websocket.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expression, 'awaitPromise': True, 'returnByValue': True}}).encode())
        for _ in range(256):
            reply = json.loads(websocket.receive())
            if reply.get('id') != 1: continue
            if reply.get('error') or reply.get('result', {}).get('exceptionDetails'): raise RuntimeError('Steam native API refused registration')
            return reply['result']['result'].get('value')
        raise RuntimeError('Too many debugger events')
    finally: websocket.socket.close()


def registration_expression(items):
    paths = [{'path': entry(item)['alias'], 'label': 'NTFS ' + item['mount_name']} for item in items]
    return '''(async()=>{const requested=REQUESTED;const api=SteamClient.InstallFolder;
const before=await api.GetInstallFolders();if(!Array.isArray(before))throw Error('Invalid install folders');
const result=[];for(const item of requested){let folders=await api.GetInstallFolders();
let found=folders.find(f=>f.strFolderPath===item.path);if(found){if(found.bIsMounted!==true)throw Error('Existing library is not mounted');result.push({path:item.path,status:'existing'});continue;}
const index=await api.AddInstallFolder(item.path);folders=await api.GetInstallFolders();found=folders.find(f=>f.strFolderPath===item.path);
if(!Number.isInteger(index)||!found||found.nFolderIndex!==index||found.bIsMounted!==true)throw Error('Steam did not mount selected library');await api.SetFolderLabel(index,item.label);
result.push({path:item.path,status:'added'});}return result;})()'''.replace('REQUESTED', json.dumps(paths))


def register(config, status=None, query=steam_query):
    if (os.geteuid(), os.getegid()) != (config['uid'], config['gid']): raise RuntimeError('Deck session required')
    status = read_json(STATUS) if status is None else status
    if status.get('schema') != 1 or status.get('config') != config: raise RuntimeError('No current root preparation report')
    selected = [item for item in config['mounts'] if status.get('mounts', {}).get(item['partuuid'], {}).get('status') == 'prepared']
    if not selected: return {'status': 'pending', 'reason': 'Libraries await root preparation'}
    # Recheck mount policy in the deck session; stale reports never authorize a different mount.
    for item in selected:
        parent = find_mount(item['parent']); parent_policy(parent, config)
        alias = find_mount(item['alias']); alias_policy(alias, parent)
        prepared = status['mounts'][item['partuuid']]
        if parent.get('maj:min') != prepared.get('device') or alias.get('id') != prepared.get('mount_id') or alias.get('id') is None: raise RuntimeError('Prepared mount changed')
    return {'status': 'registered', 'libraries': query(registration_expression(selected))}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=('prepare', 'register', 'make-directory', 'probe', 'stop')); parser.add_argument('--partuuid'); args = parser.parse_args()
    config = load_config()
    if args.action == 'prepare': result = prepare(config)
    elif args.action == 'stop': result = stop(config)
    elif args.action == 'register':
        try: result = register(config)
        except Exception as error: result = {'status': 'pending', 'reason': str(error)[:512]}
    else:
        if (os.geteuid(), os.getegid()) != (config['uid'], config['gid']): raise RuntimeError('Deck identity required')
        matches = [item for item in config['mounts'] if item['partuuid'] == args.partuuid]
        if len(matches) != 1: raise RuntimeError('Unselected partition')
        item = matches[0]; parent_policy(find_mount(item['parent']), config)
        if args.action == 'make-directory': make_directory(item)
        else: alias_policy(find_mount(item['alias']), find_mount(item['parent'])); probe(item)
        result = {'status': 'complete'}
    print(json.dumps(result))


if __name__ == '__main__': main()
