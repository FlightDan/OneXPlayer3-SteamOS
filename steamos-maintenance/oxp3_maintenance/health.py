"""Read-only, bounded diagnostics. Findings are evidence, never repair authority.

No input events, journal text, config contents, serial numbers or credentials are
exported. A healthy enumeration does not prove that buttons reach a game.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
import zipfile

from . import inventory
from .adoption import _MUTABLE_SETTINGS
from .transactions import Store

STATE = 'home/.oxp3-maintenance'
MAX_STATE = 256 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_PATHS = 20000
MAX_DETAILS = 100
UNITS = ('inputplumber.service', 'oxp3-gyro.service')
PROPERTIES = ('Id', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState',
              'Result', 'ExecMainStatus', 'ConditionResult')
STATUSES = ('warning', 'unknown', 'info', 'ok')


def words(zh, en):
    return {'zh': zh, 'en': en}


def clean(value, limit=160):
    return ''.join(c for c in str(value) if c.isprintable())[:limit]


@contextmanager
def regular(root, relative, *, trusted=False):
    """Pin each ancestor; do not follow links or open special files for reading."""
    parts = inventory._parts(relative)
    with inventory._directory(root, '/'.join(parts[:-1]), trusted=trusted) as (parent, _):
        if os.name == 'posix':
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        else:
            path = parent / parts[-1]
            if inventory._linked(path.lstat()):
                raise ValueError('unsafe_file')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('unsafe_file')
            if trusted and not inventory._protected(info):
                raise ValueError('untrusted_metadata')
            yield stream, info


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_json(root, relative, maximum=8 * 1024 * 1024):
    with regular(root, relative, trusted=True) as (stream, before):
        if before.st_size > maximum:
            raise ValueError('size_limit')
        raw = stream.read(maximum + 1)
        if len(raw) > maximum or stamp(before) != stamp(os.fstat(stream.fileno())):
            raise ValueError('size_limit_or_changed_during_check')
    value = json.loads(raw, object_pairs_hook=inventory._unique)
    if not isinstance(value, dict):
        raise ValueError('invalid_record')
    return value


def fingerprint(root, relative, budget):
    Store._path(relative)
    try:
        with regular(root, relative) as (stream, before):
            if before.st_size > MAX_FILE or budget[0] + before.st_size > MAX_TOTAL:
                raise ValueError('size_limit')
            digest, length = hashlib.sha256(), 0
            while chunk := stream.read(1024 * 1024):
                length += len(chunk)
                budget[0] += len(chunk)
                if length > MAX_FILE or budget[0] > MAX_TOTAL:
                    raise ValueError('size_limit')
                digest.update(chunk)
            if stamp(before) != stamp(os.fstat(stream.fileno())):
                raise ValueError('changed_during_check')
            return {'exists': True, 'sha256': digest.hexdigest(), 'bytes': length,
                    'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid, 'gid': before.st_gid}
    except FileNotFoundError:
        return {'exists': False}


def expected_snapshot(value):
    if not isinstance(value, dict) or type(value.get('exists')) is not bool:
        raise ValueError('invalid_snapshot')
    if not value['exists']:
        return {'exists': False}
    blob = value.get('data')
    if not isinstance(blob, str) or len(blob) > (MAX_FILE + 2) // 3 * 4:
        raise ValueError('size_limit')
    raw = base64.b64decode(blob, validate=True)
    result = {'exists': True, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    for key in ('mode', 'uid', 'gid'):
        if type(value.get(key)) is not int or value[key] < 0:
            raise ValueError('invalid_metadata')
        result[key] = value[key]
    if result['mode'] > 0o7777:
        raise ValueError('invalid_metadata')
    return result


def read_kernel(root, relative, maximum=256 * 1024):
    """Kernel sysfs links are permitted only inside this root's sys/proc tree."""
    area = relative.split('/')[0]
    if area not in ('sys', 'proc'):
        raise ValueError('invalid_kernel_path')
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to((root / area).resolve(strict=True)):
        raise ValueError('unsafe_kernel_link')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('size_limit')
    return raw.decode('utf-8', errors='replace')


def input_devices(raw):
    result = []
    for block in raw.split('\n\n'):
        if not block.strip():
            continue
        if len(result) >= 128:
            raise ValueError('device_limit')
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        identity = re.fullmatch(r'Bus=([0-9a-fA-F]{4}) Vendor=([0-9a-fA-F]{4}) Product=([0-9a-fA-F]{4}) Version=([0-9a-fA-F]{4})', fields.get('I', ''))
        handlers = re.findall(r'\b(?:event|js)\d+\b', fields.get('H', ''))
        name = fields.get('N', '').removeprefix('Name=').strip('"')
        # Bitmap lines have repeated B: keys; extract KEY directly.
        key_line = next((line[7:] for line in block.splitlines() if line.startswith('B: KEY=')), '')
        keys = 0
        for word in key_line.split():
            if not re.fullmatch('[0-9a-fA-F]{1,16}', word):
                raise ValueError('invalid_bitmap')
            # This distribution targets x86_64 SteamOS, including Windows fixtures.
            keys = (keys << 64) | int(word, 16)
        gamepad = bool(keys & (0xffff << 0x130)) or any(h.startswith('js') for h in handlers)
        # Phys and Uniq are deliberately discarded; Sysfs is reduced to a flag.
        result.append({'name': clean(name), 'handlers': handlers,
                       'vendor': identity[2].lower() if identity else None,
                       'product': identity[3].lower() if identity else None,
                       'gamepad_capability': gamepad,
                       'virtual': '/devices/virtual/' in fields.get('S', '')})
    return result


def service_states():
    result = subprocess.run(['/usr/bin/systemctl', 'show', '--no-pager',
        '--property=' + ','.join(PROPERTIES), *UNITS], capture_output=True, text=True,
        timeout=12, env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C', 'LANG': 'C.UTF-8'})
    if len(result.stdout) > 16384:
        raise ValueError('size_limit')
    states = {}
    for block in result.stdout.split('\n\n'):
        fields = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        name = fields.get('Id')
        if name in UNITS:
            states[name] = {key: clean(fields[key], 80) for key in PROPERTIES if key in fields}
    if not states:
        raise ValueError('service_query_unavailable')
    return states


class Report:
    def __init__(self, root):
        self.root = Path(os.path.abspath(root))
        self.checks = []
        self.budget = [0]

    def add(self, identifier, status, title, message, advice, **evidence):
        self.checks.append(dict(id=identifier, status=status, title=title, message=message,
                                advice=advice, evidence=evidence))

    def unknown(self, identifier, title, error):
        self.add(identifier, 'unknown', title,
                 words('此项未能完成，不能据此判断正常。', 'This check could not finish; health is unknown.'),
                 words('重新体检；若仍无法读取，请导出报告反馈。', 'Run the check again. Export the report if it remains unavailable.'),
                 reason=type(error).__name__)

    def interrupted(self):
        # A first transaction writes pending before index. Inspect markers even
        # when the index/lock is missing; never interpret legacy data as current
        # while files may be between generations. No private snapshots are read.
        found = []
        for name in ('pending.json', 'live-operation.json'):
            try:
                with regular(self.root, STATE + '/' + name, trusted=True):
                    found.append(name)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, RuntimeError) as error:
                self.unknown('maintenance.operation', words('维护操作状态', 'Maintenance operation state'), error)
                return True
        if found:
            self.add('maintenance.operation', 'warning', words('存在待完成的维护操作', 'An unfinished maintenance operation exists'),
                     words('文件可能处于更改过程中，本次跳过安装基线比对。', 'Files may be between generations; installation baseline comparison was skipped.'),
                     words('若升级仍在运行，请等待完成后重新体检；否则到“恢复”检查中断操作。',
                           'If an update is running, let it finish and rerun the check. Otherwise review interrupted operations under Recovery.'),
                     markers=found)
        return bool(found)

    def compare(self, name, entries, *, source):
        title = words('组件文件：' + name, 'Component files: ' + name)
        if not entries:
            self.add('files.' + name, 'unknown', title,
                     words('没有可核对的文件基线。', 'No file baseline is available.'),
                     words('保留现状，结合服务和设备检查结果判断。', 'Keep the current setup and review service/device findings.'))
            return
        differences, unknown, custom, checked, problems = [], 0, 0, 0, 0
        for relative, expected, mutable in entries:
            try:
                actual = fingerprint(self.root, relative, self.budget)
                mismatch = {key: {'expected': value, 'actual': actual.get(key)}
                            for key, value in expected.items() if actual.get(key) != value}
                checked += 1
                if not mismatch:
                    continue
                customized = mutable and expected.get('exists') and actual.get('exists') and set(mismatch) <= {'sha256', 'bytes'}
                if customized:
                    custom += 1
                else:
                    problems += 1
                if len(differences) < MAX_DETAILS:
                    differences.append({'path': relative, 'kind': 'customized' if customized else 'mismatch', 'differences': mismatch})
            except (OSError, ValueError, RuntimeError) as error:
                unknown += 1
                if len(differences) < MAX_DETAILS:
                    differences.append({'path': clean(relative, 300), 'kind': 'unreadable', 'reason': type(error).__name__})
        status = 'warning' if problems else 'unknown' if unknown else 'info' if custom else 'ok'
        self.add('files.' + name, status, title,
                 words(f'已核对 {checked} 项；差异 {problems} 项，自定义配置 {custom} 项，未能读取 {unknown} 项。',
                       f'Checked {checked} files; {problems} mismatches, {custom} customized settings, {unknown} unreadable.'),
                 words('差异不等于故障。先查看路径并导出报告，确认原因后再选择修复；自定义配置不会自动覆盖。',
                       'A difference is not necessarily a fault. Review paths and export the report before choosing repairs; custom settings are not overwritten.'),
                 source=source, checked=checked, mismatches=problems, customized=custom,
                 unreadable=unknown, details=differences, details_truncated=problems + custom + unknown > len(differences))

    def managed(self, system):
        """Take a nonblocking shared lock on an EXISTING lock file. Never create it."""
        selected, authoritative = set(), set()
        title = words('维护记录与未完成操作', 'Maintenance records and unfinished operations')
        try:
            with regular(self.root, STATE + '/lock', trusted=True) as (lock, _):
                if os.name == 'posix':
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                index = read_json(self.root, STATE + '/index.json', MAX_STATE)
                if index.get('format') != 1 or not isinstance(index.get('slots'), dict):
                    raise ValueError('invalid_index')
                slot = system.get('slot', {}).get('id')
                if not slot:
                    raise ValueError('unknown_active_slot')
                slot_record = index['slots'].get(slot, {})
                if not isinstance(slot_record, dict):
                    raise ValueError('invalid_slot_record')
                current = slot_record.get('current')
                if current is not None:
                    if not isinstance(current, dict):
                        raise ValueError('invalid_generation')
                    paths = current.get('paths')
                    if not isinstance(paths, dict) or len(paths) > MAX_PATHS:
                        raise ValueError('invalid_paths')
                    choices = current.get('selected', [])
                    if not isinstance(choices, list) or any(not isinstance(n, str) for n in choices):
                        raise ValueError('invalid_choices')
                    selected = set(choices)
                    adopted = current.get('legacy_adopted', [])
                    if not isinstance(adopted, list) or any(not isinstance(n, str) for n in adopted):
                        raise ValueError('invalid_adopted_choices')
                    authoritative = selected | set(adopted)
                    grouped = {}
                    for relative, entry in paths.items():
                        Store._path(relative)
                        if not isinstance(entry, dict):
                            raise ValueError('invalid_entry')
                        name = entry.get('component')
                        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name) or type(entry.get('mutable')) is not bool:
                            raise ValueError('invalid_entry')
                        grouped.setdefault(name, []).append((relative, expected_snapshot(entry['snapshot']), entry['mutable']))
                    for name in sorted(grouped):
                        self.compare(name, grouped[name], source='maintenance_snapshot')
                pending = None
                try:
                    pending = read_json(self.root, STATE + '/pending.json', MAX_STATE)
                except FileNotFoundError:
                    pass
                self.add('maintenance.state', 'warning' if pending is not None else 'ok', title,
                         words('发现未完成的维护事务。' if pending is not None else '已读取当前系统槽的维护记录。',
                               'An unfinished maintenance transaction exists.' if pending is not None else 'Read maintenance records for the active system slot.'),
                         words('请先在“恢复”中检查中断操作。' if pending is not None else '文件检查仅以当前记录为基线，不证明所有功能实际有效。',
                               'Review interrupted operations under Recovery.' if pending is not None else 'File checks use the saved baseline; they do not prove runtime behavior.'),
                         pending=pending is not None)
        except FileNotFoundError:
            if (self.root / STATE / 'index.json').exists():
                self.unknown('maintenance.state', title, ValueError('missing_lock'))
                return selected, None
            self.add('maintenance.state', 'info', title,
                     words('未找到完整的维护记录，将尝试旧安装记录。', 'No complete maintenance record; checking legacy installer records.'),
                     words('首次使用或尚未接管的旧安装可能出现此结果。', 'This can occur on first use or an installation not yet adopted.'))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            self.unknown('maintenance.state', title, error)
            # An unreadable current index must never revive stale legacy records.
            return selected, None
        return selected, authoritative

    def legacy(self, system, authoritative):
        if authoritative is None:
            return set()
        evidence = inventory.inspect(self.root, system)
        selected = set()
        for name, record in evidence['components'].items():
            if name in authoritative or record['state'] == 'absent':
                continue
            if record['selected']:
                selected.add(name)
            sources = [p for p in record['sources'] if p.endswith('/state.json')]
            if not sources:
                continue
            try:
                entries = []
                for source in sources:
                    journal = read_json(self.root, source)
                    inventory._backup_complete(journal)
                    for relative in journal['allowed']:
                        Store._path(relative)
                        raw = base64.b64decode(journal['applied'][relative], validate=True)
                        # Legacy applied journals record bytes, not necessarily final metadata.
                        expected = {'exists': True, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                        entries.append((relative, expected, relative in _MUTABLE_SETTINGS.get(name, set())))
                self.compare(name, entries, source='legacy_installer_bytes')
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                self.unknown('legacy.' + name, words('旧安装记录：' + name, 'Legacy installation: ' + name), error)
        if evidence['conflicts']:
            self.add('legacy.records', 'unknown', words('旧安装记录读取', 'Legacy record checks'),
                     words('部分安装记录存在冲突或无法读取。', 'Some installation records conflict or could not be read.'),
                     words('导出报告排查；本次不会接管或更改这些记录。', 'Export the report for investigation; these records are not adopted or modified.'),
                     conflicts=evidence['conflicts'][:MAX_DETAILS])
        return selected

    def controllers(self, system, selected, query):
        try:
            devices = input_devices(read_kernel(self.root, 'proc/bus/input/devices'))
            candidates = [d for d in devices if d['gamepad_capability']]
            self.add('input.devices', 'info' if candidates else 'warning',
                     words('系统识别到的手柄', 'Controllers visible to the system'),
                     words(f'发现 {len(candidates)} 个带游戏手柄能力的输入设备。', f'Found {len(candidates)} input devices with gamepad capabilities.'),
                     words('在 Steam 的控制器测试中按键确认。没有识别到时，检查手柄模式、连接及 InputPlumber 服务。',
                           'Confirm buttons in Steam controller testing. If no controller is visible, check its mode, connection and InputPlumber.'),
                     devices=devices, gamepads=len(candidates))
        except (OSError, ValueError) as error:
            self.unknown('input.devices', words('系统识别到的手柄', 'Controllers visible to the system'), error)
        try:
            states = query()
            for unit in UNITS:
                state = states.get(unit)
                if not state or not all(k in state for k in ('LoadState', 'ActiveState')):
                    self.unknown('service.' + unit, words('输入服务：' + unit, 'Input service: ' + unit), ValueError())
                    continue
                oxp3 = system.get('dmi', {}).get('sys_vendor') == 'ONE-NETBOOK' and system.get('dmi', {}).get('product_name') == 'ONEXPLAYER 3'
                required = ('input' in selected or oxp3) if unit == 'inputplumber.service' else 'gyro' in selected
                healthy = state['LoadState'] == 'loaded' and state['ActiveState'] == 'active'
                self.add('service.' + unit, 'ok' if healthy else 'warning' if required else 'info',
                         words('输入服务：' + unit, 'Input service: ' + unit),
                         words('服务已加载并运行。' if healthy else '服务未运行、缺失或启动失败。',
                               'The service is loaded and active.' if healthy else 'The service is inactive, missing or failed.'),
                         words('服务运行不能证明按键转发正常。陀螺仪服务是可选项，未安装时不作为手柄故障。',
                               'An active service does not prove button forwarding. The optional gyro service is not required for basic gamepad input.'),
                         **state)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.unknown('input.services', words('输入服务状态', 'Input service state'), error)
        if system.get('dmi', {}).get('sys_vendor') == 'ONE-NETBOOK' and system.get('dmi', {}).get('product_name') == 'ONEXPLAYER 3':
            try:
                profiles = {}
                for name in ('49-onexplayer_3-gyro.yaml', '50-onexplayer_3.yaml'):
                    value = fingerprint(self.root, 'etc/inputplumber/devices.d/' + name, self.budget)
                    profiles[name] = value.get('exists', False)
                found = any(profiles.values())
                self.add('input.profile', 'info' if found else 'warning', words('OXP3 输入配置', 'OXP3 input profile'),
                         words('已发现项目输入配置。' if found else '未发现项目的基础或陀螺仪输入配置。',
                               'A project input profile exists.' if found else 'Neither project input profile was found.'),
                         words('陀螺仪配置可替代基础配置；存在文件不代表匹配或生效。结合文件差异和 Steam 按键测试判断。',
                               'The gyro profile can replace the base profile. File presence does not prove it matches or is active; review differences and test in Steam.'),
                         profiles=profiles)
            except (OSError, ValueError, RuntimeError) as error:
                self.unknown('input.profile', words('OXP3 输入配置', 'OXP3 input profile'), error)


def collect(*, root=Path('/'), system_probe=None, query_services=None):
    from . import probe
    report = Report(root)
    system = {}
    try:
        system = (system_probe or probe.live)()
        # Only these identity fields enter the public report; no disk serial/PARTUUID.
        context = {'os': {k: clean(v) for k, v in system.get('os', {}).items() if k in ('ID', 'VERSION_ID', 'BUILD_ID')},
                   'kernel': clean(system.get('kernel', '')), 'bios': clean(system.get('bios', '')),
                   'dmi': {k: clean(v) for k, v in system.get('dmi', {}).items() if k in ('sys_vendor', 'product_name')},
                   'slot': clean(system.get('slot', {}).get('label', '?')),
                   'inputplumber': clean(system.get('packages', {}).get('inputplumber', 'unknown'))}
        report.add('system.identity', 'ok', words('系统信息', 'System identity'),
                   words('已识别当前系统与活动系统槽。', 'Identified the system and active slot.'),
                   words('只针对当前运行的系统检查。', 'Checks apply to the currently running system.'), **context)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report.unknown('system.identity', words('系统信息', 'System identity'), error)
        # Device enumeration must remain useful when strict slot/base probing fails.
        for key, relative in (('sys_vendor', 'sys/class/dmi/id/sys_vendor'),
                              ('product_name', 'sys/class/dmi/id/product_name')):
            try:
                system.setdefault('dmi', {})[key] = clean(read_kernel(report.root, relative, 4096).strip())
            except (OSError, ValueError):
                pass
        if system.get('dmi'):
            report.add('system.device', 'info', words('设备型号', 'Device model'),
                       words('系统槽检测未完成，已读取基本设备型号。', 'Slot detection did not complete; basic device identity was read.'),
                       words('仍可查看输入设备和服务状态。', 'Input devices and services can still be checked.'), **system['dmi'])
    selected, authoritative = (set(), None) if report.interrupted() else report.managed(system)
    try:
        selected |= report.legacy(system, authoritative)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        report.unknown('legacy.records', words('旧安装记录', 'Legacy installation records'), error)
    report.controllers(system, selected, query_services or service_states)
    report.add('input.manual_test', 'info', words('按键实际响应', 'Actual button response'),
               words('本次没有读取按键事件，尚未验证游戏内响应。', 'Input events were not captured; in-game response is unverified.'),
               words('打开 Steam → 设置 → 控制器 → 测试设备输入，按动按键和摇杆；反馈时注明桌面或游戏模式、故障发生时间及体检报告。',
                     'Open Steam → Settings → Controller → Test Device Inputs and test buttons/sticks. Include desktop/game mode, when the problem started, and this report with feedback.'))
    report.checks.sort(key=lambda item: STATUSES.index(item['status']))
    counts = {status: sum(item['status'] == status for item in report.checks) for status in STATUSES}
    return {'schema': 1, 'kind': 'oxp3-health-report', 'created_at': datetime.now(timezone.utc).isoformat(),
            'read_only': True, 'scope': 'active_system_configuration_and_controller_enumeration',
            'summary': counts, 'checks': report.checks}


def render_text(report, language='zh'):
    lines = ['OXP3 ' + ('体检报告' if language == 'zh' else 'Health report'), report['created_at'], '']
    for check in report['checks']:
        lines.extend([f"[{check['status']}] {check['title'][language]}", check['message'][language],
                      check['advice'][language], json.dumps(check['evidence'], ensure_ascii=False, indent=2), ''])
    return '\n'.join(lines)


def export_report(report, destination, language='zh'):
    """User-initiated export in the unprivileged desktop process, no upload."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    name = 'oxp3-health-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.zip'
    path = destination / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('report.json', json.dumps(report, ensure_ascii=False, indent=2))
            archive.writestr('report.txt', render_text(report, language))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
