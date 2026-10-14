#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vdd/size)" = 167772160
test "$(cat /sys/block/vdd/ro)" = 1
python3 -B /mnt/payload/tasks/ui-cancelled-check.py
printf '\nOXP_TASK_RESULT=passed\n'
