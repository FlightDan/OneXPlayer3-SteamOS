#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/deployment-hardstop.py interrupt
# No success marker: this guest must be killed at the explicit pause boundary.
exit 1
