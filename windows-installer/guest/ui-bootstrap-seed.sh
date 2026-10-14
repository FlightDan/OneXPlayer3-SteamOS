#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vdd/size)" = 167772160
python3 - <<'PY'
import json,subprocess
table=json.loads(subprocess.check_output(['sfdisk','--json','/dev/vdd']))['partitiontable']
if [p.get('name') for p in table['partitions']] != ['Windows EFI fixture','Windows data fixture']:
    raise RuntimeError('Component install seed must preserve an unappended managed fixture')
PY
OXP_INTENT_INITIALIZE=1 . /mnt/payload/tasks/mount-intent.sh
test ! -e /mnt/session-state/oxp3/installation-intent.json
umount /mnt/session-state
printf '\nOXP_TASK_RESULT=passed\n'
