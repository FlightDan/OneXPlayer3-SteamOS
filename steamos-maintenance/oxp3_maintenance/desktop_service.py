"""Touch UI controller. Unprivileged discovery; explicit, reviewed root writes."""
import json
from pathlib import Path
import subprocess
import uuid

from . import cli


class DesktopService:
    mutating_actions = {'apply', 'rollback', 'restore', 'recover'}

    def __init__(self, args, language='en'):
        self.zh = language == 'zh'
        self.source = args.bundle_dir or args.bundle
        extracted = Path(__file__).resolve().parent.parent.parent
        if not self.source and (extracted / 'manifest.json').is_file():
            self.source = str(extracted)
        self.candidate = None
        self.review = None
        self.seed = self.source
        self.health_report = None
        self.on_progress = None
        self.labels = dict(zip(
            ('input','multifunction','gyro','hdr','desktop-hdr','gamescope-env','wifi','xe-dsb','gm7-resume','manager','native-tdp','overlay','fan-driver','oxp3-fan','oxp3-cpu','charging','legacy-runtime','windows-reboot','decky','steamgriddb','protondb','tabmaster','css-loader','autoflatpaks','deck-settings','hltb','animation-changer','waydroid','flathub-ustc','slot-switch','refind'),
            ('背键驱动','多功能键','陀螺仪','游戏模式 HDR','桌面 HDR','游戏模式启动环境','无线与蓝牙固件','显示兼容配置','GM7 休眠恢复','SteamOS 管理器','原生功耗控制','性能叠加层','风扇与充电驱动','风扇控制插件','CPU 控制插件','充电控制插件','音量与电量修复','重启进入 Windows','Decky 插件环境','SteamGridDB 游戏封面','ProtonDB 兼容性标记','TabMaster 游戏库分页','CSS Loader 界面主题','AutoFlatpaks 应用更新','Deck Settings 游戏设置','HLTB 游戏时长','Animation Changer 启动画面','Waydroid 安卓环境','Flathub 应用源','系统槽位切换','rEFInd 启动菜单')
        )) if self.zh else {}
        self.settings = Path.home() / '.config/oxp3-maintenance/settings.json'
        self.preferences = self._preferences()
        from .network import NETWORK_MODES
        requested_network = getattr(args, 'github_network', None)
        if requested_network in NETWORK_MODES:
            self.preferences['github_network'] = requested_network
        if self.zh:
            self.labels['serial-console-policy'] = '串口登录重复报错修复'
            self.labels['autoflatpaks-compat'] = 'AutoFlatpaks 电池状态兼容修复'
            self.labels['animation-changer-compat'] = 'Animation Changer 已安装版本路径兼容修复'
            self.labels['opti2xmx'] = 'Opti2XMX 游戏图像增强'
            self.labels['oxp3-light'] = '原生灯效控制插件'
            self.labels['split-lock'] = 'Split-lock 报告洪泛修复'

    @property
    def has_source(self):
        return bool(self.source)

    @property
    def has_candidate(self):
        return self.candidate is not None

    def t(self, zh, en):
        return zh if self.zh else en

    def _network_progress(self, event):
        if self.on_progress:
            if 'attempt' not in event:
                message = self.t('正在下载所选组件', 'Downloading selected components')
                received, total = event.get('received'), event.get('total')
                if isinstance(received, int) and isinstance(total, int) and total > 0:
                    message += ' (%d%%)' % max(0, min(100, received * 100 // total))
                self.on_progress(message)
                return
            message = self.t('正在重试项目发布服务' if event['phase'] == 'retrying_github' else '正在连接项目发布服务',
                             'Retrying project release service' if event['phase'] == 'retrying_github' else 'Contacting project release service')
            self.on_progress(message + ' (%s/%s)' % (event['attempt'], event['attempts']))

    def _preferences(self):
        from .network import NETWORK_MODES
        try:
            value = json.loads(self.settings.read_text())
            return {'enabled': value.get('check_updates', True) is not False,
                    'channel': 'stable' if value.get('channel') == 'stable' else 'beta',
                    'github_network': value.get('github_network') if value.get('github_network') in NETWORK_MODES else 'auto'}
        except (OSError, ValueError, TypeError, AttributeError):
            return {'enabled': True, 'channel': cli.installed_release().get('channel', 'beta'), 'github_network': 'auto'}

    def _network_kwargs(self):
        from .network import NetworkPolicy
        mode = self.preferences.get('github_network', 'auto')
        return {'opener': NetworkPolicy(mode).open}

    def _view(self, heading, message='', **values):
        return dict(heading=heading, message=message, tone='normal', **values)

    def _label(self, name):
        return self.labels.get(name, {'keyboard': self.t('屏幕键盘', 'Touch keyboard'),
            '_maintenance': self.t('维护工具', 'Maintenance tool')}.get(name, name))

    def _reason(self, reason):
        text = str(reason)
        if not self.zh:
            return text
        patterns = [
            ('Ready for transactional', '可以安装；应用前会再次检查文件和原件。'),
            ('Legacy adoption requires review', '旧安装记录与当前文件不一致，已保留现状。请先检查旧安装恢复记录。'),
            ('separate installer', '需要使用独立安装或系统恢复入口。'),
            ('separate operation', '需要使用独立安装或系统恢复入口。'),
            ('separate installer/recovery', '需要使用独立安装或系统恢复入口。'),
            ('Use the separate', '需要使用独立安装或系统恢复入口。'),
            ('Payload is not available', '此版本没有提供该项资源。'),
            ('No maintenance adapter', '此功能尚无适用于当前系统的安装适配器。'),
            ('No compatible', '当前系统不满足这项功能的兼容条件。'),
            ('requires SteamOS', '此项需要匹配的 SteamOS 版本、内核和软件包。'),
            ('Unsupported', '当前设备或系统不满足这项功能的兼容条件。'),
            ('Supported OXP3 SteamOS', '适用于此 OXP3 系统；安装前仍需检查资源和冲突。'),
            ('requires the tested', '此项需要已验证的 SteamOS 底座与内核。'),
        ]
        for marker, translation in patterns:
            if marker.lower() in text.lower():
                return translation
        return self.t('暂不可安装；详细原因：', '') + text

    def error_text(self, error):
        text = str(error)
        if not self.zh:
            return text
        lower = text.lower()
        if any(word in lower for word in ('github', 'network', 'timed out', 'connection', 'urlopen', 'release data')):
            return '暂时无法连接项目发布服务。请检查网络后重试，也可以导入已下载的离线维护包。当前系统未发生修改。'
        if 'cancel' in lower or 'authentication' in lower:
            return '已取消系统认证，操作未执行。需要修改时请重新点击并完成认证。'
        if any(word in lower for word in ('signature', 'signing key', 'trusted key', 'trust anchor')):
            return '维护包或功能目录未通过签名检查。请从本项目下载完整文件，并核对发行公钥。'
        return '操作未完成：' + text

    def _backend(self, action, selected=(), *, all_components=False, tool_only=False,
                 expected_version=None, expected_manifest=None):
        if action not in {'status', 'logs', 'plan', 'apply', 'rollback', 'restore', 'recover', 'health'}:
            raise ValueError('Unsupported desktop action')
        installed = Path('/usr/local/lib/oxp3-maintenance/entry.py')
        entry = installed if installed.is_file() else Path(__file__).resolve().parent.parent / 'entry.py'
        command_action = 'bootstrap' if action == 'apply' and not installed.is_file() else action
        command = ['pkexec', '/usr/bin/python3', '-I', '-B', str(entry), command_action, '--json']
        if action in ('plan', 'apply'):
            if not self.source:
                raise RuntimeError(self.t('请先选择维护包。', 'Choose a maintenance bundle first.'))
            command += ['--bundle-dir' if Path(self.source).is_dir() else '--bundle', str(self.source), '--selected-only']
        if selected:
            command += ['--select', *selected]
        if all_components:
            command += ['--all-components']
        if tool_only:
            command += ['--tool-only']
        if expected_version:
            command += ['--expected-version', expected_version]
        if expected_manifest:
            command += ['--expected-manifest', expected_manifest]
        try:
            if self.on_progress and action == 'plan':
                self.on_progress(self.t('正在检查安装条件；如出现身份验证窗口，请输入系统密码。',
                                        'Checking installation requirements; enter your system password if authentication appears.'))
            if self.on_progress and action == 'health':
                self.on_progress(self.t('正在只读检查；系统可能请求授权以读取安装记录。',
                                        'Running read-only checks; authentication may be needed to read installation records.'))
            # A write is allowed to finish; closing the UI never kills a transaction.
            value = subprocess.run(command, capture_output=True, text=True,
                                   timeout=None if action in self.mutating_actions else 300)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(self.t('读取超时，请稍后重试。', 'Reading timed out; retry later.')) from error
        if value.returncode:
            if value.returncode == 2:
                try:
                    refused = json.loads(value.stdout)
                    if refused.get('status') == 'preflight_refused':
                        return refused
                except (ValueError, AttributeError):
                    pass
            if value.returncode in (126, 127):
                raise RuntimeError('Authentication cancelled')
            try:
                message = json.loads(value.stderr)['error']
            except (ValueError, KeyError, TypeError):
                message = value.stderr.strip()[:2000] or 'Operation did not complete'
            raise RuntimeError(message)
        return json.loads(value.stdout)

    def _plan_view(self, result, *, review=False):
        catalog = result.get('catalog', {})
        categories = {}
        for group in ('repairs', 'plugins'):
            for item in catalog.get(group, []):
                self.labels[item['id']] = item.get('zh' if self.zh else 'en', item['id'])
                categories[item['id']] = group
        items = []
        for name, item in result['components'].items():
            ready = item['status'] == 'ready'
            category = categories.get(name, 'plugins')
            installed = result.get('installed_states', {}).get(name)
            installed = installed if type(installed) is bool else None
            items.append({'id': name, 'title': self._label(name), 'detail': self._reason(item.get('reason', '')),
                          'enabled': ready, 'category': category, 'installed': installed,
                          'selected': name in result['selected'] if review else ready and category == 'repairs' and installed is not True})
        items.sort(key=lambda item: item['category'] != 'repairs')
        facts = [(self.t('项目版本', 'Project version'), result['release']['version'])]
        if review:
            facts.append((self.t('待写入文件', 'Files to install'), str(result['file_count'])))
        if review and result.get('restart_required'):
            facts.append((self.t('生效方式', 'Activation'), self.t('需要重启或新会话', 'Restart or new session required')))
        for group in result.get('restore_groups', []):
            facts.append((self.t('恢复时须同时选择', 'Restore together'),
                          '、'.join(self._label(name) for name in group['components'])))
        if review:
            facts.append((self.t('应用内容（含依赖）', 'Apply, including dependencies'),
                          '、'.join(self._label(n) for n in result['selected']) or self.t('仅维护工具', 'Maintenance tool only')))
            if result.get('retained'):
                facts.append((self.t('保持原状', 'Keep unchanged'),
                              '、'.join(self._label(n) for n in result['retained'])))
        return self._view(self.t('确认本次修改' if review else '选择修复与插件', 'Review changes' if review else 'Choose repairs and plugins'),
                          self.t('只有确认后才会应用。未选择的旧组件保持原状。', 'Changes apply only after confirmation. Unselected components stay unchanged.'),
                          facts=facts, items=items, review=review, can_apply=result['can_apply'],
                          source=str(self.source), source_ready=True, selection=result['selected'])

    def _result_view(self, result, heading=None):
        op = result.get('operation', result)
        pending = result.get('restart_required', False)
        message = self.t('已完成，文件和恢复记录已保存。', 'Completed. Files and recovery records were saved.')
        if op.get('changed') is False:
            message = self.t('没有需要处理的更改。', 'No changes were needed.')
        if pending:
            message += self.t(' 请在方便时重启或重新登录，工具不会自动重启。', ' Restart or sign in again when convenient; this tool will not restart automatically.')
        facts = [(self.t('本次保留的自定义配置', 'Custom settings preserved'), str(len(op.get('preserved', []))))]
        if 'generation' in op:
            facts.append((self.t('恢复记录', 'Recovery record'), str(op['generation'])))
        return dict(heading=heading or self.t('操作完成', 'Completed'), message=message, tone='success', facts=facts)

    def _health_view(self):
        report = self.health_report
        language = 'zh' if self.zh else 'en'
        labels = {'ok': self.t('通过', 'Passed'), 'warning': self.t('需检查', 'Needs attention'),
                  'unknown': self.t('未能判断', 'Unknown'), 'info': self.t('提示', 'Information')}
        items = []
        for check in report['checks']:
            detail = check['message'][language] + '\n' + check['advice'][language]
            evidence = check['evidence']
            for difference in evidence.get('details', [])[:10]:
                detail += '\n' + difference['path'] + ' — ' + difference['kind']
                for key, values in difference.get('differences', {}).items():
                    detail += '\n  ' + key + ': ' + self.t('预期 ', 'expected ') + str(values['expected']) + self.t('；实际 ', '; actual ') + str(values['actual'])
            if len(evidence.get('details', [])) > 10:
                detail += self.t('\n更多差异见导出的报告。', '\nSee the exported report for additional differences.')
            if 'ActiveState' in evidence:
                detail += '\n' + ' / '.join(str(evidence.get(key, '?')) for key in ('LoadState', 'ActiveState', 'SubState', 'Result'))
            if 'devices' in evidence:
                for device in evidence['devices']:
                    if device['gamepad_capability']:
                        detail += '\n' + device['name'] + ' (' + ' '.join(device['handlers']) + ')'
            items.append({'id': check['id'], 'title': labels[check['status']] + ' · ' + check['title'][language], 'detail': detail})
        counts = report['summary']
        view = self._view(self.t('一键体检结果', 'Health check results'),
                           self.t('已完成只读检查，异常和无法判断的项目优先显示。实际按键响应和互联网连接仍需另行验证。',
                                  'Read-only checks finished; warnings and unknowns appear first. Actual button response and Internet access still need separate verification.'),
                         facts=[(self.t('检查时间', 'Checked at'), report['created_at']),
                                (self.t('结果', 'Results'), ' · '.join(labels[k] + ' ' + str(v) for k, v in counts.items()))],
                         items=items, report_ready=True)
        view['tone'] = 'warning' if counts.get('warning') or counts.get('unknown') else 'normal'
        return view

    def _distribution(self):
        if not self.source or not Path(self.source).is_file():
            return None
        from .distribution import describe_source
        from .downloads import trusted_key
        return describe_source(self.source, trusted_key())

    def _distribution_view(self, value):
        from .catalog import describe
        from .update_state import component_states
        try:
            from .probe import live
            system = live()
        except Exception:
            system = None
        installed = cli.installed_release()
        slot = system.get('slot', {}).get('id') if system else None
        states = component_states(value, installed, slot)
        report = describe(value, system, states)
        items = []
        for item in report['components']:
            name = item['id']
            self.labels[name] = item.get('zh' if self.zh else 'en', name)
            enabled = item['status'] in ('requires_preflight', 'download_available')
            current = states.get(name)
            previously_managed = name in installed.get('component_revisions_by_slot', {}).get(slot, {})
            items.append(dict(id=name, title=self._label(name), detail=self._reason(item['reason']),
                              enabled=enabled, category=item['kind'], installed=current,
                              selected=enabled and current is not True and (item['kind'] == 'repairs' or previously_managed)))
        return self._view(self.t('选择更新与修复', 'Choose updates and repairs'),
                          self.t('清单包含全部组件。只下载所选项目及其依赖；旧版本无需逐版升级。',
                                 'The complete catalog covers every component. Download selected items and dependencies directly from any older version.'),
                          facts=[(self.t('目标版本', 'Target version'), value['release']['version'])],
                          items=items, source=str(self.source or ''), source_ready=self.has_source)

    def _materialize(self, selected, catalog):
        from .distribution import materialize
        from .downloads import trusted_key
        folder = Path.home() / 'Downloads/OXP3'
        folder.mkdir(parents=True, exist_ok=True)
        result = materialize(self.source, selected, folder / ('selection-' + uuid.uuid4().hex + '.tar.gz'),
                             trusted_key(), catalog=catalog, cache=folder / 'packages', progress=self._network_progress,
                             **self._network_kwargs())
        self.source = result['path']
        return result

    def perform(self, action, **params):
        try:
            return self._perform(action, **params)
        except Exception as error:
            raise RuntimeError(self.error_text(error)) from error

    def _perform(self, action, **params):
        if action == 'health':
            # A failed rerun must not silently export an older successful report.
            self.health_report = None
            result = self._backend('health')
            if result.get('kind') != 'oxp3-health-report' or result.get('schema') != 1:
                raise RuntimeError(self.t('体检接口不可用，请先更新维护工具。', 'Health checks are unavailable; update the maintenance tool first.'))
            self.health_report = result
            return self._health_view()
        if action == 'export-health':
            if self.health_report is None:
                raise RuntimeError(self.t('请先完成一次体检。', 'Run a health check first.'))
            from .health import export_report
            path = export_report(self.health_report, Path.home() / 'Downloads/OXP3/diagnostics', 'zh' if self.zh else 'en')
            view = self._health_view()
            view['facts'].append((self.t('报告已保存，可将此 ZIP 发给维护者', 'Report saved; share this ZIP with the maintainer'), str(path)))
            return view
        if action == 'overview':
            release = cli.installed_release()
            return self._view(self.t('OXP3 修复与项目更新', 'OXP3 repairs and project updates'),
                              self.t('检查最新能力，按需安装修复和插件。此工具仅更新本项目。', 'Discover project updates and choose repairs and plugins.'),
                              facts=[(self.t('已安装项目', 'Installed project'), release['version']),
                                     (self.t('更新通道', 'Update channel'), self.t('稳定版' if self.preferences['channel'] == 'stable' else '稳定版与 Beta', self.preferences['channel']))],
                              source_ready=self.has_source, source=str(self.source or ''))
        if action == 'preferences':
            return self._view(self.t('更新设置', 'Update settings'), **self.preferences)
        if action == 'settings':
            from .network import NETWORK_MODES
            if type(params.get('enabled')) is not bool or params.get('channel') not in ('stable', 'beta'):
                raise ValueError('Invalid update settings')
            network = params.get('github_network', self.preferences.get('github_network', 'auto'))
            if network not in NETWORK_MODES:
                raise ValueError('Invalid GitHub network route')
            self.settings.parent.mkdir(parents=True, exist_ok=True)
            value = {'check_updates': params['enabled'], 'channel': params['channel'], 'github_network': network}
            temporary = self.settings.with_suffix('.tmp')
            temporary.write_text(json.dumps(value))
            temporary.replace(self.settings)
            self.preferences = {'enabled': params['enabled'], 'channel': params['channel'], 'github_network': network}
            for command in (['systemctl', '--user', 'daemon-reload'],
                            ['systemctl', '--user', 'enable' if params['enabled'] else 'disable', '--now', 'oxp3-maintenance-check.timer']):
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                if result.returncode:
                    raise RuntimeError(self.t('设置已保存，但定时器未能切换。安装维护工具后可重试。', 'Settings saved, but the timer could not change. Install the tool and retry.'))
            return self._view(self.t('设置已保存', 'Settings saved'), self.t('自动检查只提示更新，下载和修改仍需你确认。', 'Automatic checks notify only; downloads and changes require confirmation.'))
        if action == 'status':
            result = self._backend('status')
            system = result['system']
            current = result.get('operations', {}).get('slots', {}).get(system['slot']['id'], {}).get('current') or {}
            names = [n for n in current.get('selected', []) if n != '_maintenance']
            legacy = current.get('legacy_selected', [])
            facts = [(self.t('项目版本', 'Project version'), result['release']['version']),
                     ('SteamOS', system['os'].get('VERSION_ID', '?')),
                     (self.t('当前系统槽', 'Current system slot'), system['slot'].get('label', '?')),
                     (self.t('本工具管理的组件', 'Managed components'), str(len(names))),
                     (self.t('保留的旧版选择', 'Retained legacy choices'), str(len(legacy)))]
            if {'gm7-resume', 'split-lock'} <= set(names):
                facts.append((self.t('恢复时须同时选择', 'Restore together'),
                              self.t('GM7 休眠恢复、Split-lock 报告洪泛修复', 'GM7 suspend recovery, split-lock workaround')))
            pending = result.get('operations', {}).get('pending')
            message = self.t('存在未完成的操作，请到“恢复”继续处理。', 'An unfinished operation needs recovery.') if pending else self.t('系统状态读取完成。旧版文件只有通过接管预检后才会纳入管理。', 'Status loaded. Legacy files require adoption checks before becoming managed.')
            if not pending and current.get('release', {}).get('apply_outcome') == 'aborted_engine_retained':
                message = self.t('组件升级已中止；已恢复升级前的组件，仅保留维护恢复程序。上方版本为维护程序版本。',
                                 'The component upgrade was aborted. Components returned to their prior state; the recovery engine was retained. The version above identifies the maintenance engine.')
            return self._view(self.t('当前状态', 'Current status'), message, facts=facts,
                              items=[dict(id=n, title=self._label(n), detail=self.t('由维护工具管理', 'Managed by this tool'), enabled=True, selected=False) for n in names])
        if action == 'discover':
            self.review = None
            from .releases import check_releases, fetch_catalog
            from .downloads import trusted_key
            from .catalog import describe
            self.candidate = None
            self.seed = None
            release = cli.installed_release()
            report = check_releases(release['version'], self.preferences['channel'], progress=self._network_progress, **self._network_kwargs())
            latest = report.get('latest_project')
            facts = [(self.t('已安装项目', 'Installed project'), release['version'])]
            if latest:
                facts.append((self.t('最新项目', 'Latest project'), latest['version']))
            candidate = report.get('latest_maintenance')
            if not candidate:
                unknown = report['status'] == 'maintenance_availability_unknown'
                message = self.t('已找到项目版本，但暂时无法确认维护包，请重试或导入离线包。' if unknown else '该项目版本尚未提供 Linux 维护包。可稍后重试，也可以导入离线维护包。',
                                 'Project versions found, but bundle availability is unknown. Retry or import offline.' if unknown else 'This project release has no Linux maintenance bundle yet. Retry later or import an offline bundle.')
                return dict(heading=self.t('更新检查完成', 'Update check complete'), message=message, tone='warning', facts=facts)
            value = fetch_catalog(candidate, trusted_key(), progress=self._network_progress, **self._network_kwargs())
            self.candidate = candidate
            # The newly displayed catalog owns the next selection. Never pair
            # it with an unrelated offline bundle retained from an earlier view.
            self.source = None
            if value.get('schema') == 2:
                return self._distribution_view(value)
            try:
                from .probe import live
                system = live()
            except Exception:
                system = None
            catalog = describe(value, system)
            items = []
            for item in catalog['components']:
                name = item['id']
                self.labels[name] = item.get('zh' if self.zh else 'en', name)
                enabled = item['status'] in ('requires_preflight', 'download_available')
                category = item.get('category', item.get('kind', 'plugins'))
                category = category if category in ('repairs', 'plugins') else 'plugins'
                installed = item.get('installed')
                installed = installed if type(installed) is bool else None
                items.append(dict(id=name, title=self._label(name), detail=self._reason(item['reason']), enabled=enabled,
                                  category=category, installed=installed,
                                  selected=enabled and category == 'repairs' and installed is not True))
            items.sort(key=lambda item: item['category'] != 'repairs')
            facts.append((self.t('完整维护包', 'Full maintenance bundle'), '%.1f MiB' % (candidate['size'] / 1024 ** 2)))
            return self._view(self.t('最新修复与插件', 'Latest repairs and plugins'),
                              self.t('功能目录签名已验证。可以只下载，或选择组件后检查安装条件。', 'Signed catalog verified. Download only, or choose components for installation checks.'),
                              facts=facts, items=items, source_ready=self.has_source)
        if action == 'download':
            self.review = None
            if not self.candidate:
                raise RuntimeError(self.t('请先检查更新。', 'Check updates first.'))
            from .downloads import save
            result = save(self.candidate, Path.home() / 'Downloads/OXP3', progress=self._network_progress, **self._network_kwargs())
            self.source = result['path']
            self.seed = self.source
            self.review = None
            distribution = self._distribution()
            if distribution and params.get('selected'):
                self._materialize(params['selected'], distribution)
            return self._view(self.t('维护包已保存', 'Bundle saved'),
                              self.t('所下载内容已通过签名检查。未下载的可选组件会在选择后获取。', 'Downloaded content is verified. Optional components are fetched when selected.'),
                              facts=[(self.t('保存位置', 'Saved to'), str(self.source))], source=str(self.source), source_ready=True)
        if action == 'import':
            path = params.get('path')
            if not isinstance(path, str) or not path:
                raise ValueError('Choose a maintenance bundle')
            self.source = path
            self.seed = path
            self.review = None
            distribution = self._distribution()
            if distribution:
                return self._distribution_view(distribution)
            return self._plan_view(self._backend('plan', all_components=True))
        if action == 'plan':
            self.review = None
            if not self.source:
                self._perform('download')
            selected = params.get('selected', [])
            if not isinstance(selected, list) or any(not isinstance(n, str) for n in selected):
                raise ValueError('Invalid component selection')
            selected = list(selected)
            tool_only = bool(params.get('tool_only', False))
            if not selected and not tool_only:
                raise RuntimeError(self.t('至少选择一项，或选择“仅更新工具”。', 'Choose a component or select tool-only update.'))
            distribution = self._distribution()
            continuation = None
            if distribution:
                from .update_state import needs_engine_bridge
                if needs_engine_bridge(cli.installed_release()):
                    # The old privileged verifier can authenticate the schema-1
                    # seed. Upgrade it with an explicit review before asking it
                    # to process a modular archive; never run fetched code as root.
                    if not self.seed:
                        raise RuntimeError('Import the core maintenance package to upgrade the older maintenance engine first')
                    self.source = self.seed
                    from .bundle import inspect_bundle
                    from .downloads import trusted_key
                    if inspect_bundle(self.source, trusted_key())['schema'] != 1:
                        raise RuntimeError('The older maintenance engine needs the core package; run the latest Bash installer')
                    continuation = list(selected) if not tool_only else None
                    selected, tool_only = [], True
                elif not tool_only:
                    self._materialize(selected, distribution)
            result = self._backend('plan', selected, tool_only=tool_only)
            self.review = {'source': self.source, 'selected': list(selected), 'tool_only': tool_only,
                           'version': result['release']['version'], 'digest': result['manifest_digest'],
                           'continuation': continuation} if result['can_apply'] else None
            view = self._plan_view(result, review=True)
            if continuation is not None:
                view['message'] = self.t('先升级维护程序以支持按需下载；现有修复保持原状。完成后继续检查你选择的组件。',
                                         'First upgrade the maintenance engine for component downloads, preserving existing repairs. Your selected updates will be reviewed next.')
            return view
        if action == 'apply':
            if not self.review or self.review['source'] != self.source:
                raise RuntimeError(self.t('请重新检查并确认本次修改。', 'Review the changes again before applying.'))
            review, self.review = self.review, None
            result = self._backend('apply', review['selected'], tool_only=review['tool_only'],
                                   expected_version=review['version'], expected_manifest=review['digest'])
            if result.get('status') == 'preflight_refused':
                return self._plan_view(result, review=True)
            from .gui import _after_install
            _after_install(result)
            if review.get('continuation') is not None:
                return self._perform('plan', selected=review['continuation'])
            return self._result_view(result)
        if action in ('rollback', 'restore', 'recover'):
            selected = params.get('selected', [])
            if action == 'restore' and not selected:
                raise RuntimeError(self.t('先选择要恢复原状的组件。', 'Choose components to restore first.'))
            return self._result_view(self._backend(action, selected))
        if action == 'logs':
            result = self._backend('logs')
            if result.get('status') == 'no_operations_recorded':
                return self._view(self.t('最近操作', 'Last operation'), self.t('还没有操作记录。', 'No operations have been recorded.'))
            value = result.get('result', result)
            if 'error' in value:
                return self._view(self.t('最近操作未完成', 'Last operation did not finish'), self.error_text(value['error']))
            if value.get('status') == 'preflight_refused':
                return dict(heading=self.t('上次操作未应用', 'Last operation was not applied'),
                            message=self.t('预检未通过，没有写入组件文件。调整选择或检查旧安装记录后重试。',
                                           'Preflight refused the changes. No component files were written. Adjust the selection or review legacy installation records.'),
                            tone='warning', facts=[(self._label(name), self._reason(item.get('reason', '')))
                                                  for name, item in value.get('components', {}).items() if item.get('status') == 'blocked'])
            view = self._result_view(value, self.t('最近操作', 'Last operation'))
            if result.get('time'):
                view['facts'].insert(0, (self.t('时间', 'Time'), result['time']))
            return view
        raise ValueError('Unknown desktop action')
