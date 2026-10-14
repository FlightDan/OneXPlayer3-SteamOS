"""Steam inventory and reversible OptiScaler/native XeSS setup, ordinary user only.

Game file paths are derived from installed Steam manifests. The UI cannot submit
arbitrary write paths or shell commands. Launch options remain in the Steam API.
"""
import argparse
import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import sys
import uuid
from opti import OptiMixin
from download_progress import OperationProgress


def vdf(text):
    # Steam text KeyValues; quoted strings, braces, comments. Preserve Windows escapes.
    tokens = re.finditer(r'"((?:\\.|[^"\\])*)"|([{}])|//[^\n]*', text)
    stream = iter([m.group(1).replace('\\"', '"').replace('\\\\', '\\')
                   if m.group(1) is not None else m.group(2)
                   for m in tokens if m.group(1) is not None or m.group(2)])
    def parse(nested=False):
        result = {}
        for key in stream:
            if key == '}':
                if not nested:
                    raise ValueError('Unexpected KeyValues closing brace')
                return result
            value = next(stream)
            result[key] = parse(True) if value == '{' else value
        if nested:
            raise ValueError('Incomplete Steam manifest')
        return result
    return parse()


def pe_version(path):
    with path.open('rb') as handle:
        data = handle.read(80 * 1024 * 1024)
    if data[:2] != b'MZ':
        return None
    at = data.find(b'\xbd\x04\xef\xfe\x00\x00\x01\x00')
    if at < 0 or at + 16 > len(data):
        return None
    _, _, ms, ls = struct.unpack_from('<4I', data, at)
    return (ms >> 16, ms & 65535, ls >> 16, ls & 65535)


def ini_set(text, section, key, value):
    lines = text.splitlines()
    header = next((n for n, line in enumerate(lines)
                   if line.strip().lower() == '[' + section.lower() + ']'), None)
    if header is None:
        lines.extend(['', '[' + section + ']', key + '=' + value])
    else:
        end = next((n for n in range(header + 1, len(lines)) if lines[n].strip().startswith('[')), len(lines))
        matches = [n for n in range(header + 1, end)
                   if re.match(r'\s*' + re.escape(key) + r'\s*=', lines[n], re.I)]
        if len(matches) > 1:
            raise RuntimeError('重复 INI 配置项，请先整理：' + key)
        if matches:
            lines[matches[0]] = key + '=' + value
        else:
            lines.insert(end, key + '=' + value)
    return '\n'.join(lines) + '\n'


class Manager(OptiMixin):
    def __init__(self, home=None, engine=None):
        self.home = Path(home or Path.home()).resolve()
        self.root = self.home / '.local/share/opti2xmx'
        self.engine = engine
        self.progress = OperationProgress()

    def runtime(self):
        if self.engine is None:
            p = Path(__file__).with_name('per_game.py')
            spec = importlib.util.spec_from_file_location('xmx_runtime', p)
            self.engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.engine)
        return self.engine

    def inventory(self):
        steam = next((p.resolve() for p in [self.home / '.local/share/Steam', self.home / '.steam/steam']
                      if (p / 'steamapps').is_dir()), None)
        if not steam:
            return []
        libraries = {steam}
        lf = steam / 'steamapps/libraryfolders.vdf'
        if lf.exists():
            for value in vdf(lf.read_text()).get('libraryfolders', {}).values():
                if isinstance(value, dict) and 'path' in value:
                    libraries.add(Path(value['path']).resolve())
        result = []
        for library in sorted(libraries):
            for manifest in sorted((library / 'steamapps').glob('appmanifest_*.acf')):
                try:
                    data = vdf(manifest.read_text())['AppState']
                    if re.match(r'^(Proton(?: |$)|Steam Linux Runtime|Steamworks Common Redistributables)', data['name']):
                        continue
                    appid = int(data['appid'])
                    install = data['installdir']
                    if Path(install).name != install or install in ('.', '..'):
                        continue
                    game = library / 'steamapps/common' / install
                    if not game.is_dir() or game.is_symlink():
                        continue
                    prefixes = [library / 'steamapps/compatdata' / str(appid) / 'pfx',
                                steam / 'steamapps/compatdata' / str(appid) / 'pfx']
                    prefix = next((p for p in prefixes if p.is_dir()), prefixes[0])
                    result.append(dict(appid=appid, name=data['name'], game=str(game), prefix=str(prefix)))
                except (KeyError, ValueError, OSError, StopIteration):
                    continue
        return sorted(result, key=lambda g: g['name'].casefold())

    def game(self, appid):
        if isinstance(appid, bool) or not isinstance(appid, int) or appid <= 0:
            raise ValueError('无效 Steam App ID')
        found = [g for g in self.inventory() if g['appid'] == appid]
        if len(found) != 1:
            raise RuntimeError('未找到唯一的已安装 Steam 游戏')
        return found[0]

    def pointer(self, appid):
        return self.root / 'games' / str(appid) / 'current.json'

    def state(self, appid):
        pointer = self.pointer(appid)
        if not pointer.exists():
            return None
        record = json.loads(pointer.read_text())
        state = Path(record['state'])
        if state.parent != pointer.parent or state.is_symlink():
            raise RuntimeError('无效的游戏备份路径')
        return json.loads((state / 'plugin.json').read_text())

    def save(self, record):
        self.runtime().atomic_text(Path(record['state']) / 'plugin.json', json.dumps(record, ensure_ascii=False, indent=2) + '\n')

    def dependencies(self):
        # An installer may stage these portable locations. Development machine
        # discovery is read-only and never makes it into a public binary bundle.
        config = self.root / 'runtime.json'
        if config.exists():
            data = json.loads(config.read_text())
            package, sr = Path(data['package']), Path(data['sr'])
        else:
            package = self.home / '.local/share/opti2xmx/runtime'
            sr = self.home / '.local/share/opti2xmx/sdk/libxess.dll'
            if not package.is_dir():
                package = self.home / 'oxp3-research/xess/xess-xmx-linux-20261005'
            if not sr.is_file():
                sr = self.home / 'oxp3-research/xess-sr/payload/libxess.dll'
        ready = (package / 'igdext64.dll').is_file() and sr.is_file() and (pe_version(sr) or ()) >= (2, 0, 2, 68)
        return package, sr, ready

    def inspect_game(self, appid):
        g = self.game(appid)
        root = Path(g['game'])
        exes, libraries, optis = [], [], []
        count = 0
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [n for n in dirs if not (Path(folder) / n).is_symlink()]
            for name in files:
                count += 1
                if count > 100000:
                    raise RuntimeError('游戏文件过多，停止自动扫描')
                p = Path(folder) / name
                if p.is_symlink():
                    continue
                rel = str(p.relative_to(root))
                if name.lower().endswith('.exe'):
                    exes.append(rel)
                if name.lower() == 'libxess.dll':
                    libraries.append({'path': rel, 'version': pe_version(p)})
                if name.lower() == 'optiscaler.ini':
                    optis.append(rel)
        _, _, ready = self.dependencies()
        owner = Path(g['prefix']) / '.oxp3-xess-owner.json'
        state = self.state(appid)
        info = dict(**g, executables=sorted(exes), libraries=libraries, optis=optis,
                    runtime_ready=ready, prefix_ready=(Path(g['prefix']) / 'drive_c').is_dir(),
                    external_managed=owner.exists() and not (state and state['status'] not in ('restored', 'failed')),
                    state=state)
        info['automatic'] = self.automatic(info)
        info['opti'] = self.opti_status(info)
        return info

    def automatic(self, info):
        """Infer only an unambiguous game executable; helpers never win a tie."""
        state = info['state']
        if state and state['status'] not in ('restored', 'failed'):
            return dict(executable=state['executable'], route=state['route'], reason='', candidates=[])
        helpers = re.compile(r'crash|reporter|launcher|webhelper|unins|setup|redist|benchmark|eac|easyanticheat', re.I)
        candidates = [p for p in info['executables'] if not helpers.search(Path(p).name)]
        optidirs = {str(Path(p).parent) for p in info['optis']}
        route = 'opti' if optidirs else 'native'
        owned = self.opti_record(info['appid'])
        if owned and owned['status']=='active' and not owned.get('injection_enabled',True):route='native'
        if optidirs:
            candidates = [p for p in candidates if str(Path(p).parent) in optidirs]
        else:
            srdirs = {str(Path(p['path']).parent) for p in info['libraries']}
            beside = [p for p in candidates if str(Path(p).parent) in srdirs]
            if beside:
                candidates = beside
            shipping = [p for p in candidates if Path(p).name.lower().endswith('-shipping.exe')]
            if len(shipping) == 1:
                candidates = shipping
        executable = candidates[0] if len(candidates) == 1 else ''
        reason = ''
        if info['external_managed']:
            reason = '此游戏已有其他 XMX 配置，需要先迁移后才能用此开关。'
        elif not info['runtime_ready']:
            reason = 'XMX 运行组件未就绪。'
        elif not info['prefix_ready']:
            reason = '请先从 Steam 用 Proton 启动游戏一次，退出后点击刷新。'
        elif not info['libraries']:
            reason = '尚未发现 XeSS。请先为此游戏安装 OptiScaler 并运行一次，再刷新。'
        elif not candidates:
            reason = '未识别到可接入的游戏程序，请检查游戏安装。'
        elif not executable:
            reason = '发现多个游戏程序，请在下面确认一次。'
        elif route == 'opti':
            folder = Path(info['game']) / Path(executable).parent
            if not (folder / 'dxgi.dll').is_file() or not (folder / 'libxess.dll').is_file():
                reason = 'OptiScaler 文件不完整，需要同目录的 dxgi.dll 和 libxess.dll。'
        return dict(executable=executable, route=route, reason=reason, candidates=candidates)

    def enable(self, appid, executable, route, old_launch):
        rt = self.runtime()
        rt.ordinary_user()
        info = self.inspect_game(appid)
        if self.state(appid) and self.state(appid)['status'] not in ('restored', 'failed'):
            raise RuntimeError('已有接入或待恢复操作，请先完成恢复')
        if info['external_managed']:
            raise RuntimeError('此游戏已有外部 XMX 接入；保留原配置，暂不接管')
        if not info['runtime_ready'] or not info['prefix_ready']:
            raise RuntimeError('需要已安装运行组件，并至少启动过一次该 Proton 游戏')
        if executable not in info['executables'] or route not in ('opti', 'native'):
            raise ValueError('请选择检测到的游戏程序和接入方式')
        # Only replace launchers we understand; arbitrary chains may copy DLLs
        # after us or override the environment. Never silently discard them.
        owned = self.opti_record(appid)
        if old_launch not in ('', '%command%', '~/fgmod/fgmod %command%', owned['launch'] if owned and owned['status']=='active' else None):
            raise RuntimeError('检测到自定义启动项，请先保留并清理，首版不自动合并')
        if route == 'native' and old_launch == '~/fgmod/fgmod %command%':
            raise RuntimeError('检测到 fgmod，请选择 OptiScaler 接入')
        if route == 'native' and info['optis'] and not (owned and owned['status']=='active' and not owned.get('injection_enabled',True)):
            raise RuntimeError('检测到已有 OptiScaler，请选择 OptiScaler 接入，避免遗留伪装配置')
        game = Path(info['game']); prefix = Path(info['prefix'])
        exe = game / executable
        if not exe.is_file() or exe.is_symlink():
            raise RuntimeError('游戏程序已经变化，请刷新')
        rt.no_symlink_parents(exe)
        rt.game_idle(prefix, exe.name)
        targets = [game / lib['path'] for lib in info['libraries']]
        if not targets:
            raise RuntimeError('没有找到 XeSS 库；请先安装并确认 OptiScaler 能加载，或使用原生 XeSS 游戏')
        ini = None
        if route == 'opti':
            inis = [game / p for p in info['optis'] if (game / p).parent == exe.parent]
            dxgi = exe.parent / 'dxgi.dll'
            if len(inis) != 1 or not dxgi.is_file():
                raise RuntimeError('首版需要主程序同目录已有 OptiScaler.ini 和 dxgi.dll')
            data = dxgi.read_bytes()
            if b'OptiScaler' not in data and 'OptiScaler'.encode('utf-16le') not in data:
                raise RuntimeError('dxgi.dll 未识别为 OptiScaler，保留原文件')
            ini = inis[0]
            if (exe.parent / 'libxess.dll') not in targets:
                raise RuntimeError('OptiScaler 目录缺少 libxess.dll')
        for p in targets + ([ini] if ini else []):
            rt.no_symlink_parents(p)
            if p.stat().st_uid != os.getuid():
                raise RuntimeError('游戏文件不属于当前用户')
        package, sr, _ = self.dependencies()
        parent = self.pointer(appid).parent
        rt.no_symlink_parents(parent / 'placeholder')
        parent.mkdir(parents=True, exist_ok=True)
        state = parent / ('setup-' + uuid.uuid4().hex)
        state.mkdir(mode=0o700)
        record = dict(appid=appid, state=str(state), game=info['game'], prefix=str(prefix),
                      executable=executable, route=route, old_launch=old_launch, status='preparing', files=[])
        self.save(record)
        rt.atomic_text(self.pointer(appid), json.dumps({'state': str(state)}))
        try:
            # Core handles prefix ownership and preserves its own rollback journal.
            with contextlib.redirect_stdout(io.StringIO()):
                rt.install(argparse.Namespace(prefix=str(prefix), package=str(package), state=str(state / 'xmx'),
                                              game_exe=exe.name, config=None))
            with rt.prefix_lock(prefix):
                rt.game_idle(prefix, exe.name)
                (state / 'original').mkdir()
                (state / 'applied').mkdir()
                for n, p in enumerate(targets + ([ini] if ini else [])):
                    original = state / 'original' / str(n)
                    applied = state / 'applied' / str(n)
                    shutil.copy2(p, original)
                    if p == ini:
                        text = p.read_text(encoding='utf-8-sig')
                        for section, key, value in [('Upscalers','Dx12Upscaler','xess'), ('Spoofing','Dxgi','false'),
                              ('Spoofing','StreamlineSpoofing','false'), ('FrameGen','Enabled','false'),
                              ('FrameGen','FGType','nofg'), ('OptiFG','Enabled','false')]:
                            if owned and owned['status']=='active' and section in ('FrameGen','OptiFG'):
                                continue
                            text = ini_set(text, section, key, value)
                        applied.write_text(text, encoding='utf-8')
                    else:
                        # Do not downgrade an already newer SR runtime.
                        shutil.copy2(sr if (pe_version(p) or ()) < pe_version(sr) else p, applied)
                    record['files'].append(dict(path=str(p), original=str(original), applied=str(applied)))
                    self.save(record)
                    rt.atomic_copy(applied, p)
                config = state / 'xmx/game.conf'
                dll = rt.prefix_dll_path(prefix)
                winpath = 'C:\\' + str(dll.parent.relative_to(prefix / 'drive_c')).replace('/', '\\')
                text = config.read_text() + '\nexport INTC_ALT_DRIVER_EXTENSIONS_PATH=' + shlex.quote(winpath) + '\n'
                rt.atomic_text(config, text)
                overrides = 'igdext64=n,b' + (';dxgi=n,b' if route == 'opti' else '')
                launcher = '#!/bin/bash\nset -eu\n'
                launcher += 'export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}' + overrides + '"\n'
                launcher += 'exec ' + shlex.quote(str(state / 'xmx/launch.sh')) + ' "$@"\n'
                rt.atomic_text(state / 'launch.sh', launcher, mode=0o700)
                record['launch'] = shlex.quote(str(state / 'launch.sh')) + ' %command%'
                record['status'] = 'pending_launch'
                self.save(record)
                self.opti_sync(appid, [f['path'] for f in record['files']])
        except Exception as error:
            record['error'] = str(error)
            record['status'] = 'recovery_required'
            self.save(record)
            # The UI exposes recovery; do not hide partially applied changes.
            raise RuntimeError('接入未完成，已保留备份；请点击恢复。' + str(error)) from error
        return record

    def confirm_launch(self, appid, actual):
        self.game(appid)
        record = self.state(appid)
        if not record:
            raise RuntimeError('没有待确认的接入')
        expected = record.get('launch') if record['status'] in ('pending_launch', 'active') else record['old_launch']
        if actual != expected:
            raise RuntimeError('Steam 启动项读回不一致，请恢复或刷新后重试')
        if record['status'] in ('pending_launch', 'active'):
            record['status'] = 'active'
        elif record['status'] == 'pending_restore_launch':
            record['status'] = 'restored'
        else:
            raise RuntimeError('当前操作尚未完成')
        self.save(record)
        return record

    def restore(self, appid, actual):
        rt = self.runtime(); rt.ordinary_user()
        self.game(appid)
        record = self.state(appid)
        if not record or record['status'] == 'restored':
            raise RuntimeError('没有需要恢复的接入')
        if actual not in (record['old_launch'], record.get('launch')):
            raise RuntimeError('启动项已被其他工具修改；保留改动，请先恢复本插件启动项再重试')
        prefix = Path(record['prefix'])
        with rt.prefix_lock(prefix):
            rt.game_idle(prefix, Path(record['executable']).name)
            # Preflight every file before writing any. Compare bytes, not hashes.
            for f in record['files']:
                p = Path(f['path']); rt.no_symlink_parents(p)
                if not p.is_file() or p.read_bytes() not in (Path(f['original']).read_bytes(), Path(f['applied']).read_bytes()):
                    raise RuntimeError('文件已被游戏或其他工具修改，保留现场：' + p.name)
            for f in record['files']:
                rt.atomic_copy(Path(f['original']), Path(f['path']))
        # Imported, already-working setups retain their original core state path.
        core = Path(record.get('core_state', str(Path(record['state']) / 'xmx')))
        if (core / 'manifest.json').exists():
            m = rt.load(core)
            if m['status'] != 'restored':
                with contextlib.redirect_stdout(io.StringIO()):
                    rt.restore(argparse.Namespace(state=str(core)))
        record['status'] = 'pending_restore_launch'
        self.save(record)
        self.opti_sync(appid, [f['path'] for f in record['files']])
        return record
