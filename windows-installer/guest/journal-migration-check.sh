#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_fs_metadata.py
python3 -B /mnt/payload/tasks/journal-migration-check.py
printf '\nOXP_TASK_RESULT=passed\n'
