"""Live orchestration around pure plans and recoverable file generations."""
from contextlib import contextmanager
import base64
import json
import hashlib
import os
from pathlib import Path
import re
import stat
import shutil
import subprocess
import tempfile
import uuid

from . import adoption, probe
from .bundle import verify_bundle, verify_directory
from .components import build_plan
from .transactions import Store
from .packages import PackageStore
from .compatibility import device_supported, evaluate

STATE = Path('/home/.oxp3-maintenance')
RUNTIME = Path('/usr/local/lib/oxp3-maintenance')
UNIT = re.compile(r'[A-Za-z0-9_.@-]+\.service\Z')
BOOT_COMPONENTS = {'input', 'multifunction', 'gyro', 'hdr', 'desktop-hdr',
                   'keyboard', 'gamescope-env', 'wifi', 'xe-dsb', 'gm7-resume', 'split-lock', 'serial-console-policy', 'fan-driver'}


def command(*args, check=True):
    value = subprocess.run(args, capture_output=True, text=True, timeout=180,
                           env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C', 'LANG': 'C.UTF-8'})
    if check and value.returncode:
        raise RuntimeError('Command failed: ' + args[0] + ': ' + value.stderr.strip()[:1000])
    return value.stdout.strip()


def require_root():
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Use the desktop launcher or pkexec to authorize this operation')


def trusted_code(directory=None):
    directory = Path(directory or Path(__file__).resolve().parent.parent)
    for path in (directory, *directory.parents):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('The privileged backend must run from its installed root-owned directory')
    for path in directory.rglob('*'):
        info = path.lstat()
        if path.is_symlink() or info.st_uid or info.st_mode & 0o022:
            raise RuntimeError('Untrusted installed application file: ' + str(path))


@contextmanager
def authenticated(args):
    """Never import from an update. Re-verify within a private staging tree."""
    key = Path(__file__).resolve().parent.parent / 'trusted-public-key.pem'
    with tempfile.TemporaryDirectory(prefix='oxp3-verified-') as temporary:
        destination = Path(temporary) / 'bundle'
        destination.mkdir(mode=0o700)
        if args.bundle:
            # Copy untrusted bytes before verification, avoiding cache races.
            source = Path(args.bundle)
            archive = Path(temporary) / 'download.tar.gz'
            descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 ** 3:
                os.close(descriptor)
                raise RuntimeError('Invalid update archive')
            with os.fdopen(descriptor, 'rb') as incoming, archive.open('xb') as outgoing:
                copied = 0
                while chunk := incoming.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > 1024 ** 3:
                        raise RuntimeError('Update archive is too large')
                    outgoing.write(chunk)
            manifest = verify_bundle(archive, key, destination)
        elif args.bundle_dir:
            manifest = verify_directory(Path(args.bundle_dir), key, destination)
        else:
            raise RuntimeError('Choose a signed project maintenance package first')
        if getattr(args, 'expected_version', None) and manifest['release']['version'] != args.expected_version:
            raise RuntimeError('Signed project version does not match the advertised update')
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if getattr(args, 'expected_manifest', None) and digest != args.expected_manifest:
            raise RuntimeError('The maintenance package changed after review; review it again')
        manifest['_review_digest'] = digest
        yield destination, manifest


def store_for(system):
    return Store(Path('/'), STATE, uid=system['uid'], gid=system['gid'])


def current_selection(system, store):
    current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
    if current is not None:
        actual = [name for name in current['selected'] if name != '_maintenance']
        if 'legacy_selected' in current:
            legacy = Store._legacy_choices(current['legacy_selected'])
        else:
            # Migrate generations created before legacy selection was tracked.
            # An explicit empty list is a durable tombstone after adoption or
            # restore and must never be repopulated from an old request.
            adopted = set(Store._legacy_choices(current.get('legacy_adopted', [])))
            legacy = [name for name in (_legacy_request_selection(system) or []) if name not in adopted]
        return list(dict.fromkeys(actual + legacy))
    return _legacy_request_selection(system)


def _legacy_request_selection(system):
    label = system['slot'].get('label')
    if label in ('A', 'B'):
        request = STATE.parent / '.oxp3-installer/integration' / label / 'request.json'
        if os.path.lexists(request):
            adoption._trusted(request, STATE.parent)
            value = json.loads(request.read_text())
            if not isinstance(value, dict):
                raise ValueError('Invalid legacy component request')
            choices = value.get('repairs', []) + value.get('plugins', [])
            return Store._legacy_choices(choices)
    return None


def summarize(plan, release, system):
    return {'schema': 1, 'release': release, 'slot': system['slot'],
            'project_updates_only': True, 'selected': plan['selected'],
            'components': plan['components'], 'retained': plan.get('retained', {}),
            'legacy_selected': plan.get('legacy_selected'),
            'file_count': len(plan['files']),
            'restore_groups': plan.get('restore_groups', []),
            'can_apply': all(v['status'] in ('ready', 'not_applicable')
                             for v in plan['components'].values()),
            'restart_required': any(v.get('restart_required') and v['status'] == 'ready'
                                    for v in plan['components'].values())}


def require_plan_packages(manifest, plan):
    """A sparse bundle is never authority to omit a selected dependency."""
    if not plan['selected']:
        return
    if manifest.get('schema') != 2:
        if 'payload/components/distribution-manifest.json' in manifest.get('files', {}):
            raise RuntimeError('Download selected component packages before applying the core maintenance entry')
        return
    present = set(manifest['present_packages'])
    for name in plan['selected']:
        required = manifest['component_packages'].get(name)
        if required is None or not set(required) <= present:
            raise RuntimeError('Selected component package is missing: ' + name)


def prepare(payload, selected, system, store, *, tool_only=False, selected_only=False):
    # A user-cache plan is never authoritative. Recompute under Store.lock().
    package_store = PackageStore(STATE, system['slot']['id'], command)
    package_record = package_store._read()
    system['verified_slot_only_packages'] = []
    if not tool_only and package_record is not None and package_record['phase'] == 'installed':
        package_store._verify_installed(package_record)
        system['verified_slot_only_packages'] = [item['name'] for item in package_record['packages']
                                                 if not item['original_installed']]
    system['shared_compatible'] = False if tool_only else probe.verify_shared(system)
    system['shared_os_compatible'] = probe.verify_shared_os(system)
    system['transactional_packages'] = True
    if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected) or len(set(selected)) != len(selected):
        raise ValueError('Expected unique component choices')
    from .payload_policy import REMOVED_PLUGIN_IDS
    if set(selected) & REMOVED_PLUGIN_IDS:
        raise ValueError('Third-party plugins are installed by the user; maintenance leaves them unchanged')
    retained = {}
    prior_known = True
    try:
        prior = current_selection(system, store) or []
        if not isinstance(prior, list) or any(not isinstance(name, str) for name in prior):
            raise ValueError('Invalid legacy component selection')
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        prior = []
        prior_known = False
        retained['_legacy_selection'] = 'Kept unchanged; legacy selection is unreadable or invalid: ' + str(error)[:1000]
    managed = store.managed()
    slot = system['slot']['id']
    migrated = {name for name, item in managed['components'].items() if slot in item.get('slots', [])}
    status = store.status()
    generation = status.get('slots', {}).get(slot, {}).get('current') if isinstance(status, dict) else None
    if generation is not None:
        migrated.update(Store._legacy_choices(generation.get('legacy_adopted', [])))
    if tool_only:
        retained.update({name: 'Kept unchanged; only the maintenance engine is being updated' for name in prior})
        return {'selected': [], 'components': {}, 'files': {}, 'retained': retained,
                'legacy_selected': sorted(set(prior) - migrated) if prior_known else None}, {}
    catalog = json.loads((Path(payload) / 'components/options.json').read_text(encoding='utf-8-sig'))
    items = {}
    for item in catalog['repairs'] + catalog['plugins']:
        name = item['id']
        if name in REMOVED_PLUGIN_IDS:
            continue
        if name in items or not isinstance(item.get('dependencies'), list) or any(not isinstance(value, str) for value in item['dependencies']):
            raise ValueError('Invalid or duplicate component catalog entry')
        items[name] = item
    manual = {'slot-switch', 'refind', 'shared-storage'}
    explicit = set(selected)
    automatic = []
    for name in prior:
        if name in explicit:
            continue
        if selected_only:
            retained[name] = 'Kept unchanged; outside the selected update scope'
        elif name in manual:
            retained[name] = 'Kept unchanged; this component requires a separate installer/recovery operation'
        elif name not in items:
            retained[name] = 'Kept unchanged; component is absent from this release catalog'
        elif not items[name].get('available', True):
            retained[name] = 'Kept unchanged; component payload is unavailable in this release'
        elif not evaluate(name, system)['supported']:
            retained[name] = 'Kept unchanged; ' + evaluate(name, system)['reason']
        else:
            automatic.append(name)
    managed['paths'] = {path: item for path, item in managed['paths'].items()
                        if item.get('scope') == 'shared' or slot in item.get('slots', [])}
    imported, import_errors = {}, {}

    def closure(name, visiting=None):
        visiting = set() if visiting is None else visiting
        if name in manual:
            raise ValueError('Requires a separate installer/recovery operation: ' + name)
        if name not in items or name in visiting:
            raise ValueError('Unknown or cyclic component dependency: ' + name)
        order = []
        for dependency in items[name]['dependencies']:
            for value in closure(dependency, visiting | {name}):
                if value not in order:
                    order.append(value)
        return order + [name]

    def make_plan(roots):
        valid, graph_errors, order = [], {}, []
        for name in roots:
            try:
                dependencies = closure(name)
                valid.append(name)
                order.extend(value for value in dependencies if value not in order)
            except ValueError as error:
                graph_errors[name] = str(error)
                if name not in order:
                    order.append(name)
        for name in order:
            if name in migrated or name in imported or name in import_errors or name in graph_errors:
                continue
            try:
                imported[name] = adoption.validate_current('/', adoption.import_originals('/', system, [name]), system)
            except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
                import_errors[name] = 'Legacy adoption requires review: ' + str(error)[:1000]
        owned = dict(managed, paths=dict(managed['paths']))
        for name in order:
            for path, record in imported.get(name, {}).items():
                existing = owned['paths'].get(path)
                if existing is not None and existing.get('component') != record['component']:
                    import_errors[name] = 'Legacy adoption overlaps another component: ' + path
                else:
                    owned['paths'].setdefault(path, {'component': record['component']})
        plan = build_plan(payload, Path('/'), valid, system, owned)
        for name, reason in graph_errors.items():
            plan['components'][name] = {'status': 'blocked', 'reason': reason,
                'dependencies': list(items.get(name, {}).get('dependencies', [])), 'units': [],
                'restart_required': False, 'compatibility': evaluate(name, system)}
        plan['selected'] = order
        blocked = set(graph_errors)
        for name in order:
            report = plan['components'][name]
            reason = import_errors.get(name)
            if not reason and set(report['dependencies']) & blocked:
                reason = 'Dependency is blocked or requires legacy adoption review'
            if reason:
                report.update(status='blocked', reason=reason, units=[])
            if report['status'] == 'blocked':
                blocked.add(name)
        plan['files'] = {path: value for path, value in plan['files'].items() if value['component'] not in blocked}
        originals = {}
        for name in order:
            if name not in blocked:
                for path, record in imported.get(name, {}).items():
                    if path in originals:
                        raise RuntimeError('Overlapping legacy component ownership: ' + path)
                    originals[path] = record
        return plan, originals

    plan, original = make_plan(automatic + selected)
    failed = {name for name in automatic if plan['components'][name]['status'] == 'blocked'}
    if failed:
        for name in failed:
            retained[name] = 'Kept unchanged; ' + plan['components'][name]['reason']
        # Rebuild without optional failed roots, dropping their unused payloads.
        plan, original = make_plan([name for name in automatic if name not in failed] + selected)
    plan['retained'] = retained
    for name in plan['selected']:
        retained.pop(name, None)
    plan['legacy_selected'] = sorted(set(prior) - migrated - set(plan['selected'])) if prior_known else None
    return plan, original


def check_space(files):
    """Reserve journal, staging and replacement space before changing services."""
    size = sum(len(item['data']) for item in files.values())
    current = STATE / 'index.json'
    journal_size = current.stat().st_size if current.exists() else 0
    required = size * 10 + journal_size * 3 + 64 * 1024 * 1024
    if shutil.disk_usage(STATE).free < required:
        raise RuntimeError('Not enough shared-home space for update backups and recovery; need ' + str(required // (1024 ** 2)) + ' MiB free')
    devices = {}
    for relative, item in files.items():
        parent = (Path('/') / relative).parent
        while not parent.exists():
            parent = parent.parent
        device = parent.stat().st_dev
        entry = devices.setdefault(device, [parent, 0])
        entry[1] += len(item['data']) * 2
    for path, needed in devices.values():
        if shutil.disk_usage(path).free < needed + 16 * 1024 * 1024:
            raise RuntimeError('Not enough free space on target filesystem: ' + str(path))


def _save_private(path, value):
    data = (json.dumps(value, sort_keys=True) + '\n').encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    temporary = path.with_name('.live-' + uuid.uuid4().hex)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _unit_state(units):
    if any(not UNIT.fullmatch(unit) for unit in units):
        raise RuntimeError('Invalid component service name')
    return {unit: {'active': command('systemctl', 'is-active', unit, check=False) == 'active',
                   'enabled': command('systemctl', 'is-enabled', unit, check=False)}
            for unit in sorted(set(units))}


def _service_history(store, system, units, *, remember=False):
    slot = system['slot']['id']
    originals_path = STATE / ('service-originals-' + slot + '.json')
    history_path = STATE / ('service-generations-' + slot + '.json')
    originals = json.loads(originals_path.read_text()) if originals_path.exists() else {}
    history = json.loads(history_path.read_text()) if history_path.exists() else {}
    if remember:
        current = store.status()['slots'].get(slot, {}).get('current')
        values = _unit_state(units)
        for unit, value in values.items():
            originals.setdefault(unit, value)
        if current:
            existing = history.setdefault(str(current['id']), {})
            existing.update(values)
        _save_private(originals_path, originals)
        _save_private(history_path, history)
    return originals, history


def _file_intent(store, system, live, action, components, *, package_operation=False):
    current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
    live.update(file_action=action, file_components=list(components),
                source_generation=current['id'] if current else None,
                file_generation=store._index()['next_generation'],
                package_operation=package_operation)
    _save_private(STATE / 'live-operation.json', live)


def _generation(store, system):
    current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
    return current['id'] if current else None


def _abort_apply(store, system, components):
    current = store.status()['slots'][system['slot']['id']]
    if current['previous'] is None:
        return store.restore(system['slot']['id'], components)
    return store.rollback(system['slot']['id'])


def _managed_gyro_binding(store, slot):
    """Recognize only the immutable, installed recovery-aware gyro adapter."""
    if store is None:
        return False
    generation = store._index()['slots'].get(slot, {}).get('current')
    paths = generation.get('paths', {}) if generation else {}
    helper = 'var/lib/oxp3-gyro-v1/binding.py'
    if helper not in paths:
        return False  # Legacy gyro must never run its global rmmod stop here.
    required = (helper, 'var/lib/oxp3-gyro-v1/load.sh',
                'var/lib/oxp3-gyro-v1/unload.sh', 'etc/systemd/system/oxp3-gyro.service')
    for relative in required:
        entry = paths.get(relative, {})
        snapshot = entry.get('snapshot', {})
        if (entry.get('component') != 'gyro' or entry.get('user') or entry.get('mutable')
                or not snapshot.get('exists') or snapshot.get('uid') != 0
                or snapshot.get('mode', 0) & 0o7022
                or store._read(relative, user=False) != snapshot):
            raise RuntimeError('Managed gyro binding files changed; recover them before replacing the gyro')
    wrapper = b'#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py stop\n'
    if paths[required[2]]['snapshot']['data'] != base64.b64encode(wrapper).decode('ascii'):
        raise RuntimeError('Managed gyro stop wrapper is not the recovery-aware adapter')
    return True


def _quiesce_gyro_binding(store, record):
    if not _managed_gyro_binding(store, record['slot']):
        raise RuntimeError('Cannot safely finish the interrupted gyro binding stop')
    record['gyro_binding_stopped'] = True
    _save_private(STATE / 'live-operation.json', record)
    command('/usr/bin/python3', '-I', '-B', '/var/lib/oxp3-gyro-v1/binding.py', 'stop')
    # Explicit stop also turns a still-active oneshot inactive. Merely starting
    # an already-active unit during recover would not execute its loader again.
    command('systemctl', 'stop', 'oxp3-gyro.service')
    record['gyro_binding_quiesced'] = True
    _save_private(STATE / 'live-operation.json', record)


def _restore_lifecycle(record, *, restore_enabled=True, restart=True, store=None):
    try:
        command('systemctl', 'daemon-reload')
        for unit, previous in record.get('services', {}).items():
            if not UNIT.fullmatch(unit):
                raise RuntimeError('Invalid recorded service name')
            if restore_enabled:
                if previous['enabled'] in ('enabled', 'enabled-runtime'):
                    command('systemctl', 'enable', unit, check=False)
                else:
                    command('systemctl', 'disable', unit, check=False)
            if restart and previous['active'] and command('systemctl', 'show', unit, '-p', 'LoadState', '--value', check=False) not in ('', 'not-found'):
                if (unit == 'oxp3-gyro.service' and record.get('gyro_binding_stopped')
                        and not _managed_gyro_binding(store, record['slot'])):
                    continue  # A restored legacy loader cannot safely rebind the stock device.
                command('systemctl', 'start', unit)
    finally:
        if record['readonly'] == 'enabled':
            command('steamos-readonly', 'enable')


@contextmanager
def live_write(store, system, units):
    path = STATE / 'live-operation.json'
    if path.exists():
        raise RuntimeError('An interrupted service operation needs recover before another write')
    readonly = command('steamos-readonly', 'status').strip().lower()
    if readonly not in ('enabled', 'disabled'):
        raise RuntimeError('Cannot determine the root filesystem protection state')
    record = {'slot': system['slot']['id'], 'readonly': readonly, 'phase': 'writing',
              'services': _unit_state(units)}
    _save_private(path, record)
    succeeded = False
    try:
        if readonly == 'enabled':
            command('steamos-readonly', 'disable')
        if 'oxp3-gyro.service' in record['services'] and _managed_gyro_binding(store, system['slot']['id']):
            # Stop while the verified helper/wrappers still exist, including a
            # failed service whose ExecStopPost left a recoverable binding.
            _quiesce_gyro_binding(store, record)
        # Input/display and module changes always wait for reboot. Restarting
        # the user's controlling input device mid-dialog is deliberately avoided.
        for unit, previous in record['services'].items():
            if previous['active'] and unit not in ('inputplumber.service', 'oxp3-gyro.service', 'oxp3-fan-module.service'):
                command('systemctl', 'stop', unit)
        yield record
        # Service guards can now read this durable marker without acquiring the
        # operation lock held by their parent systemctl caller.
        record['phase'] = 'coherent'
        _save_private(path, record)
        succeeded = True
    finally:
        try:
            if succeeded and record.get('after_services') is not None:
                record['services'] = record['after_services']
            _restore_lifecycle(record, restore_enabled=not succeeded or 'after_services' in record,
                               restart=succeeded, store=store)
        except Exception:
            # Keep the record so recover can retry after the next boot.
            raise
        else:
            if succeeded:
                path.unlink()


def runtime_files(app, release, plan, *, installed_runtime=None):
    # Offline image preparation must read the target image, never the host.
    installed_runtime = Path(installed_runtime) if installed_runtime is not None else RUNTIME
    version = release['version']
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,79}', version):
        raise RuntimeError('Invalid project version')
    app = Path(app)

    def snapshot(directory, *, installed=False):
        """Snapshot regular source bytes once; never follow runtime links."""
        info = directory.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                or not stat.S_ISDIR(info.st_mode)):
            raise RuntimeError('Unsafe maintenance runtime directory')
        if installed:
            adoption._trusted(directory, Path('/'), directory=True)
        output = {}
        for parent, directories, filenames in os.walk(directory, followlinks=False):
            for name in directories + filenames:
                source = Path(parent) / name
                info = source.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise RuntimeError('Unsafe maintenance runtime source link')
                is_directory = stat.S_ISDIR(info.st_mode)
                if not is_directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    raise RuntimeError('Unsafe maintenance runtime source file')
                if installed:
                    adoption._trusted(source, Path('/'), directory=is_directory)
                if not is_directory:
                    relative = source.relative_to(directory).as_posix()
                    if any(part in ('', '.', '..') for part in relative.split('/')) or '\\' in relative or ':' in relative:
                        raise RuntimeError('Invalid maintenance runtime source path')
                    output[relative] = source.read_bytes()
        return output

    content = snapshot(app)
    if 'entry.py' not in content or 'OXP3-Maintenance.desktop' not in content:
        raise RuntimeError('Maintenance runtime is missing its entry or desktop launcher')
    digest = hashlib.sha256()
    for relative, data in sorted(content.items()):
        name = relative.encode('utf-8')
        digest.update(len(name).to_bytes(8, 'big'))
        digest.update(name)
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    runtime_name = version + '-' + digest.hexdigest()
    runtime_prefix = 'usr/local/lib/oxp3-maintenance/releases/'
    prefix = runtime_prefix + runtime_name
    files = {}
    prior_release = {}
    public_release = installed_runtime / 'current-release.json'
    if public_release.is_file():
        adoption._trusted(public_release, Path('/'))
        prior_release = json.loads(public_release.read_text())
        prior = prior_release.get('maintenance_runtime', prior_release['version'])
        if not isinstance(prior, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,159}', prior):
            raise RuntimeError('Invalid installed maintenance runtime name')
        prior_root = installed_runtime / 'releases' / prior
        previous_content = snapshot(prior_root, installed=True)
        if prior == runtime_name and previous_content != content:
            raise RuntimeError('Installed maintenance runtime does not match its content generation')
        for relative, data in sorted(previous_content.items()):
            files[runtime_prefix + prior + '/' + relative] = {
                'data': data, 'mode': 0o644, 'component': '_maintenance', 'user': False}
    for relative, data in sorted(content.items()):
        files[prefix + '/' + relative] = {'data': data, 'mode': 0o644,
                                         'component': '_maintenance', 'user': False}
    # Fixed root-owned entry; changing generations is the final atomic file write.
    wrapper = ('#!/usr/bin/python3\nimport runpy\n'
               'runpy.run_path(' + repr('/' + prefix + '/entry.py') + ', run_name="__main__")\n')
    files['usr/local/lib/oxp3-maintenance/entry.py'] = {
        'data': wrapper.encode(), 'mode': 0o755, 'component': '_maintenance', 'user': False}
    components = {}
    previous_activation = installed_runtime / 'activation.json'
    if previous_activation.is_file():
        adoption._trusted(previous_activation, Path('/'))
        previous = json.loads(previous_activation.read_text())
        if previous.get('schema') != 1 or not isinstance(previous.get('components'), dict):
            raise RuntimeError('Invalid installed activation metadata; recover it before updating')
        components.update(previous['components'])
        for item in components.values():
            item.setdefault('installed_project_version', previous.get('release', {}).get('version'))
    components.update({name: dict(item, installed_project_version=release['version']) for name, item in plan['components'].items()})
    activation = {'schema': 1, 'release': release, 'components': components}
    files['usr/local/lib/oxp3-maintenance/activation.json'] = {
        'data': (json.dumps(activation) + '\n').encode(), 'mode': 0o600,
        'component': '_maintenance', 'user': False}
    revisions_by_slot = dict(prior_release.get('component_revisions_by_slot', {}))
    if plan.get('revision_slot'):
        slot_revisions = dict(revisions_by_slot.get(plan['revision_slot'], {}))
        # Only actually applied components receive a revision receipt. A tool
        # upgrade must never claim that the user's older repairs are current.
        for name in plan.get('selected', []):
            if (name in plan.get('component_revisions', {})
                    and plan.get('components', {}).get(name, {}).get('status') == 'ready'):
                revision = plan['component_revisions'][name]
                slot_revisions[name] = revision
                # Owned by the component itself, so normal restore/rollback and
                # crash recovery remove/restore this receipt with its files.
                receipt = 'usr/local/lib/oxp3-maintenance/component-receipts/' + plan['revision_slot'] + '/' + name + '.json'
                files[receipt] = {'data': (json.dumps({'component': name, 'revision': revision,
                                                     'slot': plan['revision_slot']}) + '\n').encode(),
                                  'mode': 0o644, 'component': name, 'user': False}
            else:
                slot_revisions.pop(name, None)
        revisions_by_slot[plan['revision_slot']] = slot_revisions
    files['usr/local/lib/oxp3-maintenance/current-release.json'] = {
        'data': (json.dumps(dict(release, maintenance_runtime=runtime_name,
                                maintenance_distribution=2, component_revisions_by_slot=revisions_by_slot)) + '\n').encode(), 'mode': 0o644,
        'component': '_maintenance', 'user': False}
    desktop = content['OXP3-Maintenance.desktop']
    for target in ('home/deck/Desktop/OXP3-Maintenance.desktop',
                   'home/deck/.local/share/applications/OXP3-Maintenance.desktop'):
        files[target] = {'data': desktop, 'mode': 0o755, 'user': True, 'component': '_maintenance'}
    user_service = b'[Unit]\nDescription=Check OXP3 project updates\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py check-updates --background\n'
    timer = b'[Unit]\nDescription=Daily OXP3 project update check\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=30m\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    for name, data in (('service', user_service), ('timer', timer)):
        files['home/deck/.config/systemd/user/oxp3-maintenance-check.' + name] = {
            'data': data, 'mode': 0o644, 'user': True, 'component': '_maintenance'}
    files['etc/systemd/system/oxp3-maintenance-activate.service'] = {
        'data': b'[Unit]\nDescription=Activate selected OXP3 project repairs\nAfter=local-fs.target\nBefore=display-manager.service\nRequiresMountsFor=/home\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py activate\n[Install]\nWantedBy=multi-user.target\n',
        'mode': 0o644, 'component': '_maintenance', 'user': False}
    return files


def check_release_version(release, installed, *, updating=False):
    """A normal application may add same-version options, never downgrade code."""
    from .releases import _Version
    candidate, current = _Version(release['version']), _Version(installed['version'])
    if candidate < current or updating and candidate == current:
        raise RuntimeError('Use explicit rollback for a downgrade; project updates must be newer than the installed version')


def apply(args, *, bootstrap=False):
    require_root()
    if not bootstrap:
        trusted_code()
    system = probe.live()
    if not device_supported(system):
        raise RuntimeError('This project release does not support the current device/system base')
    store = store_for(system)
    with store.lock(), authenticated(args) as (directory, manifest):
        from .cli import installed_release
        check_release_version(manifest['release'], installed_release(), updating=args.action == 'update')
        plan, original = prepare(directory / 'payload', args.select, system, store,
                                 tool_only=getattr(args, 'tool_only', False), selected_only=getattr(args, 'selected_only', False))
        plan['revision_slot'] = system['slot']['id']
        require_plan_packages(manifest, plan)
        if manifest.get('schema') == 2:
            from .distribution import index_from_manifest
            from .update_state import revisions
            plan['component_revisions'] = revisions(index_from_manifest(manifest))
        result = summarize(plan, manifest['release'], system)
        if not result['can_apply']:
            return dict(result, status='preflight_refused')
        files = dict(plan['files'])
        if not system['shared_os_compatible']:
            raise RuntimeError('Cannot install shared desktop/update entries until the other slot compatibility is verified')
        files.update(runtime_files(directory / 'app', manifest['release'], plan))
        check_space(files)
        units = [unit for item in plan['components'].values() for unit in item.get('units', [])]
        units += ['oxp3-maintenance-activate.service']
        previous_activation = RUNTIME / 'activation.json'
        if previous_activation.is_file():
            old = json.loads(previous_activation.read_text())
            units += [unit for name, item in old['components'].items() if name in plan['selected'] for unit in item.get('units', [])]
        replace_legacy = not plan.get('retained') and Path('/etc/systemd/system/oxp3-selected-components.service').exists()
        if replace_legacy:
            units += ['oxp3-selected-components.service']
        try:
            previous_components = set(current_selection(system, store) or [])
        except (RuntimeError, OSError, ValueError, KeyError, TypeError):
            # prepare already reported unreadable legacy evidence as retained.
            # It is never authority to enable/disable legacy component units.
            previous_components = set()
        _service_history(store, system, units, remember=True)
        packages = PackageStore(STATE, system['slot']['id'], command)
        package_new = False
        package_report = plan['components'].get('waydroid', {})
        if package_report.get('package_install_required'):
            staged = directory / 'package-preflight'
            staged.mkdir(mode=0o700)
            sources = []
            for index, relative in enumerate(package_report['package_files']):
                path = staged / (str(index) + '.pkg.tar.zst')
                path.write_bytes(plan['files'][relative]['data'])
                path.chmod(0o600)
                sources.append(path)
            package_new = packages.prepare(sources)['phase'] != 'installed'
        with live_write(store, system, units) as live:
            desired = {unit: dict(value) for unit, value in live['services'].items()}
            desired['oxp3-maintenance-activate.service']['enabled'] = 'enabled'
            if 'oxp3-selected-components.service' in desired:
                desired['oxp3-selected-components.service'].update(enabled='disabled', active=False)
            for name, item in plan['components'].items():
                if item['status'] == 'ready' and name not in previous_components:
                    for unit in item.get('units', []):
                        desired[unit]['enabled'] = 'enabled'
            live['after_services'] = desired
            _file_intent(store, system, live, 'apply', plan['selected'],
                         package_operation=bool(package_report.get('package_install_required')))
            operation = store.apply(files, manifest['release'], plan['selected'] + ['_maintenance'],
                                    system['slot']['id'], adopt=original, legacy_selected=plan.get('legacy_selected'))
            live['file_generation'] = operation['generation']
            _save_private(STATE / 'live-operation.json', live)
            try:
                if package_report.get('package_install_required'):
                    # Persist source paths on the installed root before pacman;
                    # recovery must work after temporary verification data is gone.
                    packages.prepare([Path('/') / p for p in package_report['package_files']])
                    packages.install()
                if set(plan['selected']) & {'input', 'gyro', 'fan-driver'}:
                    command('depmod', '-a', probe.KERNEL)
                command('systemctl', 'daemon-reload')
                command('systemctl', 'enable', 'oxp3-maintenance-activate.service')
                # Supersede only this slot's old activation orchestrator. Its
                # explicit OS-update-policy files are never imported or restored.
                if replace_legacy:
                    command('systemctl', 'disable', 'oxp3-selected-components.service')
                for name, item in plan['components'].items():
                    if item['status'] == 'ready' and name not in previous_components:
                        for unit in item.get('units', []):
                            command('systemctl', 'enable', unit, check=False)
            except Exception:
                if package_new:
                    packages.rollback()
                if operation['changed']:
                    _abort_apply(store, system, plan['selected'])
                live['after_services'] = live['services']
                live['file_action'] = 'aborted'
                live['file_generation'] = _generation(store, system)
                _save_private(STATE / 'live-operation.json', live)
                raise
        _service_history(store, system, units, remember=True)
        return dict(result, status='files_installed', operation=operation,
                    activation='pending_reboot' if result['restart_required'] else 'next_activation')


def activate():
    require_root()
    trusted_code()
    system = probe.live()
    if not device_supported(system):
        raise RuntimeError('Activation refused on a different device or system base')
    store = store_for(system)
    with store.lock():
        if (STATE / 'live-operation.json').exists() or store.status()['pending']:
            raise RuntimeError('Recover the interrupted operation before activation')
        record = json.loads((RUNTIME / 'activation.json').read_text())
        current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
        if current is None:
            raise RuntimeError('No installed component generation for this slot')
        output = {}
        package_store = PackageStore(STATE, system['slot']['id'], command)
        package_state = package_store._read() or {'phase': 'absent'}
        for name, item in record['components'].items():
            if name not in current['selected'] or item['status'] != 'ready':
                continue
            requirements = item.get('compatibility', {}).get('requirements', {})
            policy = evaluate(name, system, {'packages': requirements.get('packages', {})})
            if not policy['supported'] or any(system['packages'].get(package) != version for package, version in requirements.get('packages', {}).items()):
                output[name] = 'incompatible_after_system_change'
                continue
            if name == 'waydroid' and package_state['phase'] != 'installed':
                raise RuntimeError('Waydroid host packages need recovery before activation')
            if name == 'waydroid':
                package_store.recover()  # Installed phase: read-only version verification.
            if name == 'gyro' and system['bios'] != '5.09':
                raise RuntimeError('Gyro activation requires BIOS 5.09')
            for unit in item.get('units', []):
                if not UNIT.fullmatch(unit):
                    raise RuntimeError('Invalid activation service')
                if unit != 'oxp3-fan-sleep.service':
                    enabled = command('systemctl', 'is-enabled', unit, check=False)
                    if enabled in ('enabled', 'enabled-runtime', 'static', 'indirect'):
                        command('systemctl', 'start', unit)
            output[name] = 'setup_required' if item.get('setup_required') else 'configured'
        _save_private(STATE / ('activation-' + system['slot']['id'] + '.json'),
                      {'release': record['release'], 'components': output})
        return output


def restore(args, *, previous=False, recovery=False):
    require_root()
    trusted_code()
    system = probe.live()
    store = store_for(system)
    with store.lock():
        if recovery:
            path = STATE / 'live-operation.json'
            saved = None
            if path.exists():
                saved = json.loads(path.read_text())
                if saved['slot'] != system['slot']['id']:
                    raise RuntimeError('Return to the original system slot to recover')
            readonly = command('steamos-readonly', 'status').strip().lower()
            if readonly not in ('enabled', 'disabled'):
                raise RuntimeError('Cannot determine root protection before recovery')
            if readonly == 'enabled':
                command('steamos-readonly', 'disable')
            try:
                if saved and saved.get('gyro_binding_stopped') and not saved.get('gyro_binding_quiesced'):
                    # No file mutation is permitted until the fixed helper has
                    # restored the original driver and systemd is truly inactive.
                    _quiesce_gyro_binding(store, saved)
                packages = PackageStore(STATE, system['slot']['id'], command)
                if saved and saved.get('package_removal'):
                    packages.restore()
                result = store.recover(slot=system['slot']['id'])
                committed = (saved is not None and isinstance(saved.get('file_generation'), int)
                             and _generation(store, system) == saved['file_generation'])
                if saved and not committed and _generation(store, system) == saved.get('source_generation'):
                    if saved.get('file_action') == 'restore':
                        result = store.restore(system['slot']['id'], saved['file_components'])
                        saved['file_generation'] = result.get('generation', _generation(store, system))
                        committed = True
                    elif saved.get('file_action') == 'rollback':
                        result = store.rollback(system['slot']['id'])
                        saved['file_generation'] = result['generation']
                        committed = True
                package_state = packages.recover()
                apply_packages = saved and saved.get('file_action') == 'apply' and saved.get('package_operation')
                if apply_packages and package_state['phase'] == 'prepared':
                    # A crash may have occurred before the persistent source-path
                    # refresh. Resume only from journaled, installed package files.
                    sources = sorted(Path('/usr/local/lib/oxp3-waydroid/packages').glob('*.pkg.tar.zst'))
                    if committed and len(sources) == 5:
                        packages.prepare(sources)
                        packages.install()
                    else:
                        packages.rollback()
                        if committed:
                            result = _abort_apply(store, system, saved['file_components'])
                            committed = False
                elif apply_packages and package_state['phase'] == 'restored' and committed:
                    result = _abort_apply(store, system, saved['file_components'])
                    committed = False
                current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
                modules = set(saved.get('file_components', []) if saved else [])
                if current:
                    modules.update(current['selected'])
                if modules & {'input', 'gyro', 'fan-driver'}:
                    command('depmod', '-a', probe.KERNEL)
                if saved is not None:
                    saved['phase'] = 'coherent'
                    if committed and saved.get('after_services') is not None:
                        saved['services'] = saved['after_services']
                    _save_private(path, saved)
                    _restore_lifecycle(saved, store=store)
                    path.unlink()
            finally:
                if readonly == 'enabled' or saved and saved['readonly'] == 'enabled':
                    command('steamos-readonly', 'enable')
            return result
        record = json.loads((RUNTIME / 'activation.json').read_text())
        current = store.status()['slots'].get(system['slot']['id'], {}).get('current')
        installed = set(current['selected'] if current else []) - {'_maintenance'}
        selected = args.select or sorted(installed)
        if set(selected) - installed:
            raise RuntimeError('Choose installed repair/plugin components; the recovery engine is retained')
        if previous and current:
            prior = store.status()['slots'][system['slot']['id']]['previous']
            if prior is None:
                raise RuntimeError('No previous project generation to roll back to')
            if prior and 'waydroid' in prior['selected'] and 'waydroid' not in installed:
                raise RuntimeError('Reinstall Waydroid from a signed package before rolling back into a generation that requires its host packages')
        if not previous:
            from .split_lock import require_joint_restore
            private_current = store._index()['slots'].get(system['slot']['id'], {}).get('current') or {}
            current_paths = private_current.get('paths', {})
            require_joint_restore(current_paths, selected)
            for name, item in record['components'].items():
                if name in installed and name not in selected and set(item.get('dependencies', [])) & set(selected):
                    raise RuntimeError('Restore dependent component first: ' + name)
        units = [u for n, item in record['components'].items() if n in selected
                 for u in item.get('units', [])]
        originals, history = _service_history(store, system, units, remember=True)
        if previous:
            desired = dict(originals)
            desired.update(history.get(str(prior['id']), {}))
            units = list(set(units) | set(desired))
        else:
            desired = {unit: originals[unit] for unit in units if unit in originals}
        remove_waydroid = 'waydroid' in selected and not previous
        if previous and current:
            remove_waydroid = 'waydroid' in installed and 'waydroid' not in prior['selected']
        with live_write(store, system, units) as live:
            live['after_services'] = desired
            live['package_removal'] = remove_waydroid
            _file_intent(store, system, live, 'rollback' if previous else 'restore', selected)
            # Disable before restoring/removing a unit file, while systemd can
            # still remove the Wants links associated with that unit.
            for unit, target in desired.items():
                if target['enabled'] not in ('enabled', 'enabled-runtime'):
                    command('systemctl', 'disable', unit, check=False)
            if remove_waydroid:
                PackageStore(STATE, system['slot']['id'], command).restore()
            result = store.rollback(system['slot']['id']) if previous else store.restore(system['slot']['id'], selected)
            live['file_generation'] = result.get('generation', _generation(store, system))
            _save_private(STATE / 'live-operation.json', live)
            if set(selected) & {'input', 'gyro', 'fan-driver'}:
                command('depmod', '-a', probe.KERNEL)
        _service_history(store, system, units, remember=True)
        return result
