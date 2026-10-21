#!/usr/bin/python3
"""X2mini KDE HDR trial. No display changes before a detached guard is ready."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import locale
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

# -I deliberately removes the script directory from sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from x2mini_device import is_x2mini, install_launchers, cleanup_launchers

PROFILE = 'X2MINI_HDR_TRIAL_475_700_V1'
POLICY = 'OXP3_GAMMA22_POLICY_EDID_ONLY_V2'
PREFIX = Path('/opt/oxp3-desktop-gamma22/6.7.3-1.6')
TIMEOUT = 10.0
ACTIVE_PHASES = {'armed', 'enabled', 'visible', 'reverting', 'rollback_failed'}


def uid():
    return os.getuid() if hasattr(os, 'getuid') else None


def check_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item.lstat() if item.exists() else None, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Linked HDR state/configuration path refused')
    return path


def read_json(path, private=True):
    path = check_path(path)
    if not path.exists():
        return None
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024
            or uid() is not None and (info.st_uid != uid() or info.st_mode & (0o077 if private else 0o022))):
        raise RuntimeError('Unsafe HDR state/configuration file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, encoding='utf-8') as stream:
        return json.load(stream)


def write_json(path, value, private=True):
    path = check_path(path)
    previous = path.stat() if path.exists() else None
    if previous:
        read_json(path, private)
    fd, temporary = tempfile.mkstemp(prefix='.hdr-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o600) if hasattr(os, 'fchmod') else None
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Journal:
    def __init__(self, directory):
        self.directory = check_path(directory)
        self.path = self.directory / 'trial.json'

    @contextmanager
    def lock(self):
        check_path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.stat()
        if uid() is not None and (info.st_uid != uid() or info.st_mode & 0o077):
            raise RuntimeError('Private HDR state directory required')
        lock = check_path(self.directory / 'trial.lock')
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or uid() is not None and (info.st_uid != uid() or info.st_mode & 0o077)):
                raise RuntimeError('Unsafe HDR trial lock')
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:  # Allows file/state regressions on the Windows build host.
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            yield
        finally:
            os.close(fd)

    def read(self):
        value = read_json(self.path)
        if value is None and not self.path.exists():
            return None
        if (not isinstance(value, dict) or value.get('profile') != PROFILE
                or value.get('phase') not in ACTIVE_PHASES | {'confirmed', 'reverted'}
                or not re.fullmatch('[0-9a-f]{32}', str(value.get('token', '')))
                or type(value.get('deadline')) not in (int, float) or not math.isfinite(value['deadline'])
                or not isinstance(value.get('original'), dict)
                or set(value['original']) != {'hdr', 'wcg'}
                or any(type(flag) is not bool for flag in value['original'].values())
                or not isinstance(value.get('boot'), str)):
            raise RuntimeError('Invalid HDR trial journal; preserve for recovery')
        return value

    def save(self, value):
        write_json(self.path, value)


class Trial:
    def __init__(self, journal, backend, clock=time.monotonic, boot=None):
        self.journal, self.backend, self.clock = journal, backend, clock
        self.boot = boot if boot is not None else Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    def begin(self):
        original = self.backend.flags()
        with self.journal.lock():
            # Removal keeps a durable interlock outside the runtime tree. A
            # successful deployment explicitly clears it; a login cannot.
            if check_path(self.journal.directory / 'disabled.json').exists():
                raise RuntimeError('HDR trial is disabled during component restore; reinstall it first')
            old = self.journal.read()
            if old and old['phase'] in ACTIVE_PHASES:
                raise RuntimeError('An unconfirmed HDR trial needs recovery first')
            value = dict(profile=PROFILE, token=uuid.uuid4().hex, phase='armed',
                         original=original, deadline=self.clock() + TIMEOUT,
                         boot=self.boot, watchdog_ready=False)
            self.journal.save(value)
            return value['token']

    def guarded(self, token):
        with self.journal.lock():
            value = self.journal.read()
            return bool(value and value['token'] == token and value['boot'] == self.boot
                        and value['phase'] == 'armed' and value.get('watchdog_ready') is True
                        and self.clock() < value['deadline'])

    def arm_guard(self, token):
        with self.journal.lock():
            value = self.journal.read()
            if (not value or value['token'] != token or value['boot'] != self.boot
                    or value['phase'] != 'armed' or value.get('watchdog_ready')):
                raise RuntimeError('Trial guard token/state changed')
            value['watchdog_ready'] = True
            value['guard_pid'] = os.getpid()
            self.journal.save(value)

    def request_enable(self, token):
        with self.journal.lock():
            value = self.journal.read()
            if (not value or value['token'] != token or value['phase'] != 'armed'
                    or not value.get('watchdog_ready') or value.get('enable_requested')
                    or self.clock() >= value['deadline']):
                raise RuntimeError('HDR recovery guard is unavailable or expired')
            value['enable_requested'] = True
            # Guard startup is outside the user's ten-second display trial.
            # Only this first request may set the trial deadline.
            value['deadline'] = self.clock() + TIMEOUT
            self.journal.save(value)

    def activated(self, token):
        with self.journal.lock():
            value = self.journal.read()
            if (not value or value['token'] != token or value['phase'] != 'armed'
                    or value.get('guard_pid') != os.getpid() or not value.get('enable_requested')
                    or self.clock() >= value['deadline']):
                raise RuntimeError('HDR activation was cancelled or expired')
            value['phase'] = 'enabled'
            self.journal.save(value)

    def visible(self, token):
        with self.journal.lock():
            value = self.journal.read()
            if (not value or value['token'] != token or value['phase'] != 'enabled'
                    or not value.get('watchdog_ready') or self.clock() >= value['deadline']):
                raise RuntimeError('HDR trial expired before the first HDR frame')
            value['phase'] = 'visible'
            self.journal.save(value)

    def confirm(self, token):
        # No subprocess or compositor IPC while holding the watchdog's lock.
        if self.backend.flags() != {'hdr': True, 'wcg': True} or not self.backend.persisted_enabled():
            return False
        with self.journal.lock():
            value = self.journal.read()
            if (not value or value['token'] != token or value['boot'] != self.boot
                    or value['phase'] != 'visible' or not value.get('watchdog_ready')
                    or self.clock() >= value['deadline']):
                return False
            value['phase'] = 'confirmed'
            self.journal.save(value)
            return True

    def cancel(self, token):
        # The UI never performs display IPC, including on cancellation. Only
        # the detached guard can enable/restore, so old UI work cannot race a
        # later confirmed trial after the previous one becomes terminal.
        with self.journal.lock():
            value = self.journal.read()
            if not value or value['token'] != token or value['phase'] in {'confirmed', 'reverted'}:
                return
            value['phase'] = 'reverting' if value.get('watchdog_ready') else 'reverted'
            self.journal.save(value)

    def rollback(self, token):
        with self.journal.lock():
            value = self.journal.read()
            if not value or value['token'] != token or value['phase'] in {'confirmed', 'reverted'}:
                return True
            value['phase'] = 'reverting'
            self.journal.save(value)
        try:
            self.backend.restore(value['original'])
            success = True
        except Exception:
            success = False
        with self.journal.lock():
            current = self.journal.read()
            if current and current['token'] == token and current['phase'] != 'confirmed':
                current['phase'] = 'reverted' if success else 'rollback_failed'
                self.journal.save(current)
        return success

    def watchdog(self, token):
        self.arm_guard(token)
        try:
            while True:
                with self.journal.lock():
                    value = self.journal.read()
                if not value or value['token'] != token or value['phase'] in {'confirmed', 'reverted'}:
                    return
                if value.get('guard_pid') != os.getpid():
                    raise RuntimeError('HDR guard ownership changed')
                if value['boot'] != self.boot or self.clock() >= value['deadline'] or value['phase'] == 'reverting':
                    return
                if value['phase'] == 'armed' and value.get('enable_requested'):
                    self.backend.enable()
                    self.activated(token)
                time.sleep(0.05)
        finally:
            # No display IPC happens after terminal 'reverted' is published.
            # A delayed enable or exception is followed by restore in this
            # same owner before another trial is allowed to start.
            if not self.rollback(token):
                raise RuntimeError('HDR rollback failed; startup recovery remains armed')


def output_flags(value, require_internal_only=True):
    if require_internal_only and any(item.get('name') != 'eDP-1' and item.get('enabled') is True for item in value.get('outputs', [])):
        raise RuntimeError('Disconnect enabled external displays before the HDR trial / 请先断开已启用的外屏')
    outputs = [item for item in value.get('outputs', []) if item.get('name') == 'eDP-1']
    if len(outputs) != 1 or not outputs[0].get('enabled', False):
        raise RuntimeError('One enabled internal eDP-1 output required')
    flags = {name: outputs[0].get(name) for name in ('hdr', 'wcg')}
    if any(type(flag) is not bool for flag in flags.values()):
        raise RuntimeError('Unknown KScreen HDR/WCG state')
    return flags


def saved_outputs(value):
    if not isinstance(value, list):
        raise RuntimeError('Invalid KWin output settings')
    return [out for group in value if isinstance(group, dict) and group.get('name') == 'outputs'
            for out in group.get('data', []) if isinstance(out, dict) and out.get('connectorName') == 'eDP-1']


def recover_startup(journal, config):
    # Runs BEFORE KWin. Never depend on a working display/session for recovery.
    if not journal.path.exists() and not journal.path.is_symlink():
        return
    with journal.lock():
        trial = journal.read()
        if not trial or trial['phase'] in {'confirmed', 'reverted'}:
            return
        value = read_json(config, private=False)
        if value is not None or Path(config).exists():
            outputs = saved_outputs(value)
            if not outputs:
                raise RuntimeError('Pending HDR trial has no internal output to restore')
            for output in outputs:
                output['highDynamicRange'] = trial['original']['hdr']
                output['wideColorGamut'] = trial['original']['wcg']
            write_json(config, value, private=False)
        trial['phase'] = 'reverted'
        journal.save(trial)


class KDE:
    def __init__(self, home):
        self.config = home / '.config/kwinoutputconfig.json'

    def command(self, *args, timeout=1.5):
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
        return result.stdout

    def flags(self, require_internal_only=True):
        return output_flags(json.loads(self.command('/usr/bin/kscreen-doctor', '-j')), require_internal_only)

    def restore(self, flags):
        self.command('/usr/bin/kscreen-doctor', *[
            'output.eDP-1.' + key + ('.enable' if flags[key] else '.disable') for key in ('hdr', 'wcg')])
        self.command('/usr/bin/kscreen-doctor', '--dpms', 'on')
        if self.flags(require_internal_only=False) != flags:
            raise RuntimeError('KDE has not restored the previous display state')
        deadline = time.monotonic() + 0.5
        while not self.persisted_matches(flags):
            if time.monotonic() >= deadline:
                raise RuntimeError('KDE has not saved restored settings; startup recovery remains armed')
            time.sleep(0.05)

    def enable(self):
        self.flags()  # Recheck hotplug at the point of activation.
        self.command('/usr/bin/kscreen-doctor', 'output.eDP-1.hdr.enable', 'output.eDP-1.wcg.enable')
        if self.flags() != {'hdr': True, 'wcg': True}:
            raise RuntimeError('KDE did not enable HDR/WCG')

    def persisted_enabled(self):
        self.flags()  # A new external screen cannot be used to confirm the internal one.
        return self.persisted_matches({'hdr': True, 'wcg': True})

    def persisted_matches(self, flags):
        outputs = saved_outputs(read_json(self.config, private=False))
        return bool(outputs) and all(out.get('highDynamicRange') is flags['hdr'] and out.get('wideColorGamut') is flags['wcg'] for out in outputs)

    def check(self):
        if not is_x2mini():
            raise RuntimeError('This HDR trial is only available on X2mini / 此 HDR 测试仅适用于 X2mini')
        if os.environ.get('XDG_SESSION_TYPE') != 'wayland' or not any(
                name.casefold() in {'kde', 'plasma'} for name in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':')):
            raise RuntimeError('Run this test in the KDE Wayland desktop / 请在 KDE Wayland 桌面运行')
        for tool in ('kdialog', 'kscreen-doctor', 'qdbus6', 'systemd-run'):
            if not os.access('/usr/bin/' + tool, os.X_OK):
                raise RuntimeError('Required KDE tool missing: ' + tool)
        panels = list(Path('/sys/class/drm').glob('card*-eDP-1/edid'))
        if len(panels) != 1:
            raise RuntimeError('One internal eDP-1 EDID required / 内屏 EDID 缺失或不唯一')
        edid = panels[0].read_bytes()
        if len(edid) < 128 or edid[:12] != bytes((0, 255, 255, 255, 255, 255, 255, 0, 0x4c, 0x83, 1, 0x43)):
            raise RuntimeError('Internal SDC4301 panel check failed / 内屏面板不匹配')
        support = self.command('/usr/bin/qdbus6', 'org.kde.KWin', '/KWin', 'supportInformation')
        if POLICY not in support or PROFILE not in support:
            raise RuntimeError('The 475/700 mapped HDR runtime is not active / 475/700 HDR 运行时尚未就绪')
        if not os.access(PREFIX / 'bin/oxp3-hdr-pattern', os.X_OK):
            raise RuntimeError('HDR test pattern renderer missing / 缺少 HDR 测试图程序')
        self.flags()


def detached_guard(token, home):
    required = {'XDG_RUNTIME_DIR': '/run/user/' + str(uid())}
    if os.environ.get('XDG_RUNTIME_DIR') != required['XDG_RUNTIME_DIR']:
        raise RuntimeError('User runtime directory does not match this user')
    for name in ('DBUS_SESSION_BUS_ADDRESS', 'WAYLAND_DISPLAY'):
        value = os.environ.get(name, '')
        if not value or any(ord(char) < 32 for char in value):
            raise RuntimeError('KDE session environment missing')
        required[name] = value
    # A detached service (not a scope) survives closing/crashing the dialog.
    subprocess.run(['/usr/bin/systemd-run', '--user', '--quiet', '--collect',
                    '--property=Type=exec', '--expand-environment=no', '--unit=x2mini-hdr-' + token,
                    '--setenv=HOME=' + str(home),
                    *['--setenv=' + key + '=' + value for key, value in required.items()],
                    '/usr/bin/python3', '-I', '-B', str(Path(__file__).resolve()), '--watchdog', token],
                   check=True, timeout=2, capture_output=True)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.3)


def run_trial(home, journal):
    backend = KDE(home)
    backend.check()
    zh = (locale.getlocale()[0] or '').startswith('zh')
    title = 'X2mini HDR 测试' if zh else 'X2mini HDR Trial'
    notice = ('3 秒后切换 HDR。若黑屏请勿操作，10 秒后自动恢复。' if zh else
              'Switching to HDR in 3 seconds. If the screen goes black, do nothing; it will revert after 10 seconds.')
    subprocess.run(['/usr/bin/kdialog', '--title', title, '--passivepopup', notice, '3'], check=True, timeout=4)
    time.sleep(3)
    trial = Trial(journal, backend)
    token = trial.begin()
    pattern = dialog = None
    try:
        detached_guard(token, home)
        guard_wait = time.monotonic() + 1
        while not trial.guarded(token):
            if time.monotonic() >= guard_wait:
                raise RuntimeError('Independent HDR recovery task did not become ready')
            time.sleep(0.02)
        trial.request_enable(token)
        while True:
            with journal.lock():
                current = journal.read()
            if current['phase'] == 'enabled':
                break
            if current['phase'] != 'armed' or time.monotonic() >= current['deadline']:
                raise RuntimeError('HDR activation was cancelled or expired')
            time.sleep(0.02)
        pattern = subprocess.Popen([str(PREFIX / 'bin/oxp3-hdr-pattern'), '10', 'trial'],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        with selectors.DefaultSelector() as selector:
            selector.register(pattern.stdout, selectors.EVENT_READ)
            buffer = b''
            while b'FIRST_PRESENT_OK\n' not in buffer:
                with journal.lock():
                    current = journal.read()
                if pattern.poll() is not None or time.monotonic() >= current['deadline']:
                    raise RuntimeError('A real HDR test frame was not presented before timeout')
                if selector.select(0.05):
                    buffer += os.read(pattern.stdout.fileno(), 4096)
                    if len(buffer) > 65536:
                        raise RuntimeError('Unexpected HDR pattern output')
        trial.visible(token)
        text = ('画面、四个 HDR 色块和亮度都正常吗？\n未确认会在切换后 10 秒自动恢复。' if zh else
                'Are the picture, four HDR patches and brightness correct?\nReverts 10 seconds after switching unless confirmed.')
        dialog = subprocess.Popen(['/usr/bin/kdialog', '--title', title, '--warningyesno', text,
                                   '--yes-label', '确认并保存' if zh else 'Confirm and save',
                                   '--no-label', '恢复原设置' if zh else 'Restore previous settings', '--defaultno'])
        while dialog.poll() is None:
            with journal.lock():
                current = journal.read()
            if pattern.poll() is not None or current['phase'] != 'visible' or time.monotonic() >= current['deadline']:
                return False
            time.sleep(0.03)
        return dialog.returncode == 0 and pattern.poll() is None and trial.confirm(token)
    finally:
        stop(dialog)
        stop(pattern)
        # A failed/late confirmation never cancels the independent recovery job.
        trial.cancel(token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--device-check', action='store_true')
    actions.add_argument('--install-launcher', action='store_true')
    actions.add_argument('--uninstall-launcher', action='store_true')
    actions.add_argument('--recover-startup', action='store_true')
    actions.add_argument('--watchdog')
    args = parser.parse_args()
    if args.device_check:
        return 0 if is_x2mini() else 3
    if os.name != 'posix' or uid() == 0:
        raise RuntimeError('Run as the KDE desktop user, without sudo')
    home = Path.home()
    journal = Journal(home / '.local/state/x2mini-hdr')
    if args.recover_startup:
        recover_startup(journal, home / '.config/kwinoutputconfig.json')
    elif args.install_launcher:
        if not is_x2mini():
            print('X2mini not detected; no launcher installed')
            return 0
        install_launchers(home, Path(__file__).resolve())
    elif args.uninstall_launcher:
        cleanup_launchers(home)
    elif args.watchdog:
        Trial(journal, KDE(home)).watchdog(args.watchdog)
    else:
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, interrupted)
        result = run_trial(home, journal)
        if result:
            subprocess.run(['/usr/bin/kdialog', '--passivepopup', 'HDR 已确认并保存 / HDR confirmed and saved', '3'], timeout=4)
        return 0 if result else 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        if not any(flag in sys.argv for flag in ('--watchdog', '--recover-startup', '--install-launcher', '--uninstall-launcher', '--device-check')):
            subprocess.run(['/usr/bin/kdialog', '--error', str(error)], timeout=15, check=False)
        raise SystemExit(2)
