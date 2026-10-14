"""Linux review/confirmation/append controller, currently executable only in QEMU.

Windows preview is never a write authorization. Confirmation is a separate
Linux-side record and metadata is reread immediately before partition append.
"""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import signal
import uuid

from handoff import bind
from deployment import Deployment, run, table, fs
from media_layer import inspect as inspect_media, SELECTION
from handoff import guid
from layout import plan
from component_choice import selected
from bootstrap_payload import library as bootstrap_library


def review(selection, candidates):
    bound = bind(selection, candidates)
    return {'action': 'install', 'device': bound['device'], 'disk_guid': bound['disk_guid'],
            'range': bound['range'], 'append_layout': bound['append_layout'],
            'protected_partitions': copy.deepcopy(bound['protected_table']['partitions']), 'components': selected(selection)}


def accept_current(selection, candidates, accepted):
    fresh = review(selection, candidates)
    if isinstance(accepted, dict) and 'components' not in accepted and not selected(selection): accepted = dict(accepted, components=[])
    if accepted != fresh: raise RuntimeError('Installation review was cancelled or disk metadata changed')
    return fresh


def candidate(device):
    name = Path(device).name
    return {'table': table(device), 'size': int(Path('/sys/class/block', name, 'size').read_text()) * 512,
            'sector_size': int(Path('/sys/class/block', name, 'queue/logical_block_size').read_text())}


def source_preflight(source, planned):
    if (not stat.S_ISBLK(os.stat(source).st_mode) or os.path.realpath(source) != source
            or Path('/sys/class/block', Path(source).name, 'ro').read_text().strip() != '1'):
        raise RuntimeError('Source must be a canonical read-only block device')
    source_table = table(source)
    parts = source_table['partitions']
    if (source_table.get('label') != 'gpt' or source_table.get('sectorsize') != 512
            or [p.get('name') for p in parts] != ['esp', 'efi-A', 'rootfs-A', 'var-A', 'home']):
        raise RuntimeError('Unsupported recovery source layout')
    if parts[2]['size'] > min(p['size'] for p in planned if p['name'].startswith('rootfs-')):
        raise RuntimeError('Source does not fit the new root slots')
    root = Path('/mnt/oxp3-session-source'); root.mkdir(parents=True, exist_ok=True)
    run('mount', '-t', 'btrfs', '-o', 'ro,rescue=nologreplay', parts[2]['node'], str(root))
    try:
        Deployment.check_os(None, root)
        if run('btrfs', 'property', 'get', '-ts', str(root), 'ro', capture=True).strip() != 'ro=true':
            raise RuntimeError('Source root protection is not supported')
        media = inspect_media(root)
        if media is None: raise RuntimeError('Use generated media with a recorded detachable layer')
        choice = json.loads((root / SELECTION).read_text())
        selected(choice)
        bootstrap_available = bootstrap_library(root) is not None
        if selected(choice) and not bootstrap_available: raise RuntimeError('Component selection lacks trusted bootstrap source')
    finally: run('umount', str(root))
    return {'table': source_table, 'root_uuid': fs(parts[2]['node'], 'UUID'), 'media_layer': media, 'selection': choice, 'bootstrap_available': bootstrap_available}


def partition_identity(partition):
    value = {k: v for k, v in partition.items() if k != 'node'}
    for field in ('uuid', 'type'): value[field] = guid(value[field])
    return value


def table_identity(value):
    return {**{k: v for k, v in value.items() if k not in ('device', 'partitions')},
            'partitions': [partition_identity(p) for p in value['partitions']]}


def source_identity(snapshot):
    return {**snapshot, 'table': table_identity(snapshot['table'])}


def prepare_intent(selection, before, accepted, source):
    accept_current(selection, [before], accepted)
    planned = [dict(p, uuid=str(uuid.uuid4())) for p in accepted['append_layout']]
    return {'schema': 1, 'mode': 'virtual_install_intent', 'id': str(uuid.uuid4()), 'status': 'prepared',
            'selection': copy.deepcopy(selection), 'before': copy.deepcopy(before),
            'confirmation': copy.deepcopy(accepted), 'planned': planned, 'source': copy.deepcopy(source)}


def reconcile_intent(record, current):
    """Prove unchanged protected partitions and an exact prefix of owned append."""
    if (type(record.get('schema')) is not int or record['schema'] != 1
            or record.get('mode') != 'virtual_install_intent'
            or record.get('status') not in ('prepared', 'appended', 'esp_journal_ready')):
        raise RuntimeError('Unsupported installation intent')
    guid(record['id'])
    before = record['before']; accepted = record['confirmation']
    accept_current(record['selection'], [before], accepted)
    expected = plan(before['table'], accepted['range']['start'], accepted['range']['size'])
    planned = record['planned']
    if len(planned) != len(expected): raise RuntimeError('Intent partition count changed')
    ids = [guid(p['uuid']) for p in planned]
    if len(ids) != len(set(ids)) or set(ids) & {guid(p['uuid']) for p in before['table']['partitions']}:
        raise RuntimeError('Intent partition identifiers are ambiguous')
    for wanted, actual in zip(expected, planned):
        if {k: v for k, v in actual.items() if k != 'uuid'} != wanted:
            raise RuntimeError('Intent partition plan changed')
    if current['size'] != before['size'] or current['sector_size'] != before['sector_size']:
        raise RuntimeError('Target capacity or sector format changed')
    old_table = before['table']; now = current['table']
    if {k: v for k, v in now.items() if k not in ('device', 'partitions')} != {k: v for k, v in old_table.items() if k not in ('device', 'partitions')}:
        raise RuntimeError('Target GPT identity or boundaries changed')
    count = len(old_table['partitions']); partitions = now['partitions']
    if len(partitions) < count or [partition_identity(p) for p in partitions[:count]] != [partition_identity(p) for p in old_table['partitions']]:
        raise RuntimeError('Protected partition metadata changed')
    appended = partitions[count:]
    if len(appended) > len(planned): raise RuntimeError('Unexpected partitions after the protected layout')
    for wanted, actual in zip(planned, appended):
        if partition_identity(actual) != partition_identity(wanted):
            raise RuntimeError('Appended partition is not owned by this intent')
    if record['status'] != 'prepared' and len(appended) != len(planned):
        raise RuntimeError('Previously appended partitions disappeared')
    return {'count': len(appended), 'remaining': planned[len(appended):],
            'range': copy.deepcopy(accepted['range']), 'device': now['device']}


def resume_review(record, current):
    match = reconcile_intent(record, current)
    return {'action': 'resume', 'id': record['id'], 'device': match['device'],
            'disk_guid': guid(current['table']['id']), 'range': match['range'],
            'already_appended': match['count'], 'remaining': copy.deepcopy(match['remaining']),
            'protected_partitions': copy.deepcopy(current['table']['partitions'][:len(record['before']['table']['partitions'])]), 'components': selected(record['selection'])}


def pause_boundary(fault, value):
    if fault == 'pause-' + value:
        run('sync')
        print('OXP_INSTALL_HARDSTOP=' + value + ':intent-durable', flush=True)
        while True: signal.pause()


def execute_virtual(selection, source, target, confirmation, journal=None, fault=None):
    # The same review and deployment logic will serve the boot UI after release
    # acceptance. There is no physical override or automatic confirmation here.
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
        raise RuntimeError('Physical installation release acceptance is pending')
    if confirmation is None: return None
    if journal is None: raise RuntimeError('A durable staging intent is required before target writes')
    journal.require_durable_mount(target)
    with journal.locked():
        return _execute_locked(selection, source, target, confirmation, journal, fault)


def _execute_locked(selection, source, target, confirmation, journal, fault):
    before = candidate(target)
    record = journal.load()
    if record:
        if record['selection'] != selection or resume_review(record, before) != confirmation:
            raise RuntimeError('A fresh resume review is required for this intent')
        accepted = record['confirmation']; pending = reconcile_intent(record, before)['remaining']
    else:
        accepted = accept_current(selection, [before], confirmation); pending = accepted['append_layout']
    if before['table']['device'] != target or before['size'] != 80 * 1024**3:
        raise RuntimeError('Not the supported disposable virtual fixture')
    if (os.path.realpath(target) != target or not stat.S_ISBLK(os.stat(target).st_mode)
            or Path('/sys/class/block', Path(target).name, 'ro').read_text().strip() != '0'
            or os.stat(source).st_rdev == os.stat(target).st_rdev):
        raise RuntimeError('Invalid writable target or source/target alias')
    devices = [target] + [p['node'] for p in before['table']['partitions']]
    numbers = {f'{os.major(os.stat(p).st_rdev)}:{os.minor(os.stat(p).st_rdev)}' for p in devices}
    if any(line.split()[2] in numbers for line in Path('/proc/self/mountinfo').read_text().splitlines()):
        raise RuntimeError('Target partitions are already mounted')
    source_snapshot = source_preflight(source, accepted['append_layout'])
    if source_snapshot['selection'].get('source') != selection.get('source') or selected(source_snapshot['selection']) != selected(selection):
        raise RuntimeError('Component choices/source differ between confirmed preview and media')
    # Source probing is read-only but can take time; rebind again before writes.
    fresh = candidate(target)
    if record:
        if source_identity(record['source']) != source_identity(source_snapshot): raise RuntimeError('Recovery source or choices changed')
        if resume_review(record, fresh) != confirmation: raise RuntimeError('Target changed after resume confirmation')
    else:
        accept_current(selection, [fresh], confirmation)
        record = prepare_intent(selection, fresh, accepted, source_snapshot)
        journal.save(record, create=True); pending = record['planned']
        print('OXP_INSTALL_SESSION=intent-persisted-before-target-write', flush=True)
    pause_boundary(fault, 'intent')
    if pending:
        commands = '\n'.join(f'start={p["start"]},size={p["size"]},type={p["type"]},uuid={p["uuid"]},name="{p["name"]}"' for p in pending) + '\n'
        print('OXP_INSTALL_SESSION=confirmed-fresh-virtual-range', flush=True)
        subprocess.run(['sfdisk', '--append', target], input=commands, text=True, check=True)
    import shutil
    if shutil.which('mdev'): run('mdev', '-s')
    else: run('udevadm', 'settle', '--timeout=10')
    match = reconcile_intent(record, candidate(target))
    if match['count'] != 8: raise RuntimeError('Partition append is incomplete')
    pause_boundary(fault, 'appended')
    if record['status'] == 'prepared':
        record['status'] = 'appended'; journal.save(record)
    result = {'schema': 1, 'mode': 'virtual_install', 'source_table': source_snapshot['table'],
              'target_table': table(target), 'range': accepted['range'], 'append_intent': copy.deepcopy(record)}
    # Deployment opens its durable ESP journal and revalidates every write node.
    return result


def handoff_to_esp(selection, journal):
    """Publish the original intent inside the deployment journal before formatting other roles."""
    with journal.locked():
        record = journal.load()
        if not record or selection['append_intent']['id'] != record['id']:
            raise RuntimeError('ESP handoff does not match the durable intent')
        reconcile_intent(record, candidate(selection['target_table']['device']))
        probe = Deployment(selection)
        try:
            probe.preflight(); probe.open_state()
            if probe.state['selection'].get('append_intent', {}).get('id') != record['id']:
                raise RuntimeError('Existing ESP journal belongs to another append intent')
            probe.state['append_intent_id'] = record['id']; probe.save()
            record['status'] = 'esp_journal_ready'; journal.save(record)
            print('OXP_INSTALL_SESSION=intent-published-in-esp-journal', flush=True)
        finally: probe.cleanup()
