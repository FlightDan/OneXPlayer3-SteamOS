#!/bin/sh
# vde is a separate 16 MiB staging disk created by the native fixture adapter.
set -eu
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vde/size)" = 32768
test "$(cat /sys/block/vde/ro)" = 0
if test "${OXP_INTENT_INITIALIZE:-0}" = 1; then
    if test -n "$(python3 -B /mnt/payload/tasks/fs_metadata.py /dev/vde TYPE)"; then
        echo 'State initialization requires a fresh empty staging disk' >&2; exit 1
    fi
    mkfs.ext4 -F -L OXP_INTENT /dev/vde
fi
state_type=$(python3 -B /mnt/payload/tasks/fs_metadata.py /dev/vde TYPE)
state_label=$(python3 -B /mnt/payload/tasks/fs_metadata.py /dev/vde LABEL)
printf 'OXP_INTENT_VOLUME=type:%s,label:%s\n' "$state_type" "$state_label"
if test "$state_type" != ext4 || test "$state_label" != OXP_INTENT; then
    echo 'Persistent staging filesystem metadata does not match' >&2; exit 1
fi
mkdir -p /mnt/session-state
mount -t ext4 /dev/vde /mnt/session-state
mkdir -m 0700 -p /mnt/session-state/oxp3
