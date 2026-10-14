#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
. /mnt/payload/tasks/mount-intent.sh
python3 -B /mnt/payload/tasks/intent-hardstop.py recover
sync
umount /mnt/session-state
printf '\nOXP_TASK_RESULT=passed\n'
