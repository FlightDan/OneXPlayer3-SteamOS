#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/block/vdc/ro)" = 1
mkdir -p /mnt/source
mount -t btrfs -o ro,rescue=nologreplay /dev/vdc3 /mnt/source
chroot /mnt/source steamos-bootconf --help
umount /mnt/source
printf '\nOXP_TASK_RESULT=passed\n'
