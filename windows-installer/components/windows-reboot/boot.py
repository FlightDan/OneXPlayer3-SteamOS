"""One-shot Windows or SteamOS boot-manager entry; never changes BootOrder."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess

EFI = '/usr/bin/efibootmgr'
SYSTEMCTL = '/usr/bin/systemctl'
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


def command(args):
    result = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=20, env=ENV)
    if result.returncode:
        raise RuntimeError(Path(args[0]).name + ': ' +
                           (result.stderr.strip()[:2048] or 'exit status ' + str(result.returncode)))
    return result.stdout


def parse(text):
    entries, manager_entries = [], []
    for line in text.splitlines():
        match = re.match(r'^Boot([0-9A-Fa-f]{4})(\*?)\s+(.+)$', line)
        if not match:
            continue
        number, active, detail = match.groups()
        # Match the actual Microsoft loader path, not an arbitrary entry label.
        path = re.search(r'(?:File\(\\EFI\\Microsoft\\Boot\\bootmgfw\.efi\)|'
                         r'/\\EFI\\Microsoft\\Boot\\bootmgfw\.efi(?=[0-9A-Fa-f]*(?:\s|$)))', detail, re.I)
        if path:
            entries.append({'id': number.upper(), 'active': bool(active),
                            'label': detail.split('\t', 1)[0].split('HD(', 1)[0].strip()})
        label = detail.split('\t', 1)[0].split('HD(', 1)[0].split('File(', 1)[0].strip()
        # The installer's SteamOS entry points at its ESP fallback, which hosts
        # rEFInd when selected. Never select an unrelated disk's fallback or
        # the official steamcl A/B loader that bypasses the system menu.
        manager_path = r'\\EFI\\OXP3-rEFInd\\refind_x64\.efi'
        if re.fullmatch(r'SteamOS(?: \(OXP3\))?', label, re.I):
            manager_path = r'\\EFI\\(?:BOOT\\BOOTX64\.EFI|OXP3-rEFInd\\refind_x64\.efi)'
        if re.search(r'(?:File\(' + manager_path + r'\)|/' + manager_path +
                     r'(?=[0-9A-Fa-f]*(?:\s|$)))', detail, re.I):
            manager_entries.append({'id': number.upper(), 'active': bool(active), 'label': label})
    next_boot = re.search(r'^BootNext:\s*([0-9A-Fa-f]{4})\s*$', text, re.M)
    return {'entries': entries, 'manager_entries': manager_entries,
            'boot_next': next_boot[1].upper() if next_boot else None}


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('Administrator permission is required. / 需要管理员权限。')
    if not Path('/sys/firmware/efi/efivars').is_dir():
        raise RuntimeError('UEFI variables are unavailable. / 无法访问 UEFI 启动变量。')
    for binary in (EFI, SYSTEMCTL):
        if not os.access(binary, os.X_OK):
            raise RuntimeError('Required system tool is missing: ' + binary)


@contextmanager
def reboot_lock():
    import fcntl
    descriptor = os.open('/run/lock/oxp3-windows-reboot.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RuntimeError('Untrusted reboot lock')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A reboot request is already running. / 正在处理重启请求。')
        yield
    finally:
        os.close(descriptor)


class Controller:
    def __init__(self, run=command):
        self.run = run

    def read(self):
        return parse(self.run([EFI, '-v']))

    def status(self, destination='windows'):
        if destination not in ('windows', 'manager'):
            raise ValueError('Invalid boot destination')
        preflight()
        state = self.read()
        candidates = state['entries' if destination == 'windows' else 'manager_entries']
        active = [entry for entry in candidates if entry['active']]
        reason = ''
        if destination == 'manager':
            if not candidates:
                reason = 'SteamOS boot-manager entry not found. / 未找到 SteamOS 启动管理器入口。'
            elif len(candidates) != 1:
                reason = 'Multiple boot-manager entries found. / 找到多个启动管理器入口，请先整理启动项。'
            elif not active:
                reason = 'Boot-manager entry is disabled. / 启动管理器入口已禁用。'
        elif not candidates:
            reason = 'Windows boot entry not found. / 未找到 Windows 启动项。'
        elif len(candidates) != 1:
            reason = 'Multiple Windows boot entries found. / 找到多个 Windows 启动项，请先整理启动项。'
        elif not active:
            reason = 'Windows boot entry is disabled. / Windows 启动项已禁用。'
        return dict(state, ready=not reason, reason=reason,
                    target=active[0]['id'] if not reason else None)

    def reboot(self, expected, destination='windows'):
        if not isinstance(expected, str) or not re.fullmatch('[0-9A-F]{4}', expected):
            raise ValueError('Invalid boot entry')
        preflight()
        with reboot_lock():
            state = self.status(destination)
            if not state['ready']:
                raise RuntimeError(state['reason'])
            if state['target'] != expected:
                raise RuntimeError('Boot entry changed. Refresh and try again. / 启动项已变化，请刷新后重试。')
            previous = state['boot_next']
            try:
                self.run([EFI, '-n', expected])
                if self.read()['boot_next'] != expected:
                    raise RuntimeError('BootNext verification failed. / 下一次启动设置验证失败。')
                self.run([SYSTEMCTL, 'reboot'])
            except Exception as error:
                # A failed command can still have written the variable. Restore
                # only our own value; do not overwrite another writer's choice.
                try:
                    if self.read()['boot_next'] == expected:
                        self.run([EFI, '-n', previous] if previous else [EFI, '-N'])
                        if self.read()['boot_next'] != previous:
                            raise RuntimeError('BootNext restoration did not persist')
                except Exception as recovery:
                    raise RuntimeError('Reboot failed; BootNext restoration also failed. / 重启失败，启动项恢复也失败：'
                                       + str(recovery)) from error
                raise RuntimeError('Reboot was not completed. / 未能完成重启：' + str(error)) from error
            return {'reboot_requested': True, 'target': expected}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'reboot', 'status-manager', 'reboot-manager'])
    parser.add_argument('expected', nargs='?')
    args = parser.parse_args()
    try:
        restarting = args.action in ('reboot', 'reboot-manager')
        if restarting and args.expected is None:
            raise ValueError('Expected boot entry is required')
        if not restarting and args.expected is not None:
            raise ValueError('Status takes no arguments')
        controller = Controller()
        destination = 'manager' if args.action.endswith('-manager') else 'windows'
        data = controller.reboot(args.expected, destination) if restarting else controller.status(destination)
        print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
