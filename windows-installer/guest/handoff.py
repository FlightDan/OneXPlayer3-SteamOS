"""Bind a Windows preview to fresh Linux metadata. Read-only; grants no write capability."""
from uuid import UUID
from layout import plan
from component_choice import selected


def guid(value):
    try:
        parsed = UUID(value)
        if parsed.int == 0: raise ValueError()
        return str(parsed)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Missing or invalid GPT identity') from None


def integer(value):
    if type(value) is not int or value < 0: raise ValueError('Invalid byte count or sector size')
    return value


def bind(selection, candidates):
    selected(selection)
    if selection.get('schema') != 1 or selection.get('handoff_schema') != 1:
        raise ValueError('Recreate media with a supported Windows disk snapshot')
    if selection.get('stage') != 'preview_only' or selection.get('allow_disk_write') is not False:
        raise ValueError('Unsupported handoff capabilities')
    target = selection.get('target')
    if not target or not target.get('Identity'): raise ValueError('No verifiable Windows target selection')
    identity = target['Identity']; disk_id = guid(identity.get('DiskGuid'))
    matching = []
    for candidate in candidates:
        try: candidate_id = guid(candidate['table'].get('id'))
        except ValueError: continue
        if candidate_id == disk_id: matching.append(candidate)
    if len(matching) != 1: raise ValueError('Selected GPT disk is missing or duplicated')
    candidate = matching[0]; table = candidate['table']
    if integer(candidate['size']) != integer(target['DiskSize']): raise ValueError('Selected disk capacity changed')
    if integer(identity['SectorSize']) != 512 or integer(candidate['sector_size']) != 512 or table.get('sectorsize') != 512:
        raise ValueError('Unsupported or changed logical sector size')
    expected = {}
    for partition in identity['Partitions']:
        key = guid(partition['Guid'])
        if key in expected: raise ValueError('Duplicate original partition identity')
        expected[key] = (integer(partition['Offset']), integer(partition['Size']), guid(partition['GptType']))
    actual = {}
    for partition in table['partitions']:
        key = guid(partition.get('uuid'))
        if key in actual: raise ValueError('Duplicate live partition identity')
        actual[key] = (integer(partition['start']) * 512, integer(partition['size']) * 512, guid(partition.get('type')))
    if actual != expected: raise ValueError('Original partition layout changed since Windows selection')
    start, size = integer(target['Start']), integer(target['Size'])
    parts = plan(table, start, size)
    visible = selection.get('layout')
    filesystems = {name: ('vfat' if name == 'esp' or name.startswith('efi-') else 'btrfs' if name.startswith('rootfs-') else 'ext4') for name in [p['name'] for p in parts]}
    expected_layout = [{'name': p['name'], 'start': p['start'] * 512, 'size': p['size'] * 512, 'filesystem': filesystems[p['name']]} for p in parts]
    if visible != expected_layout: raise ValueError('Windows layout differs from the live Linux space plan')
    # Windows Disk is a display label only. Linux device comes from the live table.
    return {'schema': 1, 'status': 'matched', 'device': table['device'], 'disk_guid': disk_id,
            'range': {'start': start, 'size': size}, 'append_layout': parts,
            'protected_table': table, 'allow_disk_write': False,
            'pending': 'Explicit installation confirmation and physical release acceptance'}
