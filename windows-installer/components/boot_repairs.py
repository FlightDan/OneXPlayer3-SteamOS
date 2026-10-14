"""Offline GM7 boot repair; only the reviewed destination disk selects it."""
from pathlib import Path
import re

GRUB_DROPIN = 'etc/default/grub.d/oxp3-nvme.cfg'
GRUB_CONFIG = 'efi/EFI/steamos/grub.cfg'


def affected_gm7(target):
    return (isinstance(target, dict) and target.get('bus') == 'NVMe'
            and isinstance(target.get('model'), str)
            and re.search(r'\bGM7\b', target['model'], re.I) is not None)


def gm7_files(root, target):
    if not affected_gm7(target):
        return {}
    # Both slot EFI partitions must be mounted by the offline image runner.
    path = Path(root) / GRUB_CONFIG
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('GM7 repair requires the mounted slot EFI grub.cfg')
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        # Valve generates steamenv_boot, including its fallback menu entries.
        if re.match(r'^\s*(?:steamenv_boot|linux|linuxefi)\s', line) and '/boot/vmlinuz-' in line:
            tokens = line.split()
            overrides = [x for x in tokens if x.startswith(('nvme.noacpi=', 'nvme.quirks='))]
            if any(x != 'nvme.noacpi=1' for x in overrides):
                raise RuntimeError('Conflicting existing NVMe tuning; preserve it for review')
            if 'nvme.noacpi=1' not in tokens:
                lines[index] = line.rstrip('\r\n') + ' nvme.noacpi=1\n'
            count += 1
    if not count:
        raise RuntimeError('No supported Valve kernel boot entry in slot EFI')
    # Retain the setting when this system regenerates its boot configuration.
    dropin = ('# Selected destination: Predator GM7; accepted suspend workaround.\n'
              'GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} nvme.noacpi=1"\n')
    return {GRUB_DROPIN: {'data': dropin.encode()},
            GRUB_CONFIG: {'data': ''.join(lines).encode()}}
