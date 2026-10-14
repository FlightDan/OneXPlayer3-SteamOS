#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_fs_metadata.py
python3 -B /mnt/payload/tasks/test_intent.py
OXP_INTENT_INITIALIZE=1 . /mnt/payload/tasks/mount-intent.sh
boundary=$(cat /mnt/payload/fault-boundary.txt)
python3 -B /mnt/payload/tasks/intent-hardstop.py "$boundary"
exit 1
