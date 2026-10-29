"""Pinned, user-provided FSR model import and reversible per-game preparation.

The public plugin contains the open-source decompression bridge, never the
user-provided upscaler, original weights or NVIDIA DLL.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import tempfile
import uuid
import zipfile


def descriptor():
    return json.loads(Path(__file__).with_name('fsr-source.json').read_text(encoding='utf-8'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def patch_decompressor_import(data):
    """Change only the pinned DLL's import name, leaving system Cabinet alone."""
    data = bytearray(data)
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if (data[:2] != b'MZ' or data[pe:pe + 4] != b'PE\0\0'
            or struct.unpack_from('<H', data, pe + 4)[0] != 0x8664):
        raise ValueError('FSR DLL is not the expected x64 PE')
    count = struct.unpack_from('<H', data, pe + 6)[0]
    optional_size = struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    if count > 96 or optional_size < 128 or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('FSR DLL has an invalid PE header')
    sections = optional + optional_size

    def offset(rva, size=1):
        for index in range(count):
            row = sections + 40 * index
            virtual_size, virtual_address, raw_size, raw = struct.unpack_from('<4I', data, row + 8)
            delta = rva - virtual_address
            if 0 <= delta and delta + size <= raw_size and raw + delta + size <= len(data):
                return raw + delta
        raise ValueError('FSR import lies outside its PE sections')

    imports, length = struct.unpack_from('<2I', data, optional + 120)
    table = offset(imports, min(length, 20))
    changed = 0
    for index in range(min(length // 20, 4096)):
        row = table + 20 * index
        if row + 20 > len(data):
            raise ValueError('FSR import table is truncated')
        fields = struct.unpack_from('<5I', data, row)
        if not any(fields):
            break
        name = offset(fields[3])
        end = data.find(b'\0', name, min(name + 256, len(data)))
        if end < 0:
            raise ValueError('FSR import name is unterminated')
        if bytes(data[name:end]).lower() == b'cabinet.dll':
            data[name:end] = b'fsrxdec.dll'
            changed += 1
    if changed != 1:
        raise ValueError('FSR Cabinet import does not match the verified build')
    return bytes(data)


def neutral_fsr(text):
    """The XMX-off snapshot must never launch an XMX FSR model on stock ANV."""
    from manager import ini_set
    text = ini_set(text, 'Upscalers', 'Dx12Upscaler', 'xess')
    text = ini_set(text, 'FSR', 'UpscalerIndex', 'auto')
    return text


class FsrMixin:
    def _fsr_root(self):
        return self.root / 'fsr'

    def _fsr_compat(self):
        folder = Path(__file__).with_name('fsr_compat')
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        rows = manifest['files']
        expected = {'bin/fsrxdec.dll', 'bin/libwim-15.dll'}
        if (manifest.get('schema') != 1 or manifest.get('architecture') != 'x86_64'
                or {row['path'] for row in rows} != expected or len(rows) != 2):
            raise RuntimeError('FSR 解压兼容组件清单无效，请重新安装插件。')
        result = {}
        for row in rows:
            path = folder / row['path']
            self.runtime().no_symlink_parents(path)
            if (not path.is_file() or path.is_symlink() or path.stat().st_size != row['size']
                    or digest(path) != row['sha256']):
                raise RuntimeError('FSR 解压兼容组件校验失败，请重新安装插件。')
            result[path.name] = path
        return result

    def _fsr_payload(self):
        pin = descriptor()
        pointer = self._fsr_root() / 'current.json'
        self.runtime().no_symlink_parents(pointer)
        current = json.loads(pointer.read_text(encoding='utf-8'))
        name = current.get('directory', '')
        prefix = pin['version'] + '-'
        if (not name.startswith(prefix) or not re.fullmatch(re.escape(prefix) + r'[a-f0-9]{32}', name)
                or current.get('source_sha256') != pin['sha256']):
            raise RuntimeError('FSR 模型缓存记录无效，请重新导入。')
        folder = pointer.parent / name
        for filename, expected in pin['files'].items():
            path = folder / filename
            self.runtime().no_symlink_parents(path)
            wanted = pin['patched_upscaler_sha256'] if filename == 'amd_fidelityfx_upscaler_dx12.dll' else expected['sha256']
            if (not path.is_file() or path.is_symlink() or path.stat().st_size != expected['size_bytes']
                    or digest(path) != wanted):
                raise RuntimeError('FSR 模型文件校验失败，请重新导入。')
        return folder

    def fsr_status(self):
        pin = descriptor()
        try:
            self._fsr_compat()
            self._fsr_payload()
            ready, reason = True, ''
        except FileNotFoundError:
            ready, reason = False, '请导入 FSR 4.1.2 Lite XMX 模型包。'
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            ready, reason = False, str(error)
        return dict(ready=ready, version=pin['version'], reason=reason)

    def fsr_import(self, source):
        rt = self.runtime()
        rt.ordinary_user()
        if not isinstance(source, str) or not source or '\0' in source:
            raise ValueError('请选择本地 FSR ZIP 模型包。')
        source = Path(source).expanduser().resolve(strict=True)
        pin = descriptor()
        if not source.is_file() or source.stat().st_size != pin['size_bytes']:
            raise ValueError('FSR 模型包大小不匹配，请选择已支持的原始 ZIP。')
        parent = self._fsr_root()
        rt.no_symlink_parents(parent / 'placeholder')
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.import-', dir=parent) as temporary:
            stage = Path(temporary)
            snapshot = stage / 'source.zip'
            total, checksum = 0, hashlib.sha256()
            with source.open('rb') as input_stream, snapshot.open('xb') as output:
                for chunk in iter(lambda: input_stream.read(1024 * 1024), b''):
                    total += len(chunk)
                    if total > pin['size_bytes']:
                        raise ValueError('FSR 模型包在读取期间变化，请重试。')
                    checksum.update(chunk)
                    output.write(chunk)
            if total != pin['size_bytes'] or checksum.hexdigest() != pin['sha256']:
                raise ValueError('FSR 模型包 SHA-256 不匹配，请选择受支持的原始 ZIP。')
            with zipfile.ZipFile(snapshot) as archive:
                entries = archive.infolist()
                if len(entries) != len(pin['files']) or {entry.filename for entry in entries} != set(pin['files']):
                    raise ValueError('FSR 模型包文件列表不匹配。')
                for entry in entries:
                    expected = pin['files'][entry.filename]
                    if (entry.is_dir() or entry.file_size != expected['size_bytes']
                            or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
                        raise ValueError('FSR 模型包包含无效文件。')
                    target = stage / entry.filename
                    with archive.open(entry) as input_stream, target.open('xb') as output:
                        shutil.copyfileobj(input_stream, output, 1024 * 1024)
                    if digest(target) != expected['sha256']:
                        raise ValueError('FSR 模型文件哈希不匹配：' + entry.filename)
                    target.chmod(0o600)
            mod = stage / 'amd_fidelityfx_upscaler_dx12.dll'
            mod.write_bytes(patch_decompressor_import(mod.read_bytes()))
            if digest(mod) != pin['patched_upscaler_sha256']:
                raise RuntimeError('FSR 解压导入适配结果与固定版本不匹配。')
            snapshot.unlink()  # Retain only validated model files in the private cache.
            destination = parent / (pin['version'] + '-' + uuid.uuid4().hex)
            stage.rename(destination)
            rt.atomic_text(parent / 'current.json', json.dumps({'directory': destination.name, 'source_sha256': pin['sha256']}))
        return self.fsr_status()

    def fsr_game_status(self, info):
        result = self.fsr_status()
        pin = descriptor()
        r = self.opti_record(info['appid'])
        prepared = bool(r and r.get('status') == 'active' and r.get('fsr_source_sha256') == pin['sha256']
                        and r.get('version') == pin['opti_version'])
        xmx = info['state']
        bridge_ready = bool(xmx and xmx.get('status') == 'active' and xmx.get('fsr_bridge') == 1)
        result.update(prepared=prepared, bridge_ready=bridge_ready, opti_version=pin['opti_version'])
        return result

    def fsr_prepare(self, appid, executable, actual, source):
        pin = descriptor()
        self._fsr_payload()
        self._fsr_compat()
        identity = self.progress.begin(appid, 'opti_install', pin['opti_version'])
        try:
            pending = self._opti_install(appid, executable, actual, pin['opti_version'], source, identity, fsr=True)
            self.progress.finish(identity, phase='awaiting-launch')
            return pending
        except Exception as error:
            self.progress.finish(identity, error=error)
            raise

    def fsr_changes(self, folder):
        pin = descriptor()
        payload = self._fsr_payload()
        package, _, ready = self.dependencies()
        if not ready:
            raise RuntimeError('XMX 运行组件未就绪。')
        changes = {str(folder / 'OptiScaler' / name): (payload / name).read_bytes() for name in pin['files']}
        changes[str(folder / 'OptiScaler/igdext64.dll')] = (package / 'igdext64.dll').read_bytes()
        changes.update({str(folder / name): path.read_bytes() for name, path in self._fsr_compat().items()})
        return changes

    def fsr_install_bridge(self, state, package):
        """Make the compiler wrapper independent of future plugin upgrades."""
        rt = self.runtime()
        source = Path(__file__).with_name('fsr_cm.py')
        rt.atomic_copy(source, state / 'fsr_cm.py')
        helper = state / 'fsr-compile.sh'
        rt.atomic_text(helper, '#!/bin/sh\nset -eu\nexec python3 ' + shlex.quote(str(state / 'fsr_cm.py'))
                       + ' ' + shlex.quote(str(package / 'tools/cm-compile.sh')) + ' "$@"\n', mode=0o700)
        config = state / 'xmx/game.conf'
        text = config.read_text()
        text += '\nexport ANV_CM_HELPER=' + shlex.quote(str(helper)) + '\n'
        text += rt.dll_overrides_config('dxgi', 'fsrxdec', 'libwim-15')
        text += 'export FSR4_XMX_NO_DIALOG=1\n'
        rt.atomic_text(config, text)

    def fsr_validate_selected(self, info):
        status = self.fsr_game_status(info)
        if not status['ready']:
            raise RuntimeError(status['reason'])
        if not status['prepared'] or not status['bridge_ready']:
            raise RuntimeError('请先准备 FSR 并重新开启 XMX。')
        folder = Path(info['game']) / Path(self.opti_record(info['appid'])['executable']).parent
        expected = self.fsr_changes(folder)
        for name, data in expected.items():
            path = Path(name)
            self.runtime().no_symlink_parents(path)
            if not path.is_file() or path.is_symlink() or digest(path) != hashlib.sha256(data).hexdigest():
                raise RuntimeError('FSR 游戏文件已变化，请关闭 XMX 后重新准备。')
