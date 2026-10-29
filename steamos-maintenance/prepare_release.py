#!/usr/bin/env python3
"""Stage an explicit release version and independently built Opti plugin ZIP.

Inputs stay unchanged. This does not build Windows, fetch binaries, sign, publish
or execute any file from the plugin. Use a fresh prepared payload from the target
branch after its component work has completed.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

from build_bundle import _metadata
from oxp3_maintenance.bundle import BundleError
from oxp3_maintenance.payload_policy import sanitize_payload, json_bytes

PUBLIC_FSR_COMPAT_MEMBERS = frozenset({
    'fsr_compat/manifest.json',
    'fsr_compat/bin/fsrxdec.dll', 'fsr_compat/bin/libwim-15.dll',
    'fsr_compat/licenses/fsrxdec-LICENSE.txt',
    'fsr_compat/licenses/wimlib/COPYING.GPLv3.txt',
    'fsr_compat/licenses/wimlib/COPYING.LGPL.txt',
    'fsr_compat/licenses/wimlib/COPYING.libdivsufsort-lite.txt',
    'fsr_compat/licenses/wimlib/COPYING.txt',
    'fsr_compat/sources/fsr_compat/build.ps1',
    'fsr_compat/sources/fsr_compat/dependency-source.json',
    'fsr_compat/sources/fsr_compat/fsrxdec.c',
    'fsr_compat/sources/fsr_compat/fsrxdec.def',
    'fsr_compat/sources/fsr_compat/LICENSE',
    'fsr_compat/sources/fsr_compat/README.md',
    'fsr_compat/sources/fsr_compat/test_fsrxdec.py',
    'fsr_compat/sources/wimlib-1.14.5.tar.gz',
})


def _public_plugin_member(relative):
    if relative.startswith('fsr_compat/'):
        return relative in PUBLIC_FSR_COMPAT_MEMBERS
    return PurePosixPath(relative).suffix.lower() in {'.py', '.json', '.js', '.md', '.png', '.txt'} or relative == 'LICENSE'


def plugin_files(archive):
    records, total = {}, 0
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 128:
            raise ValueError('Plugin ZIP has too many members')
        for item in source.infolist():
            name = item.filename
            if (not name.startswith('opti2xmx/') or '\\' in name or ':' in name
                    or any(part in ('', '.', '..') for part in name.rstrip('/').split('/'))
                    or any(ord(c) < 32 for c in name)):
                raise ValueError('Unsafe plugin ZIP path')
            if item.is_dir():
                continue
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError('Plugin ZIP links and special files are forbidden')
            relative = name[len('opti2xmx/'):]
            if (relative in records or item.file_size > 16 * 1024 * 1024
                    or not _public_plugin_member(relative)):
                raise ValueError('Unexpected, duplicate or oversized plugin resource')
            total += item.file_size
            if total > 32 * 1024 * 1024:
                raise ValueError('Plugin ZIP must not contain runtime binaries')
            records[relative] = source.read(item)
    required = {'plugin.json', 'package.json', 'main.py', 'manager.py', 'opti.py',
                'per_game.py', 'runtime_setup.py', 'runtime-source.json', 'dist/index.js'}
    if not required <= records.keys():
        raise ValueError('Independent Opti plugin is missing its runtime download interface')
    if json.loads(records['plugin.json']).get('name') != 'Opti2XMX':
        raise ValueError('Expected the independently built Opti2XMX plugin')
    return records


def _overlay_runtime(stage, manifest, records, runtime):
    descriptor = json.loads(records['runtime-source.json'])
    if (not isinstance(descriptor, dict) or descriptor.get('published') is not True
            or type(descriptor.get('size_bytes')) is not int
            or not 0 < descriptor['size_bytes'] <= 200 * 1024 * 1024
            or not isinstance(descriptor.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', descriptor['sha256'])):
        raise ValueError('Runtime overlay requires a published size/hash-pinned descriptor')
    reference = (manifest.get('opti2xmx-runtime', {}).get('runtime_archive')
                 or manifest.get('opti2xmx', {}).get('runtime_archive'))
    if (not isinstance(reference, str) or not reference or reference.startswith('/')
            or '\\' in reference or ':' in reference
            or any(part in ('', '.', '..') for part in reference.split('/'))):
        raise ValueError('Unsafe prepared runtime archive reference')
    runtime = Path(runtime)
    info = runtime.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Runtime input must be a single regular archive')
    destination = stage / 'integration' / reference
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with runtime.open('rb') as source, destination.open('wb') as target:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > descriptor['size_bytes']:
                raise ValueError('Runtime input exceeds its pinned size')
            digest.update(chunk)
            target.write(chunk)
    if size != descriptor['size_bytes'] or digest.hexdigest() != descriptor['sha256']:
        raise ValueError('Runtime input differs from its published descriptor')
    return {'archive': reference, 'size_bytes': size, 'sha256': digest.hexdigest(),
            'url': descriptor.get('url'), 'source_name': runtime.name}


def prepare_release(payload, release_metadata, opti_plugin, output, opti_runtime=None):
    payload, release_metadata, opti_plugin, output = map(Path, (payload, release_metadata, opti_plugin, output))
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(payload.resolve()):
        raise ValueError('Release output must be a fresh directory outside the payload')
    output.parent.mkdir(parents=True, exist_ok=True)
    records = plugin_files(opti_plugin)
    release = json.loads(release_metadata.read_text(encoding='utf-8-sig'))
    with tempfile.TemporaryDirectory(prefix='.oxp3-release-input-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'payload'
        policy = sanitize_payload(payload, stage)
        (stage / 'components/release.json').write_bytes(json_bytes(release))
        _metadata(stage)
        source_copy = stage / 'components/opti2xmx'
        if source_copy.exists():
            shutil.rmtree(source_copy)
        for name, content in records.items():
            path = source_copy / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        manifest_path = stage / 'integration/manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        runtime_overlay = _overlay_runtime(stage, manifest, records, opti_runtime) if opti_runtime is not None else None
        entry = manifest['opti2xmx']
        prefix = 'home/deck/homebrew/plugins/opti2xmx/'
        kept = []
        for item in entry['files']:
            if item['target'].startswith(prefix):
                # The old generated copies become unreferenced. Remove only
                # files within this known integration folder in private staging.
                parts = PurePosixPath(item['source']).parts
                if len(parts) != 2 or parts[0] != 'opti2xmx' or parts[1] in ('.', '..'):
                    raise ValueError('Unexpected old Opti integration resource')
                (stage / 'integration' / item['source']).unlink(missing_ok=True)
            else:
                kept.append(item)
        for index, (name, content) in enumerate(sorted(records.items())):
            source = 'opti2xmx/plugin-%03d.bin' % index
            path = stage / 'integration' / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            kept.append({'source': source, 'target': prefix + name, 'mode': 0o644, 'user': True})
        entry['files'] = kept
        manifest_path.write_bytes(json_bytes(manifest))
        report = {'release': release, 'plugin_version': json.loads(records['package.json'])['version'],
                  'plugin_sha256': hashlib.sha256(opti_plugin.read_bytes()).hexdigest(),
                  'plugin_files': len(records), 'excluded': policy['excluded'],
                  'source_payload': payload.name, 'published': False}
        if runtime_overlay is not None:
            report['runtime_overlay'] = runtime_overlay
        (stage / 'components/release-preparation.json').write_bytes(json_bytes(report))
        previous = stage / 'components/preparation-report.json'
        if previous.exists():
            value = json.loads(previous.read_text(encoding='utf-8-sig'))
            value['release'] = release
            # Old input inventory no longer describes the independent plugin.
            value['release_overlay'] = report
            value.pop('source_inventory', None)
            previous.write_bytes(json_bytes(value))
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--release-metadata', type=Path, required=True)
    parser.add_argument('--opti-plugin', type=Path, required=True)
    parser.add_argument('--opti-runtime', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_release(**vars(args))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, BundleError) as error:
        parser.exit(1, 'Release preparation failed: %s\n' % error)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
