"""KDE recovery launcher; status first, explicit save-and-reboot confirmation."""
import html
import json
import os
import subprocess

HELPER = '/home/.oxp3-slot-switch/oxp3-switch-slot'
DIALOG = '/usr/bin/kdialog'
ZH = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', '')).startswith('zh')


def text(zh, en):
    return zh if ZH else en


def helper(*args):
    result = subprocess.run(['/usr/bin/pkexec', HELPER, *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    try: reply = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(text('授权已取消或后台程序无法启动。请检查管理员密码。',
                                'Authorization was cancelled or the helper could not start. Check your administrator password.'))
    if result.returncode or not reply.get('ok'):
        raise RuntimeError(reply.get('error', text('操作失败。', 'Operation failed.')))
    return reply['data']


def message(state):
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
    # KDE rich-text detection must not render content from metadata as markup.
    return '<qt>' + '<br/>'.join(html.escape(line) for line in lines) + '</qt>'


def main():
    try:
        state = helper('status')
        result = subprocess.run([DIALOG, '--title', text('SteamOS 槽位切换 / 系统回退', 'SteamOS Slot Switch / OS Recovery'),
                                 '--continue-label', text('切换并重启', 'Switch and Restart'),
                                 '--cancel-label', text('取消', 'Cancel'),
                                 '--warningcontinuecancel', message(state)], timeout=3600)
        if result.returncode in (1, 2): return 0
        if result.returncode != 0: raise RuntimeError(text('确认窗口无法打开。', 'Could not open the confirmation dialog.'))
        helper('reboot', state['target'], state['token'])
        return 0
    except Exception as error:
        subprocess.run([DIALOG, '--title', text('无法切换 SteamOS 槽位', 'Could Not Switch SteamOS Slot'),
                        '--error', html.escape(str(error))], timeout=3600)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
