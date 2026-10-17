#!/usr/bin/env python3
"""Local publisher preparation. Never upload, publish or change device trust."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

SOURCE = Path(__file__).resolve().parent
WORKSPACE = SOURCE.parent
DEFAULT_STORE = WORKSPACE / '.release-private/maintenance-ed25519'


def openssl_path(explicit=None):
    local = WORKSPACE / '.release-work/toolchain/openssl/ucrt64/bin/openssl.exe'
    candidate = explicit or os.environ.get('OXP3_OPENSSL') or (
        str(local) if local.is_file() else shutil.which('openssl'))
    if not candidate:
        raise ValueError('OpenSSL CLI is required for release packaging; use --openssl or OXP3_OPENSSL.')
    resolved = shutil.which(str(candidate))
    if not resolved:
        raise ValueError('OpenSSL executable is unavailable.')
    result = subprocess.run([resolved, 'version'], capture_output=True, timeout=15, check=True)
    if not result.stdout.startswith(b'OpenSSL 3.'):
        raise ValueError('Release packaging requires OpenSSL 3.x with Ed25519 support.')
    return resolved


def metadata(version):
    from oxp3_maintenance.releases import _Version
    if _Version(version).text != version:
        raise ValueError('Use a canonical project version.')
    path = SOURCE / 'release' / (version + '.json')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    expected = 'beta' if _Version(version).pre else 'stable'
    if value.get('version') != version or value.get('channel') != expected:
        raise ValueError('Release metadata does not match version/channel.')
    return path, value


def install_public_key(status, destination=None):
    """Pin only the public half. A different existing anchor is never replaced."""
    destination = SOURCE / 'trusted-public-key.pem' if destination is None else Path(destination)
    content = Path(status['public_key']).read_bytes()
    if b'PRIVATE KEY' in content or not content.startswith(b'-----BEGIN PUBLIC KEY-----\n'):
        raise ValueError('Expected canonical public PEM.')
    if destination.is_symlink():
        raise ValueError('Canonical public key must not be a symlink.')
    if destination.exists():
        if destination.read_bytes() != content:
            raise ValueError('Canonical publisher public key differs; refusing replacement.')
    else:
        with destination.open('xb') as target:
            target.write(content)
    return str(destination.absolute())


def preflight(version, store, *, openssl=None, opti_plugin=None):
    from publisher_keys import key_status
    report = {'version': version, 'ready': False, 'blockers': [], 'published': False}
    try:
        _, report['release'] = metadata(version)
    except (OSError, ValueError) as error:
        report['blockers'].append(str(error))
    try:
        report['signing'] = key_status(store, openssl=openssl)
        if report['signing'].get('status') != 'ready':
            raise ValueError('No formal publisher identity; run init-key once.')
        canonical = SOURCE / 'trusted-public-key.pem'
        if canonical.is_symlink() or canonical.read_bytes() != Path(report['signing']['public_key']).read_bytes():
            raise ValueError('Canonical publisher public key is missing or differs; run init-key.')
    except (OSError, ValueError, RuntimeError) as error:
        report['blockers'].append('Signing key: ' + str(error))
    try:
        report['openssl'] = openssl_path(openssl)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['blockers'].append(str(error))
    if opti_plugin is None:
        report['blockers'].append('Provide the final independently built Opti2XMX ZIP with --opti-plugin.')
    else:
        try:
            from prepare_release import plugin_files
            records = plugin_files(Path(opti_plugin))
            runtime_descriptor(records)
            package = json.loads(records['package.json'])
            if not isinstance(package, dict) or not isinstance(package.get('version'), str):
                raise ValueError('Invalid independent plugin version metadata.')
            report['opti_plugin_version'] = package['version']
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
            report['blockers'].append('Opti input: ' + str(error))
    report['ready'] = not report['blockers']
    return report


def runtime_descriptor(records):
    from oxp3_maintenance.distribution import runtime_asset_url
    descriptor = json.loads(records['runtime-source.json'])
    if (not isinstance(descriptor, dict) or type(descriptor.get('schema')) is not int
            or descriptor['schema'] != 1 or not isinstance(descriptor.get('version'), str)
            or not re.fullmatch('[A-Za-z0-9._-]{1,40}', descriptor['version'])
            or descriptor.get('published') is not True
            or not isinstance(descriptor.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', descriptor['sha256'])
            or type(descriptor.get('size_bytes')) is not int
            or not 0 < descriptor['size_bytes'] <= 200 * 1024 * 1024
            or not runtime_asset_url(descriptor.get('url'))):
        raise ValueError('Opti runtime descriptor must pin a published immutable runtime, digest and size.')
    return descriptor


def validate_runtime(payload, opti_plugin):
    """Reject an old cache even when the independent plugin ZIP is current."""
    from prepare_release import plugin_files
    descriptor = runtime_descriptor(plugin_files(Path(opti_plugin)))
    manifest = json.loads((payload / 'integration/manifest.json').read_text(encoding='utf-8-sig'))
    runtime = manifest.get('opti2xmx-runtime', {}).get('runtime_archive') or manifest['opti2xmx']['runtime_archive']
    if not isinstance(runtime, str):
        raise ValueError('Unsafe prepared runtime reference.')
    relative = Path(runtime)
    if (not runtime or runtime.startswith('/') or relative.is_absolute()
            or '..' in relative.parts or ':' in runtime or '\\' in runtime):
        raise ValueError('Unsafe prepared runtime reference.')
    archive = payload / 'integration' / relative
    if archive.is_symlink() or not archive.resolve().is_relative_to((payload / 'integration').resolve()):
        raise ValueError('Unsafe prepared runtime reference.')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    expected_size = descriptor.get('size_bytes', descriptor.get('size'))
    if digest.hexdigest() != descriptor['sha256'] or archive.stat().st_size != expected_size:
        raise ValueError('Prepared XMX runtime differs from the published plugin descriptor; refresh its cache.')


def prepare(version, store, *, openssl=None, opti_plugin=None, opti_runtime=None, output=None):
    # Fail before creating output when dependencies or final plugin inputs are missing.
    report = preflight(version, store, openssl=openssl, opti_plugin=opti_plugin)
    if not report['ready']:
        raise ValueError('\n'.join(report['blockers']))
    from prepare_payload import prepare_payload
    from prepare_release import prepare_release
    from package_release import package_release
    from publisher_keys import signing_key
    if output is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output = WORKSPACE / '.release-work' / ('maintenance-v' + version + '-' + stamp)
    candidate = Path(output).absolute()
    for ancestor in (candidate, *candidate.parents):
        if os.path.lexists(ancestor) and (ancestor.is_symlink()
                or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Publisher output ancestors must not be links or junctions.')
    output = candidate.resolve()
    # Restrict working files to an ignored publisher directory, away from inputs/secrets.
    allowed = (WORKSPACE / '.release-work').absolute()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('Publisher output must be a fresh child of .release-work.')
    output.parent.mkdir(parents=True, exist_ok=True)
    for ancestor in (output.parent, *output.parent.parents):
        if ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Publisher output ancestors must not be links or junctions.')
    output.mkdir()
    result = {'version': version, 'published': False, 'complete': False}
    try:
        base = output / 'prepared-current'
        coverage = prepare_payload(WORKSPACE, base,
                                   maintenance_options=SOURCE / 'release/maintenance-options.json')
        if not coverage['resource_complete']:
            raise ValueError('Prepared resources are incomplete; inspect components/preparation-report.json.')
        overlay = output / 'prepared-release'
        release_metadata, _ = metadata(version)
        prepare_release(base, release_metadata, Path(opti_plugin), overlay, opti_runtime=opti_runtime)
        validate_runtime(overlay, opti_plugin)
        with signing_key(store, openssl=report['openssl']) as private:
            package_release(overlay, Path(report['signing']['public_key']), private,
                            output / 'artifacts', source=SOURCE, openssl=report['openssl'],
                            modular=True, tag='maintenance-v' + version,
                            opti_tag='maintenance-assets-v' + version)
        result.update(complete=True, artifacts=str(output / 'artifacts'),
                      fingerprint_sha256=report['signing']['fingerprint_sha256'])
    finally:
        (output / 'publisher-report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init-key', 'status', 'preflight', 'prepare'))
    parser.add_argument('--version', default='0.1.4')
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    parser.add_argument('--openssl')
    parser.add_argument('--opti-plugin', type=Path)
    parser.add_argument('--opti-runtime', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'init-key':
            from publisher_keys import ensure_keys
            result = ensure_keys(args.store, openssl=args.openssl)
            result['canonical_public_key'] = install_public_key(result)
        elif args.action == 'status':
            from publisher_keys import key_status
            result = key_status(args.store, openssl=args.openssl)
        elif args.action == 'preflight':
            result = preflight(args.version, args.store, openssl=args.openssl, opti_plugin=args.opti_plugin)
        else:
            result = prepare(args.version, args.store, openssl=args.openssl,
                             opti_plugin=args.opti_plugin, opti_runtime=args.opti_runtime, output=args.output)
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, 'Publisher preparation failed: %s\n' % error)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if args.action == 'preflight' and not result['ready'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
