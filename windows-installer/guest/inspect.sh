#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
test "$(cat /sys/block/vdc/ro)" = 1
printf '\nOXP_IMAGE_LAYOUT_BEGIN\n'
sfdisk --json /dev/vdc
blkid /dev/vdc* || true
printf '\nOXP_IMAGE_LAYOUT_END\n'
mkdir -p /mnt/source
for partition in /dev/vdc[0-9]*; do
    if mount -o ro "$partition" /mnt/source; then
        printf '\nOXP_PARTITION=%s\n' "$partition"
        if test -f /mnt/source/etc/os-release; then
            find /mnt/source/etc/inputplumber /mnt/source/usr/share/inputplumber /mnt/source/usr/lib/inputplumber -iname '*onex*' 2>/dev/null || true
            ls -ld /mnt/source/etc/pacman.conf /mnt/source/var/lib/pacman /mnt/source/usr/lib/holo/pacmandb || true
            for map in /mnt/source/usr/share/inputplumber/*/*onex* /mnt/source/etc/inputplumber/*/*onex*; do
                if test -f "$map"; then printf '\nOXP_MAP=%s\n' "$map"; cat "$map"; fi
            done
            cat /mnt/source/etc/pacman.conf || true
        fi
        for file in /mnt/source/etc/os-release /mnt/source/etc/fstab /mnt/source/EFI/steamos/grub.cfg /mnt/source/deck/tools/repair_device.sh /mnt/source/deck/tools/repair_system.sh /mnt/source/deck/tools/repair_reimage.sh /mnt/source/usr/bin/steamos-chroot /mnt/source/usr/bin/steamos-partsets /mnt/source/usr/bin/steamos-bootconf; do
            if test -f "$file"; then printf '\nOXP_FILE=%s\n' "$file"; cat "$file"; fi
        done
        find /mnt/source -maxdepth 3 -name '*repair*' -o -name '*grub*' -o -name '*os-release*' 2>/dev/null || true
        umount /mnt/source
    else
        printf 'Partition cannot be mounted read-only: %s\n' "$partition"
        exit 1
    fi
done
printf '\nOXP_TASK_RESULT=passed\n'
