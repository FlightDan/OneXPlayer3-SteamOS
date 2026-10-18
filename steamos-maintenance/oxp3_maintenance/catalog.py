"""Small signed capability index. Discovery never imports downloaded Python."""
import hashlib
import json
from pathlib import Path
import re

from .bundle import BundleError, _unique_object, _verify_signature
from .releases import _Version

MAX_CATALOG_BYTES = 1024 * 1024
MANUAL = {'refind', 'shared-storage'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def names(version):
    if _Version(version).text != version:
        raise BundleError('Invalid catalog version')
    prefix = 'oxp3-maintenance-' + version
    return prefix + '-catalog.json', prefix + '-catalog.sig'


def create(payload, manifest, archive):
    """Use the same payload and manifest as the signed installation bundle."""
    payload = Path(payload)
    options = json.loads((payload / 'components/options.json').read_text(encoding='utf-8-sig'))
    integration = json.loads((payload / 'integration/manifest.json').read_text(encoding='utf-8-sig'))
    entries = []
    for group in ('repairs', 'plugins'):
        for item in options[group]:
            metadata = integration.get(item['id'], {})
            entries.append({
                'id': item['id'], 'kind': group, 'zh': item.get('zh', item['id']),
                'en': item.get('en', item['id']), 'default': bool(item.get('default')),
                'dependencies': item.get('dependencies', []),
                'delivery': 'separate_operation' if item['id'] in MANUAL else 'maintenance',
                'available': item.get('available', True) and not bool(metadata.get('missing')),
                'packages': metadata.get('packages', {}),
                'missing': metadata.get('missing', []),
            })
    digest = hashlib.sha256()
    with Path(archive).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {'schema': 1, 'release': manifest['release'], 'components': entries,
            'bundle': {'name': Path(archive).name, 'size': Path(archive).stat().st_size,
                       'sha256': digest.hexdigest(),
                       'manifest_digest': hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}}


def verify(raw, signature, key, *, expected_version=None, openssl='openssl'):
    if len(raw) > MAX_CATALOG_BYTES or len(signature) > 256:
        raise BundleError('Capability catalog exceeds the size limit')
    _verify_signature(raw, signature, key, openssl)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        release, bundle, entries = value['release'], value['bundle'], value['components']
        version = _Version(release['version'])
        if (type(value['schema']) is not int or value['schema'] not in (1, 2) or version.text != release['version']
                or release.get('channel') not in ('stable', 'beta')
                or bool(version.pre) and (release['channel'] != 'beta' or version.pre[0] != 'beta')
                or expected_version is not None and version.text != expected_version
                or bundle['name'] != 'oxp3-maintenance-' + version.text + '-linux-x86_64.tar.gz'
                or type(bundle['size']) is not int or not 0 < bundle['size'] <= 1024 ** 3
                or any(not re.fullmatch('[0-9a-f]{64}', bundle[k]) for k in ('sha256', 'manifest_digest'))
                or not isinstance(entries, list) or not 0 < len(entries) <= 256):
            raise ValueError()
        seen = set()
        for item in entries:
            if (not isinstance(item, dict) or not re.fullmatch('[a-z][a-z0-9-]{0,79}', item['id'])
                    or item['id'] in seen or item['kind'] not in ('repairs', 'plugins')
                    or item['delivery'] not in ('maintenance', 'separate_operation')
                    or type(item['available']) is not bool
                    or not isinstance(item['dependencies'], list)
                    or any(not isinstance(x, str) for x in item['dependencies'])
                    or any(not isinstance(item[k], str) or len(item[k]) > 1024 for k in ('zh', 'en'))):
                raise ValueError()
            seen.add(item['id'])
        if any(set(item['dependencies']) - seen for item in entries):
            raise ValueError()
        # Even signed indexes must fail closed on cycles before closure expansion.
        graph = {item['id']: item['dependencies'] for item in entries}
        visiting, visited = set(), set()
        def visit(component):
            if component in visiting:
                raise ValueError()
            if component in visited:
                return
            visiting.add(component)
            for dependency in graph[component]:
                visit(dependency)
            visiting.remove(component)
            visited.add(component)
        for component in graph:
            visit(component)
        if value['schema'] == 2:
            from .distribution import validate_index
            validate_index(value)
        return value
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        raise BundleError('Signed capability catalog is malformed or has the wrong release') from error


def describe(value, system=None, installed=None):
    """Catalog support is advisory; a full live plan remains authoritative."""
    from .compatibility import evaluate
    items = []
    for item in value['components']:
        state = installed.get(item['id']) if isinstance(installed, dict) else None if installed is None else item['id'] in installed
        state = state if type(state) is bool else None
        category = item.get('kind') if item.get('kind') in ('repairs', 'plugins') else 'plugins'
        report = dict(item, installed=state, category=category)
        if item['delivery'] == 'separate_operation':
            report.update(status='separate_operation', reason='Use the separate installer/recovery tool')
        elif not item['available']:
            report.update(status='unavailable', reason='Payload is not available in this project release')
        elif system is None:
            report.update(status='download_available', reason='Run in SteamOS to check installation compatibility')
        else:
            compatibility = evaluate(item['id'], system)
            report.update(compatibility=compatibility, status='requires_preflight' if compatibility['supported'] else 'incompatible',
                          reason=compatibility['reason'])
        report['selected'] = (report['status'] in ('requires_preflight', 'download_available')
                              and category == 'repairs' and state is not True)
        items.append(report)
    items.sort(key=lambda item: item['category'] != 'repairs')
    result = {'schema': value.get('schema', 1), 'release': value['release'], 'components': items,
              'bundle': value['bundle'], 'installation_requires_live_preflight': True}
    if value.get('schema') == 2:
        for field in ('packages', 'component_packages', 'distribution_manifest_digest'):
            result[field] = value[field]
    return result
