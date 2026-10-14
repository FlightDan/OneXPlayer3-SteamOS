#!/bin/sh
set -eu
# All tools are supplied by the host on a read-only virtual FAT disk.
printf '%s\n' /media/sr0/apks > /etc/apk/repositories
mkdir -p /var/cache/apk
ln -s /var/cache/apk /etc/apk/cache
apk add --no-network --no-progress /mnt/payload/apks/*.apk
modprobe btrfs
modprobe ext4
