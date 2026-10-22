"""Explicit private export of verified legacy adoption metadata.

The pure translator below is mirrored from boiler-device/adapter.py. It does not
execute that adapter's installation hooks. Its existing directory-journal decoder
is imported from this authenticated installed maintenance package instead of a
model payload. Original code is AGPL-3.0-only; see the repository LICENSE.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat


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


def collect_adoption(root, slot, expected_key, *, legacy_slot, reader=None):
    """Translate exact known OXP3 metadata; never mutate old journals or keys.

    The returned receipt contains private original snapshots. A generic engine
    must validate it again and commit ownership before calling migration done.
    ``slot`` is the explicit A/B installer label; ``legacy_slot`` separately
    selects the maintenance index/originals identity and is never inferred.
    """
    root = Path(root).absolute()
    if slot not in ('A', 'B'):
        raise RuntimeError('Explicit legacy slot is required')
    if not isinstance(legacy_slot, str) or not re.fullmatch(r'(?:partuuid-[a-z0-9-]{8,64}|[AB])', legacy_slot):
        raise RuntimeError('Explicit stable legacy slot identity is required')
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
        generation = index.get('slots', {}).get(legacy_slot, {}).get('current')
        if not isinstance(generation, dict) or type(generation.get('id')) is not int or not isinstance(generation.get('paths'), dict):
            raise RuntimeError('No known current legacy maintenance generation for this slot')
        if generation.get('aborted_apply'):
            raise RuntimeError('Recover aborted legacy maintenance generation before adoption')
        for name, entry in generation['paths'].items():
            _relative(name)
            scope = ('shared' if name.startswith(('home/', 'opt/')) else legacy_slot) + ':' + name
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
            raw(prefix+'/.installer-state/state.json', 'installer-runtime-journal')
            from . import adoption as legacy
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
    return {'schema_version': 1, 'kind': 'LegacyAdoptionReceipt', 'device_id': 'oxp3', 'slot': slot, 'legacy_slot': legacy_slot,
            'source_format': source_format, 'source_release': release, 'evidence': evidence,
            'trusted_public_key': next(item for item in evidence if item['role'] == 'trusted-public-key'),
            'components': [{'id': name, 'version': release.get('version', '1.0.6'), 'operations': entries} for name, entries in sorted(components.items())],
            'preserve_legacy': True, 'translation_complete': True, 'migration_complete': False,
            'remaining': 'Generic engine must authenticate the receipt, recheck live before/after snapshots, and commit ownership.'}


def _private_directory(destination):
    """Open each protected ancestor without following links; return its fd."""
    destination = Path(destination)
    if not destination.is_absolute() or '..' in destination.parts or destination.name in ('', '.', '..'):
        raise RuntimeError('An absolute private receipt filename is required')
    descriptor = os.open(destination.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in destination.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise RuntimeError('Receipt ancestors must be protected root-owned directories')
        info = os.fstat(descriptor)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError('Receipt parent must be an existing private root-owned directory')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_receipt(destination, data):
    """Publish a complete create-only 0600 receipt in a protected directory."""
    destination = Path(destination)
    directory = _private_directory(destination)
    temporary = '.adoption-export-'+secrets.token_hex(16)
    descriptor = None
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # link(2) is an atomic no-replace publication. Unlike rename, it cannot
        # overwrite any preexisting file, symlink, or previous receipt.
        os.link(temporary, destination.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.unlink(temporary, dir_fd=directory)
        created = False
        os.fsync(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def _collect_export(root, slot, expected_key, *, legacy_slot):
    """Recheck evidence under the old lock, preserving separate slot identities."""
    root = Path(root)
    lifecycle = root/'home/.oxp3-maintenance/live-operation.json'
    if os.path.lexists(lifecycle):
        snapshot = _protected_snapshot(root, lifecycle.relative_to(root).as_posix())
        if snapshot['mode'] & 0o077:
            raise RuntimeError('Legacy lifecycle state is not private')
        record = json.loads(base64.b64decode(snapshot['data']), object_pairs_hook=_pairs)
        if record.get('phase') != 'coherent' or record.get('slot') != legacy_slot:
            raise RuntimeError('Recover the legacy live operation before adoption export')
    receipt = collect_adoption(root, slot, expected_key, legacy_slot=legacy_slot)
    if os.path.lexists(lifecycle):
        receipt['evidence'].append({'path': lifecycle.relative_to(root).as_posix(), 'role': 'legacy-lifecycle',
                                    'sha256': hashlib.sha256(base64.b64decode(snapshot['data'])).hexdigest(),
                                    'size': len(base64.b64decode(snapshot['data']))})
    for evidence in receipt['evidence']:
        data = base64.b64decode(_protected_snapshot(root, evidence['path'])['data'])
        if len(data) != evidence['size'] or hashlib.sha256(data).hexdigest() != evidence['sha256']:
            raise RuntimeError('Legacy evidence changed during adoption export')
    for component in receipt['components']:
        for operation in component['operations']:
            after = operation['after']
            actual = _normal_snapshot(_protected_snapshot(root, operation['target'],
                                      user_uid=after.get('uid') if operation['target'].startswith('home/deck/') else None))
            if actual != after:
                raise RuntimeError('Legacy target changed during adoption export')
    # Check absent/pending state again as it is deliberately not synthesized
    # into an ownership record. The old transaction lock excludes old writers.
    if os.path.lexists(root/'home/.oxp3-maintenance/pending.json'):
        raise RuntimeError('Recover the pending legacy transaction before adoption export')
    return receipt


def export_live(destination):
    """Only the installed privileged CLI calls this fixed live-system action."""
    from . import operations, probe
    operations.require_root()
    operations.trusted_code()
    if not destination:
        raise RuntimeError('export-adoption requires --output in an existing root-private directory')
    system = probe.live()
    if not system.get('compatible') or not system.get('device_supported'):
        raise RuntimeError('This legacy adoption bridge requires the supported OXP3 SteamOS baseline')
    topology = system.get('slot', {})
    slot, legacy_slot = topology.get('label'), topology.get('id')
    # A/B labels select the historical installer's logical journals only. Live
    # maintenance generations, originals and lifecycle always use the probed
    # PARTUUID identity. Never guess an A/B fallback key in a live index.
    if slot not in ('A', 'B') or not isinstance(legacy_slot, str) or not re.fullmatch(r'partuuid-[a-z0-9-]{8,64}', legacy_slot):
        raise RuntimeError('Verified A/B label and stable live legacy slot identity are required')
    key = (Path(__file__).resolve().parent.parent/'trusted-public-key.pem').read_bytes()
    store = operations.store_for(system)
    with store.lock():
        again = probe.live()
        if again != system:
            raise RuntimeError('Live target identity changed before adoption export')
        receipt = _collect_export(Path('/'), slot, key, legacy_slot=legacy_slot)
        data = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
        _write_receipt(destination, data)
    return {'status': 'adoption_receipt_exported', 'slot': slot, 'legacy_slot': legacy_slot, 'path': str(destination),
            'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
            'components': [item['id'] for item in receipt['components']],
            'migration_complete': False, 'preserve_legacy': True,
            'remaining': 'Review the private receipt and explicitly adopt it with the trusted Boiler runtime.'}
