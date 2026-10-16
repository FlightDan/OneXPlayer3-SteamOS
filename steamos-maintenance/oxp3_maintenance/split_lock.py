# SPDX-License-Identifier: MIT
# Derived from kas5852's PR #16 and the 20261015 fix pack.
# Copyright (c) 2026 HANA & Claude. The complete upstream license is shipped
# in components/split-lock/UPSTREAM_LICENSE and installed with this repair.
"""Reviewed boot-file transformation; never imports a downloaded generator."""
import re

GRUB = 'efi/EFI/steamos/grub.cfg'
DROPIN = 'etc/default/grub.d/oxp3-splitlock.cfg'
BOOT_REPAIRS = frozenset({'gm7-resume', 'split-lock'})
DROPIN_DATA = b'''# Steam split-lock report flood workaround; upstream kas5852, PR #16.
# Copyright (c) 2026 HANA & Claude; MIT (see accompanying UPSTREAM_LICENSE).
# Revert this setting through the component transaction, then reboot.
GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} split_lock_detect=off"
'''


def patch_grub(text):
    lines = text.splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        if re.match(r'^\s*(?:steamenv_boot|linux|linuxefi)\s', line) and '/boot/vmlinuz-' in line:
            tokens = line.split()
            if any(token.startswith('#') for token in tokens) or '\\' in line or ';' in line:
                raise ValueError('Inline boot comments/continuations require manual review')
            flags = [token for token in tokens if token.startswith('split_lock_detect=')]
            if any(flag != 'split_lock_detect=off' for flag in flags) or len(flags) > 1:
                raise ValueError('Conflicting split-lock boot setting; preserve it for review')
            if not flags:
                ending = '\r\n' if line.endswith('\r\n') else '\n'
                lines[index] = line.rstrip('\r\n') + ' split_lock_detect=off' + ending
            count += 1
    if not count:
        raise ValueError('No supported Valve kernel boot entries in mounted slot EFI')
    return ''.join(lines)


def restore_group(paths):
    """Only these two managed repairs can share this exact boot file."""
    boot = paths.get(GRUB, {})
    owners = {entry.get('component') for entry in paths.values() if isinstance(entry, dict)}
    return sorted(BOOT_REPAIRS) if boot.get('component') in BOOT_REPAIRS and BOOT_REPAIRS <= owners else []


def require_joint_restore(paths, selected):
    group = restore_group(paths)
    if group and set(selected).intersection(group) and not set(group) <= set(selected):
        raise ValueError('GM7 suspend recovery and split-lock share Valve boot settings; explicitly select both gm7-resume and split-lock to restore them together')
