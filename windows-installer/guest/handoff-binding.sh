#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vdd/size)" = 167772160
test "$(cat /sys/block/vdd/ro)" = 1
python3 -B /mnt/payload/tasks/test_handoff.py
python3 - <<'PY'
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/mnt/payload/tasks')
from handoff import bind
table = json.loads(subprocess.check_output(['sfdisk', '--json', '/dev/vdd']))['partitiontable']
selection = json.loads(Path('/mnt/payload/selection.json').read_text())
result = bind(selection, [{'table': table, 'size': int(Path('/sys/block/vdd/size').read_text()) * 512, 'sector_size': table['sectorsize']}])
if result['device'] != '/dev/vdd' or selection['target']['Disk'] != 27 or result['allow_disk_write'] is not False:
    raise RuntimeError('Incorrect native/Linux handoff')
print('OXP_HANDOFF_BINDING=windows-disk-27-matched-live-vdd-readonly')
print('OXP_HANDOFF_PLAN_PARTS=' + str(len(result['append_layout'])))
PY
printf '\nOXP_TASK_RESULT=passed\n'
