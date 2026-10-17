"""Bounded, read-only installation evidence. This is never adoption authority.

Only protected project metadata supplies version/selection provenance. External
plugin manifests are observations, even when they claim familiar project names.
No executable, credential file, original snapshot or plugin module is loaded.
"""
from contextlib import contextmanager
import base64
import json
import os
from pathlib import Path
import re
import stat

from . import compatibility

MAX_ENTRIES = 128
MAX_JSON = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}\Z')
_KNOWN = compatibility.BASELINE | compatibility.PORTABLE
_PLUGIN_NAMES = {
    'SteamGridDB': 'steamgriddb', 'ProtonDB Badges': 'protondb', 'TabMaster': 'tabmaster',
    'CSS Loader': 'css-loader', 'AutoFlatpaks': 'autoflatpaks', 'Deck Settings': 'deck-settings',
    'HLTB for Deck': 'hltb', 'Animation Changer': 'animation-changer',
}


class InventoryError(RuntimeError):
    pass


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _protected(info):
    return info.st_uid == 0 and not info.st_mode & 0o022


def _parts(relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or '\x00' in relative or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise InventoryError('unsafe_path')
    return relative.split('/')


@contextmanager
def _directory(root, relative='', *, trusted=False):
    """Pin every POSIX directory descriptor; refuse links on every platform."""
    parts = _parts(relative) if relative else []
    for ancestor in root.parents:
        info = ancestor.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise InventoryError('unsafe_root_ancestor')
    root_info = root.lstat()
    if _linked(root_info) or not stat.S_ISDIR(root_info.st_mode):
        raise InventoryError('unsafe_root')
    protected = _protected(root_info)
    if os.name == 'posix':
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                info = os.fstat(descriptor)
                protected = protected and _protected(info)
            if trusted and not protected:
                raise InventoryError('untrusted_metadata')
            yield descriptor, protected
        finally:
            os.close(descriptor)
    else:
        current = root
        for part in parts:
            current /= part
            info = current.lstat()
            if _linked(info) or not stat.S_ISDIR(info.st_mode):
                raise InventoryError('unsafe_directory')
            protected = protected and _protected(info)
        if trusted and not protected:
            raise InventoryError('untrusted_metadata')
        yield current, protected


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError('duplicate_json_key')
        result[key] = value
    return result


def installed_components(report):
    """Only the validated current store establishes present installation.

    Protected legacy journals describe historical installation and backups;
    they may survive a later component restore and are not current authority.
    """
    return [name for name, item in report['components'].items()
            if item['state'] == 'managed']


class _Reader:
    def __init__(self, root):
        self.root, self.total = root, 0

    def read(self, relative, *, trusted=True, maximum=MAX_JSON):
        parts = _parts(relative)
        with _directory(self.root, '/'.join(parts[:-1]), trusted=trusted) as (parent, protected):
            if os.name == 'posix':
                descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            else:
                path = parent / parts[-1]
                if _linked(path.lstat()):
                    raise InventoryError('unsafe_file')
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise InventoryError('unsafe_file')
                protected = protected and _protected(info)
                if trusted and not protected:
                    raise InventoryError('untrusted_metadata')
                if info.st_size > maximum or self.total + info.st_size > MAX_TOTAL:
                    raise InventoryError('metadata_limit')
                raw = stream.read(min(maximum, MAX_TOTAL - self.total) + 1)
                self.total += len(raw)
                if len(raw) > maximum or self.total > MAX_TOTAL:
                    raise InventoryError('metadata_limit')
                after = os.fstat(stream.fileno())
                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise InventoryError('metadata_changed')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise InventoryError('invalid_metadata')
        return value, protected

    def entries(self, relative, *, trusted=True):
        with _directory(self.root, relative, trusted=trusted) as (directory, protected):
            # scandir streams instead of allocating an unbounded directory list.
            with os.scandir(directory) as entries:
                names = []
                for entry in entries:
                    if len(names) >= MAX_ENTRIES:
                        raise InventoryError('entry_limit')
                    names.append(entry.name)
        return sorted(names), protected


def _error(exc):
    if isinstance(exc, PermissionError):
        return 'unreadable_metadata'
    if isinstance(exc, InventoryError):
        return str(exc)
    return 'invalid_or_unsafe_metadata'


_ERRORS = (OSError, InventoryError, ValueError, TypeError, RecursionError)


def _release(value):
    if not isinstance(value, dict):
        raise InventoryError('invalid_release')
    version = value.get('version')
    if not isinstance(version, str) or not 0 < len(version) <= 128 or any(ord(c) < 32 for c in version):
        raise InventoryError('invalid_release')
    result = {'version': version}
    for key in ('display_version', 'channel', 'product'):
        item = value.get(key)
        if isinstance(item, str):
            result[key] = item[:256]
    return result


def _choices(value):
    if not isinstance(value, dict):
        raise InventoryError('invalid_selection')
    choices = []
    for key in ('repairs', 'plugins'):
        group = value.get(key, [])
        if not isinstance(group, list) or len(group) > MAX_ENTRIES:
            raise InventoryError('invalid_selection')
        if any(not isinstance(name, str) or not _ID.fullmatch(name) for name in group):
            raise InventoryError('invalid_selection')
        choices.extend(group)
    return sorted(set(choices))


def _backup_complete(value):
    if value.get('phase') != 'installed':
        raise InventoryError('legacy_recovery_required')
    allowed = value.get('allowed')
    originals, applied = value.get('original'), value.get('applied')
    if (not isinstance(allowed, list) or not 0 < len(allowed) <= 12000
            or not isinstance(originals, dict) or not isinstance(applied, dict)):
        raise InventoryError('missing_legacy_originals')
    if len(set(allowed)) != len(allowed) or set(allowed) != set(originals) or set(allowed) != set(applied):
        raise InventoryError('incomplete_legacy_originals')
    for relative in allowed:
        _parts(relative)
        original = originals[relative]
        if not isinstance(original, dict) or type(original.get('exists')) is not bool:
            raise InventoryError('invalid_legacy_originals')
        if original['exists']:
            for key in ('mode', 'uid', 'gid'):
                if type(original.get(key)) is not int or original[key] < 0:
                    raise InventoryError('invalid_legacy_originals')
            if original['mode'] > 0o7777:
                raise InventoryError('invalid_legacy_originals')
            base64.b64decode(original['data'], validate=True)
        base64.b64decode(applied[relative], validate=True)
    return len(allowed)


def inspect(root, system, managed=None):
    """Report sanitized evidence without modifying state or adopting ownership.

    ``managed`` must come from the caller's validated Store.managed() result.
    ``legacy_with_backups`` describes complete protected file journals only;
    adoption must additionally check live files, metadata and runtime backups.
    """
    root = Path(os.path.abspath(root))
    reader = _Reader(root)
    active = system.get('slot', {}).get('label')
    slot_id = system.get('slot', {}).get('id')
    result = {'schema': 1, 'release': None, 'maintenance_release': None, 'installer_release': None,
              'selected': [], 'components': {}, 'slots': {}, 'unknown_journals': [],
              'conflicts': [], 'observed_plugins': [], 'observed_decky': [], 'evidence_only': True}
    for name in sorted(_KNOWN):
        result['components'][name] = {'state': 'absent', 'selected': False, 'sources': [], 'conflicts': []}

    def conflict(source, reason, component=None):
        record = {'source': source, 'reason': reason}
        if component is not None:
            record['component'] = component
            result['components'].setdefault(component, {'state': 'absent', 'selected': False, 'sources': [], 'conflicts': []})['conflicts'].append(reason)
        result['conflicts'].append(record)

    def load(relative, *, maximum=MAX_JSON, trusted=True):
        try:
            return reader.read(relative, trusted=trusted, maximum=maximum)
        except FileNotFoundError:
            return None
        except _ERRORS as exc:
            conflict(relative, _error(exc))
            return None

    for key, relative in (
            ('maintenance_release', 'usr/local/lib/oxp3-maintenance/current-release.json'),
            ('installer_release', 'usr/local/lib/oxp3-integration/release.json')):
        loaded = load(relative, maximum=64 * 1024)
        if loaded:
            try:
                result[key] = dict(_release(loaded[0]), source=relative, trust='protected_project_metadata')
            except _ERRORS as exc:
                conflict(relative, _error(exc))
    result['release'] = result['maintenance_release'] or result['installer_release']
    selected = set()
    legacy = {}
    for group in ('A', 'B', 'shared'):
        base = 'home/.oxp3-installer/integration/' + group
        slot = {'selected': [], 'release': None}
        result['slots'][group] = slot
        if group != 'shared':
            request_choices = None
            for filename in ('request.json', 'result.json'):
                relative = base + '/' + filename
                loaded = load(relative, maximum=2 * 1024 * 1024)
                if not loaded:
                    continue
                value = loaded[0]
                try:
                    if filename == 'result.json' and value.get('slot', group) != group:
                        raise InventoryError('legacy_slot_mismatch')
                    choices = _choices(value if filename == 'request.json' else value.get('options', {}))
                    if filename == 'request.json':
                        request_choices = choices
                    elif request_choices is not None and choices != request_choices:
                        raise InventoryError('legacy_selection_mismatch')
                    slot['selected'] = sorted(set(slot['selected']) | set(choices))
                    if group == active:
                        selected.update(choices)
                    if filename == 'result.json':
                        if 'release' in value:
                            slot['release'] = dict(_release(value['release']), source=relative, trust='protected_project_metadata')
                        reports = value.get('components', {})
                        if not isinstance(reports, dict) or len(reports) > MAX_ENTRIES:
                            raise InventoryError('invalid_component_report')
                        if group == active:
                            for name, report in reports.items():
                                if _ID.fullmatch(name) and isinstance(report, dict) and report.get('status') == 'files_installed':
                                    legacy.setdefault(name, []).append({'source': relative, 'backups': False})
                except _ERRORS as exc:
                    conflict(relative, _error(exc))
        try:
            names, _ = reader.entries(base)
        except FileNotFoundError:
            continue
        except _ERRORS as exc:
            conflict(base, _error(exc))
            continue
        for name in names:
            if name in ('request.json', 'result.json', 'target-disk.json', 'lock'):
                continue
            if not _ID.fullmatch(name):
                conflict(base, 'unsafe_journal_name')
                continue
            relative = base + '/' + name + '/state.json'
            loaded = load(relative)
            if not loaded:
                continue
            if name not in _KNOWN:
                result['unknown_journals'].append({'component': name, 'source': relative, 'slot': group})
                continue
            if group not in (active, 'shared'):
                continue
            value = loaded[0]
            if value.get('phase') == 'rolled_back':
                continue
            evidence = {'source': relative, 'backups': False}
            try:
                evidence.update(backups=True, file_count=_backup_complete(value))
            except (KeyError, *_ERRORS) as exc:
                conflict(relative, _error(exc), name)
            legacy.setdefault(name, []).append(evidence)
    for name, evidence in legacy.items():
        entry = result['components'].setdefault(name, {'state': 'absent', 'selected': False, 'sources': [], 'conflicts': []})
        journals = [item for item in evidence if item['source'].endswith('/state.json')]
        entry['state'] = 'legacy_with_backups' if journals and all(item['backups'] for item in journals) else 'unmanaged'
        entry['sources'].extend(item['source'] for item in evidence)
        entry['adoption_verified'] = False
    for name, record in (managed or {}).get('components', {}).items():
        if not isinstance(name, str) or not _ID.fullmatch(name) or not isinstance(record, dict):
            continue
        if slot_id not in record.get('slots', []):
            continue
        entry = result['components'].setdefault(name, {'state': 'absent', 'selected': False, 'sources': [], 'conflicts': []})
        entry.update(state='managed')
        entry['sources'].append('validated_maintenance_store')
        selected.add(name)
    for relative in ('home/deck/homebrew/services/PluginLoader',
                     'var/lib/oxp3-installer/decky/runtime/services/PluginLoader',
                     'etc/systemd/system/plugin_loader.service'):
        try:
            parts = _parts(relative)
            with _directory(root, '/'.join(parts[:-1])) as (parent, protected):
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False) if os.name == 'posix' else (parent / parts[-1]).lstat()
                if _linked(info) or not stat.S_ISREG(info.st_mode):
                    raise InventoryError('unsafe_file')
                result['observed_decky'].append({'source': relative, 'trust': 'observed_only',
                                                 'protected': bool(protected and _protected(info))})
        except FileNotFoundError:
            continue
        except _ERRORS as exc:
            conflict(relative, _error(exc), 'decky')
    if result['observed_decky'] and result['components']['decky']['state'] == 'absent':
        result['components']['decky']['state'] = 'unmanaged'
    for base in ('home/deck/homebrew/plugins', 'var/lib/oxp3-installer/decky/runtime/plugins'):
        try:
            names, _ = reader.entries(base, trusted=False)
        except FileNotFoundError:
            continue
        except _ERRORS as exc:
            conflict(base, _error(exc))
            continue
        for folder in names:
            if not _ID.fullmatch(folder):
                conflict(base, 'unsafe_plugin_folder')
                continue
            source = base + '/' + folder
            manifests = {}
            protected = True
            for filename in ('plugin.json', 'package.json'):
                loaded = load(source + '/' + filename, maximum=128 * 1024, trusted=False)
                if loaded:
                    manifests[filename] = loaded[0]
                    protected = protected and loaded[1]
            if not manifests:
                continue
            plugin, package = manifests.get('plugin.json', {}), manifests.get('package.json', {})
            name, version = plugin.get('name'), package.get('version')
            observation = {'source': source, 'trust': 'observed_only' if protected else 'untrusted_observed_only'}
            if isinstance(name, str):
                observation['name'] = name[:256]
            if isinstance(version, str):
                observation['version'] = version[:128]
            component = _PLUGIN_NAMES.get(name) if isinstance(name, str) else None
            if component:
                observation['claimed_component'] = component
                entry = result['components'][component]
                if entry['state'] == 'absent':
                    entry['state'] = 'unmanaged'
                entry['sources'].append(source)
            result['observed_plugins'].append(observation)
    result['selected'] = sorted(selected)
    for name in selected:
        result['components'].setdefault(name, {'state': 'absent', 'sources': [], 'conflicts': []})['selected'] = True
    result['complete'] = not result['conflicts']
    for entry in result['components'].values():
        if entry['state'] == 'absent':
            entry['absence_verified'] = result['complete']
    return result
