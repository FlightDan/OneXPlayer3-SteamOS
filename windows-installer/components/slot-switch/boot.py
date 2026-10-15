"""Restricted SteamOS A/B boot selection; no image writes or EFI BootOrder edits."""
import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile

BOOT = '/usr/bin/steamos-bootconf'
SYSTEMCTL = '/usr/bin/systemctl'
BUSCTL = '/usr/bin/busctl'
CONF = Path('/esp/SteamOS/conf')
RECORDS = Path('/home/.oxp3-installer/integration')
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


def command(args):
    result = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30, env=ENV)
    if result.returncode:
        raise RuntimeError(Path(args[0]).name + ': ' + (result.stderr.strip()[:1024] or str(result.returncode)))
    return result.stdout.strip()


def read_file(path, maximum=65536):
    """Reject writable or linked ancestors before reading root-owned metadata."""
    path = Path(path)
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Untrusted boot metadata directory: ' + str(parent))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Untrusted boot metadata: ' + str(path))
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise RuntimeError('Oversized boot metadata')
    return data, stat.S_IMODE(info.st_mode)


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('Administrator permission required. / 需要管理员权限。')
    if not re.search(r'^ID=["\']?steamos["\']?$', Path('/etc/os-release').read_text(), re.M):
        raise RuntimeError('This tool requires SteamOS. / 此工具仅适用于 SteamOS。')
    for tool in (BOOT, SYSTEMCTL, BUSCTL):
        if not os.access(tool, os.X_OK):
            raise RuntimeError('Required tool missing: ' + tool)


@contextmanager
def reboot_lock():
    import fcntl
    # Share the lock with the Windows reboot helper.
    fd = os.open('/run/lock/oxp3-windows-reboot.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise RuntimeError('Untrusted reboot lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another reboot request is running. / 正在处理另一个重启请求。')
        yield
    finally:
        os.close(fd)


def restore_file(path, original, expected):
    if read_file(path) != expected:
        raise RuntimeError('Boot configuration changed again; automatic restoration refused. / 启动配置再次变化，未自动覆盖。')
    fd, temporary = tempfile.mkstemp(prefix='.oxp3-restore-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(original[0]); output.flush(); os.fchmod(output.fileno(), original[1]); os.fsync(output.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class Controller:
    def __init__(self, run=command, conf=CONF, records=RECORDS):
        self.run, self.conf, self.records = run, Path(conf), Path(records)

    def configs(self):
        return {slot: read_file(self.conf / (slot + '.conf')) for slot in ('A', 'B')}

    @contextmanager
    def update_guard(self, stop_updaters=False):
        """Exclude activation; stop atomupd only with explicit consent and RAUC idle."""
        services = ('atomupd.service', 'rauc.service')
        added = []
        restart_atomupd = False
        result = {'reboot_requested': False}
        def active(service):
            return self.run([SYSTEMCTL, 'show', service, '-p', 'ActiveState', '--value'])

        def masks_verified():
            for service in services:
                if self.run([SYSTEMCTL, 'show', service, '-p', 'UnitFileState', '--value']) not in ('masked', 'masked-runtime'):
                    raise RuntimeError('Cannot exclude system updates. / 无法暂时阻止系统更新。')

        def no_job(service):
            # systemctl prints Job= for job ID zero (--all preserves empty
            # properties). A missing/unknown property must fail closed too.
            if self.run([SYSTEMCTL, 'show', service, '-p', 'Job', '--all']) != 'Job=':
                raise RuntimeError('Updater has a queued job or unknown job state; wait and try again. / 更新服务有排队任务或任务状态未知，请稍后重试。')

        def rauc_inactive():
            # An idle RAUC daemon may accept an install immediately after its
            # Operation property is read. Never stop it, even when it says idle.
            no_job('rauc.service')
            if active('rauc.service') not in ('inactive', 'failed'):
                raise RuntimeError('RAUC is running or starting; it cannot be safely interrupted, even if idle. Wait for it to exit or use the boot recovery menu. / RAUC 正在运行或启动，即使空闲也不能安全中断。请等待退出或使用开机恢复菜单。')
            self.idle()

        try:
            states = {service: active(service) for service in services}
            if states['rauc.service'] not in ('inactive', 'failed'):
                rauc_inactive()
            if states['atomupd.service'] not in ('inactive', 'failed'):
                if not stop_updaters:
                    raise RuntimeError('A system updater service is running. Explicitly choose temporary updater stopping or use the boot recovery menu. / 系统更新服务仍在运行，请明确选择临时停止更新服务，或使用开机恢复菜单。')
                if states['atomupd.service'] != 'active':
                    raise RuntimeError('Updater is changing state; wait and try again. / 更新服务状态正在变化，请稍后重试。')
            self.idle()
            for service in services:
                if self.run([SYSTEMCTL, 'show', service, '-p', 'UnitFileState', '--value']) not in ('masked', 'masked-runtime'):
                    # Track even a command that writes its mask and then fails.
                    added.append(service)
                    self.run([SYSTEMCTL, 'mask', '--runtime', service])
                elif service == 'atomupd.service' and states[service] == 'active':
                    raise RuntimeError('The running updater was already masked; it could not be restarted safely on failure. / 运行中的更新服务已被屏蔽，失败后无法安全恢复，未停止服务。')
            masks_verified()
            # Mask both activation paths first, then recheck RAUC before any
            # stop. This also rejects installs that started during masking.
            rauc_inactive()
            no_job('atomupd.service')
            atomupd_state = active('atomupd.service')
            if atomupd_state not in ('inactive', 'failed'):
                if not stop_updaters or states['atomupd.service'] != 'active' or atomupd_state != 'active':
                    raise RuntimeError('Updater started concurrently; no slot switch performed. / 更新服务同时启动，未切换槽位。')
                # A stop command may stop the service and then fail or time out.
                # Record recovery responsibility before issuing it.
                restart_atomupd = True
                self.run([SYSTEMCTL, 'stop', 'atomupd.service'])
            masks_verified()
            for service in services:
                no_job(service)
                if active(service) not in ('inactive', 'failed'):
                    raise RuntimeError('Updater started concurrently; no slot switch performed. / 更新服务同时启动，未切换槽位。')
            self.idle()
            yield result
        finally:
            # Successful reboot clears /run masks on next boot. Existing masks
            # are never removed. Failed/cancelled operations restore activation.
            if not result['reboot_requested']:
                errors = []
                for service in reversed(added):
                    try: self.run([SYSTEMCTL, 'unmask', '--runtime', service])
                    except Exception as error: errors.append(service + ': ' + str(error))
                if restart_atomupd:
                    try:
                        if active('atomupd.service') != 'active':
                            self.run([SYSTEMCTL, 'start', 'atomupd.service'])
                            if active('atomupd.service') != 'active':
                                raise RuntimeError('Updater did not return to its previous running state')
                    except Exception as error: errors.append('atomupd.service restart: ' + str(error))
                if errors:
                    raise RuntimeError('Could not restore temporary updater masks or running state. / 无法恢复临时更新服务设置或运行状态：' + '; '.join(errors))

    def idle(self):
        # Reading the bus name list must not activate a paused RAUC service.
        listing = self.run([BUSCTL, '--system', '--no-pager', '--no-legend', 'list'])
        owners = [line.split() for line in listing.splitlines()
                  if line.split() and line.split()[0] == 'de.pengutronix.rauc']
        if owners and len(owners[0]) > 1 and owners[0][1].isdigit():
            operation = self.run([BUSCTL, '--system', 'get-property', 'de.pengutronix.rauc', '/',
                                  'de.pengutronix.rauc.Installer', 'Operation'])
            if operation != 's "idle"':
                raise RuntimeError('A system update is running. Wait for it to finish. / 系统更新正在进行，请等待完成。')
        elif self.run([SYSTEMCTL, 'show', 'rauc.service', '-p', 'ActiveState', '--value']) not in ('inactive', 'failed'):
            raise RuntimeError('Cannot verify updater state. / 无法确认系统更新状态。')

    def value(self, slot, key):
        output = self.run([BOOT, 'config', '--no-create', '--image', slot, '--get', key])
        # Official tool prints key: value pairs. Missing keys have no output.
        if not output: return 0
        match = re.fullmatch(re.escape(key) + r'\s*:\s*(\d+)', output)
        if not match: raise RuntimeError('Unrecognized boot configuration value: ' + key)
        return int(match[1])

    def status(self):
        preflight()
        self.idle()
        current = self.run([BOOT, 'this-image'])
        selected = self.run([BOOT, 'selected-image'])
        if current not in ('A', 'B') or selected not in ('A', 'B'):
            raise RuntimeError('Cannot identify the SteamOS slots. / 无法识别 SteamOS 槽位。')
        configs = self.configs()
        target = 'B' if current == 'A' else 'A'
        invalid = self.value(target, 'image-invalid')
        if invalid:
            raise RuntimeError('The other slot is marked invalid. Use the boot recovery menu. / 另一槽已被标记为无效，请使用开机恢复菜单。')
        records = {}
        for slot in ('A', 'B'):
            try:
                raw, _ = read_file(self.records / slot / 'result.json', 2 * 1024 * 1024)
                data = json.loads(raw)
                if data.get('slot') == slot:
                    records[slot] = {'version': data.get('release', {}).get('version'),
                                     'system': data.get('system', {}).get('VERSION_ID'),
                                     'build': data.get('system', {}).get('BUILD_ID')}
            except FileNotFoundError:
                pass
        token = hashlib.sha256(current.encode() + selected.encode() +
                               b''.join(configs[s][0] for s in ('A', 'B'))).hexdigest()
        return {'current': current, 'selected': selected, 'target': target, 'token': token,
                'current_system': Path('/etc/os-release').read_text(), 'installation_records': records}

    def reboot(self, target, token, stop_updaters=False):
        if target not in ('A', 'B') or not re.fullmatch('[0-9a-f]{64}', token):
            raise ValueError('Invalid slot request')
        preflight()
        with reboot_lock(), self.update_guard(stop_updaters=stop_updaters) as guard:
            state = self.status()
            if state['target'] != target or state['token'] != token:
                raise RuntimeError('Slot state changed. Reopen this tool. / 槽位状态已变化，请重新打开工具。')
            original = self.configs()
            original_token = hashlib.sha256(state['current'].encode() + state['selected'].encode() +
                                            b''.join(original[s][0] for s in ('A', 'B'))).hexdigest()
            if original_token != token:
                raise RuntimeError('Slot state changed. Reopen this tool. / 槽位状态已变化，请重新打开工具。')
            # Future timestamps left by another update can outrank "now".
            stamp = max(int(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')),
                        *(self.value(s, 'boot-requested-at') + 1 for s in ('A', 'B')))
            if stamp >= 2**64: raise RuntimeError('Invalid boot timestamp')
            self.idle()
            written = None
            try:
                # Only the destination is changed; the current slot remains a fallback.
                self.run([BOOT, 'config', '--no-create', '--image', target,
                          '--set', 'boot-requested-at', str(stamp), '--set', 'boot-attempts', '0'])
                written = self.configs()
                other = state['current']
                if written[other] != original[other]:
                    raise RuntimeError('The current slot configuration changed concurrently')
                self.idle()
                if self.run([BOOT, 'selected-image']) != target:
                    raise RuntimeError('Slot selection verification failed. / 槽位选择验证失败。')
                self.run([SYSTEMCTL, 'reboot'])
                guard['reboot_requested'] = True
            except Exception as error:
                try:
                    # A failed command may have written the target already.
                    if written is None:
                        if self.configs() != original:
                            raise RuntimeError('Failed write has uncertain ownership; preserve current files')
                        written = original
                    if written[state['current']] != original[state['current']]:
                        raise RuntimeError('Concurrent boot configuration change; preserve current files')
                    if written[target] != original[target]:
                        restore_file(self.conf / (target + '.conf'), original[target], written[target])
                    if self.configs() != original:
                        raise RuntimeError('Restored boot configuration did not persist')
                except Exception as recovery:
                    raise RuntimeError('Reboot failed; restoration also failed. Use the boot recovery menu. / 重启失败，配置恢复也失败，请使用开机恢复菜单：' + str(recovery)) from error
                raise RuntimeError('Reboot was not completed; boot selection restored. / 重启未完成，已恢复原启动配置：' + str(error)) from error
        return {'reboot_requested': True, 'target': target}


def console_switch(controller, stop_updaters=False):
    if not sys.stdin.isatty():
        raise RuntimeError('Interactive terminal required. / 请在终端中运行并确认。')
    state = controller.status()
    print('Current slot / 当前槽：' + state['current'])
    print('Target slot / 目标槽：' + state['target'])
    print(state.get('current_system', '').strip())
    if stop_updaters:
        print('Temporarily stop background update checks only if safe; active RAUC still blocks switching.\n'
              '已选择临时停止后台更新检查；RAUC 正在运行时仍会拒绝切换。')
    print('Save your work. This selects the other system slot and requests a reboot; it does not repair that slot.\n'
          '请保存文件。此操作选择另一系统槽并重启，不会修复另一槽。')
    expected = 'SWITCH ' + state['target']
    try:
        confirmed = input('Type / 输入 ' + expected + ' to continue / 确认继续：') == expected
    except (EOFError, KeyboardInterrupt):
        return {'cancelled': True}
    if not confirmed:
        return {'cancelled': True}
    # Once confirmed, terminal Ctrl-C/closure must not interrupt boot-config
    # writes or their exception rollback. Restore handlers after the operation.
    saved = {}
    try:
        for name in ('SIGINT', 'SIGHUP'):
            number = getattr(signal, name, None)
            if number is not None:
                saved[number] = signal.signal(number, signal.SIG_IGN)
        return controller.reboot(state['target'], state['token'], stop_updaters=stop_updaters)
    finally:
        for number, handler in reversed(tuple(saved.items())):
            signal.signal(number, handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'reboot', 'switch'))
    parser.add_argument('target', nargs='?')
    parser.add_argument('token', nargs='?')
    parser.add_argument('--stop-updaters', action='store_true',
                        help='Temporarily stop atomupd only when RAUC is inactive; restore it if reboot fails')
    args = parser.parse_args()
    try:
        if args.action == 'status' and (args.target is not None or args.token is not None or args.stop_updaters):
            raise ValueError('Status takes no arguments')
        if args.action == 'reboot' and (args.target is None or args.token is None):
            raise ValueError('Target and state token required')
        if args.action == 'switch' and (args.target is not None or args.token is not None):
            raise ValueError('Interactive switch determines the target and state token itself')
        controller = Controller()
        if args.action == 'status':
            data = controller.status()
        elif args.action == 'switch':
            data = console_switch(controller, stop_updaters=args.stop_updaters)
        else:
            data = controller.reboot(args.target, args.token, stop_updaters=args.stop_updaters)
        print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
