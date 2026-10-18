"""Advisory per-component update identities, independent of project version."""
import hashlib
import json
from pathlib import Path
import re


def revisions(catalog):
    """Hash immutable package content and dependency requirements, not URLs/tags."""
    items = {item['id']: item for item in catalog['components']}
    packages = catalog['packages']
    mapping = catalog['component_packages']
    result, visiting = {}, set()

    def visit(name):
        if name in result:
            return result[name]
        if name in visiting or name not in items:
            raise ValueError('Unknown or cyclic update dependency')
        visiting.add(name)
        # Core also contains release metadata and application code. The builder
        # exposes a stable per-component revision for its core-owned resources.
        item = items[name]
        value = {'component': name, 'revision': item.get('revision'),
                 'packages': {group: packages[group]['sha256'] for group in mapping[name] if group != 'core'},
                 'dependencies': {dep: visit(dep) for dep in item['dependencies']}}
        if not value['revision'] and 'core' in mapping[name]:
            # Conservative fallback: never skip core updates when exact content
            # identity is unavailable. A project version isn't an install claim.
            value['core_release'] = catalog['release']['version']
        result[name] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        visiting.remove(name)
        return result[name]

    for name in items:
        visit(name)
    return result


def _receipt_matches(name, revision, slot, runtime):
    from .bundle import BundleError, _regular_input
    if (not isinstance(slot, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}', slot)
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)):
        return False
    path = Path(runtime) / 'component-receipts' / slot / (name + '.json')
    try:
        from .bootstrap import _protected
        _protected(path)
        with _regular_input(path, 4096, single_link=True) as stream:
            return json.load(stream) == {'component': name, 'revision': revision, 'slot': slot}
    except (BundleError, OSError, ValueError, RuntimeError):
        return False


def component_states(catalog, installed, slot=None, *, runtime=Path('/usr/local/lib/oxp3-maintenance')):
    """Current revision evidence only; this is not installation detection."""
    current = revisions(catalog)
    recorded = installed.get('component_revisions_by_slot', {}).get(slot, {})
    return {name: True if recorded.get(name) == revision and _receipt_matches(name, revision, slot, runtime)
            else None for name, revision in current.items()}


def available_updates(catalog, installed, slot=None):
    """Known older revisions need updates even while their files are installed."""
    recorded = installed.get('component_revisions_by_slot', {}).get(slot, {})
    return {name: recorded[name] != revision if name in recorded else None
            for name, revision in revisions(catalog).items()}


def needs_engine_bridge(installed, runtime=Path('/usr/local/lib/oxp3-maintenance')):
    """Read protected code presence, never import an older installed application."""
    runtime = Path(runtime)
    if not (runtime / 'entry.py').is_file():
        return False
    generation = installed.get('maintenance_runtime', installed.get('version', ''))
    if not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,159}', generation):
        return True
    module = runtime / 'releases' / generation / 'oxp3_maintenance/distribution.py'
    if not module.is_file():
        return True
    from .bootstrap import _protected
    _protected(module)
    return False
