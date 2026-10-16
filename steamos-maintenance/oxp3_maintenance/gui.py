"""Native KDE dialogs; the UI runs as deck and never reads private backups."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager

from .display_language import detect_language

ZH = {'title': 'OXP3 修复与项目更新', 'intro': '安装本项目修复、插件和项目更新。',
      'browse': '浏览最新修复与插件', 'download': '下载维护包（保留离线使用）',
      'apply': '选择并应用修复', 'update': '检查项目更新', 'offline': '导入离线维护包',
      'status': '查看当前状态', 'rollback': '回退上次项目更新', 'restore': '恢复组件原状',
      'recover': '恢复中断的操作', 'settings': '自动检查更新设置', 'select': '选择组件；依赖将自动补齐',
      'logs': '查看最近操作日志',
      'confirm': '确认应用这些项目修复？', 'exit': '关闭', 'working': '正在处理，请等待完成后再关闭窗口。',
      'choose': '选择签名维护包', 'none': '暂时没有可用的项目更新。', 'enable': '启用每日项目更新提示？',
      'pending': '该项目版本尚未提供 Linux 维护包。当前系统未发生修改。',
      'downloaded': '维护包已验证并保存。可导入此包选择修复和插件。',
      'install': '下载并选择安装', 'review': '查看全部功能及兼容条件',
      'channel': '选择项目更新通道', 'stable': '稳定版', 'beta': '稳定版与 Beta',
      'retained': '以下旧组件保持原状，本次不更新：'}
EN = {'title': 'OXP3 Repairs and Project Updates', 'intro': 'Install OXP3 project repairs, plugins and updates.',
      'browse': 'Browse latest repairs and plugins', 'download': 'Download maintenance bundle for offline use',
      'apply': 'Select and apply repairs', 'update': 'Check project updates', 'offline': 'Import offline bundle',
      'status': 'Current status', 'rollback': 'Roll back last project update', 'restore': 'Restore components',
      'recover': 'Recover interrupted operation', 'settings': 'Automatic update check settings',
      'logs': 'Last operation log',
      'select': 'Select components; required dependencies are included', 'confirm': 'Apply these project repairs?',
      'exit': 'Close', 'working': 'Working. Wait for completion before closing the window.',
      'choose': 'Choose a signed maintenance bundle', 'none': 'No project update is available.',
      'enable': 'Enable daily project update notifications?',
      'pending': 'This project release has no Linux maintenance bundle yet. No system changes were made.',
      'downloaded': 'The verified bundle was saved. Import it to choose repairs and plugins.',
      'install': 'Download and choose components', 'review': 'View all capabilities and requirements',
      'channel': 'Choose the project update channel', 'stable': 'Stable', 'beta': 'Stable and Beta',
      'retained': 'These older components will remain unchanged:'}
ZH['tool'] = '仅更新维护工具（保留现有修复）'
EN['tool'] = 'Update maintenance tool only; keep existing repairs'
ZH['unknown'] = '已获取项目版本，但暂时不能确认维护包是否可下载。请稍后重试，或导入已下载的签名维护包。'
EN['unknown'] = 'Project versions were found, but maintenance availability could not be verified. Retry later or import a signed offline bundle.'


class Cancelled(Exception):
    pass


def _dialog(*args):
    value = subprocess.run(['kdialog', *args], capture_output=True, text=True)
    if value.returncode:
        raise Cancelled()
    return value.stdout.strip()


@contextmanager
def _progress():
    bus = shutil.which('qdbus6') or shutil.which('qdbus')
    reference = []
    if bus:
        value = subprocess.run(['kdialog', '--title', 'OXP3', '--progressbar',
                                'OXP3: processing / 正在处理，请等待完成…', '0'],
                               capture_output=True, text=True)
        if value.returncode == 0:
            reference = value.stdout.strip().split()
    try:
        yield
    finally:
        if len(reference) == 2:
            subprocess.run([bus, *reference, 'close'], capture_output=True, timeout=10, check=False)


def _backend(action, source, selected=(), *, all_components=False, expected_version=None, expected_manifest=None, tool_only=False):
    installed = Path('/usr/local/lib/oxp3-maintenance/entry.py')
    entry = installed if installed.is_file() else Path(__file__).resolve().parent.parent / 'entry.py'
    if action in ('apply', 'update') and not installed.is_file():
        action = 'bootstrap'
    args = ['pkexec', '/usr/bin/python3', '-I', '-B', str(entry), action, '--json']
    if source:
        args += ['--bundle-dir' if Path(source).is_dir() else '--bundle', str(source)]
    if selected:
        args += ['--select', *selected]
    if action in ('plan', 'apply', 'update', 'bootstrap'):
        args += ['--selected-only']
    if all_components:
        args += ['--all-components']
    if tool_only:
        args += ['--tool-only']
    if expected_version:
        args += ['--expected-version', expected_version]
    if expected_manifest:
        args += ['--expected-manifest', expected_manifest]
    with _progress():
        value = subprocess.run(args, capture_output=True, text=True)
    if value.returncode:
        if value.returncode in (126, 127):
            raise Cancelled()
        try:
            message = json.loads(value.stderr)['error']
        except (ValueError, KeyError):
            message = value.stderr.strip() or 'Operation did not complete'
        raise RuntimeError(message)
    return json.loads(value.stdout)


def _show(result, title):
    # Logs exclude payload data and private snapshots; the text viewer supports
    # scrolling, selection, and native font scaling on the handheld screen.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', encoding='utf-8', delete=False) as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        name = file.name
    try:
        _dialog('--title', title, '--textbox', name, '850', '550')
    finally:
        Path(name).unlink(missing_ok=True)


def _show_text(content, title):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', encoding='utf-8', delete=False) as file:
        file.write(content)
        name = file.name
    try:
        _dialog('--title', title, '--textbox', name, '850', '550')
    finally:
        Path(name).unlink(missing_ok=True)


def catalog_text(report, text):
    zh = text is ZH
    statuses = ({'requires_preflight': '可预检安装', 'download_available': '可下载，待设备检测',
                 'incompatible': '当前系统不兼容', 'unavailable': '本版本未提供载荷',
                 'separate_operation': '独立安装／恢复操作'} if zh else {})
    lines = [report['release'].get('display_version', report['release']['version']),
             '仅更新本项目；安装前逐项检测依赖与冲突。' if zh else 'Project updates only. Installation requires live dependency and conflict checks.', '']
    for item in report['components']:
        installed = ('已安装 · ' if zh else 'Installed · ') if item.get('installed') else ''
        lines += [item['zh' if zh else 'en'] + '  [' + installed + statuses.get(item['status'], item['status']) + ']',
                  item['reason']]
        if item['dependencies']:
            lines.append(('依赖：' if zh else 'Requires: ') + ', '.join(item['dependencies']))
        lines.append('')
    return '\n'.join(lines)


def _online(text, action):
    from .cli import check_updates, installed_release
    from .releases import fetch_catalog, _Version
    from .downloads import save, trusted_key
    from .catalog import describe
    report = check_updates()
    if report.get('status') == 'maintenance_availability_unknown':
        version = (report.get('latest_project') or {}).get('display_version', '')
        _dialog('--msgbox', text['unknown'] + '\n\n' + version)
    if report.get('status') == 'maintenance_package_pending':
        _dialog('--msgbox', text['pending'] + '\n\n' + report['latest_project']['display_version'])
    candidate = report.get('latest_maintenance')
    if not candidate:
        if report.get('status') not in ('maintenance_package_pending', 'maintenance_availability_unknown'):
            _dialog('--msgbox', text['none'])
        return
    if action == 'update' and not report['candidates']:
        if report.get('status') not in ('maintenance_package_pending', 'maintenance_availability_unknown'):
            _dialog('--msgbox', text['none'] + '\n' + text['browse'])
        return
    if action == 'browse':
        value = fetch_catalog(candidate, trusted_key())
        try:
            from .probe import live
            system = live()
        except Exception:
            system = None
        _show_text(catalog_text(describe(value, system), text), text['title'])
        action = _dialog('--menu', candidate['display_version'], 'download', text['download'], 'install', text['install'], 'tool', text['tool'])
    _dialog('--yesno', candidate['display_version'] + '\n\n' +
            str(round(candidate['size'] / (1024 ** 2), 1)) + ' MiB\n\n' +
            (text['download'] if action == 'download' else text['install']))
    with _progress():
        saved = save(candidate, Path.home() / 'Downloads/OXP3')
    if action == 'download':
        _dialog('--msgbox', text['downloaded'] + '\n\n' + saved['path'])
    else:
        _apply(saved['path'], text,
               updating=_Version(candidate['version']) > _Version(installed_release()['version']),
               expected_version=candidate['version'], tool_only=action == 'tool')


def _apply(source, text, *, updating=False, expected_version=None, tool_only=False):
    if tool_only:
        plan = _backend('plan', source, tool_only=True, expected_version=expected_version)
        _dialog('--yesno', text['tool'] + '\n\n' + plan['release']['version'])
        result = _backend('update' if updating else 'apply', source, tool_only=True,
                          expected_version=expected_version, expected_manifest=plan['manifest_digest'])
        _show(result, text['title'])
        _after_install(result)
        return
    first = _backend('plan', source, all_components=True, expected_version=expected_version)
    catalog = {item['id']: item for category in ('repairs', 'plugins') for item in first['catalog'][category]}
    checklist = []
    for name, item in first['components'].items():
        if item['status'] != 'ready':
            continue
        label = catalog[name].get('zh' if text is ZH else 'en', name)
        checklist += [name, label, 'on' if name in first['defaults'] else 'off']
    blocked = {catalog[k].get('zh' if text is ZH else 'en', k): v['reason'] for k, v in first['components'].items() if v['status'] == 'blocked'}
    if blocked:
        _show_text('\n\n'.join(name + '\n' + reason for name, reason in blocked.items()), text['title'])
    if not checklist:
        _dialog('--yesno', text['tool'])
        return _apply(source, text, updating=updating, expected_version=expected_version, tool_only=True)
    chosen = _dialog('--title', text['title'], '--separate-output', '--checklist', text['select'], *checklist).splitlines()
    if not chosen:
        raise Cancelled()
    plan = _backend('plan', source, chosen, expected_version=expected_version)
    if not plan['can_apply']:
        _show(plan, text['title'])
        return
    names = '\n'.join(catalog[name].get('zh' if text is ZH else 'en', name) for name in plan['selected'])
    version = plan['release'].get('display_version', plan['release']['version'])
    if plan.get('retained'):
        names += '\n\n' + text['retained'] + '\n' + '\n'.join(plan['retained'])
    _dialog('--title', text['title'], '--yesno', text['confirm'] + '\n\n' + version + '\n' + names)
    subprocess.run(['kdialog', '--passivepopup', text['working'], '8'], check=False)
    result = _backend('update' if updating else 'apply', source, chosen,
                      expected_version=expected_version, expected_manifest=plan['manifest_digest'])
    _show(result, text['title'])
    _after_install(result)


def _after_install(result):
    if result.get('status') == 'files_installed':
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=False)
        settings = Path.home() / '.config/oxp3-maintenance/settings.json'
        enabled = not settings.exists() or json.loads(settings.read_text()).get('check_updates', True)
        if enabled:
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'oxp3-maintenance-check.timer'], check=False)


def run(args):
    if not shutil.which('kdialog') or not shutil.which('pkexec'):
        raise RuntimeError('Desktop Mode requires kdialog and pkexec; use the CLI on supported SteamOS')
    if os.geteuid() == 0:
        raise RuntimeError('Open the graphical launcher as the desktop user, not root')
    text = ZH if detect_language() == 'zh' else EN
    source = args.bundle_dir or args.bundle
    extracted = Path(__file__).resolve().parent.parent.parent
    if not source and (extracted / 'manifest.json').is_file():
        source = str(extracted)
    while True:
        try:
            choices = ['browse', 'update', 'download', 'apply', 'offline', 'tool', 'status', 'rollback', 'restore', 'recover', 'settings', 'logs']
            menu = [value for name in choices for value in (name, text[name])]
            action = _dialog('--title', text['title'], '--menu', text['intro'], *menu)
        except Cancelled:
            return None
        try:
            if action == 'status':
                _show(_backend('status', None), text['title'])
            elif action == 'logs':
                _show(_backend('logs', None), text['title'])
            elif action == 'settings':
                enabled = True
                try:
                    _dialog('--yesno', text['enable'])
                except Cancelled:
                    enabled = False
                folder = Path.home() / '.config/oxp3-maintenance'
                folder.mkdir(parents=True, exist_ok=True)
                channel = _dialog('--menu', text['channel'], 'stable', text['stable'], 'beta', text['beta'])
                (folder / 'settings.json').write_text(json.dumps({'check_updates': enabled, 'channel': channel}))
                subprocess.run(['systemctl', '--user', 'enable' if enabled else 'disable', '--now',
                                'oxp3-maintenance-check.timer'], check=False)
            elif action in ('rollback', 'recover', 'restore'):
                selected = []
                if action == 'restore':
                    status = _backend('status', None)
                    slot = status['system']['slot']['id']
                    current = status['operations']['slots'].get(slot, {}).get('current')
                    names = [n for n in (current['selected'] if current else []) if n != '_maintenance']
                    if not names:
                        _show({'status': 'no_installed_components'}, text['title'])
                        continue
                    choices = [value for n in names for value in (n, n, 'off')]
                    selected = _dialog('--separate-output', '--checklist', text['restore'], *choices).splitlines()
                    if not selected:
                        raise Cancelled()
                _dialog('--yesno', text[action] + '?\n\n' + '\n'.join(selected))
                _show(_backend(action, None, selected), text['title'])
            elif action in ('browse', 'update', 'download'):
                _online(text, action)
            else:
                if action == 'offline' or not source:
                    source = _dialog('--title', text['choose'], '--getopenfilename', str(Path.home()), '*.tar.gz')
                _apply(source, text, tool_only=action == 'tool')
        except Cancelled:
            pass
        except Exception as error:
            try:
                _dialog('--title', text['title'], '--error', str(error))
            except Cancelled:
                pass
