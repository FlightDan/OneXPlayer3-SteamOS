#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/integration-image.py
sync
printf '\nOXP_TASK_RESULT=passed\n'
