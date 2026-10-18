"""Small native KDE interface; status is unprivileged, changes use pkexec."""
import html
import json
import os
from pathlib import Path
import subprocess

HOME = '/home/.oxp3-partition-mount'
HELPER = HOME + '/oxp3-partition-mount'
DIALOG = '/usr/bin/kdialog'


def language():
    # Match Plasma's UI language even when number/date formats differ.
    import configparser
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'plasma-localerc', encoding='utf-8')
        value = parser.get('Translations', 'LANGUAGE', fallback='')
    except (OSError, configparser.Error, UnicodeError):
        value = ''
    value = value or os.environ.get('LANGUAGE') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', 'en')
    return value.lower().startswith('zh')


ZH = language()


def tr(zh, en):
    return zh if ZH else en


def rich(value):
    return '<qt>' + html.escape(value).replace('\n', '<br/>') + '</qt>'


def dialog(kind, message, *items):
    result = subprocess.run([DIALOG, '--title', tr('SteamOS 分区自动挂载', 'SteamOS Partition Mounts'),
                             kind, rich(message), *items], text=True, stdout=subprocess.PIPE, timeout=3600)
    if result.returncode in (1, 2): return None
    if result.returncode:
        raise RuntimeError(tr('无法打开 KDE 对话框。', 'Could not open the KDE dialog.'))
    return result.stdout.strip()


def helper(*args):
    command = [HELPER, *args]
    if args[0] != 'status': command.insert(0, '/usr/bin/pkexec')
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try: reply = json.loads(result.stdout)
    except ValueError: reply = None
    if not isinstance(reply, dict) or type(reply.get('ok')) is not bool:
        if result.returncode in (126, 127):
            raise RuntimeError(tr('授权取消或未获授权。请确认已设置管理员密码，并在 KDE 中运行。',
                                  'Authorization was cancelled or denied. Set an administrator password and run from KDE.'))
        raise RuntimeError(tr('后台程序没有返回有效结果。请重新安装分区挂载工具。',
                              'The helper returned an invalid response. Reinstall Partition Mounts.'))
    if result.returncode or not reply['ok']:
        raise RuntimeError(str(reply.get('error') or 'Helper failed'))
    data = reply.get('data')
    if not isinstance(data, dict): raise RuntimeError('Invalid helper data')
    if args[0] == 'status':
        if not isinstance(data.get('partitions'), list) or not isinstance(data.get('managed'), dict) or not isinstance(data.get('token'), str):
            raise RuntimeError('Invalid partition status')
    elif data.get('saved') is not True or type(data.get('mounted')) is not bool or not isinstance(data.get('warning'), str):
        raise RuntimeError('Invalid save result')
    return data


def partition_label(item):
    size = int(item.get('size') or 0) / (1024 ** 3)
    paths = [path for path in item.get('mountpoints', []) if path]
    state = tr('已挂载：', 'Mounted: ') + ', '.join(paths) if paths else tr('未挂载', 'Not mounted')
    return f"{item.get('path', '?')} | {item.get('label') or tr('无卷标', 'No label')} | {size:.1f} GiB | {item.get('fstype') or '?'} | {state} | UUID {item.get('uuid') or '?'}"


def excluded_listing(state):
    reasons = {
        'not_plain_partition': ('不是普通分区（整盘文件系统或复合设备暂不支持）', 'Not a plain partition (whole-disk filesystems and layered devices are unsupported)'),
        'unsupported_filesystem': ('文件系统未识别或不支持；加密卷需先解锁', 'Filesystem missing or unsupported; encrypted volumes must be unlocked first'),
        'missing_uuid': ('缺少有效 UUID；重新扫描或检查文件系统', 'Missing valid UUID; rescan or check the filesystem'),
        'readonly': ('设备只读', 'Device is read-only'),
        'protected_partition_type': ('系统/保留分区类型或分区类型未知', 'Protected or unknown partition type'),
        'missing_device_id': ('设备标识不完整；重新扫描', 'Incomplete device identity; rescan'),
        'system_label': ('系统或恢复分区卷标', 'System or recovery partition label'),
        'mounted_elsewhere': ('已在其他系统路径挂载；保留现有配置', 'Already mounted at another system path; existing configuration is preserved'),
        'duplicate_uuid': ('多个设备具有相同 UUID；断开克隆盘后重试', 'Multiple devices share this UUID; disconnect the clone and retry'),
    }
    return '\n\n'.join(partition_label(item) + '\n' + tr(*reasons.get(item.get('reason'),
                       ('当前不可用', 'Currently unavailable'))) for item in state.get('excluded', []))


def main():
    try:
        while True:
            state = helper('status')
            action = dialog('--menu', tr(
                'KDE 中点击分区通常只挂载本次会话。这里可保存重启后继续使用的配置。\n'
                '可选择未挂载的 Windows NTFS 分区及 exFAT、FAT32、ext4 SD 卡分区。Linux 不使用 C/D 盘符，请按卷标和容量识别。\n'
                '系统、恢复及加密分区受保护；可查看不可选分区的原因。',
                'A mount from KDE may last only for the current session. Save a persistent mount here.\n'
                'Select unmounted Windows NTFS or exFAT, FAT32 and ext4 SD card partitions. Linux does not use C/D drive letters; identify volumes by label and size.\n'
                'System, recovery and encrypted partitions are protected. View unavailable partitions for details.'),
                'enable', tr('挂载分区并启用自动挂载', 'Mount a partition and enable persistent mount'),
                'disable', tr('取消自动挂载', 'Disable persistent mount'),
                'view', tr('查看已保存的挂载', 'View saved mounts'),
                'unavailable', tr('查看不可选分区及原因', 'View unavailable partitions and reasons'))
            if action is None: return 0
            if action == 'unavailable':
                dialog('--msgbox', excluded_listing(state) or tr('没有被排除的分区。', 'No excluded partitions.'))
                continue
            if action == 'view':
                listing = '\n'.join(f"{uuid} → /var/mnt/oxp3-volumes/{uuid}" for uuid in state['managed'])
                dialog('--msgbox', listing or tr('尚未保存自动挂载分区。', 'No persistent mounts saved.'))
                continue
            choices = {item['uuid']: item for item in state['partitions']}
            if action == 'enable':
                options = [value for uuid, item in choices.items() for value in (uuid, partition_label(item))]
            elif action == 'disable':
                options = [value for uuid in state['managed'] for value in (uuid, partition_label(choices[uuid]) if uuid in choices else uuid + tr('（未连接或当前不可用）', ' (disconnected or unavailable)'))]
            else:
                continue
            if not options:
                message = tr('没有可选分区。请检查磁盘连接，返回菜单后会重新扫描。',
                             'No partitions available. Check the disk connection; returning to the menu rescans devices.')
                if action == 'enable':
                    message += '\n\n' + excluded_listing(state)
                dialog('--msgbox', message)
                continue
            uuid = dialog('--menu', tr('选择分区（请核对设备、容量和 UUID）：', 'Select a partition (check device, size and UUID):'), *options)
            if uuid is None: continue
            if uuid not in options[::2]: raise RuntimeError('Invalid partition selection')
            path = '/var/mnt/oxp3-volumes/' + uuid
            if action == 'enable':
                prompt = tr(
                    '启用此分区的自动挂载？\n{label}\n挂载目录：{path}\n\n'
                    '保存到当前系统槽的 /etc/fstab，使用 UUID 识别；后续开机会按需挂载，缺盘不会阻塞启动。\n'
                    '本次也会尝试挂载；若已由 KDE 挂载，将保留现状并在下次重启使用新目录。\n'
                    'NTFS 休眠/脏卷不会被强制挂载；ext4 保留盘内文件权限。请勿同时在 Windows 休眠状态使用共享盘。',
                    'Enable a persistent mount?\n{label}\nMount path: {path}\n\n'
                    'Saves UUID-based configuration to /etc/fstab in the current OS slot. Future boots mount on access; a missing disk will not block startup.\n'
                    'Mounting is also attempted now. An existing KDE mount stays in place until restart.\n'
                    'Hibernated/dirty NTFS is never forced. ext4 keeps on-disk permissions. Fully shut down Windows before sharing a disk.'
                ).format(label=partition_label(choices[uuid]), path=path)
            else:
                prompt = tr('取消 {uuid} 的自动挂载？\n不会删除分区或文件；当前挂载保留到重启。',
                            'Disable the persistent mount for {uuid}?\nFiles and partitions are kept. The current mount remains until restart.').format(uuid=uuid)
            if dialog('--warningcontinuecancel', prompt) is None: continue
            result = helper(action, uuid, state['token'])
            if action == 'disable':
                message = tr('自动挂载已取消。当前挂载将在重启后解除；现在拔盘前仍需在 Dolphin 安全卸载。',
                             'Persistent mount disabled. Restart to release the current mount; safely unmount in Dolphin before disconnecting now.')
            elif result['mounted']:
                message = tr('配置已保存，分区已挂载到：\n', 'Configuration saved. Partition mounted at:\n') + result['path']
            else:
                message = tr('配置已保存，本次尚未挂载到新目录。重启后访问以下目录会尝试挂载：\n',
                             'Configuration saved; the new path is not mounted yet. After restart, accessing this path attempts the mount:\n') + result['path']
            if result['warning']:
                message += '\n\n' + tr('本次激活提示：\n', 'Activation details:\n') + result['warning']
            dialog('--msgbox', message)
    except Exception as error:
        dialog('--error', str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
