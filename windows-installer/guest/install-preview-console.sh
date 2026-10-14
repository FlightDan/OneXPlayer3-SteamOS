#!/bin/sh
# Shared by fresh image generation and migration of our own preview copies.
set -eu
console=/mnt/root/usr/local/lib/oxp3-installer/console
modules=/mnt/root/usr/lib/x86_64-linux-gnu/kmscon
if test -e "$modules" && ! test -f "$console/oxp3-owned"; then
    echo 'Existing kmscon module directory is not owned by this preview; refusing replacement' >&2
    exit 1
fi
mkdir -p "$console" "$modules"
cp -R /mnt/payload/console/. "$console/"
cp /mnt/payload/console/modules/mod-bbulk.so "$modules/mod-bbulk.so"
printf 'development preview console\n' > "$console/oxp3-owned"
chmod -R go-w "$console" "$modules"
chmod 0755 "$console/kmscon"
chmod 0644 "$console/libtsm.so.4" "$modules/mod-bbulk.so"
cp /mnt/payload/tasks/preview-launcher.py /mnt/root/usr/local/lib/oxp3-installer/preview-launcher.py
sh /mnt/payload/tasks/install-ui-files.sh
chmod 0755 /mnt/root/usr/local/lib/oxp3-installer/preview-launcher.py
# Test the exact executable and its glibc dependencies inside the target root.
chroot /mnt/root /usr/bin/env LD_LIBRARY_PATH=/usr/local/lib/oxp3-installer/console \
    /usr/local/lib/oxp3-installer/console/kmscon --help >/tmp/oxp3-console-help.txt 2>&1
grep -q 'font-engine' /tmp/oxp3-console-help.txt
cat > /mnt/root/etc/systemd/system/oxp3-preview.service <<'UNIT'
[Unit]
Description=OXP3 read-only DRM installation preview
After=multi-user.target systemd-user-sessions.service
Conflicts=display-manager.service getty@tty1.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/lib/oxp3-installer/preview-launcher.py
StandardInput=null
StandardOutput=journal+console
StandardError=journal+console
KillMode=control-group
[Install]
WantedBy=oxp3-preview.target
UNIT
