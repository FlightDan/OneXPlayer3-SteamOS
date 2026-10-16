#!/usr/bin/env python3
"""Stage and locally package a complete maintenance release; never publish it."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

import build_bundle
from build_installer import INSTALLER_NAME, build_installer, public_key_bytes
from oxp3_maintenance.bundle import BundleError


def package_release(payload: Path, public_key: Path, private_key: Path, output_dir: Path,
                    source: Path | None = None, *, openssl='openssl', modular=False,
                    previous_catalog=None, previous_signature=None, tag=None, opti_tag=None,
                    opti_repository='FlightDan/Opti2XMX') -> Path:
    """Build into a private sibling directory, exposing output only on success."""
    payload, public_key, private_key, output_dir = map(Path, (payload, public_key, private_key, output_dir))
    source = Path(source) if source is not None else Path(__file__).resolve().parent
    if not modular and any(value is not None for value in (previous_catalog, previous_signature, tag, opti_tag)):
        raise BundleError('Previous catalogs and release tags require --modular.')
    if output_dir.exists() or output_dir.is_symlink():
        raise BundleError('Release output directory already exists.')
    for root in (source, payload):
        if private_key.resolve().is_relative_to(root.resolve()):
            raise BundleError('Keep the private signing key outside all release input directories.')
        if output_dir.resolve().is_relative_to(root.resolve()):
            raise BundleError('Release output must be outside all release input directories.')
    if not private_key.is_file() or private_key.is_symlink():
        raise BundleError('Publisher private signing key is unavailable or a symlink.')
    key = public_key_bytes(public_key, openssl=openssl)
    release = build_bundle._metadata(payload)
    # Staging deliberately excludes Windows installers, build scripts, caches,
    # arbitrary adjacent files, and the source checkout's trust-key file.
    with tempfile.TemporaryDirectory(prefix='.oxp3-release-', dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        app, artifacts = staging / 'source', staging / 'artifacts'
        app.mkdir()
        if not modular:
            artifacts.mkdir()
        inputs = build_bundle._collect_tree(source / 'oxp3_maintenance', 'oxp3_maintenance', python_only=True)
        for name in build_bundle.LAUNCHERS:
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise BundleError('Maintenance launcher is missing or a symlink: ' + name)
            inputs[name] = path
        for name in ('README.md', 'VALIDATION.md'):
            path = source / name
            if path.is_file() and not path.is_symlink():
                inputs[name] = path
        for name, path in sorted(inputs.items()):
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        (app / 'trusted-public-key.pem').write_bytes(key)
        if modular:
            from build_distribution import build_distribution
            build_distribution(payload, app, private_key, artifacts,
                previous_catalog=previous_catalog, previous_signature=previous_signature,
                tag=tag, opti_tag=opti_tag, opti_repository=opti_repository, openssl=openssl)
            artifacts.rename(output_dir)
            return output_dir
        archive = artifacts / ('oxp3-maintenance-' + release['version'] + '-linux-x86_64.tar.gz')
        manifest = build_bundle.build_bundle(payload, app, private_key, archive, openssl=openssl)
        build_bundle.write_catalog(payload, manifest, archive, private_key, openssl=openssl)
        build_installer(app, app / 'trusted-public-key.pem', artifacts / INSTALLER_NAME, openssl=openssl)
        (artifacts / 'trusted-public-key.pem').write_bytes(key)
        lines = []
        for path in sorted(artifacts.iterdir()):
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            lines.append(digest.hexdigest() + '  ' + path.name + '\n')
        (artifacts / 'SHA256SUMS').write_text(''.join(lines), encoding='ascii', newline='\n')
        artifacts.rename(output_dir)
    return output_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--openssl', default='openssl')
    parser.add_argument('--modular', action='store_true', help='Build core, signed complete catalog, and on-demand component assets')
    parser.add_argument('--previous-catalog', type=Path)
    parser.add_argument('--previous-signature', type=Path)
    parser.add_argument('--tag')
    parser.add_argument('--opti-tag')
    parser.add_argument('--opti-repository', default='FlightDan/Opti2XMX')
    args = parser.parse_args(argv)
    try:
        package_release(args.payload, args.public_key, args.private_key, args.output_dir, args.source,
            openssl=args.openssl, modular=args.modular, previous_catalog=args.previous_catalog,
            previous_signature=args.previous_signature, tag=args.tag, opti_tag=args.opti_tag,
            opti_repository=args.opti_repository)
    except (BundleError, OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, 'Release packaging failed: %s\n' % error)
    print('Packaged local release: ' + str(args.output_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
