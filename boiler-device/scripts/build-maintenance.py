"""Prepare the fixed OXP3 XE maintenance baseline, without target scripts or signing."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boiler_model_build', ROOT/'scripts/build.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
MAX_METADATA = 8*1024*1024


def build(archive_path, output, *, version='0.1.0-dev.1', source_commit=None,
          lock_path=ROOT/'maintenance-static-lock.json', upstream_path=ROOT/'upstream-lock.json'):
    """Export only authenticated static bytes; component version cannot be overridden."""
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?', version):
        raise ValueError('Package version must be a canonical three-part version')
    contents = common.committed_model(ROOT, source_commit) if source_commit else None
    if contents is not None and (Path(lock_path).resolve() != (ROOT/'maintenance-static-lock.json').resolve() or
                                 Path(upstream_path).resolve() != (ROOT/'upstream-lock.json').resolve()):
        raise ValueError('Release builds require committed source locks')
    def local(name, path):
        return contents[name] if contents is not None else Path(path).read_bytes()
    lock = json.loads(local('maintenance-static-lock.json', lock_path))
    upstream_raw = local('upstream-lock.json', upstream_path)
    if hashlib.sha256(upstream_raw).hexdigest() != lock['upstream_lock_sha256']:
        raise ValueError('Upstream lock differs from the reviewed static source')
    upstream = json.loads(upstream_raw)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new directory')
    exported = {}
    with common.public_input(Path(archive_path), upstream['asset']) as incoming, zipfile.ZipFile(incoming) as archive:
        entries = archive.infolist()
        if len(entries) > 100000:
            raise ValueError('Public archive inventory is too large')
        seen = set()
        for entry in entries:
            name = common.safe_path(entry.filename.rstrip('/'))
            if name.casefold() in seen:
                raise ValueError('Duplicate public archive path')
            seen.add(name.casefold())
            mode = entry.external_attr >> 16
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Public archive links and special files are forbidden')
        def read(name):
            info = archive.getinfo(name)
            if info.is_dir() or info.file_size > MAX_METADATA:
                raise ValueError('Static package source exceeds its bounded size')
            return archive.read(info)
        build_info = json.loads(read('build-info.json'))
        if build_info.get('source_commit') != upstream['source_commit'] or build_info.get('package_channel') != 'public-release':
            raise ValueError('Public source/build identity mismatch')
        release = json.loads(read('components/release.json'))
        if release.get('version') != lock['component_version']:
            raise ValueError('Static baseline differs from its public source generation')
        resource = json.loads(read('cache/integration/manifest.json'))['xe-dsb']
        expected = [{'target': lock['target'], 'source': 'xe-dsb/000.bin', 'mode': lock['mode'], 'user': False}]
        if resource.get('files') != expected or any(resource.get(field) != value for field,value in
                                                   (('units', []), ('packages', {}), ('missing', []))):
            raise ValueError('XE source ownership or execution requirements changed')
        payload = read(lock['source'])
        if len(payload) != lock['size'] or hashlib.sha256(payload).hexdigest() != lock['sha256']:
            raise ValueError('Static payload differs from its reviewed size and SHA-256')
        exported['payload/xe-oxp3.conf'] = payload
        for name in ('LICENSE', 'licenses/upstream-fixes-MIT.txt'):
            exported[name] = read(name)
    compatibility = dict(common.COMPATIBILITY)
    component = {
        'schema_version': 1, 'kind': 'ComponentManifest', 'id': lock['component_id'],
        'version': lock['component_version'], 'minimum_engine_version': '0.1.0',
        'name': {'en': 'OXP3 XE display workaround baseline', 'zh': 'OXP3 XE 显示修复基线'},
        'description': {'en': 'Keeps the published enable_dsb=0 configuration. This baseline contains no new repair.',
                        'zh': '保留已公开的 enable_dsb=0 配置；此基线未增加修复。'},
        'optional': True, 'default': False, 'requires': [], 'conflicts': [],
        'compatibility': compatibility, 'retain_owned_paths': True,
        'files': [{'source': 'payload/xe-oxp3.conf', 'target': lock['target'], 'sha256': lock['sha256'],
                   'size': lock['size'], 'mode': lock['mode']}]
    }
    manifest = {
        'schema_version': 1, 'kind': 'DevicePackage', 'id': lock['package_id'], 'version': version,
        'minimum_engine_version': '0.1.0', 'purpose': 'maintenance', 'status': 'experimental',
        'name': {'en': 'ONEXPLAYER 3 static maintenance baseline', 'zh': 'ONEXPLAYER 3 静态维护基线'},
        'source': {'kind': 'github', 'repository': common.REPOSITORY, 'commit': source_commit} if contents is not None else
                  {'kind': 'local', 'path': ROOT.name, 'repository': upstream['repository'], 'base_commit': upstream['source_commit']},
        'upstream_source': {'repository': upstream['repository'], 'commit': upstream['source_commit'],
                            'release_tag': upstream['release_tag'], 'asset': upstream['asset']},
        'compatibility': compatibility, 'trust': {'status': 'index-signature-required' if contents is not None else 'unsigned-development',
                                                'official_release': False},
        'components': [component],
        'notes': ['Maintenance-only catalog; never an installer model selection.',
                  lock['meaning'], 'Only already-owned components may retain journal-proven paths; no scripts run.',
                  'A newer coarse legacy version blocks this older baseline; do not relabel identical bytes to force an upgrade.'],
        'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name,data in sorted(exported.items())]
    }
    output.mkdir(parents=True)
    for name,data in exported.items():
        destination = output/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-installer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--zip',type=Path)
    parser.add_argument('--version',default='0.1.0-dev.1',help='Independent package version; never changes the pinned component baseline')
    parser.add_argument('--source-commit',help='Exact clean public model commit for an authenticated-index candidate')
    args = parser.parse_args()
    if args.zip and args.zip.exists():
        raise SystemExit('Archive output already exists')
    manifest = build(args.public_installer,args.output,version=args.version,source_commit=args.source_commit)
    report = {'id': manifest['id'], 'version': manifest['version'], 'component_version':manifest['components'][0]['version'],
              'manifest_sha256': common.digest(args.output/'manifest.json'), 'manifest_size': (args.output/'manifest.json').stat().st_size,
              'status': manifest['trust']['status']}
    if args.zip:
        common.deterministic_zip(args.output,args.zip)
        report['archive'] = {'name': args.zip.name, 'size': args.zip.stat().st_size, 'sha256':common.digest(args.zip)}
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
