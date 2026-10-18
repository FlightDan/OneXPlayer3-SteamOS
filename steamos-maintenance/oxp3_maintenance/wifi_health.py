"""Bounded, read-only Wi-Fi observations; never export network identities/logs."""
from datetime import datetime, timezone
from itertools import islice
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

MAX_OUTPUT = 128 * 1024
MAX_INTERFACES = 8
MAX_LOGS = 200
TIMEOUT = 5
TOTAL_TIMEOUT = 12
ENV = {'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C', 'LANG': 'C.UTF-8'}
DRIVERS = frozenset(('iwlwifi', 'ath9k', 'ath10k_pci', 'ath11k_pci', 'ath12k_pci',
                     'rtw89_8852be', 'rtw89_8852ce', 'rtw89_8922ae', 'rtw88_8822ce',
                     'mt7921e', 'mt7925e', 'brcmfmac', 'mac80211_hwsim'))
# Stable numeric enums, verified against the upstream D-Bus reference:
# https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-dbus-types.html
NM_REASONS = {0: 'none', 1: 'unknown', 4: 'configuration_failed',
              5: 'ip_configuration_unavailable', 6: 'ip_configuration_expired',
              7: 'secrets_unavailable', 8: 'supplicant_disconnected',
              9: 'supplicant_configuration_failed', 10: 'supplicant_failed',
              11: 'supplicant_timeout', 15: 'dhcp_start_failed', 17: 'dhcp_failed',
              22: 'autoip_failed', 38: 'connection_removed', 39: 'user_disconnected',
              53: 'ssid_not_found'}
NM_STATES = {10: 'unmanaged', 20: 'unavailable', 30: 'disconnected',
             40: 'preparing', 50: 'configuring', 60: 'secrets_required',
             70: 'ip_configuring', 80: 'ip_checking', 90: 'secondaries',
             100: 'activated', 110: 'deactivating', 120: 'failed'}
NM_STATES_ZH = {10: '未托管', 20: '不可用', 30: '未连接', 40: '准备连接',
                50: '正在配置', 60: '需要认证信息', 70: '正在配置地址',
                80: '正在检查地址', 90: '等待附加连接', 100: '已连接',
                110: '正在断开', 120: '连接失败'}
NM_REASONS_ZH = {0: '无特定原因', 1: '未知错误', 4: '配置失败', 5: '无法获取地址',
                 6: '地址配置过期', 7: '缺少认证信息', 8: '认证程序断开',
                 9: '认证程序配置失败', 10: '认证程序失败', 11: '认证超时',
                 15: 'DHCP 启动失败', 17: 'DHCP 失败', 22: '自动地址配置失败',
                 38: '连接已消失', 39: '用户或客户端请求断开', 53: '未找到目标无线网络'}
EVENTS_ZH = {'driver_firmware_error': '驱动固件或微码错误',
             'firmware_load_failed': '固件加载失败', 'driver_timeout': '无线驱动超时',
             'wireless_driver_error': '无线驱动错误',
             'authentication_secrets_unavailable': '缺少无线认证信息',
             'authentication_failed': '无线认证失败', 'supplicant_failure': '无线认证程序失败',
             'ip_configuration_failed': '无线地址配置失败',
             'wireless_connection_failed': '无线连接失败'}


def words(zh, en):
    return {'zh': zh, 'en': en}


def check(identifier, status, title, message, advice, **evidence):
    return {'id': identifier, 'status': status, 'title': words(*title),
            'message': words(*message), 'advice': words(*advice), 'evidence': evidence}


def unknown(identifier, title, reason, **evidence):
    return check(identifier, 'unknown', title,
                 ('此项未能完整读取，不能据此判断正常。',
                  'This observation is incomplete; health is unknown.'),
                 ('重新体检；仍无法读取时可导出报告反馈。',
                  'Run the check again; export the report if it remains unavailable.'),
                 reason=reason, **evidence)


def _query(argv, *, timeout=None):
    """Drain both pipes with a hard memory cap and terminate on time/output limits.

    stderr is used only as an availability flag, and is never returned/exported.
    All callers supply absolute executable paths and fixed read-only arguments.
    """
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=ENV, stdin=subprocess.DEVNULL, shell=False)
    except OSError:
        return {'stdout': '', 'reason': 'tool_unavailable'}
    buffers = [bytearray(), bytearray()]
    limited = threading.Event()

    def drain(stream, target):
        try:
            while True:
                chunk = os.read(stream.fileno(), 4096)
                if not chunk:
                    break
                remaining = MAX_OUTPUT - len(target)
                target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    limited.set()
                    process.kill()
                    break
        except OSError:
            limited.set()
        finally:
            stream.close()

    workers = [threading.Thread(target=drain, args=(stream, target), daemon=True)
               for stream, target in zip((process.stdout, process.stderr), buffers)]
    for worker in workers:
        worker.start()
    reason = None
    try:
        process.wait(timeout=TIMEOUT if timeout is None else timeout)
    except subprocess.TimeoutExpired:
        reason = 'timeout'
        process.kill()
        process.wait(timeout=1)
    for worker in workers:
        worker.join(timeout=0.2)
    if limited.is_set() or any(worker.is_alive() for worker in workers):
        reason = reason or 'output_limit'
    elif process.returncode or buffers[1]:
        reason = reason or 'query_failed_or_partial_access'
    return {'stdout': bytes(buffers[0]).decode('utf-8', errors='replace'), 'reason': reason}


def _limited_query(deadline):
    def run(argv):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'stdout': '', 'reason': 'query_budget_exhausted'}
        return _query(argv, timeout=min(TIMEOUT, remaining))
    return run


def _inside(root, relative):
    base = (root / 'sys').resolve(strict=True)
    # A redirected sys anchor must not redefine the permitted kernel subtree.
    # Links below a genuine sys root (normal sysfs class/device links) are valid.
    if base != root.resolve(strict=True) / 'sys':
        raise ValueError('unsafe_sysfs_anchor')
    target = (root / relative).resolve(strict=True)
    if not target.is_relative_to(base):
        raise ValueError('unsafe_sysfs_link')
    return target


def _read(root, relative):
    with _inside(root, relative).open('rb') as stream:
        raw = stream.read(129)
    if len(raw) > 128:
        raise ValueError('sysfs_output_limit')
    return raw.decode('ascii').strip()


def _entries(root, relative, maximum=128):
    values = list(islice(_inside(root, relative).iterdir(), maximum + 1))
    if len(values) > maximum:
        raise ValueError('sysfs_entry_limit')
    return sorted(values, key=lambda path: path.name)


def _interfaces(root):
    result = []
    for entry in _entries(root, 'sys/class/net'):
        # Names are used only as an argv element, never as output or an option.
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', entry.name):
            raise ValueError('invalid_interface_name')
        relative = 'sys/class/net/' + entry.name
        _inside(root, relative)
        wireless = False
        for marker in ('wireless', 'phy80211'):
            try:
                _inside(root, relative + '/' + marker)
                wireless = True
            except FileNotFoundError:
                pass
        if wireless:
            result.append(entry.name)
            if len(result) > MAX_INTERFACES:
                raise ValueError('interface_limit')
    return result


def _nm(raw):
    values = {}
    ipv4 = ipv6 = False
    for line in raw.splitlines():
        if line.startswith('IP4.ADDRESS['):
            ipv4 |= bool(line.partition(':')[2].strip())
        elif line.startswith('IP6.ADDRESS['):
            ipv6 |= bool(line.partition(':')[2].strip())
        elif line.startswith(('GENERAL.STATE:', 'GENERAL.REASON:')):
            key, _, value = line.partition(':')
            match = re.fullmatch(r'(\d{1,3})(?:\s+\([^\r\n]*\))?', value.strip())
            if match:
                values[key] = int(match[1])
    if not all(key in values for key in ('GENERAL.STATE', 'GENERAL.REASON')):
        raise ValueError('incomplete_networkmanager_state')
    state, reason = values['GENERAL.STATE'], values['GENERAL.REASON']
    if state not in NM_STATES:
        raise ValueError('unknown_networkmanager_state')
    return {'state': NM_STATES[state], 'state_code': state, 'reason_code': reason,
            'reason': NM_REASONS.get(reason, 'other'), 'has_ipv4': ipv4, 'has_ipv6': ipv6}


def _event(raw):
    """Map identified errors to fixed categories; discard every raw text field."""
    if not isinstance(raw, dict) or not isinstance(raw.get('MESSAGE'), str):
        return None
    message = raw['MESSAGE']
    if len(message) > 32768:
        return None
    lower = message.lower()
    kernel = raw.get('_TRANSPORT') == 'kernel'
    nm = raw.get('_SYSTEMD_UNIT') == 'NetworkManager.service'
    driver = any(name in lower for name in ('iwlwifi', 'ath9k', 'ath10k', 'ath11k',
                                           'ath12k', 'rtw89', 'rtw88', 'mt7921',
                                           'mt7925', 'brcmfmac'))
    category = None
    if kernel and driver:
        if re.search(r'(?:failed|failure).*(?:firmware|ucode)|firmware.*(?:failed|failure|not found)', lower):
            category = 'firmware_load_failed'
        elif re.search(r'(?:microcode|ucode|firmware).*\b(?:error|crash|assert)\b', lower):
            category = 'driver_firmware_error'
        elif re.search(r'timed?\s*out|timeout', lower):
            category = 'driver_timeout'
        elif re.search(r'\b(?:error|failed|failure)\b', lower):
            category = 'wireless_driver_error'
    elif nm and re.search(r'\b(?:wifi|wi-fi|wl[a-z0-9_.-]*|supplicant)\b', lower):
        if re.search(r'no.secrets|secrets.*(?:failed|missing|unavailable)', lower):
            category = 'authentication_secrets_unavailable'
        elif re.search(r'auth.*(?:fail|timeout)|(?:fail|timeout).*auth', lower):
            category = 'authentication_failed'
        elif re.search(r'supplicant.*(?:fail|timeout|disconnect)', lower):
            category = 'supplicant_failure'
        elif re.search(r'ip-config-unavailable|dhcp.*(?:fail|timeout)', lower):
            category = 'ip_configuration_failed'
        elif re.search(r'\b(?:failed|failure|error|timeout)\b', lower):
            category = 'wireless_connection_failed'
    if category is None:
        return None
    event = {'category': category}
    # Only constrained numeric error codes and UTC time survive the mapping.
    code = re.search(r'\b(?:error|errno|status|reason|ucode)(?:\s+code)?\s*[=:]\s*(-?\d{1,5})(?!\d)', lower)
    if code:
        event['code'] = int(code[1])
    timestamp = raw.get('__REALTIME_TIMESTAMP')
    if isinstance(timestamp, str) and re.fullmatch(r'\d{1,17}', timestamp):
        try:
            event['time_utc'] = datetime.fromtimestamp(int(timestamp) / 1000000, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return event


def _logs(query, boot):
    title = ('最近 Wi-Fi 报错（本次启动）', 'Recent Wi-Fi errors (current boot)') if boot == 0 else (
        '最近 Wi-Fi 报错（上次启动）', 'Recent Wi-Fi errors (previous boot)')
    identifier = 'wifi.logs.current' if boot == 0 else 'wifi.logs.previous'
    response = query(['/usr/bin/journalctl', '--no-pager', '--quiet', '--boot=' + str(boot),
                      '--priority=warning', '--lines=' + str(MAX_LOGS), '--output=json',
                      '--output-fields=MESSAGE,__REALTIME_TIMESTAMP,_TRANSPORT,_SYSTEMD_UNIT',
                      '_TRANSPORT=kernel', '+', '_SYSTEMD_UNIT=NetworkManager.service'])
    events, malformed, lines = [], False, response.get('stdout', '').splitlines()
    for line in lines[:MAX_LOGS]:
        try:
            record = json.loads(line)
            if (not isinstance(record, dict) or not isinstance(record.get('MESSAGE'), str)
                    or len(record['MESSAGE']) > 32768):
                malformed = True
                continue
            event = _event(record)
            if event:
                events.append(event)
        except (ValueError, TypeError):
            malformed = True
    evidence = {'boot': boot, 'events': events[-40:], 'events_truncated': len(events) > 40,
                'query_limit': MAX_LOGS, 'warning_priority_only': True,
                'scope': 'recent_kernel_and_networkmanager_warnings'}
    incomplete = response.get('reason') or ('invalid_or_truncated_output' if malformed or len(lines) > MAX_LOGS else None)
    summary = '; '.join(event['category'] + (' @ ' + event['time_utc'] if 'time_utc' in event else '') +
                        (' (code ' + str(event['code']) + ')' if 'code' in event else '') for event in events[-3:])
    summary_zh = '；'.join(EVENTS_ZH[event['category']] + ('，时间 ' + event['time_utc'] if 'time_utc' in event else '') +
                          ('，错误码 ' + str(event['code']) if 'code' in event else '') for event in events[-3:])
    if incomplete or not lines:
        result = unknown(identifier, title, incomplete or 'journal_unavailable_or_empty', **evidence)
        if summary:
            result['message']['zh'] += ' 已读取的部分错误：' + summary_zh
            result['message']['en'] += ' Errors in the readable portion: ' + summary
        return result
    return check(identifier, 'warning' if events else 'info', title,
                 ('发现无线错误：' + summary_zh + '。历史错误不一定仍存在。' if events else '有限日志范围内未发现已识别的无线错误，不证明 Wi-Fi 正常。',
                  'Wireless errors: ' + summary + '. Historical errors may have cleared.' if events else 'No recognized wireless errors in the limited log window; this does not establish Wi-Fi health.'),
                 ('结合时间、当前状态及用户遇到故障的时间判断；报告不包含原始日志。',
                  'Compare timestamps with current state and the observed fault; raw logs are excluded.'), **evidence)


def collect(*, root=Path('/'), query=None):
    """Return health check items; an injected query enables isolated fixture tests.

    Offline roots never query the running host unless explicitly injected.
    """
    root = Path(root)
    if query is None:
        query = _limited_query(time.monotonic() + TOTAL_TIMEOUT) if root.resolve() == Path('/').resolve() and os.name == 'posix' else (
            lambda argv: {'stdout': '', 'reason': 'not_live_linux_root'})
    results = []
    try:
        interfaces = _interfaces(root)
        results.append(check('wifi.devices', 'info' if interfaces else 'unknown',
            ('无线网卡枚举', 'Wireless interface enumeration'),
            (f'系统可见 {len(interfaces)} 个无线网络接口。', f'{len(interfaces)} wireless interfaces are visible.'),
            ('未发现接口时，不能仅据此判断网卡损坏；检查设备支持、驱动及固件。',
             'An absent interface does not prove hardware failure; check support, drivers and firmware.'), count=len(interfaces)))
    except (OSError, ValueError, RuntimeError):
        interfaces = []
        results.append(unknown('wifi.devices', ('无线网卡枚举', 'Wireless interface enumeration'), 'sysfs_unavailable_or_unsafe'))
    drivers = []
    for index, interface in enumerate(interfaces, 1):
        record = {'interface_index': index}
        try:
            driver = _inside(root, 'sys/class/net/' + interface + '/device/driver')
            record.update(bound=True, driver=driver.name if driver.name in DRIVERS else 'other')
        except FileNotFoundError:
            record.update(bound=False, driver='unknown')
        except (OSError, ValueError, RuntimeError):
            record.update(bound=None, driver='unknown')
        drivers.append(record)
    driver_summary = '; '.join(str(d['interface_index']) + ': ' + d['driver'] +
                              (' (bound)' if d['bound'] else ' (unbound)' if d['bound'] is False else ' (unknown)') for d in drivers)
    driver_summary_zh = '；'.join(str(d['interface_index']) + '：' +
                               ('其他驱动' if d['driver'] == 'other' else '未知驱动' if d['driver'] == 'unknown' else d['driver']) +
                               ('（已绑定）' if d['bound'] else '（未绑定）' if d['bound'] is False else '（绑定状态未知）') for d in drivers)
    results.append(check('wifi.driver', 'warning' if any(d['bound'] is False for d in drivers) else
        'unknown' if not drivers or any(d['bound'] is None for d in drivers) else 'ok',
        ('无线网卡驱动绑定', 'Wireless driver binding'),
        ('驱动：' + (driver_summary_zh or '未知') + '。仅检查内核绑定，不代表联网成功。',
         'Drivers: ' + (driver_summary or 'unknown') + '. Kernel binding alone does not establish a working connection.'),
        ('驱动未绑定或固件错误时，结合日志检查系统支持；本次不会修改驱动。',
         'For missing bindings or firmware errors, review system support and logs; no driver changes are made.'), interfaces=drivers))
    try:
        blocks = []
        for entry in _entries(root, 'sys/class/rfkill'):
            if not re.fullmatch(r'rfkill\d{1,6}', entry.name):
                raise ValueError('invalid_rfkill_name')
            relative = 'sys/class/rfkill/' + entry.name
            if _read(root, relative + '/type') != 'wlan':
                continue
            soft, hard = _read(root, relative + '/soft'), _read(root, relative + '/hard')
            if soft not in ('0', '1') or hard not in ('0', '1'):
                raise ValueError('invalid_rfkill_state')
            blocks.append({'soft_blocked': soft == '1', 'hard_blocked': hard == '1'})
        blocked = any(b['soft_blocked'] or b['hard_blocked'] for b in blocks)
        soft_count, hard_count = sum(b['soft_blocked'] for b in blocks), sum(b['hard_blocked'] for b in blocks)
        results.append(check('wifi.rfkill', 'warning' if blocked else 'ok' if blocks else 'unknown',
            ('无线开关（rfkill）', 'Wireless radio switches (rfkill)'),
            (f'WLAN 开关 {len(blocks)} 个；软件阻止 {soft_count} 个，硬件阻止 {hard_count} 个。无记录时状态未知。',
             f'{len(blocks)} WLAN switches; {soft_count} soft-blocked, {hard_count} hard-blocked. No records means unknown state.'),
            ('被阻止时检查飞行模式和硬件开关；本次不会解除阻止。', 'If blocked, check airplane mode and hardware switches; this check does not unblock radios.'), radios=blocks))
    except (OSError, ValueError, RuntimeError, UnicodeError):
        results.append(unknown('wifi.rfkill', ('无线开关（rfkill）', 'Wireless radio switches (rfkill)'), 'rfkill_unavailable_or_unsafe'))
    states, failures = [], []
    for index, interface in enumerate(interfaces, 1):
        try:
            response = query(['/usr/bin/nmcli', '--terse', '--escape', 'no', '--fields',
                              'GENERAL.STATE,GENERAL.REASON,IP4.ADDRESS,IP6.ADDRESS', 'device', 'show', interface])
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            response = {'stdout': '', 'reason': 'networkmanager_query_unavailable'}
        if response.get('reason'):
            failures.append({'interface_index': index, 'reason': response['reason']})
            continue
        try:
            states.append({'interface_index': index, **_nm(response.get('stdout', ''))})
        except ValueError:
            failures.append({'interface_index': index, 'reason': 'incomplete_networkmanager_state'})
    nm_summary = '; '.join(str(s['interface_index']) + ': ' + s['state'] + ', reason=' + str(s['reason_code']) +
                          ' (' + s['reason'] + '), IPv4=' + str(s['has_ipv4']) + ', IPv6=' + str(s['has_ipv6']) for s in states)
    nm_summary_zh = '；'.join(str(s['interface_index']) + '：' + NM_STATES_ZH[s['state_code']] +
                             '，原因 ' + str(s['reason_code']) + '（' + NM_REASONS_ZH.get(s['reason_code'], '其他原因') + '）' +
                             '，IPv4 ' + ('有地址' if s['has_ipv4'] else '无地址') +
                             '，IPv6 ' + ('有地址' if s['has_ipv6'] else '无地址') for s in states)
    results.append(check('wifi.networkmanager', 'unknown' if failures or not states else
        'warning' if any(s['state'] == 'failed' for s in states) else 'info',
        ('NetworkManager 无线状态', 'NetworkManager wireless state'),
        ('连接状态：' + (nm_summary_zh or '未知') + f'；未能读取 {len(failures)} 个。未连接不等于驱动故障，未测试外网。',
         'Connection states: ' + (nm_summary or 'unknown') + f'; {len(failures)} unreadable. Disconnection does not imply a driver fault; internet access was not tested.'),
        ('结合状态原因、无线开关及近期日志判断；SSID、地址和凭据不会导出。',
         'Review state reasons, radio switches and recent logs together; SSIDs, addresses and credentials are excluded.'),
        interfaces=states, unreadable=failures))
    for boot in (0, -1):
        try:
            results.append(_logs(query, boot))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            results.append(unknown('wifi.logs.current' if boot == 0 else 'wifi.logs.previous',
                ('无线日志读取', 'Wireless log access'), 'log_query_unavailable'))
    return results
