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
    issue = data.get('issue')
    if issue is not None and (not isinstance(issue, dict) or
                              not isinstance(issue.get('code'), str) or
                              not isinstance(issue.get('details'), str)):
        raise RuntimeError('Invalid mount diagnostic')
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


def issue_message(issue):
    code = issue.get('code')
    reasons = {
        'ntfs_inconsistent': ('NTFS 元数据不一致（例如 $MFT 与 $MFTMirr 不一致）。', 'NTFS metadata is inconsistent (for example, $MFT/$MFTMirr).'),
        'ntfs_hibernated': ('Windows 仍处于休眠状态，分区尚未完全关闭。', 'Windows left this volume hibernated.'),
        'ntfs_unclean': ('NTFS 未正常卸载或带有脏卷标记（dirty）。', 'NTFS was not cleanly unmounted or is marked dirty.'),
        'ntfs_invalid': ('分区未通过 NTFS 格式检查，请核对分区用途。', 'The volume did not pass the NTFS format check; confirm its identity.'),
        'ntfs_busy': ('其他程序正在独占使用此分区。', 'Another application has this volume open exclusively.'),
        'ntfs_check_failed': ('NTFS 检查未能完成，请查看详细信息。', 'The NTFS check could not complete; review the details.'),
        'ntfs_mount_failed': ('NTFS 挂载失败，尚不能确定具体原因。', 'The NTFS mount failed; the exact cause could not be confirmed.'),
    }
    message = tr(*reasons.get(code, ('挂载失败，请查看详细信息。', 'Mount failed; review the details.')))
    if code in ('ntfs_inconsistent', 'ntfs_unclean', 'ntfs_invalid'):
        message += tr(
            '\n\n处理方法：\n1. 进入 Windows，按卷标和容量找到同一分区，先备份重要文件。\n'
            '2. 以管理员身份打开终端，运行 chkdsk X: /f（把 X: 换成该分区实际盘符，不要直接照抄）。\n'
            '3. 等待检查完成；如提示下次启动检查，先在 Windows 重启完成检查，再完整关机。\n'
            '4. 回到 SteamOS，在此工具重新选择该分区并点击“挂载/重试”。仅重启 SteamOS 不能修复 NTFS。',
            '\n\nRecovery:\n1. In Windows, identify the same volume by label and size and back up important files.\n'
            '2. Run chkdsk X: /f as Administrator; replace X: with its actual drive letter.\n'
            '3. Let the check finish. Complete any scheduled check by restarting Windows, then fully shut it down.\n'
            '4. Return to SteamOS, select this partition and choose Mount / Retry. Restarting SteamOS alone does not repair NTFS.')
    elif code == 'ntfs_hibernated':
        message += tr('\n恢复 Windows 会话后完整关机，并关闭“快速启动”，再回到此工具重试挂载。',
                      '\nResume Windows, fully shut it down and disable Fast Startup, then retry the mount here.')
    elif code == 'ntfs_busy':
        message += tr('\n关闭占用程序；如 Dolphin 已挂载，先安全卸载，再重试。',
                      '\nClose the application using it; safely unmount in Dolphin if needed, then retry.')
    if issue.get('details'):
        message += '\n\n' + tr('检查详情：\n', 'Diagnostic details:\n') + str(issue['details'])
    return message


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
                'enable', tr('挂载/重试并启用自动挂载', 'Mount / Retry and enable persistent mount'),
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
                    'NTFS 挂载前只读检查状态；确认未休眠的 dirty 卷会自动执行有限修复并复查，休眠或状态不明时停止。'
                    '有限修复可能修改元数据和日志，不能替代 Windows chkdsk。ext4 保留盘内文件权限。',
                    'Enable a persistent mount?\n{label}\nMount path: {path}\n\n'
                    'Saves UUID-based configuration to /etc/fstab in the current OS slot. Future boots mount on access; a missing disk will not block startup.\n'
                    'Mounting is also attempted now. An existing KDE mount stays in place until restart.\n'
                    'NTFS is checked read-only before mounting. Confirmed non-hibernated dirty volumes receive limited repair and rechecking; hibernated or unknown states stop. '
                    'Limited repair can change metadata and the journal and does not replace Windows chkdsk. ext4 keeps on-disk permissions.'
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
            elif result.get('issue'):
                message = tr('配置已保存，分区尚未挂载。处理以下问题后可重新选择分区重试：\n',
                             'Configuration saved; the partition is not mounted. Resolve the issue below and retry:\n') + result['path']
            else:
                message = tr('配置已保存，本次尚未挂载到新目录。重启后访问以下目录会尝试挂载：\n',
                             'Configuration saved; the new path is not mounted yet. After restart, accessing this path attempts the mount:\n') + result['path']
            if result.get('issue'):
                message += '\n\n' + issue_message(result['issue'])
            elif result['warning']:
                message += '\n\n' + tr('本次激活提示：\n', 'Activation details:\n') + result['warning']
            dialog('--msgbox', message)
    except Exception as error:
        dialog('--error', str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
