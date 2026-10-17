"""Pinned public Opti2XMX 0.1.4 installer inputs; never execute plugin code."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

PINS = json.loads((Path(__file__).resolve().parents[1] / 'components/opti2xmx-release.json').read_text(encoding='utf-8'))
VERSION = PINS['plugin_version']
PLUGIN_SHA256 = PINS['plugin_sha256']
FILES_SHA256 = PINS['files_sha256']
RUNTIME_SHA256 = PINS['runtime']['sha256']
RUNTIME_SIZE = PINS['runtime']['size_bytes']
RUNTIME_URL = PINS['runtime']['url']
FILES = ('plugin.json', 'package.json', 'main.py', 'manager.py', 'opti.py',
         'download_progress.py', 'runtime_setup.py', 'runtime-source.json',
         'per_game.py', 'dist/index.js', 'README.md', 'README.zh-CN.md', 'LICENSE',
         'THIRD_PARTY_NOTICES.md', 'docs/RUNTIME.md', 'docs/FRAME_GENERATION.md')


def _regular(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked Opti input or output path refused')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Opti input must be a single regular file')
    return path


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(records):
    package = json.loads(records['package.json'])
    descriptor = json.loads(records['runtime-source.json'])
    if package.get('version') != VERSION or json.loads(records['plugin.json']).get('name') != 'Opti2XMX':
        raise ValueError('Unexpected pinned Opti2XMX plugin identity/version')
    if (descriptor.get('schema') != 1 or descriptor.get('published') is not True
            or descriptor.get('sha256') != RUNTIME_SHA256
            or descriptor.get('size_bytes') != RUNTIME_SIZE or descriptor.get('url') != RUNTIME_URL):
        raise ValueError('Opti runtime descriptor differs from the pinned public runtime')
    return descriptor


def read_plugin(path):
    path = _regular(path)
    with path.open('rb') as stream:
        snapshot = stream.read(4 * 1024 * 1024 + 1)
    if len(snapshot) > 4 * 1024 * 1024 or hashlib.sha256(snapshot).hexdigest() != PLUGIN_SHA256:
        raise ValueError('Opti plugin archive differs from the pinned independent release')
    records = {}
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        if len(archive.infolist()) != len(FILES):
            raise ValueError('Unexpected Opti archive membership')
        for item in archive.infolist():
            name = item.filename
            relative = name.removeprefix('opti2xmx/')
            if (not name.startswith('opti2xmx/') or relative not in FILES or relative in records
                    or item.is_dir() or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG)
                    or item.file_size > 2 * 1024 * 1024):
                raise ValueError('Unsafe or unexpected Opti archive member')
            records[relative] = archive.read(item)
    _metadata(records)
    return records


def read_plugin_tree(directory):
    directory = Path(directory)
    report = json.loads(_regular(directory / 'deployment.json').read_text(encoding='utf-8'))
    files_digest = hashlib.sha256(json.dumps(report.get('files', {}), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (report.get('plugin_sha256') != PLUGIN_SHA256 or set(report.get('files', {})) != set(FILES)
            or files_digest != FILES_SHA256):
        raise ValueError('Opti deployment provenance differs from the pinned release')
    records = {name: _regular(directory / name).read_bytes() for name in FILES}
    if any(hashlib.sha256(data).hexdigest() != report['files'][name] for name, data in records.items()):
        raise ValueError('Opti deployment source changed after preparation')
    _metadata(records)
    return records


def prepare(plugin, runtime, output):
    records = read_plugin(plugin)
    descriptor = _metadata(records)
    runtime, output = validate_runtime(runtime), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Use a fresh Opti output directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    for parent in (output.parent, *output.parent.parents):
        if parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked Opti output ancestor refused')
    report = {'schema': 1, 'plugin_version': VERSION, 'plugin_sha256': PLUGIN_SHA256,
              'plugin_source': 'https://github.com/FlightDan/Opti2XMX',
              'runtime': descriptor, 'contains_game_state': False,
              'files': {name: hashlib.sha256(data).hexdigest() for name, data in records.items()}}
    with tempfile.TemporaryDirectory(prefix='.opti-input-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'payload'
        for folder in ('plugin', 'integration/sources/opti2xmx'):
            for name, data in records.items():
                target = stage / folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        encoded = (json.dumps(report, indent=2) + '\n').encode()
        (stage / 'plugin/deployment.json').write_bytes(encoded)
        (stage / 'integration/sources/opti2xmx/PROVENANCE.json').write_bytes(encoded)
        target = stage / 'integration/opti2xmx/runtime.tar.gz'
        target.parent.mkdir(parents=True)
        shutil.copyfile(runtime, target)
        if target.stat().st_size != RUNTIME_SIZE or _hash(target) != RUNTIME_SHA256:
            raise ValueError('Opti runtime changed while being copied')
        stage.rename(output)
    return report


def validate_runtime(path):
    path = _regular(path)
    if path.stat().st_size != RUNTIME_SIZE or _hash(path) != RUNTIME_SHA256:
        raise ValueError('Opti runtime differs from the pinned public archive')
    return path
