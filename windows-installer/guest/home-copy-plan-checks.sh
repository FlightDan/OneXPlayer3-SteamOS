#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
# vda is a disposable VM scratch disk, never an installation source/target.
test "$(cat /sys/class/block/vda/ro)" = 0
test "$(blockdev --getsize64 /dev/vda)" -ge 4294967296
mkdir -p /mnt/ext4-plan-fixtures
mkfs.ext4 -F -q -E lazy_itable_init=1,lazy_journal_init=1 /dev/vda
mount /dev/vda /mnt/ext4-plan-fixtures
trap 'umount /mnt/ext4-plan-fixtures' EXIT
cd /mnt/payload/tasks
TMPDIR=/mnt/ext4-plan-fixtures OXP_EXT4_REAL_FIXTURES=1 python3 -B test_ext4_copy_plan.py
# A supplied prepared source is attached read-only at vdc by the host.
if test -b /dev/vdc; then
    python3 -B /mnt/payload/tasks/ext4_copy_plan.py
fi
printf '\nOXP_TASK_RESULT=passed\n'
