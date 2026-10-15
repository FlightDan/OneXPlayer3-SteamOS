"""KDE recovery launcher; status first, explicit save-and-reboot confirmation."""
import html
import json
import os
import re
import subprocess

HELPER = '/home/.oxp3-slot-switch/oxp3-switch-slot'
DIALOG = '/usr/bin/kdialog'
ZH = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', '')).startswith('zh')


def text(zh, en):
    return zh if ZH else en


def valid_data(args, data):
    """Validate fields consumed by the dialogs before offering a reboot."""
    if not isinstance(data, dict): return False
    if args[0] == 'reboot':
        return data.get('reboot_requested') is True and data.get('target') == args[1]
    if args[0] != 'status': return False
    if any(data.get(key) not in ('A', 'B') for key in ('current', 'selected', 'target')):
        return False
    if data['current'] == data['target']: return False
    token = data.get('token')
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{64}', token): return False
    if not isinstance(data.get('current_system', ''), str): return False
    records = data.get('installation_records')
    if not isinstance(records, dict): return False
    for slot in ('A', 'B'):
        record = records.get(slot, {})
        if not isinstance(record, dict): return False
        if any(record.get(key) is not None and not isinstance(record[key], str)
               for key in ('version', 'system', 'build')): return False
    return True


def helper(*args):
    # Each backend command has its own deadline. Do not kill the privileged
    # helper while it is restoring update services after a failed operation.
    try:
        result = subprocess.run(['/usr/bin/pkexec', HELPER, *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise RuntimeError(text('无法启动授权程序 pkexec。请检查系统的 polkit 安装。',
                                'Could not start pkexec. Check the system polkit installation.')) from None
    # Do not echo raw stdout/stderr: failed launchers can print environment or
    # other unrelated data. A backend JSON error is the supported diagnostic.
    invalid = text('后台程序未返回有效响应（退出码 {code}）。请检查槽位切换组件是否完整。',
                   'The helper did not return a valid response (exit status {code}). Check that the slot switch component is intact.')
    try: reply = json.loads(result.stdout)
    except ValueError: reply = None
    if not isinstance(reply, dict) or type(reply.get('ok')) is not bool:
        if result.returncode == 126:
            raise RuntimeError(text('授权已取消。', 'Authorization was cancelled.'))
        if result.returncode == 127:
            # pkexec uses 127 when authorization cannot be obtained; a child
            # launcher can also return 127 if its executable is unavailable.
            raise RuntimeError(text('未能获得授权或启动后台程序（退出码 127）。授权可能被拒绝，或认证代理不可用；也请检查槽位切换组件是否完整。',
                                    'Could not obtain authorization or start the helper (exit status 127). Authorization may have been denied or the authentication agent may be unavailable; also check that the slot switch component is intact.'))
        raise RuntimeError(invalid.format(code=result.returncode))
    if not reply['ok']:
        error = reply.get('error')
        if not isinstance(error, str) or not error.strip():
            raise RuntimeError(invalid.format(code=result.returncode))
        raise RuntimeError(error)
    if result.returncode or not valid_data(args, reply.get('data')):
        raise RuntimeError(invalid.format(code=result.returncode))
    return reply['data']


def message(state, stop_updaters=False):
    lines = [text('当前运行：{current} 槽；原定下次启动：{selected} 槽。',
                  'Running slot: {current}; scheduled boot slot: {selected}.').format(**state)]
    system = dict(line.split('=', 1) for line in state.get('current_system', '').splitlines() if '=' in line)
    if system.get('VERSION_ID'):
        lines.append(text('当前系统：SteamOS {version} / build {build}', 'Running OS: SteamOS {version} / build {build}')
                     .format(version=system['VERSION_ID'].strip('"'), build=system.get('BUILD_ID', '?').strip('"')))
    for slot in ('A', 'B'):
        record = state['installation_records'].get(slot, {})
        if record:
            lines.append(text('{slot} 槽安装时记录：适配版 {version} / SteamOS {system} / build {build}',
                              'Slot {slot} installation record: adapted release {version} / SteamOS {system} / build {build}')
                         .format(slot=slot, **{key: record.get(key) or '?' for key in ('version', 'system', 'build')}))
        else:
            lines.append(text('{slot} 槽：无适配安装记录。', 'Slot {slot}: no adaptation installation record.').format(slot=slot))
    lines += ['', text('即将重启到 {target} 槽，请先保存游戏和文件。',
                       'Restart into slot {target}. Save games and files first.').format(**state),
              text('安装记录可能因手动更新而过期，不能保证另一槽能正常启动。',
                   'Installation records may be outdated after manual updates; the other slot may not boot.'),
              text('这只切换系统，不恢复共享的游戏、存档和个人文件。',
                   'This switches the OS; shared games, saves and personal files are not restored.'),
              text('切换成功后将继续使用该槽，直到再次切换或系统更新。',
                   'After a successful boot, this slot remains selected until another switch or OS update.')]
    if stop_updaters:
        lines += ['', text('已选择：临时停止更新服务（后台检查）。仅在 RAUC 未运行时执行；失败时恢复，重启后临时屏蔽自动清除。',
                            'Selected: temporarily stop the update service (background checks), only when RAUC is inactive. Restore it on failure; temporary masks clear on reboot.'),
                  text('RAUC 运行或安装中时仍会拒绝切换，即使它报告空闲。',
                       'Switching is still refused while RAUC is running or installing, even if it reports idle.')]
    # KDE rich-text detection must not render content from metadata as markup.
    return '<qt>' + '<br/>'.join(html.escape(line) for line in lines) + '</qt>'


def main():
    try:
        state = helper('status')
        choice = subprocess.run([DIALOG, '--title', text('更新服务处理方式', 'Updater Handling'),
                                 '--checklist', text('默认不停止任何服务。可选择临时停止更新服务的后台检查；RAUC 正在运行或状态未知时仍会拒绝切换。失败时恢复更新服务，重启后清除临时屏蔽。',
                                                    'By default, no services are stopped. You may allow temporarily stopping background update checks. Running RAUC or unknown update state still blocks switching. The updater is restored on failure and temporary masks clear on reboot.'),
                                 'stop-updaters', text('临时停止更新服务（后台检查）', 'Temporarily stop update service (background checks)'), 'off'],
                                text=True, stdout=subprocess.PIPE, timeout=3600)
        if choice.returncode in (1, 2): return 0
        if choice.returncode != 0: raise RuntimeError(text('选项窗口无法打开。', 'Could not open the options dialog.'))
        selected = choice.stdout.strip()
        if selected not in ('', 'stop-updaters', '"stop-updaters"'):
            raise RuntimeError(text('无法识别更新服务选项。', 'Unrecognized updater option.'))
        stop_updaters = bool(selected)
        result = subprocess.run([DIALOG, '--title', text('SteamOS 槽位切换 / 系统回退', 'SteamOS Slot Switch / OS Recovery'),
                                 '--continue-label', text('切换并重启', 'Switch and Restart'),
                                 '--cancel-label', text('取消', 'Cancel'),
                                 '--warningcontinuecancel', message(state, stop_updaters)], timeout=3600)
        if result.returncode in (1, 2): return 0
        if result.returncode != 0: raise RuntimeError(text('确认窗口无法打开。', 'Could not open the confirmation dialog.'))
        args = ('reboot', state['target'], state['token'])
        if stop_updaters: args += ('--stop-updaters',)
        helper(*args)
        return 0
    except Exception as error:
        subprocess.run([DIALOG, '--title', text('无法切换 SteamOS 槽位', 'Could Not Switch SteamOS Slot'),
                        '--error', html.escape(str(error))], timeout=3600)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
