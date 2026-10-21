"""Generate an InputPlumber profile for an identified MCU, without DMI checks.

ExecStartPre runs this root-owned helper with WorkingDirectory=/run/oxp3-input.
Only two fixed generated profiles under that directory are ever written. The
administrator's /etc templates and every hardware interface remain read-only.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys

RUNTIME = Path('/run/oxp3-input')
TEMPLATES = Path('/etc/inputplumber/devices.d')
HIDRAW = Path('/sys/class/hidraw')
DEVICES = Path('/sys/devices')
NAMES = ('49-onexplayer_3-gyro.yaml', '50-onexplayer_3.yaml')
PLACEHOLDER = 'matches:\n  - udev:\n      sys_path: "/run/oxp3-input/no-device"\n'
LEGACY_MATCH = ('matches:\n  - dmi_data:\n      product_name: ONEXPLAYER 3\n'
                '      sys_vendor: ONE-NETBOOK\n')
MAX_TEMPLATE = 512 * 1024
_lstat = os.lstat
_fstat = os.fstat


class ProfileError(RuntimeError):
    pass


def _validate_info(info, *, directory=False):
    if (info.st_uid != 0 or info.st_mode & 0o022
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        raise ProfileError('Untrusted input profile path')


def _chain(path, *, directory=False):
    """All ancestors must be real root-owned directories, never symlinks."""
    for parent in reversed(path.parents):
        _validate_info(_lstat(parent), directory=True)
    _validate_info(_lstat(path), directory=directory)


def _mkdir(path):
    _chain(path.parent, directory=True)
    try:
        path.mkdir(mode=0o755)
    except FileExistsError:
        pass
    _chain(path, directory=True)


def _read_template(path):
    _chain(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = _fstat(stream.fileno())
        _validate_info(info)
        if info.st_size > MAX_TEMPLATE:
            raise ProfileError('Oversized input profile template')
        data = stream.read(MAX_TEMPLATE + 1)
    if len(data) > MAX_TEMPLATE or b'\x00' in data:
        raise ProfileError('Invalid input profile template size/content')
    return data.decode('utf-8')


def _sysfs_text(path):
    if path.is_symlink():
        raise ProfileError('Unexpected sysfs attribute symlink')
    with path.open('rb') as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise ProfileError('Oversized sysfs identity')
    return data.decode('ascii').strip()


def discover_mcu(hidraw=HIDRAW, devices=DEVICES):
    """Return a unique physical vendor interface; never open /dev/hidraw*."""
    found = []
    root = devices.resolve(strict=True)
    for entry in hidraw.glob('hidraw*'):
        if not re.fullmatch(r'hidraw[0-9]+', entry.name):
            continue
        try:
            device = (entry / 'device').resolve(strict=True)
            if device == root or not device.is_relative_to(root):
                continue
            fields = {}
            for line in _sysfs_text(device / 'uevent').splitlines():
                key, separator, value = line.partition('=')
                if separator:
                    if key in fields:
                        raise ProfileError('Duplicate HID identity field')
                    fields[key] = value
            if fields.get('HID_ID', '').upper() != '0003:00001A86:0000FE00':
                continue
            for parent in (device, *device.parents):
                if parent == root or not parent.is_relative_to(root):
                    break
                interface = parent / 'bInterfaceNumber'
                if os.path.lexists(interface):
                    if _sysfs_text(interface) == '02':
                        found.append(device)
                    break
        except (OSError, UnicodeError, ProfileError):
            continue
    return found[0] if len(found) == 1 else None


def render_template(text, device):
    """Rewrite only the placeholder or exact former project DMI match block."""
    # Deliberately use a narrow text contract instead of parsing and rewriting
    # arbitrary YAML. Calibration, comments and administrator formatting survive.
    newline = '\n'
    normalized = text
    if '\r' in text:
        remainder = text.replace('\r\n', '')
        if '\r' in remainder or '\n' in remainder:
            return None
        newline = '\r\n'
        normalized = text.replace('\r\n', '\n')
    keys = set()
    allowed = {'version', 'kind', 'name', 'single_source', 'maximum_sources',
               'matches', 'source_devices', 'options', 'target_devices', 'capability_map_id'}
    for line in normalized.splitlines():
        if not line or line[0].isspace() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z_][a-z_0-9]*):(?: .*)?', line)
        if match is None or match[1] not in allowed or match[1] in keys:
            return None
        keys.add(match[1])
    blocks = [block for block in (PLACEHOLDER, LEGACY_MATCH) if normalized.count(block) == 1]
    if (len(blocks) != 1
            or len(re.findall(r'^matches\s*:', normalized, re.MULTILINE)) != 1
            or len(re.findall(r'^source_devices\s*:', normalized, re.MULTILINE)) != 1
            or blocks[0] + 'source_devices:\n' not in normalized):
        return None
    path = str(device)
    if not path.startswith('/') or any(c not in '/._:-+abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in path):
        raise ProfileError('Unexpected MCU sysfs path syntax')
    replacement = ('matches:\n  - udev:\n      sys_path: "' + path + '"\n'
                   '      subsystem: "hid"\n'
                   '      vendor_id: "6790"\n'
                   '      product_id: "65024"\n'
                   '      interface_number: "2"\n')
    return text.replace(blocks[0].replace('\n', newline), replacement.replace('\n', newline), 1)


def prepare(*, runtime=RUNTIME, templates=TEMPLATES, hidraw=HIDRAW, devices=DEVICES):
    _chain(runtime, directory=True)
    output = runtime
    for part in ('rootfs', 'usr', 'share', 'inputplumber', 'devices'):
        output = output / part
        _mkdir(output)
    # Remove both generated variants first: a previous boot, changed selection,
    # or missing hardware must never keep an earlier profile active.
    for name in NAMES:
        target = output / name
        if os.path.lexists(target):
            _chain(target)
            target.unlink()
    device = discover_mcu(hidraw, devices)
    if device is None:
        return 'no-unique-mcu'
    source = next((templates / name for name in NAMES if os.path.lexists(templates / name)), None)
    if source is None:
        return 'no-template'
    rendered = render_template(_read_template(source), device)
    if rendered is None:
        return 'custom-template-preserved'
    target = output / source.name
    temporary = output / ('.profile-' + os.urandom(12).hex())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(rendered.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        _chain(output, directory=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return 'generated:' + source.name


def main():
    if os.name != 'posix' or os.geteuid() != 0:
        raise ProfileError('Input profile preparation requires the root system service')
    print('OXP3 input profile: ' + prepare())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ProfileError) as error:
        print('Input profile preparation refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
