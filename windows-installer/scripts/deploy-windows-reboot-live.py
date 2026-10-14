"""SSH-side, journaled deployment to the current OXP3 slot. Never requests reboot."""
import argparse
from contextlib import contextmanager
import datetime
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import zipfile

BASE = Path('/home/.oxp3-installer/live-windows-reboot')
PLUGIN = Path('/var/lib/oxp3-installer/decky/runtime/plugins/oxp3-restart-windows')
ARTIFACTS = ('main.py', 'plugin.json', 'package.json', 'dist/index.js', 'boot.py', 'desktop.py',
             'oxp3-reboot-windows', 'oxp3-reboot-windows.desktop',
             'org.oxp3.restart-windows.policy', '49-oxp3-restart-windows.rules')


def run(*args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60).stdout


def guard():
    assert os.geteuid() == 0, 'Root required'
    assert Path('/sys/class/dmi/id/product_name').read_text().strip() == 'ONEXPLAYER 3'
    assert 'BUILD_ID=20260924.1000' in Path('/etc/os-release').read_text()
    unit = run('systemctl', 'cat', 'plugin_loader.service')
    assert 'Environment=PRIVILEGED_PATH=/var/lib/oxp3-installer/decky/runtime' in unit
    assert 'Environment=CHOWN_PLUGIN_PATH=0' in unit


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077


@contextmanager
def writable():
    previous = run('/usr/bin/steamos-readonly', 'status').strip()
    assert previous in ('enabled', 'disabled'), 'Unexpected root protection state'
    if previous == 'enabled': run('/usr/bin/steamos-readonly', 'disable')
    try:
        yield previous
    finally:
        if previous == 'enabled': run('/usr/bin/steamos-readonly', 'enable')


def boot_settings():
    return [line for line in run('/usr/bin/efibootmgr').splitlines()
            if line.startswith(('BootOrder:', 'BootNext:'))]


def transaction(directory):
    sys.path.insert(0, str(directory / 'payload'))
    from file_transaction import FileTransaction
    metadata = json.loads((directory / 'metadata.json').read_text())

    class LiveFiles(FileTransaction):
        def installed_metadata(self, path, original):
            return metadata[path]

    return LiveFiles(directory / 'files', metadata)


def install(archive):
    guard()
    run('systemctl', 'is-active', '--quiet', 'plugin_loader.service')
    before = boot_settings()
    # The installed image may expose its shared record parent as 0755. Keep
    # that existing mode; only this deployment's own backup must be private.
    parent = BASE.parent
    parent.mkdir(mode=0o700, exist_ok=True)
    info = parent.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    private_directory(BASE)
    directory = BASE / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + os.urandom(4).hex())
    private_directory(directory)
    payload = directory / 'payload'; private_directory(payload)
    expected = {'windows_reboot.py', 'file_transaction.py',
                *('windows-reboot/' + name for name in ARTIFACTS)}
    with zipfile.ZipFile(archive) as package:
        assert set(package.namelist()) == expected and len(package.infolist()) == len(expected)
        assert sum(item.file_size for item in package.infolist()) < 2 * 1024 * 1024
        for name in sorted(expected):
            target = payload / name
            target.parent.mkdir(mode=0o700, exist_ok=True)
            target.write_bytes(package.read(name)); target.chmod(0o600)
    shutil.copyfile(__file__, directory / 'deploy.py')
    sys.path.insert(0, str(payload))
    from windows_reboot import files
    from file_transaction import atomic_write
    values = files('/', payload)
    user = pwd.getpwnam('deck')
    metadata = {str(Path('/') / name): dict(mode=entry['mode'],
                uid=user.pw_uid if entry['user'] else 0, gid=user.pw_gid if entry['user'] else 0)
                for name, entry in values.items()}
    atomic_write(directory / 'metadata.json', (json.dumps(metadata, indent=2) + '\n').encode(), 0o600, 0, 0)
    operation = transaction(directory)
    print('WINDOWS_REBOOT_BACKUP=' + str(directory), flush=True)
    with writable() as previous:
        try:
            for name, entry in values.items():
                path = Path('/') / name
                missing = []; parent = path.parent
                while not parent.exists(): missing.append(parent); parent = parent.parent
                for parent in reversed(missing):
                    parent.mkdir(mode=0o755); parent.chmod(0o755)
                    os.chown(parent, user.pw_uid if entry['user'] else 0, user.pw_gid if entry['user'] else 0)
            operation.apply({str(Path('/') / name): entry['data'] for name, entry in values.items()})
            reply = json.loads(run('/usr/local/bin/oxp3-reboot-windows', 'status'))
            assert reply['ok'] and reply['data']['ready'], reply
            assert boot_settings() == before, 'Boot settings changed during read-only validation'
            run('systemctl', 'restart', 'plugin_loader.service')
            run('systemctl', 'is-active', '--quiet', 'plugin_loader.service')
            report = dict(installed=True, backup=str(directory), windows=reply['data'],
                          readonly_before=previous, boot_settings=before, reboot_requested=False)
            atomic_write(directory / 'deployment.json', (json.dumps(report, indent=2) + '\n').encode(), 0o600, 0, 0)
        except BaseException:
            if operation.state.exists():
                errors = operation.rollback()
                print('WINDOWS_REBOOT_RESTORE_ERRORS=' + json.dumps(errors), flush=True)
            run('systemctl', 'restart', 'plugin_loader.service')
            raise
    report['readonly_after'] = run('/usr/bin/steamos-readonly', 'status').strip()
    print(json.dumps(report, indent=2), flush=True)


def restore(directory):
    guard()
    directory = Path(directory).absolute()
    assert directory.parent == BASE
    private_directory(directory)
    operation = transaction(directory)
    with writable():
        errors = operation.rollback()
        run('systemctl', 'restart', 'plugin_loader.service')
    print(json.dumps({'restored': not errors, 'errors': errors}))
    if errors: raise RuntimeError('Restoration conflicts require inspection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'restore']); parser.add_argument('path')
    args = parser.parse_args()
    if args.action == 'install': install(args.path)
    else: restore(args.path)
