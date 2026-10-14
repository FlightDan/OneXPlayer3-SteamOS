#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_media_layer.py
python3 -B /mnt/payload/tasks/test_ui_model.py
python3 -B /mnt/payload/tasks/test_component_choice.py
# vdc is the host-created image COPY. Its metadata must match the supported recovery source.
test "$(cat /sys/block/vdc/ro)" = 0
python3 - <<'PY'
import json, subprocess
layout = json.loads(subprocess.check_output(['sfdisk', '--json', '/dev/vdc']))['partitiontable']
expected = ['esp', 'efi-A', 'rootfs-A', 'var-A', 'home']
if layout['label'] != 'gpt' or [p.get('name') for p in layout['partitions']] != expected:
    raise RuntimeError('Unsupported official recovery partition layout')
PY
mkdir -p /mnt/root /mnt/efi /mnt/home
cleanup() {
    if mountpoint -q /mnt/root; then btrfs property set -ts /mnt/root ro true 2>/dev/null || true; fi
    sync
    umount /mnt/home 2>/dev/null || true
    umount /mnt/efi 2>/dev/null || true
    umount /mnt/root 2>/dev/null || true
}
trap cleanup EXIT
printf '\nOXP_BUILD_STEP=mount-root\n'
mount -t btrfs /dev/vdc3 /mnt/root
original_ro=$(btrfs property get -ts /mnt/root ro)
test "$original_ro" = 'ro=true'
btrfs property set -ts /mnt/root ro false
printf '\nOXP_BUILD_STEP=root-writable\n'
mount /dev/vdc2 /mnt/efi
mount /dev/vdc5 /mnt/home
test -f /mnt/root/etc/os-release
grep -qx 'VERSION_ID=3.8.14' /mnt/root/etc/os-release
grep -qx 'BUILD_ID=20260707.10' /mnt/root/etc/os-release
test -f /mnt/efi/EFI/steamos/grub.cfg
test -f /mnt/home/deck/tools/repair_device.sh
python3 -B /mnt/payload/tasks/media_layer.py begin /mnt/root
mkdir -p /mnt/root/usr/local/lib/oxp3-installer /mnt/root/usr/local/share/oxp3-installer /mnt/root/etc/systemd/system/oxp3-preview.target.wants
cp /mnt/payload/tasks/preview.py /mnt/root/usr/local/lib/oxp3-installer/preview.py
cp /mnt/payload/tasks/handoff.py /mnt/payload/tasks/layout.py /mnt/root/usr/local/lib/oxp3-installer/
chmod 0644 /mnt/root/usr/local/lib/oxp3-installer/handoff.py /mnt/root/usr/local/lib/oxp3-installer/layout.py
printf '%s\n' '{"schema":1,"stage":"preview_only","allow_disk_write":false,"device":"ONEXPLAYER 3","source":{"version":"3.8.14","build":"20260707.10"},"components":[],"plugins":[],"target":null}' > /mnt/root/usr/local/share/oxp3-installer/selection.json
if test -f /mnt/payload/selection.json; then
    python3 - <<'PY'
import json
import sys
from pathlib import Path
selection = json.loads(Path('/mnt/payload/selection.json').read_text())
if selection.get('stage') != 'preview_only' or selection.get('allow_disk_write') is not False or selection.get('components') or selection.get('plugins'):
    raise RuntimeError('Unsupported selection capabilities')
sys.path.insert(0, '/mnt/payload/tasks')
from resources import stage_resources
stage_resources(selection, Path('/mnt/payload/resources'), Path('/mnt/home'))
Path('/mnt/root/usr/local/share/oxp3-installer/selection.json').write_text(json.dumps(selection, indent=2))
PY
fi
cat > /mnt/root/etc/systemd/system/oxp3-preview.target <<'UNIT'
[Unit]
Description=OXP3 read-only installation preview
Requires=multi-user.target
After=multi-user.target
Conflicts=display-manager.service getty@tty1.service
AllowIsolate=yes
UNIT
cat > /mnt/root/etc/systemd/system/oxp3-preview.service <<'UNIT'
[Unit]
Description=OXP3 read-only installation preview
After=multi-user.target
Conflicts=display-manager.service getty@tty1.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/oxp3-installer/preview.py
StandardInput=null
StandardOutput=journal+console
StandardError=journal+console
RemainAfterExit=yes
[Install]
WantedBy=oxp3-preview.target
UNIT
ln -sf ../oxp3-preview.service /mnt/root/etc/systemd/system/oxp3-preview.target.wants/oxp3-preview.service
sh /mnt/payload/tasks/install-preview-console.sh
# Preserve the original config, and select the non-destructive console preview at boot.
test ! -e /mnt/efi/EFI/steamos/grub.cfg.oxp3-original
cp /mnt/efi/EFI/steamos/grub.cfg /mnt/efi/EFI/steamos/grub.cfg.oxp3-original
python3 - <<'PY'
from pathlib import Path
file = Path('/mnt/efi/EFI/steamos/grub.cfg')
lines = file.read_text().splitlines()
count = 0
for i, line in enumerate(lines):
    if 'steamenv_boot' in line and '/boot/vmlinuz-' in line:
        words = [w for w in line.split() if w not in ('quiet', 'splash', 'fsck.mode=auto') and not w.startswith(('fbcon=', 'systemd.unit='))]
        lines[i] = '\t' + ' '.join(words) + ' console=ttyS0,115200 console=tty1 pci=noaer modprobe.blacklist=rtsx_pci plymouth.enable=0 systemd.unit=oxp3-preview.target'
        count += 1
if count != 3:
    raise RuntimeError('Unexpected recovery boot entries; refusing to publish image')
file.write_text('\n'.join(lines) + '\n')
PY
mkdir -p /mnt/home/deck/Desktop
cat > /mnt/home/deck/Desktop/oxp3-install-preview.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=ONEXPLAYER 3 installation preview (read-only)
Exec=konsole --hold -e python3 /usr/local/lib/oxp3-installer/preview.py
Icon=drive-harddisk
Terminal=false
DESKTOP
chmod 0755 /mnt/root/usr/local/lib/oxp3-installer/preview.py /mnt/home/deck/Desktop/oxp3-install-preview.desktop
chown 1000:1000 /mnt/home/deck/Desktop/oxp3-install-preview.desktop
python3 -B /mnt/payload/tasks/media_layer.py finalize /mnt/root
sync
printf '\nOXP_BUILD_STEP=restore-readonly\n'
btrfs property set -ts /mnt/root ro true
cleanup
trap - EXIT
# Verify that the modifications survive unmount/remount, before reporting completion.
printf '\nOXP_BUILD_STEP=verify-root\n'
mount -t btrfs -o ro,rescue=nologreplay /dev/vdc3 /mnt/root || { dmesg | tail -40; cat /proc/mounts; exit 1; }
test -s /mnt/root/usr/local/lib/oxp3-installer/preview.py
grep -q 'preview_only' /mnt/root/usr/local/share/oxp3-installer/selection.json
umount /mnt/root
mount -o ro /dev/vdc2 /mnt/efi
grep -q 'systemd.unit=oxp3-preview.target' /mnt/efi/EFI/steamos/grub.cfg
umount /mnt/efi
printf '\nOXP_TASK_RESULT=passed\n'
