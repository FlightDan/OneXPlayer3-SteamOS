"""Guest-only compatibility bridge for the pinned, previously public OXP3 installer.

All hardware policy and the old file journal remain inside this device package.
This bridge is experimental until the new installer and rollback lifecycle pass
the same hardware gates as the legacy release.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

PACKAGE = Path(__file__).resolve().parent
LINK = 'etc/systemd/system/multi-user.target.wants/oxp3-selected-components.service'
LINK_TARGET = '../oxp3-selected-components.service'


class _LegacyEventStream:
    """Rename nested result rows without buffering their potentially large JSON."""
    prefix = 'OXP_COMPONENT_RESULT='
    replacement = 'BOILER_DEVICE_LEGACY_RESULT='

    def __init__(self, stream):
        self.stream = stream
        self.pending = ''
        self.start = True

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, text):
        length = len(text)
        while text:
            if self.start:
                character, text = text[0], text[1:]
                self.pending += character
                if self.pending == self.prefix:
                    self.stream.write(self.replacement)
                    self.pending, self.start = '', False
                elif not self.prefix.startswith(self.pending):
                    self.stream.write(self.pending)
                    self.pending, self.start = '', character == '\n'
            else:
                newline = text.find('\n')
                if newline < 0:
                    self.stream.write(text)
                    break
                self.stream.write(text[:newline+1])
                text, self.start = text[newline+1:], True
        return length

    def flush(self):
        self.stream.flush()

    def finish(self):
        if self.pending:
            self.stream.write(self.pending)
            self.pending = ''
        self.flush()


@contextmanager
def legacy_events():
    """Keep the old protocol inside the model boundary, preserving all logs."""
    stdout, stderr = _LegacyEventStream(sys.stdout), _LegacyEventStream(sys.stderr)
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield
    finally:
        stdout.finish()
        stderr.finish()


def selection(value, catalog):
    required = {'schema_version', 'slot', 'repairs', 'plugins', 'installer_language',
                'kde_language', 'acknowledge_legacy_update_hold'}
    if not isinstance(value, dict) or set(value) != required or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported explicit OXP3 selection')
    if value['slot'] != 'guest' or value['acknowledge_legacy_update_hold'] is not True:
        raise ValueError('A guest-bound slot and legacy OS-image update-hold acknowledgement are required')
    output = {'schema': 1, 'installer_language': value['installer_language'], 'kde_language': value['kde_language']}
    for category in ('repairs', 'plugins'):
        choices = value[category]
        if not isinstance(choices, list) or any(not isinstance(x, str) or not x.startswith('oxp3:') for x in choices) or len(set(choices)) != len(choices):
            raise ValueError('Device choices must use unique oxp3:* IDs')
        output[category] = [x.removeprefix('oxp3:') for x in choices]
    known = {item['id']: item for category in ('repairs', 'plugins') for item in catalog[category]}
    selected = set(output['repairs'] + output['plugins'])
    for category in ('repairs', 'plugins'):
        allowed = {item['id'] for item in catalog[category]}
        if set(output[category]) - allowed:
            raise ValueError('Unknown device component')
    for name in selected:
        item = known[name]
        if not item.get('available', True) or set(item['dependencies']) - selected:
            raise ValueError('Unavailable component or missing dependency: ' + name)
    if output['installer_language'] not in catalog['languages'] or output['kde_language'] not in catalog['kde_languages']:
        raise ValueError('Unsupported language')
    return output


def target_root(*, metadata_only=False):
    if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise RuntimeError('OXP3 system changes run only as root inside the Linux installer guest')
    if not metadata_only:
        marker = Path('/run/boiler-guest-context')
        if not marker.is_file() or marker.is_symlink() or marker.stat().st_uid != 0 or marker.stat().st_mode & 0o022 or marker.read_text() != 'managed-qemu-integration\n':
            raise RuntimeError('Trusted Boiler installer guest marker is required')
    supplied = os.environ.get('BOILER_TARGET_ROOT', '')
    if not supplied or not Path(supplied).is_absolute():
        raise RuntimeError('Explicit target root is required')
    root = Path(supplied)
    for path in (root, *root.parents):
        if path.is_symlink():
            raise RuntimeError('Target root cannot traverse a symlink')
    root = root.resolve(strict=True)
    if root == Path('/') and not metadata_only:
        raise RuntimeError('The guest running system is not an installation target')
    release = dict(line.split('=', 1) for line in (root/'etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'steamos' or release.get('VERSION_ID', '').strip('"') != '3.10':
        raise RuntimeError('This model package supports SteamOS 3.10 only')
    return root


def run(action):
    root = target_root()
    choice = json.loads((PACKAGE/'selection.json').read_text())
    payload = PACKAGE/'payload/legacy'
    catalog = json.loads((payload/'components/options.json').read_text())
    options = selection(choice, catalog)
    # The model's public code is imported only after platform and target checks.
    sys.path.insert(0, str(payload/'components'))
    import integration
    from file_transaction import atomic_write, snapshot
    from hdr.installer import ensure_directory
    slot_file = Path('/run/boiler-install-slot')
    if slot_file.is_symlink() or not slot_file.is_file() or slot_file.stat().st_uid != 0 or slot_file.stat().st_mode & 0o022:
        raise RuntimeError('Trusted guest slot marker is required')
    slot = slot_file.read_text().strip()
    if slot not in ('A', 'B'):
        raise RuntimeError('Invalid guest slot marker')
    state = root/'home/.boiler/oxp3-adapter'
    result = root/'home/.oxp3-installer/integration'/slot/'result.json'
    record_path = state/(slot + '.json')
    def trusted_json(path):
        saved = snapshot(path, maximum=2*1024*1024)
        if saved.get('uid') != 0 or saved.get('mode', 0) & 0o077:
            raise RuntimeError('Untrusted model result or adapter journal')
        return json.loads(base64.b64decode(saved['data']))
    # Reuse the model's root-owned, no-follow journal reader for saved state.
    record = trusted_json(record_path) if os.path.lexists(record_path) else None
    if record and record.get('selection') != choice:
        raise RuntimeError('Restore the previous model selection before changing the frozen package selection')
    if action == 'apply':
        if record and record.get('phase') == 'applied':
            return run('verify')
        if record and record.get('phase') != 'restored':
            raise RuntimeError('A previous model apply was interrupted; restore it before retrying')
        if result.exists() and not (record and record.get('phase') == 'restored'):
            raise RuntimeError('Existing legacy integration requires an explicit adoption migration; refusing to overwrite its result journal')
        link = root/LINK
        if os.path.lexists(link):
            if not link.is_symlink() or os.readlink(link) != LINK_TARGET:
                raise RuntimeError('Conflicting model runtime enablement')
            previous_link = LINK_TARGET
        else:
            previous_link = None
        ensure_directory(state, 0o700)
        record = {'schema_version': 1, 'phase': 'applying', 'selection': choice, 'previous_runtime_link': previous_link}
        atomic_write(record_path, (json.dumps(record)+'\n').encode(), 0o600, 0, 0)
        with legacy_events():
            value = integration.stage(root, payload, options, slot)
        failed = [name for name, report in value['components'].items() if report.get('status') == 'not_installed']
        if failed:
            raise RuntimeError('Requested model components failed; restore before retrying: ' + ', '.join(failed))
        record['verification'] = verify_staged(root, slot, options)
        record['phase'] = 'applied'
        atomic_write(record_path, (json.dumps(record)+'\n').encode(), 0o600, 0, 0)
        return value
    if not record:
        raise RuntimeError('No adapter-owned model installation exists')
    if action == 'verify':
        if record['phase'] != 'applied':
            raise RuntimeError('Model installation is incomplete')
        proof = verify_staged(root, slot, options)
        if record.get('verification') != proof:
            raise RuntimeError('Model file or journal proof differs from completed staging')
        print('BOILER_DEVICE_VERIFY_JSON='+json.dumps({'schema': 1, 'id': 'oxp3:legacy-adaptation',
              'slot': slot, 'verified': True, 'files': len(proof['files']),
              'journals': len(proof['evidence'])-1, 'sha256': proof['sha256']}), flush=True)
        return {'status': 'verified-files', 'activation': 'firstboot-and-hardware-verification-pending',
                'slot': slot, 'files': len(proof['files']), 'sha256': proof['sha256']}
    if action != 'restore':
        raise ValueError('Unknown model action')
    if record['phase'] == 'restored':
        return {'status': 'restored', 'slot': slot}
    if not result.is_file():
        raise RuntimeError('Incomplete legacy result journal requires per-component recovery; automatic restoration is blocked')
    value = trusted_json(result)
    names = list(reversed(value['components']))
    if all(value['components'].get(name, {}).get('status') == 'files_installed' for name in ('gm7-resume', 'split-lock')):
        names = ['boot-repairs', *[name for name in names if name not in ('gm7-resume', 'split-lock')]]
    for name in [*names, 'runtime']:
        with legacy_events():
            errors = integration.restore(root, slot, name)
        if errors:
            raise RuntimeError('Model restoration preserved conflicts: ' + json.dumps(errors))
    link = root/LINK
    if record['previous_runtime_link'] is None and os.path.lexists(link):
        if not link.is_symlink() or os.readlink(link) != LINK_TARGET:
            raise RuntimeError('Runtime enablement changed; preserving it')
        link.unlink()
    record['phase'] = 'restored'
    atomic_write(record_path, (json.dumps(record)+'\n').encode(), 0o600, 0, 0)
    return {'status': 'restored', 'slot': slot}


def verify_staged(root, slot, options, *, reader=None):
    """Read-only comparison of actual bytes against protected legacy journals."""
    root = Path(root).absolute()
    if slot not in ('A', 'B'):
        raise RuntimeError('Explicit verification slot is required')
    read = reader or (lambda name, **kw: _protected_snapshot(root, name, **kw))
    evidence, files = [], {}

    def document(name):
        saved = read(_relative(name))
        if saved.get('uid') != 0 or saved.get('mode', 0) & 0o077:
            raise RuntimeError('Model verification metadata is not private and root-owned')
        raw = base64.b64decode(saved['data'], validate=True)
        evidence.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
        return json.loads(raw, object_pairs_hook=_pairs)

    base = 'home/.oxp3-installer/integration/'
    result = document(base+slot+'/result.json')
    if result.get('schema') != 1 or result.get('slot') != slot or result.get('options') != options or not isinstance(result.get('components'), dict):
        raise RuntimeError('Model result does not match the frozen selection and slot')
    reports = result['components']
    selected = set(options['repairs']+options['plugins'])
    for name in selected | {'system-update-hold', 'serial-console-policy', 'maintenance-tool'}:
        if reports.get(name, {}).get('status') != 'files_installed':
            raise RuntimeError('Required model component is not installed: '+name)
    passwd = base64.b64decode(read('etc/passwd')['data'], validate=True).decode()
    users = [line.split(':') for line in passwd.splitlines() if line.startswith('deck:')]
    if len(users) != 1:
        raise RuntimeError('Exactly one legacy desktop account is required')
    owner = tuple(int(users[0][i]) for i in (2, 3))

    def add(name, applied, metadata):
        _relative(name)
        if name in files:
            raise RuntimeError('Overlapping model verification journals: '+name)
        if applied is None:
            if os.path.lexists(root/name):
                raise RuntimeError('Deleted model target reappeared: '+name)
            files[name] = {'path': name, 'exists': False}
            return
        expected_snapshot = _normal_snapshot({'exists': True, 'data': applied, **metadata})
        expected = base64.b64decode(expected_snapshot['data'], validate=True)
        actual = read(name, user_uid=owner[0] if name.startswith('home/deck/') else None)
        data = base64.b64decode(actual['data'], validate=True)
        if data != expected or any(actual.get(key) != value for key, value in metadata.items()):
            raise RuntimeError('Model installed file differs from its applied journal: '+name)
        files[name] = {'path': name, 'exists': True, 'sha256': hashlib.sha256(data).hexdigest(),
                       'size': len(data), **metadata}

    counts = {}
    for name in sorted(set(reports) | {'runtime', 'release-note', 'desktop-session', 'decky-order-light'}):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', name):
            raise RuntimeError('Unknown model result component')
        for group in (slot, 'shared'):
            path = base+group+'/'+name+'/state.json'
            if not os.path.lexists(root/path):
                continue
            journal = document(path)
            allowed = journal.get('allowed')
            if (journal.get('phase') != 'installed' or not isinstance(allowed, list) or not allowed
                    or any(not isinstance(p, str) for p in allowed) or len(allowed) != len(set(allowed))
                    or set(journal.get('original', {})) != set(allowed) or set(journal.get('applied', {})) != set(allowed)):
                raise RuntimeError('Incomplete model file journal: '+name)
            for target in allowed:
                if target.startswith('home/') != (group == 'shared'):
                    raise RuntimeError('Model journal target is in the wrong slot scope')
                original = _normal_snapshot(journal['original'][target])
                if original['exists']:
                    metadata = {key: original[key] for key in ('mode', 'uid', 'gid')}
                else:
                    item = journal.get('metadata', {}).get(target, {})
                    uid, gid = owner if item.get('user') else (0, 0)
                    metadata = {'mode': item.get('mode', 0o644), 'uid': uid, 'gid': gid}
                add(target, journal['applied'][target], metadata)
            counts[name] = counts.get(name, 0)+len(allowed)
    for name in ('runtime', 'release-note'):
        if not counts.get(name):
            raise RuntimeError('Missing required internal model journal: '+name)
    # Large optional runtimes use the pinned old directory-journal decoder.
    for name, prefix in (('opti2xmx', 'opt/oxp3-opti2xmx'), ('desktop-hdr', 'opt/oxp3-desktop-gamma22')):
        if name not in selected or not any(path.startswith(prefix+'/') for path in reports[name].get('files', [])):
            continue
        document(prefix+'/.installer-state/state.json')
        import importlib.util
        spec = importlib.util.spec_from_file_location('oxp3_verification_decoder', PACKAGE/'payload/legacy/maintenance/app/oxp3_maintenance/adoption.py')
        decoder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(decoder)
        for target, entry in decoder._directory_originals(root, name).items():
            applied = _normal_snapshot(entry['applied'])
            add(target, applied.get('data'), {key: applied[key] for key in ('mode', 'uid', 'gid')})
    for name, report in reports.items():
        if report.get('status') != 'files_installed':
            raise RuntimeError('Model result contains a failed component: '+name)
        declared = report.get('files')
        if not isinstance(declared, list) or any(not isinstance(path, str) or path not in files for path in declared):
            raise RuntimeError('Model result has files without verified journal coverage: '+name)
    link = root/LINK
    parent = link.parent
    while parent != root:
        info = parent.lstat()
        if parent.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Model activation link has an untrusted parent')
        parent = parent.parent
    if not link.is_symlink() or os.readlink(link) != LINK_TARGET:
        raise RuntimeError('Model activation link differs from completed staging')
    body = {'slot': slot, 'files': [files[name] for name in sorted(files)],
            'evidence': sorted(evidence, key=lambda item: item['path']), 'runtime_link': LINK_TARGET}
    return dict(body, sha256=hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest())


def _relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')) or any(ord(c) < 32 for c in name):
        raise RuntimeError('Unsafe legacy target path')
    return name


def _pairs(entries):
    result = {}
    for key, value in entries:
        if key in result:
            raise RuntimeError('Duplicate legacy metadata key')
        result[key] = value
    return result


def _normal_snapshot(value):
    if not isinstance(value, dict) or type(value.get('exists')) is not bool:
        raise RuntimeError('Invalid legacy snapshot')
    if not value['exists']:
        return {'exists': False}
    if any(type(value.get(key)) is not int or value[key] < 0 for key in ('mode', 'uid', 'gid')) or value['mode'] > 0o7777:
        raise RuntimeError('Invalid legacy snapshot metadata')
    try:
        data = base64.b64decode(value['data'], validate=True)
    except (KeyError, ValueError, TypeError) as error:
        raise RuntimeError('Invalid legacy snapshot bytes') from error
    if len(data) > 128*1024*1024:
        raise RuntimeError('Legacy snapshot exceeds generic maintenance backup limit')
    return {key: value[key] for key in ('exists', 'data', 'mode', 'uid', 'gid')} | {'sha256': hashlib.sha256(data).hexdigest()}


def _protected_snapshot(root, name, *, user_uid=None):
    path = root/_relative(name)
    current = path
    while True:
        info = current.lstat()
        allowed = (0, user_uid) if user_uid is not None and current.is_relative_to(root/'home/deck') else (0,)
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()) or info.st_uid not in allowed or info.st_mode & 0o022:
            raise RuntimeError('Untrusted legacy path')
        if current == root:
            break
        if not current.is_relative_to(root):
            raise RuntimeError('Legacy path escaped target')
        current = current.parent
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256*1024*1024:
        raise RuntimeError('Invalid or oversized legacy file')
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (info.st_dev, info.st_ino, 1):
            raise RuntimeError('Legacy file changed while opening')
        data = stream.read(256*1024*1024+1)
        after = os.fstat(stream.fileno())
    if len(data) > 256*1024*1024 or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError('Legacy file changed while reading')
    return {'exists': True, 'data': base64.b64encode(data).decode(), 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}


def collect_adoption(root, slot, expected_key, *, reader=None):
    """Translate exact known OXP3 metadata; never mutate old journals or keys.

    The returned receipt contains private original snapshots. A generic engine
    must validate it again and commit ownership before calling migration done.
    """
    root = Path(root).absolute()
    if slot not in ('A', 'B'):
        raise RuntimeError('Explicit legacy slot is required')
    read = reader or (lambda name, **kw: _protected_snapshot(root, name, **kw))
    evidence = []
    def raw(name, role, *, private=True):
        snap = read(name)
        if private and snap['mode'] & 0o077:
            raise RuntimeError('Legacy private metadata is not protected')
        data = base64.b64decode(snap['data'], validate=True)
        evidence.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'role': role})
        return data
    def document(name, role):
        return json.loads(raw(name, role), object_pairs_hook=_pairs)
    def exists(name):
        return os.path.lexists(root/_relative(name))
    public_release_name = 'usr/local/lib/oxp3-maintenance/current-release.json'
    public_release = json.loads(raw(public_release_name, 'legacy-release', private=False), object_pairs_hook=_pairs)
    runtime = public_release.get('maintenance_runtime', public_release.get('version', ''))
    if not isinstance(runtime, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,159}', runtime):
        raise RuntimeError('Invalid legacy runtime generation')
    key_name = 'usr/local/lib/oxp3-maintenance/releases/' + runtime + '/trusted-public-key.pem'
    key = raw(key_name, 'trusted-public-key', private=False)
    if key != expected_key:
        raise RuntimeError('Installed legacy public key differs from the pinned model key; trust is preserved and adoption is refused')
    passwd = base64.b64decode(read('etc/passwd')['data']).decode()
    users = [line.split(':') for line in passwd.splitlines() if line.startswith('deck:')]
    if len(users) != 1:
        raise RuntimeError('Expected exactly one legacy deck account')
    uid, gid = int(users[0][2]), int(users[0][3])
    operations = {}
    def add(name, component, before, after):
        _relative(name)
        if not isinstance(component, str) or not re.fullmatch(r'_?[a-z][a-z0-9-]*', component):
            raise RuntimeError('Unknown legacy component identity')
        before, after = _normal_snapshot(before), _normal_snapshot(after)
        current = _normal_snapshot(read(name, user_uid=uid if name.startswith('home/deck/') else None))
        if after != current:
            raise RuntimeError('Legacy target changed after its recorded generation: ' + name)
        if name in operations:
            raise RuntimeError('Overlapping legacy ownership')
        cid = 'oxp3:maintenance-runtime' if component == '_maintenance' else 'oxp3:'+component
        operations[name] = {'target': name, 'component': cid, 'before': before, 'after': after}
    index_name = 'home/.oxp3-maintenance/index.json'
    if exists('home/.oxp3-maintenance/pending.json'):
        raise RuntimeError('Recover pending legacy maintenance transaction before adoption')
    if exists(index_name):
        index = document(index_name, 'maintenance-index')
        if index.get('format') != 1 or not isinstance(index.get('originals'), dict):
            raise RuntimeError('Unsupported legacy maintenance index')
        generation = index.get('slots', {}).get(slot, {}).get('current')
        if not isinstance(generation, dict) or type(generation.get('id')) is not int or not isinstance(generation.get('paths'), dict):
            raise RuntimeError('No known current legacy maintenance generation for this slot')
        if generation.get('aborted_apply'):
            raise RuntimeError('Recover aborted legacy maintenance generation before adoption')
        for name, entry in generation['paths'].items():
            _relative(name)
            scope = ('shared' if name.startswith(('home/', 'opt/')) else slot) + ':' + name
            if scope not in index['originals'] or not isinstance(entry, dict):
                raise RuntimeError('Legacy original snapshot missing')
            add(name, entry.get('component'), index['originals'][scope], entry.get('snapshot'))
        source_format = 'oxp3-maintenance-format-1'
        release = generation.get('release', public_release)
    else:
        result_name = 'home/.oxp3-installer/integration/' + slot + '/result.json'
        result = document(result_name, 'installer-result')
        if result.get('schema') != 1 or result.get('slot') != slot or not isinstance(result.get('components'), dict):
            raise RuntimeError('Unsupported legacy installer result')
        names = {name for name, entry in result['components'].items() if entry.get('status') == 'files_installed'} | {'runtime'}
        for group in (slot, 'shared'):
            for name in sorted(names):
                journal_name = 'home/.oxp3-installer/integration/' + group + '/' + name + '/state.json'
                if not exists(journal_name):
                    continue
                record = document(journal_name, 'installer-journal')
                if record.get('phase') == 'rolled_back':
                    continue
                if record.get('phase') != 'installed' or not isinstance(record.get('allowed'), list):
                    raise RuntimeError('Recover incomplete legacy installer transaction before adoption')
                for target in record['allowed']:
                    original = record['original'][target]
                    after = dict(original, exists=True, data=record['applied'][target])
                    if not original['exists']:
                        metadata = record.get('metadata', {}).get(target, {})
                        user = metadata.get('user', False)
                        after.update(mode=metadata.get('mode', 0o644), uid=uid if user else 0, gid=gid if user else 0)
                    add(target, name, original, after)
        # The old installer uses separate protected directory journals for
        # these runtimes. Reuse the pinned public, read-only decoder so runtime
        # ownership is not silently omitted from migration.
        for component, prefix in (('opti2xmx', 'opt/oxp3-opti2xmx'), ('desktop-hdr', 'opt/oxp3-desktop-gamma22')):
            if component not in names or not exists(prefix+'/.installer-state/state.json'):
                continue
            import importlib.util
            spec = importlib.util.spec_from_file_location('oxp3_legacy_adoption', PACKAGE/'payload/legacy/maintenance/app/oxp3_maintenance/adoption.py')
            legacy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(legacy)
            for target, entry in legacy._directory_originals(root, component).items():
                add(target, component, entry['original'], entry['applied'])
        source_format = 'oxp3-installer-logical-files-v1'
        release = result.get('release', public_release)
    if not operations:
        raise RuntimeError('No verified legacy managed files to adopt')
    if len(operations) > 20000 or sum(len(item['before'].get('data', '')) + len(item['after'].get('data', '')) for item in operations.values()) > 1024**3:
        raise RuntimeError('Legacy adoption exceeds migration limits')
    components = {}
    for item in sorted(operations.values(), key=lambda value: value['target']):
        components.setdefault(item['component'], []).append({key: item[key] for key in ('target', 'before', 'after')})
    return {'schema_version': 1, 'kind': 'LegacyAdoptionReceipt', 'device_id': 'oxp3', 'slot': slot,
            'source_format': source_format, 'source_release': release, 'evidence': evidence,
            'trusted_public_key': next(item for item in evidence if item['role'] == 'trusted-public-key'),
            'components': [{'id': name, 'version': release.get('version', '1.0.6'), 'operations': entries} for name, entries in sorted(components.items())],
            'preserve_legacy': True, 'translation_complete': True, 'migration_complete': False,
            'remaining': 'Generic engine must authenticate the receipt, recheck live before/after snapshots, and commit ownership.'}


def write_adoption_receipt(root, slot, destination):
    expected_key = (PACKAGE/'payload/legacy/maintenance/app/trusted-public-key.pem').read_bytes()
    value = collect_adoption(root, slot, expected_key)
    destination = Path(destination)
    if not destination.is_absolute():
        raise RuntimeError('Receipt destination must be absolute')
    for parent in (destination.parent, *destination.parent.parents):
        info = parent.lstat()
        if parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Receipt parent must be root owned and protected')
    data = (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {'receipt': str(destination), 'sha256': hashlib.sha256(data).hexdigest(), 'translation_complete': True,
            'migration_complete': False, 'components': len(value['components']), 'files': sum(len(item['operations']) for item in value['components'])}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'verify', 'restore', 'adopt'))
    parser.add_argument('--slot', choices=('A', 'B'))
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.action == 'adopt':
        if not args.slot or not args.receipt:
            parser.error('adopt requires --slot and --receipt')
        print(json.dumps(write_adoption_receipt(target_root(metadata_only=True), args.slot, args.receipt)))
    else:
        print(json.dumps(run(args.action)))
