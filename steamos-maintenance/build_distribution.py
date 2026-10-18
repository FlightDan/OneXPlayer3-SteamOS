#!/usr/bin/env python3
"""Build a signed complete index, a legacy-compatible core seed, and atomic assets.

Unchanged assets may keep exact immutable refs from a previous signed index.
This command stages local files only; it never publishes releases or uploads.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile

import build_bundle
from oxp3_maintenance.bundle import BundleError, inspect_bundle, manifest_digest, verify_bundle, _parse_manifest, _path, _regular_input
from oxp3_maintenance.catalog import canonical, create, names, verify, MAX_CATALOG_BYTES
from oxp3_maintenance.distribution import (BRIDGE_MANIFEST, BRIDGE_SIGNATURE, REPOSITORIES,
                                         _write_archive, files_digest, asset_url, describe_source)
from oxp3_maintenance.payload_policy import sanitize_payload


def _sign(raw, private_key, staging, openssl):
    source, signature = staging / 'sign-input', staging / 'sign-output'
    source.write_bytes(raw)
    build_bundle._run([str(openssl), 'pkeyutl', '-sign', '-inkey', str(private_key),
                       '-rawin', '-in', str(source), '-out', str(signature)])
    value = signature.read_bytes()
    if len(value) != 64:
        raise BundleError('Publisher key did not produce an Ed25519 signature.')
    return base64.b64encode(value) + b'\n'


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as content:
        while chunk := content.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _group(name, ids):
    """Put large installers and plugin-specific binaries outside the core."""
    if 'slot-switch' in ids and (name.startswith(('payload/components/slot-switch/',
                                                 'payload/integration/slot-switch/'))
                                 or name == 'payload/components/slot_switch.py'):
        return 'repair-slot-switch', 'slot-switch'
    if name == 'payload/integration/opti2xmx/runtime.tar.gz':
        return 'runtime-opti2xmx', 'opti2xmx-runtime'
    if name.startswith('payload/integration/opti2xmx-runtime/'):
        return 'runtime-opti2xmx', 'opti2xmx-runtime'
    if name.lower().startswith('payload/licenses/opti2xmx') and 'opti2xmx' in ids:
        return 'plugin-opti2xmx', 'opti2xmx'
    for component in ('desktop-hdr', 'gyro', 'wifi', 'manager'):
        if component in ids and name.startswith(('payload/integration/' + component + '/', 'payload/components/' + component + '/')):
            return 'runtime-' + component, component
    if 'decky' in ids and name.startswith('payload/plugins/decky/'):
        return 'runtime-decky', 'decky'
    if 'waydroid' in ids and (name.startswith(('payload/waydroid/', 'payload/components/waydroid/')) or name == 'payload/components/waydroid_setup.py'):
        return 'runtime-waydroid', 'waydroid'
    for component in ('opti2xmx', 'oxp3-fan', 'oxp3-cpu', 'charging', 'windows-reboot'):
        if component not in ids:
            continue
        if name.startswith(('payload/integration/' + component + '/', 'payload/components/' + component + '/', 'payload/plugins/' + component + '/')):
            return 'plugin-' + component, component
    if 'windows-reboot' in ids and name == 'payload/components/windows_reboot.py':
        return 'plugin-windows-reboot', 'windows-reboot'
    return 'core', None


def _split_opti_runtime(payload):
    """Migrate old prepared payloads in staging: plugin setup never fetches XMX."""
    manifest_path = payload / 'integration/manifest.json'
    integration = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    plugin = integration.get('opti2xmx')
    if not isinstance(plugin, dict) or not plugin.get('runtime_archive'):
        return
    runtime = integration.setdefault('opti2xmx-runtime', {'files': [], 'units': [], 'packages': {}, 'missing': []})
    if runtime.get('runtime_archive'):
        raise BundleError('Prepared Opti runtime is declared twice.')
    runtime['runtime_archive'] = plugin.pop('runtime_archive')
    retained, moved = [], {}
    for record in plugin.get('files', []):
        if record.get('target', '').endswith('/.local/share/opti2xmx/runtime.json'):
            _path('payload/integration/' + record['source'])
            old = payload / 'integration' / record['source']
            relative = 'opti2xmx-runtime/' + Path(record['source']).name
            target = payload / 'integration' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            old.rename(target)
            moved['integration/' + record['source']] = 'integration/' + relative
            runtime['files'].append(dict(record, source=relative))
        else:
            retained.append(record)
    plugin['files'] = retained
    manifest_path.write_bytes(canonical(integration))
    for leaf in ('options.json', 'fulloptions.json'):
        path = payload / 'components' / leaf
        if not path.is_file():
            continue
        options = json.loads(path.read_text(encoding='utf-8-sig'))
        if not any(item['id'] == 'opti2xmx-runtime' for category in ('repairs', 'plugins') for item in options[category]):
            options['plugins'].append({'id': 'opti2xmx-runtime', 'zh': 'Opti2XMX · 可选 XMX 运行环境',
                'en': 'Opti2XMX · optional XMX runtime', 'default': False, 'dependencies': ['opti2xmx']})
        path.write_bytes(canonical(options))
    report_path = payload / 'components/preparation-report.json'
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding='utf-8-sig'))
        inventory = report.get('source_inventory', {})
        for old, new in moved.items():
            if old in inventory:
                inventory[new] = inventory.pop(old)
        for relative in list(inventory):
            _path('payload/' + relative)
            path = payload / relative
            if not path.is_file():
                del inventory[relative]
            else:
                inventory[relative].update(sha256=_hash(path), size=path.stat().st_size)
        report.setdefault('coverage', {})['opti2xmx-runtime'] = {
            'dependencies': ['opti2xmx'], 'missing': runtime.get('missing', []),
            'status': 'adapter_supported', 'reason': 'Optional XMX runtime; plugin installation does not select this component.'}
        report.setdefault('distribution_transformations', []).append('Split optional Opti XMX runtime from plugin')
        report_path.write_bytes(canonical(report))


def _shard(output, root, records):
    with output.open('xb') as stream:
        with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name, record in sorted(records.items()):
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = record['size'], record['mode'], 0
                    with (root / name).open('rb') as content:
                        archive.addfile(entry, content)


def build_distribution(payload, source, private_key, output_dir, *, previous_catalog=None,
                       previous_signature=None, repository='FlightDan/OneXPlayer3-SteamOS',
                       opti_repository='FlightDan/Opti2XMX', tag=None, opti_tag=None,
                       openssl='openssl'):
    payload, source, private_key, output_dir = map(Path, (payload, source, private_key, output_dir))
    if repository not in REPOSITORIES or opti_repository != 'FlightDan/Opti2XMX':
        raise BundleError('Distribution repositories must use the publisher allowlist.')
    if output_dir.exists() or output_dir.is_symlink():
        raise BundleError('Distribution output directory already exists.')
    for root in (payload, source):
        if output_dir.resolve().is_relative_to(root.resolve()):
            raise BundleError('Distribution output must be outside input directories.')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.oxp3-distribution-build-', dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        clean = staging / 'payload'
        policy = sanitize_payload(payload, clean)
        _split_opti_runtime(clean)
        mono = staging / 'full.tar.gz'
        original = build_bundle.build_bundle(clean, source, private_key, mono, openssl=openssl)
        release = original['release']
        version = release['version']
        tag = tag or 'maintenance-v' + version
        opti_tag = opti_tag or 'maintenance-assets-v' + version
        trusted = source / 'trusted-public-key.pem'
        previous = None
        if (previous_catalog is None) != (previous_signature is None):
            raise BundleError('Previous catalog and signature must be supplied together.')
        if previous_catalog is not None:
            with _regular_input(previous_catalog, MAX_CATALOG_BYTES) as catalog_file, _regular_input(previous_signature, 256) as signature_file:
                previous = verify(catalog_file.read(MAX_CATALOG_BYTES + 1), signature_file.read(257), trusted, openssl=openssl)
            if previous['schema'] != 2:
                raise BundleError('Asset reference reuse requires a signed schema-2 catalog.')
            from oxp3_maintenance.releases import _Version
            if _Version(previous['release']['version']) > _Version(version):
                raise BundleError('Refusing asset provenance from a future release.')
        descriptor = create(clean, original, mono)
        entries = descriptor['components']
        ids = {item['id'] for item in entries}
        members, owners = {'core': []}, {}
        mapping = {identifier: ['core'] for identifier in ids}
        for name in sorted(original['files']):
            group, component = _group(name, ids)
            members.setdefault(group, []).append(name)
            if component is not None:
                if component not in mapping:
                    raise BundleError('Prepared runtime bytes have no component declaration: ' + component)
                owners[group] = component
                if group not in mapping[component]:
                    mapping[component].append(group)
        # Required groups must also exist for available integrations; no dropped
        # references can be treated as a successful component installation.
        integration = json.loads((clean / 'integration/manifest.json').read_text(encoding='utf-8-sig'))
        for item in entries:
            if not item['available']:
                continue
            metadata = integration.get(item['id'], {})
            for file in metadata.get('files', []):
                path = 'payload/integration/' + file['source']
                if path not in original['files']:
                    raise BundleError('Available component is missing an integration file: ' + item['id'])
            if metadata.get('runtime_archive') and 'payload/integration/' + metadata['runtime_archive'] not in original['files']:
                raise BundleError('Available component is missing its runtime archive: ' + item['id'])
        metadata_paths = {'payload/components/release.json', 'payload/components/options.json',
                          'payload/components/fulloptions.json', 'payload/integration/manifest.json',
                          'payload/components/preparation-report.json'}
        common = {name: original['files'][name] for name in members['core']
                  if name.startswith('payload/') and name not in metadata_paths
                  and not name.endswith(('catalog.json', 'profiles.json', 'runtime-inventory.json'))}
        for item in entries:
            own_groups = set(mapping[item['id']]) - {'core'}
            resources = {name: original['files'][name] for group in own_groups for name in members[group]}
            if not own_groups:
                resources = dict(common)
            # Adapter code generates installed units/wrappers/configuration.
            # UI-only tool changes do not change component receipts, but changes
            # to these implementation inputs must make the component outdated.
            adapter_names = ['components.py', 'compatibility.py']
            if item['id'] == 'gyro':
                adapter_names.append('gyro_binding.py')
            if item['id'] == 'serial-console-policy':
                adapter_names.append('serial_console.py')
            if item['id'] == 'autoflatpaks-compat':
                adapter_names.append('autoflatpaks_compat.py')
            if item['id'] == 'animation-changer-compat':
                adapter_names.append('animation_changer_compat.py')
            for filename in adapter_names:
                name = 'app/oxp3_maintenance/' + filename
                if name in original['files']:
                    resources[name] = original['files'][name]
            item['revision'] = hashlib.sha256(canonical({'files': resources,
                'integration': integration.get(item['id'], {}), 'dependencies': item['dependencies']})).hexdigest()
        packages = {identifier: {'files': paths, 'components': sorted(c for c, groups in mapping.items() if identifier in groups)}
                    for identifier, paths in members.items()}
        root = staging / 'files'
        root.mkdir(mode=0o700)
        verify_bundle(mono, trusted, root, openssl=openssl)
        artifacts = staging / 'artifacts'
        maintenance, opti = artifacts / 'maintenance', artifacts / 'opti2xmx'
        maintenance.mkdir(parents=True)
        opti.mkdir()
        refs, built, reused = {}, [], []
        for identifier in sorted(set(packages) - {'core'}):
            records = {name: original['files'][name] for name in packages[identifier]['files']}
            digest = files_digest(records)
            name = 'oxp3-package-' + identifier + '-' + digest[:16] + '.tar.gz'
            is_opti = owners.get(identifier) in ('opti2xmx', 'opti2xmx-runtime')
            folder = opti if is_opti else maintenance
            shard = folder / name
            _shard(shard, root, records)
            ref = {'name': name, 'size': shard.stat().st_size, 'sha256': _hash(shard), 'files_digest': digest,
                   'url': 'https://github.com/' + (opti_repository if is_opti else repository)
                          + '/releases/download/' + (opti_tag if is_opti else tag) + '/' + name}
            old = (previous or {}).get('packages', {}).get(identifier)
            raw_output = None
            if identifier == 'runtime-opti2xmx':
                raw_name = 'payload/integration/opti2xmx/runtime.tar.gz'
                raw_record = original['files'][raw_name]
                asset_name = 'opti2xmx-xmx-runtime-20261005-' + raw_record['sha256'][:16] + '.tar.gz'
                raw_asset = {'name': asset_name, 'size': raw_record['size'], 'sha256': raw_record['sha256'],
                    'url': 'https://github.com/' + opti_repository + '/releases/download/' + opti_tag + '/' + asset_name}
                old_raw = (old or {}).get('raw_asset')
                if old_raw and all(old_raw.get(field) == raw_asset[field] for field in ('name', 'size', 'sha256')):
                    raw_asset = old_raw
                else:
                    raw_output = opti / asset_name
                    shutil.copyfile(root / raw_name, raw_output)
                ref['raw_asset'] = raw_asset
            if not asset_url(ref['url']):
                raise BundleError('Distribution tag or asset filename is unsafe.')
            if old is not None and all(old.get(field) == ref[field] for field in ('name', 'size', 'sha256', 'files_digest')):
                # Origin is a security property: Opti assets always live in Opti2XMX.
                expected_repo = opti_repository if is_opti else repository
                if urllib_repo(old['url']) == expected_repo:
                    refs[identifier] = old
                    shard.unlink()
                    if raw_output is not None:
                        raw_output.unlink()
                    reused.append(identifier)
                    continue
            refs[identifier] = ref
            built.append(identifier)
        full = dict(original, schema=2, packages=packages, component_packages=mapping,
                    package_refs=refs, components=entries)
        raw = canonical(full)
        signature = _sign(raw, private_key, staging, openssl)
        _parse_manifest(raw, signature, trusted, openssl)
        # Schema-1 core is intentionally usable by older root verifiers for a
        # tool-only bridge upgrade. The signed schema-2 manifest is data, never
        # executed by the legacy installer.
        core_records = {name: original['files'][name] for name in packages['core']['files']}
        for name, data in ((BRIDGE_MANIFEST, raw), (BRIDGE_SIGNATURE, signature)):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            core_records[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'mode': 0o644}
        seed = {'schema': 1, 'release': release, 'notes': full.get('notes', ''), 'files': core_records}
        seed_raw = canonical(seed)
        seed_sig = _sign(seed_raw, private_key, staging, openssl)
        archive = maintenance / ('oxp3-maintenance-' + version + '-linux-x86_64.tar.gz')
        _write_archive(archive, root, core_records, seed_raw, seed_sig)
        inspect_bundle(archive, trusted, openssl=openssl)
        index = dict(create(clean, seed, archive), schema=2, components=entries, packages=refs,
                     component_packages=mapping, distribution_manifest_digest=manifest_digest(full))
        index_raw = canonical(index)
        index_sig = _sign(index_raw, private_key, staging, openssl)
        verify(index_raw, index_sig, trusted, expected_version=version, openssl=openssl)
        for name, data in zip(names(version), (index_raw, index_sig)):
            (maintenance / name).write_bytes(data)
        if 'runtime-opti2xmx' in refs:
            raw_asset = refs['runtime-opti2xmx']['raw_asset']
            runtime_source = {'schema': 1, 'version': '20261005', 'size_bytes': raw_asset['size'],
                'sha256': raw_asset['sha256'], 'published': False, 'url': None,
                'proposed_url': raw_asset['url'], 'asset_name': raw_asset['name']}
            runtime_raw = canonical(runtime_source)
            (opti / 'runtime-source.json').write_bytes(runtime_raw)
            (opti / 'runtime-source.sig').write_bytes(_sign(runtime_raw, private_key, staging, openssl))
        from build_installer import build_installer, INSTALLER_NAME
        build_installer(source, trusted, maintenance / INSTALLER_NAME, openssl=openssl)
        (maintenance / 'trusted-public-key.pem').write_bytes(trusted.read_bytes())
        actual = describe_source(archive, trusted, openssl=openssl)
        if actual['distribution_manifest_digest'] != index['distribution_manifest_digest']:
            raise BundleError('Built seed does not carry the expected signed distribution.')
        plan = {'schema': 1, 'release': release, 'core': str(Path('maintenance') / archive.name),
                'catalog': str(Path('maintenance') / names(version)[0]),
                'repositories': {'maintenance': repository, 'opti2xmx': opti_repository},
                'tags': {'maintenance': tag, 'opti2xmx': opti_tag}, 'built_packages': built,
                'reused_packages': reused, 'packages': refs, 'policy_excluded': policy['excluded']}
        (artifacts / 'release-plan.json').write_bytes(canonical(plan))
        for folder in (maintenance, opti):
            lines = [_hash(path) + '  ' + path.name + '\n' for path in sorted(folder.iterdir())]
            (folder / 'SHA256SUMS').write_text(''.join(lines), encoding='ascii', newline='\n')
        artifacts.rename(output_dir)
    return {'path': str(output_dir.absolute()), 'catalog': index, 'manifest': full, 'plan': plan}


def urllib_repo(url):
    import urllib.parse
    return '/'.join(urllib.parse.urlsplit(url).path.split('/')[1:3])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--previous-catalog', type=Path)
    parser.add_argument('--previous-signature', type=Path)
    parser.add_argument('--repository', default='FlightDan/OneXPlayer3-SteamOS')
    parser.add_argument('--opti-repository', default='FlightDan/Opti2XMX')
    parser.add_argument('--tag')
    parser.add_argument('--opti-tag')
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args(argv)
    try:
        result = build_distribution(**vars(args))
    except (BundleError, OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, 'Distribution build failed: %s\n' % exc)
    print('Built signed modular distribution: ' + result['path'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
