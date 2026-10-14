#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/class/dmi/id/sys_vendor)" = QEMU
test "$(cat /sys/block/vdd/size)" = 167772160
python3 - <<'PY'
import json, subprocess
table = json.loads(subprocess.check_output(['sfdisk','--json','/dev/vdd']))['partitiontable']
if [p.get('name') for p in table['partitions']] != ['Windows EFI fixture','Windows data fixture','esp','efi-A','efi-B','rootfs-A','rootfs-B','var-A','var-B','home']:
    raise RuntimeError('Only the managed virtual deployment fixture is accepted')
PY
mkdir -p /mnt/target /mnt/windows
cleanup() {
    sync
    if mountpoint -q /mnt/target; then btrfs property set -ts /mnt/target ro true 2>/dev/null || true; fi
    umount -R /mnt/target 2>/dev/null || true
    umount /mnt/windows 2>/dev/null || true
}
trap cleanup EXIT
mount -t btrfs /dev/vdd6 /mnt/target
# An interrupted earlier fixture run can leave the test subvolume writable.
# The fixture always has a read-only baseline; restore it before retrying.
btrfs property set -ts /mnt/target ro true
test "$(btrfs property get -ts /mnt/target ro)" = 'ro=true'
grep -qx 'VERSION_ID=3.8.14' /mnt/target/etc/os-release
grep -qx 'BUILD_ID=20260707.10' /mnt/target/etc/os-release
btrfs property set -ts /mnt/target ro false
mount /dev/vdd8 /mnt/target/var
mount /dev/vdd10 /mnt/target/home
install -d -o 1000 -g 1000 /mnt/target/home/deck/homebrew
for directory in dev proc sys run; do mount --bind /$directory /mnt/target/$directory; done
mount -t tmpfs tmpfs /mnt/target/tmp
ip link set lo up
python3 -B /mnt/payload/tasks/plugin-test.py
btrfs property set -ts /mnt/target ro true
cleanup
mount -t ntfs-3g -o ro /dev/vdd2 /mnt/windows
test "$(cat /mnt/windows/preserved.txt)" = 'Windows fixture data must survive partition append.'
umount /mnt/windows
printf '\nOXP_TASK_RESULT=passed\n'
