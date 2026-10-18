"""Command line for project maintenance and native desktop utilities."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime, timezone


PARTITION_MOUNT_HOME = Path('/home/.oxp3-partition-mount')


def _trusted_partition_mount_scripts(missing_message=None):
    """Return the installed desktop entry after checking its whole code path."""
    files = {
        'desktop.py': PARTITION_MOUNT_HOME / 'desktop.py',
        'mounts.py': PARTITION_MOUNT_HOME / 'mounts.py',
        'oxp3-partition-mount': PARTITION_MOUNT_HOME / 'oxp3-partition-mount',
    }
    targets = {path: name for name, path in files.items()}
    chain = []
    for path in files.values():
        chain.extend(reversed((path, *path.parents)))
    seen = set()
    for path in chain:
        if path in seen:
            continue
        seen.add(path)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise RuntimeError(missing_message or (
                'Partition Mount is not installed. Open OXP3 Maintenance → Repairs & plugins, '
                'install KDE graphical persistent partition mounts, then retry.')) from error
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022):
            raise RuntimeError('Untrusted Partition Mount program path; reinstall the component: ' + str(path))
        if path in targets:
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError('Untrusted Partition Mount program file: ' + str(path))
            if targets[path] == 'oxp3-partition-mount' and not info.st_mode & 0o111:
                raise RuntimeError('Partition Mount helper is not executable; reinstall the component.')
        elif not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('Untrusted Partition Mount program directory: ' + str(path))
    return files


def launch_partition_mount(*, missing_message=None):
    """Open the unprivileged KDE utility and wait for its window to close."""
    if os.name != 'posix' or not hasattr(os, 'geteuid'):
        raise RuntimeError('Partition Mount is available from a SteamOS desktop session.')
    if os.geteuid() == 0:
        raise RuntimeError('Open Partition Mount as the desktop user; only saving a mount asks for administrator authorization.')
    files = _trusted_partition_mount_scripts(missing_message)
    result = subprocess.run(['/usr/bin/python3', '-I', '-B', str(files['desktop.py'])],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or '').strip()
        suffix = ('\n' + detail[:1500]) if detail else ''
        raise RuntimeError('Partition Mount closed with an error (exit %d).%s' % (result.returncode, suffix))
    return {'status': 'partition_mount_closed'}


def installed_release():
    from .releases import _Version
    for path in (Path('/usr/local/lib/oxp3-maintenance/current-release.json'),
                 Path('/usr/local/lib/oxp3-integration/release.json')):
        if path.is_file() and not path.is_symlink():
            info = path.stat()
            if info.st_size > 1024 * 1024 or (os.name == 'posix' and (info.st_uid or info.st_mode & 0o022)):
                continue
            try:
                value = json.loads(path.read_text())
                _Version(value['version'])
                if value.get('channel') in ('stable', 'beta'):
                    return value
            except (ValueError, KeyError, TypeError):
                continue
    return {'version': '0.0.0', 'display_version': 'Not installed', 'channel': 'beta'}


def _legacy_bundled_opti_runtime(root, system):
    """Recognize the old combined install only through authenticated live files."""
    from . import adoption, inventory
    from .opti_migration import PLUGIN, RUNTIME_PREFIX
    try:
        root = Path(root).absolute()
        reader = inventory._Reader(root)
        label = system['slot'].get('label')
        participating = set()
        for group in ((label, 'shared') if label in ('A', 'B') else ('shared',)):
            try:
                journal, _ = reader.journal('home/.oxp3-installer/integration/' + group + '/' + PLUGIN + '/state.json')
            except FileNotFoundError:
                continue
            if journal.get('phase') == 'rolled_back':
                continue
            allowed = journal.get('allowed')
            if not isinstance(allowed, list):
                return None
            for path in allowed:
                inventory._parts(path)
            runtime_paths = {path for path in allowed if path.startswith(RUNTIME_PREFIX)}
            if runtime_paths:
                # import_originals alone does not require phase=installed or
                # complete recovery backups for ordinary file journals.
                inventory._backup_complete(journal, digests=True)
                participating.update(runtime_paths)
        directory = adoption._directory_originals(root, PLUGIN)
        if directory:
            if participating & directory.keys():
                return None  # Ambiguous original ownership between journals.
            adoption.validate_current(root, directory, system)
            return True
        records = ({path: record for path, record in adoption.import_originals(root, system, [PLUGIN]).items()
                    if path in participating and record.get('component') == PLUGIN} if participating else {})
        if records:
            adoption.validate_current(root, records, system)
            return True
        # An observed runtime without a trusted baseline is unknown, never an
        # instruction to reinstall it. A plugin/config alone proves no runtime.
        return None if os.path.lexists(Path(root) / RUNTIME_PREFIX.rstrip('/')) else False
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        return None


def installed_component_states(root, system, store, names, *, validated_originals=None):
    """Tri-state current installation evidence; legacy choices are not proof.

    Called only inside an already-authorized root plan. Reuse successful live
    adoption validation from prepare and validate any remaining protected legacy
    journals once. Restored/adopted components never revive stale old journals.
    """
    from . import adoption, inventory
    managed = store.managed()
    slot = system['slot']['id']
    index = store._index()
    current = index['slots'].get(slot, {}).get('current') or {}
    restored = set(current.get('legacy_adopted', []))
    confirmed = {record['component'] for record in (validated_originals or {}).values()}
    evidence = inventory.inspect(root, system, managed)
    output = {}

    def verify_paths(paths):
        try:
            for relative, record in paths.items():
                actual = store._read(relative, user=record['user'])
                expected = record['snapshot']
                if not actual['exists']:
                    raise RuntimeError('Managed component file is missing')
                if record['mutable']:
                    scope = ('shared' if relative.startswith(('home/', 'opt/')) else slot) + ':' + relative
                    original_baseline = index.get('originals', {}).get(scope)
                    if expected == {'exists': False} or expected == original_baseline:
                        # Reapplying after restore can keep a customized
                        # setting with its original snapshot as baseline.
                        # Its presence is still managed; validate current
                        # ownership and conservative configuration modes.
                        owner = (store.uid, store.gid) if record['user'] else (0, 0)
                        mode = actual['mode']
                        if ((actual['uid'], actual['gid']) != owner
                                or type(mode) is not int or not 0 <= mode <= 0o777
                                or mode & 0o133 or not mode & 0o400):
                            raise RuntimeError('Managed preserved configuration metadata is unsafe')
                    elif any(actual[key] != expected[key] for key in ('mode', 'uid', 'gid')):
                        raise RuntimeError('Managed configuration metadata changed')
                elif actual != expected:
                    raise RuntimeError('Managed component file changed')
            if paths:
                return True
        except (RuntimeError, OSError, ValueError, KeyError, TypeError):
            pass
        return None

    for name in names:
        if slot in managed.get('components', {}).get(name, {}).get('slots', []):
            paths = {relative: record for relative, record in current.get('paths', {}).items()
                     if record['component'] == name}
            output[name] = verify_paths(paths)
        elif name in restored:
            output[name] = False
        elif name in confirmed:
            output[name] = True
        else:
            entry = evidence.get('components', {}).get(name, {})
            state = entry.get('state')
            if state == 'legacy_with_backups' and not entry.get('conflicts'):
                try:
                    records = adoption.validate_current(root, adoption.import_originals(root, system, [name]), system)
                    output[name] = True if records else None
                except (RuntimeError, OSError, ValueError, KeyError, TypeError):
                    output[name] = None
            elif state == 'absent' and entry.get('absence_verified'):
                output[name] = False
            else:
                output[name] = None
    from .opti_migration import PLUGIN, RUNTIME, RUNTIME_PREFIX
    authoritative = restored | {name for name, record in managed.get('components', {}).items()
                                if slot in record.get('slots', [])}
    if RUNTIME in output and RUNTIME not in authoritative:
        runtime_paths = {path: record for path, record in current.get('paths', {}).items()
                         if path.startswith(RUNTIME_PREFIX)}
        if runtime_paths:
            output[RUNTIME] = (verify_paths(runtime_paths)
                               if slot in managed.get('components', {}).get(PLUGIN, {}).get('slots', [])
                               and all(item['component'] == PLUGIN for item in runtime_paths.values()) else None)
        elif PLUGIN in authoritative:
            output[RUNTIME] = None
        else:
            output[RUNTIME] = _legacy_bundled_opti_runtime(root, system)
    return output


def read_installed_component_states(root, system, names):
    """Advisory installation checks without creating locks or writing state.

    The desktop first tries this without elevation. Unreadable current state
    blocks legacy fallback, so surviving installer journals cannot revive a
    restored component. The privileged apply path still repeats full adoption.
    """
    from . import adoption, health, inventory, state_io
    from .opti_migration import PLUGIN, RUNTIME, RUNTIME_PREFIX
    output = {name: None for name in names}
    class InstallationReport(health.Report):
        def original_index(self, scope):
            if hasattr(self, '_original_index'):
                return self._original_index
            slot = system['slot']['id']
            def load(scopes):
                with health.regular(self.root, health.STATE + '/index.json', trusted=True, verify_name=True) as (stream, before):
                    if before.st_size > health.MAX_INDEX:
                        raise ValueError('index_size_limit')
                    return state_io.load(stream, slot=slot, max_bytes=health.MAX_INDEX, original_scopes=scopes)
            index = load({scope})
            paths = index['slots'][slot]['current']['paths']
            if not isinstance(paths, dict) or len(paths) > health.MAX_PATHS:
                raise ValueError('invalid_paths')
            scopes = {scope}
            for path, entry in paths.items():
                health.Store._path(path)
                if not isinstance(entry, dict):
                    raise ValueError('invalid_entry')
                if entry.get('mutable') is True:
                    scopes.add(('shared' if path.startswith(('home/', 'opt/')) else slot) + ':' + path)
            self._original_index = load(scopes) if scopes != {scope} else index
            return self._original_index

        def preserved(self, relative, expected, actual):
            # Called only by compare while managed() holds the existing shared
            # lock. Load only this path's original digest, never backup bytes.
            slot = system['slot']['id']
            scope = ('shared' if relative.startswith(('home/', 'opt/')) else slot) + ':' + relative
            index = self.original_index(scope)
            entry = index['slots'][slot]['current']['paths'][relative]
            if (type(entry.get('user')) is not bool or entry.get('mutable') is not True
                    or health.expected_snapshot(entry['snapshot']) != expected):
                return False
            original = index.get('originals', {}).get(scope)
            if expected != {'exists': False} and (original is None or health.expected_snapshot(original) != expected):
                return None
            owner = (system['uid'], system['gid']) if entry['user'] else (0, 0)
            mode = actual['mode']
            return ((actual['uid'], actual['gid']) == owner
                    and 0 <= mode <= 0o777 and not mode & 0o133 and bool(mode & 0o400))

        def matches(self, entries):
            if not entries:
                return None
            try:
                for relative, expected, mutable in entries:
                    actual = health.fingerprint(self.root, relative, self.budget)
                    if not actual.get('exists'):
                        return None
                    if mutable:
                        preserved = self.preserved(relative, expected, actual)
                        if preserved is False:
                            return None
                        if preserved is None and any(actual.get(key) != expected.get(key) for key in ('mode', 'uid', 'gid')):
                            return None
                    elif actual != expected:
                        return None
                return True
            except (OSError, RuntimeError, ValueError, KeyError, TypeError):
                return None

        def compare(self, name, entries, *, source):
            runtime_entries = [entry for entry in entries if entry[0].startswith(RUNTIME_PREFIX)]
            if runtime_entries:
                self.runtime_owner_seen = True
                if name == PLUGIN:
                    self.bundled_runtime = self.matches(runtime_entries)
                else:
                    self.runtime_other_owner = True
            if name in output:
                output[name] = self.matches(entries)

    report = InstallationReport(root)
    if report.interrupted():
        return output
    selected, authoritative = report.managed(system)
    if authoritative is None:
        return {name: None for name in names}
    for name in authoritative - selected:
        if name in output:
            output[name] = False
    evidence = inventory.inspect(root, system)
    for name in names:
        if name in authoritative:
            continue
        entry = evidence.get('components', {}).get(name, {})
        if entry.get('state') == 'legacy_with_backups' and not entry.get('conflicts'):
            try:
                records = adoption.validate_current(root, adoption.import_originals(root, system, [name]), system)
                output[name] = True if records else None
            except (RuntimeError, OSError, ValueError, KeyError, TypeError):
                pass
        elif entry.get('state') == 'absent' and entry.get('absence_verified'):
            output[name] = False
    if RUNTIME in output and RUNTIME not in authoritative:
        if getattr(report, 'runtime_owner_seen', False):
            output[RUNTIME] = (getattr(report, 'bundled_runtime', None) if PLUGIN in selected
                               and not getattr(report, 'runtime_other_owner', False) else None)
        elif PLUGIN in authoritative:
            output[RUNTIME] = None
        else:
            output[RUNTIME] = _legacy_bundled_opti_runtime(root, system)
    return output


def check_updates(background=False, channel=None, github_network=None):
    from .releases import check_releases
    release = installed_release()
    settings = Path.home() / '.config/oxp3-maintenance/settings.json'
    preferences = json.loads(settings.read_text()) if settings.is_file() else {}
    if background and not preferences.get('check_updates', True):
        return {'status': 'disabled', 'candidates': []}
    from .network import NETWORK_MODES, NetworkPolicy
    mode = github_network or preferences.get('github_network', 'auto')
    mode = mode if mode in NETWORK_MODES else 'auto'
    network = {'opener': NetworkPolicy(mode).open}
    result = check_releases(release['version'], channel or preferences.get('channel', release.get('channel', 'beta')), **network)
    latest_project = result.get('latest_project')
    project_newer = False
    if latest_project:
        from .releases import _release_order
        project_newer = _release_order(latest_project['version']) > _release_order(release['version'])
    if background and (result['candidates'] or project_newer):
        # Discovery works on every OXP3 SteamOS; compatibility is per component.
        from .probe import live
        from .compatibility import device_supported
        if not device_supported(live()):
            return dict(result, notification='unsupported_device')
        latest = latest_project if project_newer else result['candidates'][0]
        state = Path.home() / '.local/state/oxp3-maintenance'
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous = state / 'notified-version'
        if not previous.exists() or previous.read_text() != latest['version']:
            subprocess.run(['kdialog', '--passivepopup',
                            'OXP3 project update: ' + latest['display_version'] +
                            '\nOpen OXP3 Maintenance to review and install.', '12'],
                           check=True, timeout=20)
            previous.write_text(latest['version'])
    return result


def parser():
    result = argparse.ArgumentParser(description='OXP3 project repairs and updates; SteamOS base upgrades are not performed.')
    result.add_argument('action', nargs='?', default='gui', choices=(
        'gui', 'status', 'plan', 'apply', 'bootstrap', 'check-updates', 'update',
        'rollback', 'restore', 'recover', 'guard', 'activate', 'logs', 'catalog', 'download', 'health',
        'partition-mount', 'installation-status', 'session-service'))
    result.add_argument('--bundle', help='Signed maintenance .tar.gz')
    result.add_argument('--bundle-dir', help='Extracted signed maintenance directory')
    result.add_argument('--select', nargs='*', default=[], help='Component IDs; dependencies are included')
    result.add_argument('--background', action='store_true')
    result.add_argument('--all-components', action='store_true', help='Preview all available components for the desktop selector')
    result.add_argument('--expected-version', help='Bind online update to the advertised project version')
    result.add_argument('--expected-manifest', help='Bind execution to the reviewed signed manifest')
    result.add_argument('--json', action='store_true', help='Structured result (also the CLI default)')
    result.add_argument('--channel', choices=('stable', 'beta'), help='Project release channel')
    result.add_argument('--version', help='Exact project release to browse/download; defaults to newest')
    result.add_argument('--output', help='User download directory (download action)')
    result.add_argument('--tool-only', action='store_true', help='Update only the signed maintenance engine; keep existing repairs unchanged')
    result.add_argument('--selected-only', action='store_true', help='Refresh only --select components and dependencies; keep other installed components unchanged')
    from .network import NETWORK_MODES
    result.add_argument('--github-network', choices=NETWORK_MODES, help='Public GitHub download route; default: automatic fallback')
    return result


def dispatch(args):
    if args.action == 'session-service':
        from .auth_session import serve
        defaults = vars(parser().parse_args(['session-service']))
        if vars(args) != defaults:
            raise ValueError('Maintenance session service accepts no command-line parameters')
        return serve()
    if args.action == 'partition-mount':
        return launch_partition_mount()
    if args.action == 'health':
        from .health import collect
        return collect()
    if args.action == 'gui':
        from .touch_ui import run
        return run(args)
    if args.action == 'check-updates':
        return check_updates(args.background, args.channel, getattr(args, 'github_network', None))
    if args.action in ('catalog', 'download'):
        return online(args)
    from . import operations, probe
    if args.action == 'guard':
        operations.require_root()
        operations.trusted_code()
        system = probe.live()
        if not system['compatible']:
            raise RuntimeError('Unsupported OXP3 device/system base')
        # Called by systemd while the parent operation holds its lock. Never
        # acquire that same lock here; the private durable phase is the gate.
        state = operations.STATE
        if state.exists():
            for path in (state, *state.parents):
                info = path.lstat()
                if path.is_symlink() or info.st_uid or info.st_mode & 0o022:
                    raise RuntimeError('Untrusted maintenance state')
            if (state / 'pending.json').exists():
                raise RuntimeError('Project repair recovery is required before starting services')
            lifecycle = state / 'live-operation.json'
            if lifecycle.exists():
                operations.adoption._trusted(lifecycle, Path('/home'))
                record = json.loads(lifecycle.read_text())
                if record.get('slot') != system['slot']['id'] or record.get('phase') != 'coherent':
                    raise RuntimeError('Project repair recovery is required before starting services')
        return {'status': 'passed'}
    if args.action == 'activate':
        return operations.activate()
    if args.action in ('apply', 'bootstrap', 'update'):
        return operations.apply(args, bootstrap=args.action == 'bootstrap')
    if args.action in ('rollback', 'restore', 'recover'):
        return operations.restore(args, previous=args.action == 'rollback', recovery=args.action == 'recover')
    system = probe.live()
    if args.action == 'installation-status':
        from .compatibility import BASELINE, PORTABLE
        names = sorted(set(args.select)) if args.select else sorted(BASELINE | PORTABLE)
        return {'installed_states': read_installed_component_states('/', system, names),
                'system': system, 'read_only': True}
    if args.action == 'logs':
        operations.require_root()
        store = operations.store_for(system)
        with store.lock():
            path = operations.STATE / 'last-result.json'
            return json.loads(path.read_text()) if path.exists() else {'status': 'no_operations_recorded'}
    if args.action == 'status':
        from .inventory import inspect
        result = {'schema': 1, 'release': installed_release(), 'system': system,
                  'inventory': inspect('/', system), 'project_updates_only': True}
        if os.geteuid() == 0:
            store = operations.store_for(system)
            result['operations'] = store.status()
            result['inventory'] = inspect('/', system, store.managed())
            activation = operations.STATE / ('activation-' + system['slot']['id'] + '.json')
            if activation.is_file():
                result['activation'] = json.loads(activation.read_text())
        return result
    operations.require_root()
    with operations.authenticated(args) as (directory, manifest):
        store = operations.store_for(system)
        with store.lock():
            if args.tool_only:
                plan, _ = operations.prepare(directory / 'payload', [], system, store, tool_only=True)
                return dict(operations.summarize(plan, manifest['release'], system),
                            catalog={}, defaults=[], manifest_digest=manifest['_review_digest'])
            catalog = json.loads((directory / 'payload/components/options.json').read_text())
            from .payload_policy import REMOVED_PLUGIN_IDS
            catalog = dict(catalog, **{group: [item for item in catalog[group] if item['id'] not in REMOVED_PLUGIN_IDS]
                                       for group in ('repairs', 'plugins')})
            defaults = [item['id'] for category in ('repairs', 'plugins') for item in catalog[category]
                        if item.get('default') and item.get('available', True) and item['id'] not in ('refind', 'slot-switch', 'shared-storage')]
            try:
                prior = operations.current_selection(system, store)
            except (RuntimeError, OSError, ValueError, KeyError, TypeError):
                prior = []  # prepare reports invalid legacy evidence per component.
            # Prior choices are automatic roots inside prepare; do not turn old
            # separate operations into explicit requests during a plain preview.
            selected = args.select
            if args.all_components:
                selected = [item['id'] for category in ('repairs', 'plugins') for item in catalog[category]
                            if item.get('available', True) and item['id'] != 'refind']
            plan, originals = operations.prepare(directory / 'payload', selected, system, store,
                                         tool_only=args.tool_only, selected_only=args.selected_only)
            operations.require_plan_packages(manifest, plan)
            result = operations.summarize(plan, manifest['release'], system)
            result['catalog'] = catalog
            result['defaults'] = prior if prior is not None else defaults
            result['installed_states'] = installed_component_states('/', system, store,
                [item['id'] for group in ('repairs', 'plugins') for item in catalog[group]],
                validated_originals=originals)
            result['manifest_digest'] = manifest['_review_digest']
            # Return no file bytes, originals, calibration or credentials.
            return result


def online(args):
    from .releases import check_releases, fetch_catalog
    from .downloads import save, trusted_key
    from .catalog import describe
    if os.name == 'posix' and os.geteuid() == 0:
        raise RuntimeError('Browse and download as the desktop user; installation is authorized separately')
    installed = installed_release()
    from .network import NetworkPolicy
    mode = getattr(args, 'github_network', None) or 'auto'
    network = {'opener': NetworkPolicy(mode).open}
    releases = check_releases(installed['version'], args.channel or installed.get('channel', 'beta'), **network)
    choices = releases['maintenance_releases']
    if args.version:
        choices = [entry for entry in choices if entry['version'] == args.version]
    if not choices:
        return {'status': releases['status'], 'latest_project': releases['latest_project'],
                'warning': releases.get('warning'),
                'message': 'No authenticated maintenance download is currently available; retry later or import an offline bundle'}
    candidate = choices[0]
    if args.action == 'download':
        folder = Path(args.output or Path.home() / 'Downloads/OXP3')
        result = save(candidate, folder, **network)
        from .distribution import describe_source, materialize
        value = describe_source(result['path'], trusted_key())
        if value and (args.select or args.all_components):
            import uuid
            selected = args.select
            if args.all_components:
                selected = [item['id'] for item in value['components']
                            if item['available'] and item['delivery'] == 'maintenance']
            return materialize(result['path'], selected, folder / ('selection-' + uuid.uuid4().hex + '.tar.gz'),
                               trusted_key(), catalog=value, cache=folder / 'packages', **network)
        return result
    value = fetch_catalog(candidate, trusted_key(), **network)
    try:
        from .probe import live
        system = live()
    except Exception:
        system = None
    report = describe(value, system)
    return dict(report, status='catalog_verified', latest_project=releases['latest_project'],
                maintenance_release=candidate)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        _record(args, result)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if isinstance(result, dict) and result.get('status') == 'preflight_refused' else 0
    except Exception as error:
        result = {'status': 'failed', 'error': str(error)}
        _record(args, result)
        if not args.background:
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1


def _record(args, result):
    if args.action not in ('apply', 'bootstrap', 'update', 'rollback', 'restore', 'recover'):
        return
    if os.name != 'posix' or os.geteuid() != 0:
        return
    try:
        from . import operations, probe
        system = probe.live()
        store = operations.store_for(system)
        with store.lock():
            operations._save_private(operations.STATE / 'last-result.json', {
                'action': args.action, 'time': datetime.now(timezone.utc).isoformat(), 'result': result})
    except Exception:
        # Logging must never hide a successful transaction or its original error.
        pass
