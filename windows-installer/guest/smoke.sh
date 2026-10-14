#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/block/vda/size)" = 524288
mkdir -p /mnt/probe
for filesystem in btrfs ext4; do
    case "$filesystem" in
        btrfs) mkfs.btrfs -f /dev/vda ;;
        ext4) mkfs.ext4 -F /dev/vda ;;
    esac
    mount /dev/vda /mnt/probe
    printf '%s\n' "$filesystem" > /mnt/probe/probe.txt
    sync
    umount /mnt/probe
    mount /dev/vda /mnt/probe
    test "$(cat /mnt/probe/probe.txt)" = "$filesystem"
    umount /mnt/probe
done
printf '\nOXP_TASK_RESULT=passed\n'
