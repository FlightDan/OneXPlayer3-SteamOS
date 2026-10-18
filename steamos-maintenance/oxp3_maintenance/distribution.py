"""Authenticated sparse distributions; all networking runs as the desktop user.

A schema-1 seed upgrades legacy maintenance backends safely. It carries a second
signed schema-2 manifest defining every atomic package and immutable asset ref.
Only the requested component dependency closure is downloaded and assembled.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request

from .bundle import (BundleError, MAX_ARCHIVE_BYTES, MAX_MANIFEST_BYTES, MAX_SIGNATURE_BYTES, _open_archive, _parse_manifest,
                     _scan, _present_manifest, _regular_input, inspect_bundle,
                     manifest_digest, verify_bundle)
from .catalog import canonical
from .releases import ReleaseError, _request, _safe_transfer_url

BRIDGE_MANIFEST = 'payload/components/distribution-manifest.json'
BRIDGE_SIGNATURE = 'payload/components/distribution-manifest.sig'
REPOSITORIES = {'FlightDan/OneXPlayer3-SteamOS', 'FlightDan/Opti2XMX'}
_HASH = re.compile('[0-9a-f]{64}\\Z')
_ID = re.compile('[a-z][a-z0-9-]{0,79}\\Z')


def files_digest(records):
    return hashlib.sha256(canonical(records)).hexdigest()


def asset_url(url):
    """Only named immutable-tag assets from the two publisher repositories."""
    try:
        parsed = urllib.parse.urlsplit(url)
        parts = urllib.parse.unquote(parsed.path).split('/')
        return (parsed.scheme == 'https' and parsed.hostname == 'github.com'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment and len(parts) == 7
                and all(p and p not in ('.', '..') and not any(ord(c) < 33 for c in p) for p in parts[1:])
                and '/'.join(parts[1:3]) in REPOSITORIES
                and parts[3:5] == ['releases', 'download']
                and parts[5].lower() not in {'latest', 'head', 'main', 'master'}
                and bool(re.fullmatch('[A-Za-z0-9][A-Za-z0-9._+-]{0,159}', parts[5]))
                and bool(re.fullmatch('oxp3-package-[a-z0-9-]+-[0-9a-f]{16}\\.tar\\.gz', parts[6])))
    except (TypeError, ValueError, AttributeError):
        return False


def runtime_asset_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        parts = parsed.path.split('/')
        if ('/'.join(parts[1:3]) != 'FlightDan/Opti2XMX'
                or not re.fullmatch('opti2xmx-xmx-runtime-[0-9]{8}-[0-9a-f]{16}\\.tar\\.gz', parts[-1])):
            return False
        replaced = urllib.parse.urlunsplit(parsed._replace(path='/'.join(parts[:-1] + ['oxp3-package-runtime-0123456789abcdef.tar.gz'])))
        return asset_url(replaced)
    except (ValueError, TypeError, AttributeError):
        return False


def validate_index(value):
    """Validate signed index structure independently of network or local state."""
    try:
        refs, mapping = value['packages'], value['component_packages']
        entries = value['components']
        if not isinstance(refs, dict) or len(refs) > 255 or not isinstance(mapping, dict):
            raise ValueError()
        if not isinstance(value['distribution_manifest_digest'], str) or not _HASH.fullmatch(value['distribution_manifest_digest']):
            raise ValueError()
        ids = {entry['id'] for entry in entries}
        if len(ids) != len(entries) or set(mapping) != ids:
            raise ValueError()
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str)
                    or not _ID.fullmatch(entry['id']) or entry.get('kind') not in ('repairs', 'plugins')
                    or entry.get('delivery') not in ('maintenance', 'separate_operation')
                    or type(entry.get('available')) is not bool
                    or any(not isinstance(entry.get(k), str) or len(entry[k]) > 1024 for k in ('zh', 'en'))):
                raise ValueError()
        used = {'core'}
        for component, groups in mapping.items():
            if (not _ID.fullmatch(component) or not isinstance(groups, list) or 'core' not in groups
                    or any(not isinstance(group, str) or not _ID.fullmatch(group) for group in groups)
                    or len(groups) != len(set(groups))):
                raise ValueError()
            used.update(groups)
        if used - {'core'} != set(refs):
            raise ValueError()
        for identifier, ref in refs.items():
            if (not isinstance(ref, dict) or not asset_url(ref['url'])
                    or ref['name'] != urllib.parse.unquote(urllib.parse.urlsplit(ref['url']).path.rsplit('/', 1)[1])
                    or type(ref['size']) is not int or not 0 < ref['size'] <= MAX_ARCHIVE_BYTES
                    or any(not isinstance(ref[key], str) or not _HASH.fullmatch(ref[key]) for key in ('sha256', 'files_digest'))):
                raise ValueError()
            if 'raw_asset' in ref:
                raw = ref['raw_asset']
                if (identifier != 'runtime-opti2xmx' or not isinstance(raw, dict)
                        or not runtime_asset_url(raw['url'])
                        or raw['name'] != raw['url'].rsplit('/', 1)[1]
                        or type(raw['size']) is not int or not 0 < raw['size'] <= MAX_ARCHIVE_BYTES
                        or not isinstance(raw['sha256'], str) or not _HASH.fullmatch(raw['sha256'])):
                    raise ValueError()
        # Check all nodes, including unavailable/unselected entries.
        graph = {entry['id']: entry['dependencies'] for entry in entries}
        active, visited = set(), set()
        def visit(identifier):
            if identifier in active or identifier not in graph:
                raise ValueError()
            if identifier in visited:
                return
            active.add(identifier)
            if not isinstance(graph[identifier], list) or any(not isinstance(x, str) for x in graph[identifier]):
                raise ValueError()
            for dependency in graph[identifier]:
                visit(dependency)
            active.remove(identifier)
            visited.add(identifier)
        for identifier in graph:
            visit(identifier)
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise BundleError('Signed distribution index has invalid references or dependencies.') from exc


def _descriptor(manifest):
    if 'signed_files' in manifest:
        manifest = dict(manifest, files=manifest['signed_files'])
    value = {'schema': 2, 'release': manifest['release'], 'components': manifest.get('components'),
             'component_packages': manifest['component_packages'], 'packages': manifest.get('package_refs'),
             'distribution_manifest_digest': manifest_digest(manifest)}
    validate_index(value)
    if set(value['packages']) != set(manifest['packages']) - {'core'}:
        raise BundleError('Distribution package references do not cover signed package membership.')
    for identifier, ref in value['packages'].items():
        records = {name: manifest['files'][name] for name in manifest['packages'][identifier]['files']}
        if files_digest(records) != ref['files_digest']:
            raise BundleError('Distribution asset reference does not match signed file membership.')
        if 'raw_asset' in ref:
            record = records.get('payload/integration/opti2xmx/runtime.tar.gz')
            if record is None or any(ref['raw_asset'][field] != record[field] for field in ('size', 'sha256')):
                raise BundleError('Raw runtime asset does not match its signed embedded archive.')
    return value


def index_from_manifest(manifest):
    """Index from a previously authenticated schema-2 manifest view."""
    if manifest.get('schema') != 2:
        return None
    return _descriptor(manifest)


def _source(source, key, directory, openssl):
    """Copy authenticated files, preserving the exact original signed manifest."""
    view = verify_bundle(source, key, directory, openssl=openssl)
    with _open_archive(source) as stream:
        records, special = _scan(stream)
    original = _parse_manifest(special['manifest.json'], special['manifest.sig'], key, openssl)
    if manifest_digest(original) != manifest_digest(view) or records != view['files']:
        raise BundleError('Distribution source changed while being read.')
    if view['schema'] == 1:
        if BRIDGE_MANIFEST not in view['files'] and BRIDGE_SIGNATURE not in view['files']:
            return view, None, None, None
        if BRIDGE_MANIFEST not in view['files'] or BRIDGE_SIGNATURE not in view['files']:
            raise BundleError('Distribution seed has an incomplete signed bridge.')
        if (view['files'][BRIDGE_MANIFEST]['size'] > MAX_MANIFEST_BYTES
                or view['files'][BRIDGE_SIGNATURE]['size'] > MAX_SIGNATURE_BYTES):
            raise BundleError('Distribution bridge exceeds the manifest size limit.')
        raw = (directory / BRIDGE_MANIFEST).read_bytes()
        signature = (directory / BRIDGE_SIGNATURE).read_bytes()
        full = _parse_manifest(raw, signature, key, openssl)
        if full['schema'] != 2 or full['release'] != view['release']:
            raise BundleError('Distribution bridge release does not match the seed.')
        selected_records = {name: record for name, record in view['files'].items()
                            if name not in (BRIDGE_MANIFEST, BRIDGE_SIGNATURE)}
        _present_manifest(full, selected_records)
        if set(selected_records) != set(full['packages']['core']['files']):
            raise BundleError('Distribution seed must contain exactly its complete core package.')
    else:
        full, raw, signature = original, special['manifest.json'], special['manifest.sig']
    descriptor = _descriptor(full)
    descriptor['bundle'] = {'name': Path(source).name, 'size': Path(source).stat().st_size,
                            'sha256': _hash_file(source), 'manifest_digest': manifest_digest(view)}
    return full, raw, signature, descriptor


def describe_source(source, key, *, openssl='openssl'):
    """Return a trusted catalog-shaped descriptor, or None for a legacy bundle."""
    with tempfile.TemporaryDirectory(prefix='oxp3-distribution-inspect-') as temporary:
        return _source(Path(source), key, Path(temporary), openssl)[3]


source_catalog = describe_source


def _hash_file(path):
    digest = hashlib.sha256()
    with _regular_input(path, MAX_ARCHIVE_BYTES) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path, ref):
    return (not Path(path).is_symlink() and Path(path).stat().st_size == ref['size']
            and _hash_file(path) == ref['sha256'])


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not (asset_url(newurl) or _safe_transfer_url(newurl)):
            raise ReleaseError('Component download redirected outside trusted GitHub hosts.')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download(ref, target, opener=None, progress=None):
    if not asset_url(ref['url']):
        raise BundleError('Component asset URL is not allowed.')
    try:
        with _request(ref['url'], opener=opener, download=True, progress=progress) as response:
            final = response.geturl() if hasattr(response, 'geturl') else ref['url']
            if not (asset_url(final) or _safe_transfer_url(final)):
                raise ReleaseError('Component download ended outside trusted GitHub hosts.')
            count, digest = 0, hashlib.sha256()
            with target.open('xb') as output:
                while chunk := response.read(min(1024 * 1024, ref['size'] - count + 1)):
                    count += len(chunk)
                    if count > ref['size']:
                        raise BundleError('Component download exceeds its signed size.')
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress({'phase': 'downloading_component', 'received': count, 'total': ref['size']})
                output.flush()
                os.fsync(output.fileno())
            if count != ref['size'] or digest.hexdigest() != ref['sha256']:
                raise BundleError('Component download does not match its signed hash and size.')
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _write_archive(output, root, records, raw, signature):
    with output.open('xb') as file:
        with gzip.GzipFile(fileobj=file, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name, data in (('manifest.json', raw), ('manifest.sig', signature)):
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
                    archive.addfile(entry, io.BytesIO(data))
                for name, record in sorted(records.items()):
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = record['size'], record['mode'], 0
                    with (root / name).open('rb') as content:
                        archive.addfile(entry, content)


def materialize(source, selected, destination, key, *, catalog=None, cache=None,
                opener=None, progress=None, openssl='openssl'):
    """Build a selected sparse bundle. No privilege escalation or installation.

    Cached bytes are always hash checked and package files independently checked
    against the signed full manifest. The output is root-reverifiable offline.
    Existing selected groups are retained, so this also expands offline bundles.
    """
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise BundleError('Selected distribution output already exists.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if cache is not None:
        cache = Path(cache)
        if cache.is_symlink():
            raise BundleError('Distribution cache must not be a symlink.')
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.oxp3-materialize-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        root = staging / 'files'
        root.mkdir(mode=0o700)
        full, raw, signature, descriptor = _source(source, key, root, openssl)
        if descriptor is None:
            raise BundleError('Legacy bundle has no signed modular distribution manifest.')
        if catalog is not None:
            validate_index(catalog)
            for field in ('release', 'components', 'packages', 'component_packages', 'distribution_manifest_digest'):
                if catalog[field] != descriptor[field]:
                    raise BundleError('Capability catalog does not match this signed distribution.')
        entries = {item['id']: item for item in descriptor['components']}
        if not isinstance(selected, (list, tuple, set)) or any(not isinstance(item, str) for item in selected):
            raise BundleError('Component selection must contain component identifiers.')
        needed_components = set()
        def include(identifier):
            if identifier not in entries:
                raise BundleError('Unknown selected component: ' + identifier)
            if identifier in needed_components:
                return
            item = entries[identifier]
            if not item['available'] or item['delivery'] != 'maintenance':
                raise BundleError('Selected component is unavailable for maintenance: ' + identifier)
            needed_components.add(identifier)
            for dependency in item['dependencies']:
                include(dependency)
        for identifier in selected:
            include(identifier)
        needed = {'core'}
        for identifier in needed_components:
            needed.update(full['component_packages'][identifier])
        present_records = {name: full['files'][name] for name in full['files'] if (root / name).is_file()}
        present = set(_present_manifest(full, present_records)['present_packages'])
        needed.update(present)
        downloaded = []
        for identifier in sorted(needed - present):
            ref = descriptor['packages'][identifier]
            path = cache / (ref['sha256'] + '.tar.gz') if cache is not None else staging / ref['name']
            if path.exists() or path.is_symlink():
                if not _matches(path, ref):
                    raise BundleError('Cached component archive is corrupt or linked: ' + identifier)
            else:
                temporary_asset = staging / (identifier + '.download')
                _download(ref, temporary_asset, opener=opener, progress=progress)
                if cache is not None:
                    with path.open('xb') as output, temporary_asset.open('rb') as incoming:
                        shutil.copyfileobj(incoming, output, 1024 * 1024)
                    temporary_asset.unlink()
                else:
                    temporary_asset.rename(path)
                downloaded.append(identifier)
            expected = {name: full['files'][name] for name in full['packages'][identifier]['files']}
            with _open_archive(path) as stream:
                records, special = _scan(stream)
                if records != expected or special:
                    raise BundleError('Component archive membership differs from its signed package.')
                stream.seek(0)
                second, second_special = _scan(stream, root, expected)
                if second != expected or second_special:
                    raise BundleError('Component archive changed during extraction.')
            present_records.update(expected)
        staged = staging / 'selected.tar.gz'
        _write_archive(staged, root, present_records, raw, signature)
        manifest = inspect_bundle(staged, key, openssl=openssl)
        # Exclusive create avoids replacing an existing user artifact.
        created = False
        try:
            with destination.open('xb') as output, staged.open('rb') as incoming:
                created = True
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return {'path': str(destination.absolute()), 'manifest': manifest,
            'packages': sorted(needed), 'components': sorted(needed_components), 'downloaded': downloaded}
