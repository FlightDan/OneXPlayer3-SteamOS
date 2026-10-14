#!/bin/sh
# Development-only migration of our own preview copy to the current generator.
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_ui_model.py
python3 -B /mnt/payload/tasks/test_component_choice.py
test "$(cat /sys/block/vdc/ro)" = 0
mkdir -p /mnt/root /mnt/efi /mnt/home
cleanup() {
    if mountpoint -q /mnt/root; then btrfs property set -ts /mnt/root ro true 2>/dev/null || true; fi
    sync
    umount /mnt/home 2>/dev/null || true
    umount /mnt/efi 2>/dev/null || true
    umount /mnt/root 2>/dev/null || true
}
trap cleanup EXIT
mount -t btrfs /dev/vdc3 /mnt/root
test "$(btrfs property get -ts /mnt/root ro)" = 'ro=true'
grep -qx 'VERSION_ID=3.8.14' /mnt/root/etc/os-release
python3 - <<'PY'
import json
from pathlib import Path
selection = json.loads(Path('/mnt/root/usr/local/share/oxp3-installer/selection.json').read_text())
if selection.get('stage') != 'preview_only' or selection.get('allow_disk_write') is not False:
    raise RuntimeError('Only a previously generated development preview can be refined')
PY
btrfs property set -ts /mnt/root ro false
owned_layer=0
if test -f /mnt/root/usr/local/share/oxp3-installer/media-layer.json; then
    python3 -B /mnt/payload/tasks/media_layer.py start-refresh /mnt/root
    owned_layer=1
fi
cp /mnt/payload/tasks/preview.py /mnt/root/usr/local/lib/oxp3-installer/preview.py
cp /mnt/payload/tasks/handoff.py /mnt/payload/tasks/layout.py /mnt/root/usr/local/lib/oxp3-installer/
chmod 0644 /mnt/root/usr/local/lib/oxp3-installer/handoff.py /mnt/root/usr/local/lib/oxp3-installer/layout.py
chmod 0755 /mnt/root/usr/local/lib/oxp3-installer/preview.py
sh /mnt/payload/tasks/install-preview-console.sh
if test -f /mnt/payload/selection.json; then
    mount /dev/vdc5 /mnt/home
    python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '/mnt/payload/tasks')
from resources import stage_resources, publish
file = Path('/mnt/root/usr/local/share/oxp3-installer/selection.json')
current = json.loads(file.read_text())
requested = json.loads(Path('/mnt/payload/selection.json').read_text())
if set(requested) != {'resources'}: raise RuntimeError('Only resource choices can change in this migration')
current['resources'] = requested['resources']
stage_resources(current, Path('/mnt/payload/resources'), Path('/mnt/home'))
publish(file, (json.dumps(current, indent=2) + '\n').encode())
print('OXP_RESOURCE_UPDATE=public-resources-staged-not-installed')
PY
fi
python3 - <<'PY'
from pathlib import Path
for filename in ('oxp3-preview.target', 'oxp3-preview.service'):
    file = Path('/mnt/root/etc/systemd/system') / filename
    text = file.read_text()
    if 'Conflicts=' not in text:
        text = text.replace('After=multi-user.target\n', 'After=multi-user.target\nConflicts=display-manager.service getty@tty1.service\n', 1)
        file.write_text(text)
PY
mount /dev/vdc2 /mnt/efi
test -f /mnt/efi/EFI/steamos/grub.cfg.oxp3-original
python3 - <<'PY'
from pathlib import Path
file = Path('/mnt/efi/EFI/steamos/grub.cfg')
lines = file.read_text().splitlines(); matched = 0
for index, line in enumerate(lines):
    if 'steamenv_boot' in line and '/boot/vmlinuz-' in line:
        if 'systemd.unit=oxp3-preview.target' not in line: raise RuntimeError('Not a preview kernel entry')
        lines[index] = '\t' + ' '.join(word for word in line.split() if word not in ('nomodeset', 'fsck.mode=auto'))
        matched += 1
if matched != 3: raise RuntimeError('Unexpected recovery boot configuration')
file.write_text('\n'.join(lines) + '\n')
PY
if test "$owned_layer" = 1; then python3 -B /mnt/payload/tasks/media_layer.py finalize /mnt/root; fi
btrfs property set -ts /mnt/root ro true
printf '\nOXP_TASK_RESULT=passed\n'
