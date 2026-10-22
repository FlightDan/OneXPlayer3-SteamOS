"""Build a deterministic unsigned device package from a hash-locked public asset.

No model script is executed by this preparer. The archive whitelist is the only
source for legacy bytes; the local workspace and research trees are never read.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0-dev.1'
REPOSITORY = 'FlightDan/OneXPlayer3-SteamOS'
SOURCE_FILES = ('.gitignore', 'LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'adapter.py',
                'scripts/apply.sh', 'scripts/build.py', 'scripts/fetch-input.py', 'scripts/restore.sh',
                'scripts/verify.sh', 'selection.example.json', 'source-files.txt', 'tests/test_adapter.py', 'upstream-lock.json')
COMPATIBILITY = {'architectures': ['x86_64'], 'os_ids': ['steamos'], 'device_ids': ['oxp3'], 'os_versions': ['3.10'],
                 'kernels': ['7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9']}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def stream_digest(stream):
    stream.seek(0)
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b''):
        result.update(block)
    stream.seek(0)
    return result.hexdigest()


@contextmanager
def public_input(path, expected):
    """Keep the authenticated regular file open through all archive reads."""
    if path.is_symlink():
        raise ValueError('Public input must be a regular file')
    if os.name == 'nt':
        # Deny concurrent writes/deletion while preserving ordinary readers.
        import ctypes
        from ctypes import wintypes
        import msvcrt
        create = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        handle = create(str(path.absolute()), 0x80000000, 1, None, 3, 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close = ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle
            close.argtypes = (wintypes.HANDLE,)
            close(handle)
            raise
    else:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected['size'] or stream_digest(stream) != expected['sha256']:
            raise ValueError('Public input does not match the locked size and SHA-256')
        yield stream
        if os.fstat(stream.fileno()).st_size != expected['size'] or stream_digest(stream) != expected['sha256']:
            raise ValueError('Public input changed during extraction')


def safe_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Unsafe archive path')
    if any(ord(char) < 32 for char in name):
        raise ValueError('Unsafe archive path')
    return name


def read_selection(value, catalog, adapter_source=None):
    if adapter_source is not None:
        adapter = types.ModuleType('boiler_oxp3_adapter')
        adapter.__file__ = str(ROOT/'adapter.py')
        exec(compile(adapter_source, adapter.__file__, 'exec'), adapter.__dict__)
        adapter.selection(value, catalog)
        return value
    spec = importlib.util.spec_from_file_location('boiler_oxp3_adapter', ROOT/'adapter.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.selection(value, catalog)
    return value


def committed_model(root, source_commit):
    """Freeze exactly the public model subtree; never read a signing identity."""
    root = Path(root).resolve()
    if root.name != 'boiler-device' or not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('Release source requires the public boiler-device subtree and exact commit')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root.parent), *args], stderr=subprocess.PIPE)
    if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != root.parent:
        raise ValueError('Release source must be the independent public repository model subtree')
    if git('rev-parse', 'HEAD').decode().strip() != source_commit:
        raise ValueError('Release source commit must match the public checkout HEAD')
    origin = git('remote', 'get-url', 'origin').decode().strip()
    if origin not in ('https://github.com/'+REPOSITORY, 'https://github.com/'+REPOSITORY+'.git',
                      'git@github.com:'+REPOSITORY+'.git'):
        raise ValueError('Release source must use the existing public OXP3 repository origin')
    if git('status', '--porcelain=v1', '--untracked-files=all', '--', 'boiler-device'):
        raise ValueError('Public model source must be clean')
    whitelist = (root/'source-files.txt').read_text(encoding='utf-8').splitlines()
    if len(whitelist) != len(SOURCE_FILES) or set(whitelist) != set(SOURCE_FILES):
        raise ValueError('Public model source whitelist must contain exactly the reviewed 14 files')
    tracked = {}
    for entry in git('ls-tree', '-rz', source_commit, '--', 'boiler-device').split(b'\x00'):
        if not entry:
            continue
        metadata, path = entry.split(b'\t', 1)
        mode, kind, _ = metadata.decode().split()
        name = path.decode('utf-8').removeprefix('boiler-device/')
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Public model source links and submodules are forbidden')
        tracked[name] = mode
    if set(tracked) != set(SOURCE_FILES):
        raise ValueError('Committed model subtree differs from its reviewed source whitelist')
    contents = {}
    for name in SOURCE_FILES:
        data = git('show', source_commit+':boiler-device/'+name)
        path = root/name
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or path.read_bytes() != data:
            raise ValueError('Working model bytes differ from committed source: '+name)
        contents[name] = data
    return contents


def selected_path(name, lock):
    if name in lock['export_files']:
        return 'payload/legacy/' + name
    if not any(name.startswith(prefix) for prefix in lock['export_prefixes']):
        return None
    if name.startswith('cache/components/waydroid/'):
        return 'payload/legacy/waydroid/' + name.removeprefix('cache/components/waydroid/')
    if name.startswith('cache/'):
        return 'payload/legacy/' + name.removeprefix('cache/')
    return 'payload/legacy/' + name


def deterministic_zip(directory, destination):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(directory.rglob('*')):
            if not path.is_file():
                continue
            name = path.relative_to(directory).as_posix()
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if name.startswith('scripts/') else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as target:
                shutil.copyfileobj(source, target, 1024*1024)


def build(archive_path, output, choice, *, lock_path=ROOT/'upstream-lock.json', source_commit=None, version=None):
    archive_path, output = Path(archive_path), Path(output)
    if source_commit and not version:
        raise ValueError('Release mode requires an explicit model version')
    version = version or VERSION
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?', version):
        raise ValueError('Explicit model version must be a canonical three-part version')
    contents = committed_model(ROOT, source_commit) if source_commit else None
    if contents is not None:
        if Path(lock_path).resolve() != (ROOT/'upstream-lock.json').resolve():
            raise ValueError('Release builds use only the committed upstream lock')
        if choice != json.loads(contents['selection.example.json']):
            raise ValueError('Release selection differs from the committed frozen selection')
    lock = json.loads(contents['upstream-lock.json'] if contents is not None else Path(lock_path).read_bytes())
    expected = lock['asset']
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new directory')
    with public_input(archive_path, expected) as input_stream, zipfile.ZipFile(input_stream) as source:
        seen, selected = set(), []
        for info in source.infolist():
            name = info.filename.rstrip('/')
            safe_path(name)
            if name.casefold() in seen:
                raise ValueError('Duplicate archive path')
            seen.add(name.casefold())
            mode = info.external_attr >> 16
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Archive links and special files are forbidden')
            target = selected_path(name, lock)
            if target and not info.is_dir():
                selected.append((info, target))
        if sum(info.file_size for info, _ in selected) > 4*1024**3:
            raise ValueError('Model export exceeds size limit')
        build_info = json.loads(source.read('build-info.json'))
        if build_info['source_commit'] != lock['source_commit'] or build_info['package_channel'] != 'public-release':
            raise ValueError('Public source/build identity mismatch')
        catalog = json.loads(source.read('components/options.json'))
        public_catalog = {item['id']: item for item in json.loads(source.read('components/catalog.json'))['components']}
        resources = json.loads(source.read('cache/integration/manifest.json'))
        read_selection(choice, catalog, contents['adapter.py'] if contents is not None else None)
        output.mkdir(parents=True)
        for info, name in selected:
            target = output/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as original, target.open('xb') as destination:
                shutil.copyfileobj(original, destination, 1024*1024)
    for name in ('adapter.py', 'scripts/apply.sh', 'scripts/verify.sh', 'scripts/restore.sh', 'upstream-lock.json'):
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[name] if contents is not None else (ROOT/name).read_bytes())
    (output/'selection.json').write_text(json.dumps(choice, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    inventory = [{'path': path.relative_to(output).as_posix(), 'size': path.stat().st_size, 'sha256': digest(path)}
                 for path in sorted(output.rglob('*')) if path.is_file()]
    manifest = {
        'schema_version': 1, 'kind': 'DevicePackage', 'id': 'device:oxp3', 'version': version,
        'minimum_engine_version': '0.1.0',
        'name': {'en': 'ONEXPLAYER 3 legacy adaptation bridge', 'zh': 'ONEXPLAYER 3 兼容适配桥'},
        'source': {'kind': 'github', 'repository': REPOSITORY, 'commit': source_commit} if contents is not None else
                  {'kind': 'local', 'path': ROOT.name, 'repository': lock['repository'], 'base_commit': lock['source_commit']},
        'upstream_source': {'repository': lock['repository'], 'commit': lock['source_commit'],
                            'release_tag': lock['release_tag'], 'asset': lock['asset']},
        'compatibility': COMPATIBILITY,
        'hardware_matching': {
            'mode': 'manual', 'automatic_selection': False,
            'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'},
            'evidence': 'https://github.com/FlightDan/OneXPlayer3-SteamOS/blob/'+lock['source_commit']+'/windows-installer/components/controls/profile.json',
            'note': 'Published model identity is advisory; this development bridge requires explicit manual model selection and does not claim automatic DMI validation.'
        },
        'trust': {'status': 'index-signature-required' if contents is not None else 'unsigned-development', 'official_release': False},
        'components': [{
            'schema_version': 1, 'kind': 'ComponentManifest', 'id': 'oxp3:legacy-adaptation', 'version': version,
            'minimum_engine_version': '0.1.0',
            'name': {'en': 'Explicit OXP3 device adaptation', 'zh': '显式 OXP3 设备适配'},
            'description': {'en': 'Runs the pinned public OXP3 integration once using the package selection, including its explicitly acknowledged OS-image update hold.', 'zh': '按包内显式选择执行一次已公开 OXP3 集成，包含已确认的系统镜像更新暂停。'},
            'optional': True, 'default': False, 'requires': [], 'conflicts': [],
            'compatibility': COMPATIBILITY, 'files': [],
            'hooks': {'apply': 'scripts/apply.sh', 'verify': 'scripts/verify.sh', 'restore': 'scripts/restore.sh'}
        }],
        'migration_status': 'experimental-new-stack-lifecycle-not-accepted',
        'legacy_capabilities': [dict(item, id='oxp3:'+item['id'], dependencies=['oxp3:'+name for name in item['dependencies']],
                                     migration_status='packaged-existing-public-policy-new-stack-acceptance-pending',
                                     legacy_acceptance=public_catalog.get(item['id'], {}).get('state', 'see-upstream-release'),
                                     legacy_notes=public_catalog.get(item['id'], {}).get('reason', ''),
                                     targets=[entry['target'] for entry in resources.get(item['id'], {}).get('files', [])],
                                     services=resources.get(item['id'], {}).get('units', []),
                                     generated_targets='See pinned payload/legacy/components/integration.py for dynamic policy and transaction targets')
                                for category in ('repairs', 'plugins') for item in catalog[category]],
        'files': inventory
    }
    if contents is not None:
        manifest['model_source'] = {'root': 'boiler-device', 'source_whitelist_sha256': hashlib.sha256(contents['source-files.txt']).hexdigest(),
                                    'files': [{'path': 'boiler-device/'+name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                              for name, data in sorted(contents.items())]}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-installer', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--source-commit', help='Exact clean public model commit; enables index-signature-required release candidate mode')
    parser.add_argument('--version', help='Independent model version; mandatory with --source-commit')
    args = parser.parse_args()
    manifest = build(args.public_installer, args.output, json.loads(args.selection.read_text(encoding='utf-8')),
                     source_commit=args.source_commit, version=args.version)
    report = {'id': manifest['id'], 'version': manifest['version'], 'status': manifest['trust']['status'],
              'manifest_sha256': digest(args.output/'manifest.json'), 'manifest_size': (args.output/'manifest.json').stat().st_size,
              'files': len(manifest['files']), 'source': manifest['source']}
    if args.zip:
        if args.zip.exists():
            raise SystemExit('Archive output already exists')
        deterministic_zip(args.output, args.zip)
        report['archive'] = {'name': args.zip.name, 'size': args.zip.stat().st_size, 'sha256': digest(args.zip)}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
