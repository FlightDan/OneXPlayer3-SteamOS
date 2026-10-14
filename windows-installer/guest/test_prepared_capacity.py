"""Actual ext4/GPT growth checks on a new sparse test image, never a host disk."""
import json
import uuid
from pathlib import Path
from resize_prepared import run, planned_home
from layout import PARTS, GIB, MIB

if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
    raise RuntimeError('Managed VM required')
choice = json.loads(Path('/mnt/payload/selection.json').read_text())
root = Path('/mnt/capacity-test')
root.mkdir(exist_ok=True)
if choice['mode'] == 'create':
    if int(Path('/sys/class/block/vdc/size').read_text()) * 512 != 80 * GIB:
        raise RuntimeError('Wrong test image size')
    with open('/dev/vdc', 'rb') as disk:
        if any(disk.read(MIB)):
            raise RuntimeError('Test image is not blank')
    script = ['label: gpt', 'unit: sectors', 'start=2048, size=131072, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, name="Keep test data"']
    cursor = GIB
    for name, size, kind in PARTS + [('home', 64 * GIB - sum(p[1] for p in PARTS), '933AC7E1-2EB4-4F13-B844-0E14E2AEF915')]:
        script.append(f'start={cursor // 512}, size={size // 512}, type={kind}, uuid={uuid.uuid4()}, name="{name}"')
        cursor += size
    run('sfdisk', '/dev/vdc', input='\n'.join(script) + '\n')
    run('mkfs.ext4', '-F', '-E', 'nodiscard', '-O', 'casefold', '-T', 'huge', '-m', '0', '/dev/vdc9')
    run('mount', '/dev/vdc9', str(root))
    try:
        (root / 'capacity-sentinel.txt').write_text('Keep data through home expansion.\n')
    finally:
        run('umount', str(root))
    with open('/dev/vdc', 'r+b') as disk:
        disk.seek(MIB)
        disk.write(b'protected-partition-sentinel')
        disk.flush()
else:
    run('mount', '-o', 'ro,noload', '/dev/vdc9', str(root))
    try:
        assert (root / 'capacity-sentinel.txt').read_text() == 'Keep data through home expansion.\n'
    finally:
        run('umount', str(root))
    with open('/dev/vdc', 'rb') as disk:
        disk.seek(MIB)
        assert disk.read(28) == b'protected-partition-sentinel'
    print('OXP_CAPACITY_TEST=home-and-protected-data-preserved', flush=True)

table = json.loads(run('sfdisk', '--json', '/dev/vdc'))['partitiontable']
selection = dict(disk_id=table['id'].lower(), capacity=choice.get('capacity', 64 * GIB),
                 partitions=[dict(number=int(p['node'].removeprefix('/dev/vdc')), name=p['name'],
                                  start=p['start'], size=p['size'], uuid=p['uuid'].lower(), type=p['type'].lower()) for p in table['partitions']])
size = int(Path('/sys/class/block/vdc/size').read_text()) * 512
planned_home(table, selection, size)
for invalid in [63 * GIB, selection['capacity'] - MIB, selection['capacity'] + 1, size * 2]:
    try:
        planned_home(table, dict(selection, capacity=invalid), size)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Accepted invalid/shrinking capacity')
print('OXP_CAPACITY_TEST=invalid-capacities-refused', flush=True)
