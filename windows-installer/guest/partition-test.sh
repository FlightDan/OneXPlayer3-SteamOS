#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
# This path is wired only by the development harness to its NEW 80 GiB qcow2 disk.
# Refuse execution outside that QEMU fixture; this is not a production installer.
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vdd/size)" = 167772160
test ! -e /dev/vdd1
printf 'label: gpt\nstart=2048,size=131072,type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B,name="Windows EFI fixture"\nstart=133120,size=20971520,type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7,name="Windows data fixture"\n' | sfdisk /dev/vdd
mdev -s
mkfs.vfat /dev/vdd1
mkntfs -F -Q /dev/vdd2
mkdir -p /mnt/windows
mount /dev/vdd1 /mnt/windows
printf 'Windows EFI fixture file must survive deployment.\n' > /mnt/windows/preserved-efi.txt
sync
umount /mnt/windows
mount -t ntfs-3g /dev/vdd2 /mnt/windows
printf 'Windows fixture data must survive partition append.\n' > /mnt/windows/preserved.txt
sync
umount /mnt/windows
sfdisk --json /dev/vdd > /tmp/before.json
python3 - <<'PY'
import json, sys, subprocess
sys.path.insert(0, '/mnt/payload/tasks')
from layout import plan, GIB, MIB
before = json.load(open('/tmp/before.json'))['partitiontable']
start = 12 * GIB
parts = plan(before, start, 64 * GIB)
for bad_start, bad_size in [(MIB, 64 * GIB), (start, 32 * GIB), (start, 100 * GIB)]:
    try:
        plan(before, bad_start, bad_size)
    except ValueError:
        pass
    else:
        raise RuntimeError('Invalid selected space was not rejected')
commands = '\n'.join(f'start={p["start"]},size={p["size"]},type={p["type"]},name="{p["name"]}"' for p in parts) + '\n'
subprocess.run(['sfdisk', '--append', '/dev/vdd'], input=commands, text=True, check=True)
after = json.loads(subprocess.check_output(['sfdisk', '--json', '/dev/vdd']))['partitiontable']
if after['id'] != before['id'] or after['partitions'][:2] != before['partitions']:
    raise RuntimeError('Existing partition metadata changed')
if len(after['partitions']) != 10:
    raise RuntimeError('Unexpected result partition count')
for expected, actual in zip(parts, after['partitions'][2:]):
    for key in ('name', 'start', 'size', 'type'):
        if str(expected[key]).lower() != str(actual[key]).lower():
            raise RuntimeError('Appended partition differs from selected plan')
print('OXP_PARTITION_TEST=metadata-preserved')
PY
mdev -s
attempt=0
while test ! -b /dev/vdd2 && test "$attempt" -lt 20; do
    sleep 0.1
    mdev -s
    attempt=$((attempt + 1))
done
test -b /dev/vdd2
mount -t ntfs-3g -o ro /dev/vdd2 /mnt/windows
test "$(cat /mnt/windows/preserved.txt)" = 'Windows fixture data must survive partition append.'
umount /mnt/windows
printf '\nOXP_TASK_RESULT=passed\n'
