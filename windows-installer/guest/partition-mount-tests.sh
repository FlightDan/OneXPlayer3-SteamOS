#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
cd /mnt/payload/components
python3 -B -m unittest -v test_partition_mount.py test_partition_mount_integration.py test_ntfs_preflight.py
cd /mnt/payload/maintenance
PYTHONPATH=tests python3 -B -m unittest -v \
  test_partition_mount_entry \
  test_components.PlannerTests.test_partition_mount_is_portable_file_only_adapter_and_keeps_fstab_outside_transaction \
  test_components.PlannerTests.test_partition_mount_blocks_missing_dependency_and_unmanaged_helper
# Exercise the new VFAT mount options only against a fresh private file image.
# The VM has no host physical disks and no network (run-guest.mjs).
fixture=$(mktemp -d /root/partition-mount-vfat.XXXXXX)
cleanup() {
  if mountpoint -q "$fixture/mount"; then umount "$fixture/mount" || return; fi
  rm -rf -- "$fixture"
}
trap cleanup EXIT
mkdir "$fixture/mount"
truncate -s 64M "$fixture/card.img"
mkfs.vfat -F 32 "$fixture/card.img"
mount -t vfat -o loop,rw,exec,nosuid,nodev,uid=1000,gid=1000,fmask=0022,dmask=0022,utf8=1 "$fixture/card.img" "$fixture/mount"
printf 'private FAT32 fixture\n' > "$fixture/mount/test.txt"
test "$(stat -c '%u:%g:%a' "$fixture/mount/test.txt")" = '1000:1000:755'
umount "$fixture/mount"
mount -t vfat -o loop,ro,nosuid,nodev,utf8=1 "$fixture/card.img" "$fixture/mount"
test "$(cat "$fixture/mount/test.txt")" = 'private FAT32 fixture'
printf '\nPrivate FAT32 loop mount, permissions and remount passed.\n'
# Export a compressed disposable NTFS image for the separate SteamOS host QA.
# This is a new blank file, never a device snapshot or a release payload.
if [ -f /mnt/payload/export-ntfs-fixture ]; then
truncate -s 64M "$fixture/ntfs.img"
mkntfs -F -Q -L OXP3_PRIVATE_QA "$fixture/ntfs.img" >/dev/null 2>&1
python3 - "$fixture/ntfs.img" <<'PY'
import base64,gzip,pathlib,sys
data=gzip.compress(pathlib.Path(sys.argv[1]).read_bytes(),compresslevel=6,mtime=0)
print('NTFS_QA_CLEAN_BEGIN')
print(base64.encodebytes(data).decode(),end='')
print('NTFS_QA_CLEAN_END')
PY
fi
if [ -f /mnt/payload/partition-mount-test.sh ]; then
  adduser -D deck
  su deck -c '/bin/sh /mnt/payload/partition-mount-test.sh --download-only'
  printf '\nStandalone sh signed archive verification passed as non-root, offline.\n'
fi
printf '\nOXP_TASK_RESULT=passed\n'
