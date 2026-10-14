#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
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
python3 - <<'PY'
import json, subprocess
from pathlib import Path
table = json.loads(subprocess.check_output(['sfdisk', '--json', '/dev/vdd']))['partitiontable']
windows = [{'number': 27, 'guid': table['id'], 'sectorSize': table['sectorsize'],
            'model': 'Windows-like QEMU metadata fixture', 'size': int(Path('/sys/block/vdd/size').read_text()) * 512,
            'style': 'GPT', 'bus': 'NVMe', 'partitions': [
                {'number': index + 1, 'guid': part['uuid'], 'gptType': part['type'],
                 'offset': part['start'] * 512, 'size': part['size'] * 512}
                for index, part in enumerate(table['partitions'])]}]
print('OXP_HANDOFF_SNAPSHOT=' + json.dumps(windows, separators=(',', ':')))
PY
printf '\nOXP_TASK_RESULT=passed\n'
