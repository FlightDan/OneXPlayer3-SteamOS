#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_deployment_plan.py
python3 -B /mnt/payload/tasks/deployment-hardstop.py recover
printf '\nOXP_TASK_RESULT=passed\n'
