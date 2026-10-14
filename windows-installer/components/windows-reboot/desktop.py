"""KDE launcher: read target, ask once, then call the fixed privileged helper."""
import json
import os
import subprocess

HELPER = '/usr/local/bin/oxp3-reboot-windows'
DIALOG = '/usr/bin/kdialog'
ZH = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', '')).startswith('zh')


def text(zh, en):
    return zh if ZH else en


def helper(*args):
    result = subprocess.run(['/usr/bin/pkexec', HELPER, *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    try:
        reply = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(text('授权已取消或后台程序未能启动。', 'Authorization was cancelled or the helper could not start.'))
    if result.returncode or not reply.get('ok'):
        raise RuntimeError(reply.get('error', text('操作失败。', 'Operation failed.')))
    return reply['data']


def main():
    try:
        state = helper('status')
        if not state['ready']:
            raise RuntimeError(state['reason'])
        message = text('即将关闭当前会话并重启进入 Windows。请先保存游戏和文件。\n仅影响下一次启动。',
                       'This will close your session and restart into Windows. Save games and files first.\nOnly the next boot is affected.')
        result = subprocess.run([DIALOG, '--title', text('重启进入 Windows', 'Restart into Windows'),
                                 '--continue-label', text('重启', 'Restart'), '--cancel-label', text('取消', 'Cancel'),
                                 '--warningcontinuecancel', message], timeout=3600)
        if result.returncode in (1, 2):
            return 0
        if result.returncode != 0:
            raise RuntimeError('Confirmation dialog failed. / 确认对话框未能打开。')
        helper('reboot', state['target'])
        return 0
    except Exception as error:
        subprocess.run([DIALOG, '--title', text('无法重启进入 Windows', 'Could not restart into Windows'),
                        '--error', str(error)], timeout=3600)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
