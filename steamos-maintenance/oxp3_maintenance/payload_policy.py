"""Distribution policy for maintenance payloads, including legacy prepared data.

This module only reads build inputs and writes a fresh staging directory. It
never inspects or removes installed plugins; legacy adoption data remains in the
maintenance runtime for recognizing installations made by older releases.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile


REMOVED_PLUGIN_IDS = frozenset({
    'steamgriddb', 'protondb', 'tabmaster', 'css-loader', 'autoflatpaks',
    'deck-settings', 'hltb', 'animation-changer',
})
PAYLOAD_TREES = frozenset({'components', 'integration', 'plugins', 'waydroid',
                           'hdr', 'controls', 'licenses'})
PINNED_NTFS_METADATA = frozenset({
    'components/partition-mount/ntfs-tools-source.json',
    'components/partition-mount/tools/manifest.json',
})
PINNED_OPTI_METADATA = frozenset('components/opti2xmx/' + name for name in (
    'plugin.json', 'package.json', 'runtime-source.json', 'fsr-source.json',
    'fsr_compat/manifest.json', 'fsr_compat/sources/fsr_compat/dependency-source.json',
))


def distributable_path(relative):
    """Whether a payload path belongs to supported distributed resources.

    Match complete plugin IDs and their version/source-cache/license suffixes,
    not arbitrary substrings: e.g. ``my-protondb-tool`` is unrelated.
    """
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or ':' in relative or relative.startswith('/')
            or any(p in ('', '.', '..') for p in relative.split('/'))):
        raise ValueError('Unsafe payload path: ' + repr(relative))
    path = PurePosixPath(relative)
    for part in path.parts:
        name = part.casefold()
        if name.startswith('.') or name in {'cache', '__pycache__', 'node_modules'}:
            return False
        if any(name == plugin or name.startswith(tuple(plugin + x for x in ('-', '_', '.')))
               for plugin in REMOVED_PLUGIN_IDS):
            return False
    return True


def sanitize_options(options):
    """Return current options without retired plugins; reject dangling edges."""
    options = deepcopy(options)
    if not isinstance(options, dict) or options.get('schema') != 1:
        raise ValueError('Unsupported options schema')
    ids = set()
    for category in ('repairs', 'plugins'):
        values = options.get(category)
        if not isinstance(values, list) or any(not isinstance(x, dict) for x in values):
            raise ValueError('Missing component option category: ' + category)
        options[category] = [x for x in values if x.get('id') not in REMOVED_PLUGIN_IDS]
        for item in options[category]:
            name = item.get('id')
            if not isinstance(name, str) or name in ids:
                raise ValueError('Invalid or duplicate option ID')
            ids.add(name)
    for category in ('repairs', 'plugins'):
        for item in options[category]:
            dependencies = item.get('dependencies')
            if not isinstance(dependencies, list) or any(x not in ids for x in dependencies):
                raise ValueError('Unknown option dependency: ' + item['id'])
    return options


def sanitize_metadata(relative, value):
    """Remove retired records from JSON metadata without editing source code."""
    if relative in ('components/options.json', 'components/fulloptions.json'):
        return sanitize_options(value)

    def clean(item):
        if isinstance(item, list):
            return [clean(x) for x in item
                    if not (isinstance(x, dict) and
                            (x.get('id') in REMOVED_PLUGIN_IDS or x.get('component') in REMOVED_PLUGIN_IDS))
                    and not (isinstance(x, str) and x in REMOVED_PLUGIN_IDS)]
        if isinstance(item, dict):
            return {key: clean(val) for key, val in item.items()
                    if key not in REMOVED_PLUGIN_IDS
                    and ('/' not in key or distributable_path(key))}
        return item

    result = clean(value)
    if relative == 'components/preparation-report.json' and isinstance(result, dict):
        coverage = result.get('coverage', {})
        result['resource_complete'] = all(x.get('status') in ('adapter_supported', 'excluded')
                                          for x in coverage.values())
    return result


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def payload_json_bytes(relative, raw):
    """Preserve fixed build pins; fail if policy would change their contents."""
    parsed = json.loads(raw.decode('utf-8-sig'))
    sanitized = sanitize_metadata(relative, parsed)
    if relative in PINNED_NTFS_METADATA:
        if sanitized != parsed:
            raise ValueError('Excluded metadata in pinned NTFS provenance')
        return raw
    if relative in PINNED_OPTI_METADATA:
        if sanitized != parsed:
            raise ValueError('Excluded metadata in pinned Opti plugin resource')
        return raw
    return json_bytes(sanitized)


def _load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate payload JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def _check_path(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Linked payload input/output path refused: ' + str(path))
    return info


def sanitize_payload(source, destination):
    """Copy a prepared payload to a new directory, excluding retired plugins.

    Inputs are never modified. Only known payload trees are copied, so a stale
    cache/runtime sibling cannot enter a release. Existing/overlapping outputs,
    linked paths and special files are refused. The returned report describes
    copied and excluded paths; it is not an installation or migration plan.
    """
    source, destination = Path(source).absolute(), Path(destination).absolute()
    for path in (source, *source.parents, destination.parent, *destination.parent.parents):
        _check_path(path)
    source = source.resolve()
    if not source.is_dir():
        raise ValueError('Prepared payload source is not a directory')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Sanitized destination must be a new isolated directory')
    destination = destination.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Sanitized destination overlaps source')
    # A manifest can put retired component bytes outside a named plugin tree.
    excluded = set()
    manifest = source / 'integration/manifest.json'
    if manifest.is_file():
        _check_path(manifest)
        for name, record in _load_json(manifest).items():
            if name in REMOVED_PLUGIN_IDS:
                for entry in record.get('files', []):
                    relative = 'integration/' + entry['source']
                    distributable_path(relative)  # validate before adding
                    excluded.add(relative)
                if record.get('runtime_archive'):
                    relative = 'integration/' + record['runtime_archive']
                    distributable_path(relative)
                    excluded.add(relative)
    stage = Path(tempfile.mkdtemp(prefix='oxp3-sanitized-', dir=destination.parent))
    report = {'copied': [], 'excluded': []}
    try:
        for tree in sorted(PAYLOAD_TREES):
            root = source / tree
            if not root.exists():
                continue
            _check_path(root)
            for parent, directories, files in os.walk(root, followlinks=False):
                for name in directories:
                    _check_path(Path(parent) / name)
                directories[:] = sorted(d for d in directories
                    if distributable_path((Path(parent) / d).relative_to(source).as_posix()))
                for name in sorted(files):
                    path = Path(parent) / name
                    relative = path.relative_to(source).as_posix()
                    info = _check_path(path)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('Special or linked payload file refused: ' + relative)
                    if not distributable_path(relative) or relative in excluded:
                        report['excluded'].append(relative)
                        continue
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if path.suffix.lower() == '.json':
                        _load_json(path)  # Retain duplicate-key rejection.
                        target.write_bytes(payload_json_bytes(relative, path.read_bytes()))
                    else:
                        shutil.copyfile(path, target)
                    report['copied'].append(relative)
        preparation = stage / 'components/preparation-report.json'
        if preparation.is_file():
            metadata = _load_json(preparation)
            inventory = metadata.get('source_inventory', {})
            for relative in list(inventory):
                if not distributable_path(relative):
                    del inventory[relative]
                    continue
                target = stage / relative
                if not target.is_file():
                    del inventory[relative]
                    continue
                raw = target.read_bytes()
                inventory[relative].update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
            preparation.write_bytes(json_bytes(metadata))
        stage.rename(destination)
        return report
    except BaseException:
        shutil.rmtree(stage)
        raise
