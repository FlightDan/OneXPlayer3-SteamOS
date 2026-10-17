"""User-owned authenticated downloads. This module never installs a component."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .bundle import BundleError, inspect_bundle
from .releases import download_bundle, fetch_catalog, ReleaseError


def trusted_key():
    return Path(__file__).resolve().parent.parent / 'trusted-public-key.pem'


def _check(path, candidate, key, catalog=None):
    manifest = inspect_bundle(path, key)
    if manifest['release']['version'] != candidate['version']:
        raise BundleError('Downloaded package version differs from the selected release')
    if catalog:
        digest = hashlib.sha256()
        with Path(path).open('rb') as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        actual = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if (digest.hexdigest() != catalog['bundle']['sha256']
                or Path(path).stat().st_size != catalog['bundle']['size']
                or actual != catalog['bundle']['manifest_digest']):
            raise BundleError('Downloaded package does not match its signed capability catalog')
    return manifest


def save(candidate, destination, *, key=None, opener=None, progress=None):
    """Keep the full offline package; root verifies it again before any writes."""
    key = Path(key or trusted_key())
    if not key.is_file():
        raise BundleError('Trusted maintenance signing key is unavailable; download verification is disabled')
    if not isinstance(candidate.get('asset_name'), str) or candidate['asset_name'] != 'oxp3-maintenance-' + candidate['version'] + '-linux-x86_64.tar.gz':
        raise ReleaseError('Invalid maintenance download filename')
    catalog = fetch_catalog(candidate, key, opener=opener, progress=progress) if candidate.get('catalog_urls') else None
    destination = Path(destination).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / candidate['asset_name']
    if target.is_symlink():
        raise ReleaseError('Refusing a linked download destination')
    if target.exists():
        manifest = _check(target, candidate, key, catalog)
        return {'status': 'cached', 'path': str(target.absolute()), 'release': manifest['release']}
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='.oxp3-download-', dir=destination) as temporary:
            temporary = Path(temporary) / candidate['asset_name']
            download_bundle(candidate['download_url'], temporary, opener=opener, progress=progress)
            manifest = _check(temporary, candidate, key, catalog)
            with target.open('xb') as output, temporary.open('rb') as incoming:
                created = True
                while chunk := incoming.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        return {'status': 'downloaded', 'path': str(target.absolute()), 'release': manifest['release']}
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise
