"""Read-only plans for the authenticated installer data bundle.

No module in the bundle is imported or executed. The narrowly scoped config
edits below mirror the maintained Windows installer generators; installation,
service activation and recovery belong to the transaction layer.
"""
import base64
import configparser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zipfile

from . import compatibility

VERSION = compatibility.BASE
KERNEL = compatibility.KERNEL
PLUGIN_ROOT = 'var/lib/oxp3-installer/decky/runtime/plugins'
OLD_GUARD = b'ExecCondition=/usr/bin/python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py guard'
SANDBOXED_GUARD = b'ExecCondition=/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py guard'
# The read-only guard authenticates the host root device and /home recovery
# state. systemd's per-command + prefix lets only this trusted root check see
# the host; PrivateDevices/ProtectHome and other restrictions still apply to
# ExecStart and all other service commands. Keep the guard's exit status gate.
GUARD = b'ExecCondition=+/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py guard'
PLUGIN_NAMES = {'steamgriddb': 'SteamGridDB', 'protondb': 'ProtonDB Badges',
                'tabmaster': 'TabMaster', 'css-loader': 'CSS Loader',
                'autoflatpaks': 'AutoFlatpaks', 'deck-settings': 'Deck Settings',
                'hltb': 'HLTB for Deck', 'animation-changer': 'Animation Changer'}
RESTART = {'hdr', 'desktop-hdr', 'keyboard', 'input', 'multifunction', 'gyro',
           'gamescope-env', 'wifi', 'xe-dsb', 'gm7-resume', 'split-lock', 'serial-console-policy', 'autoflatpaks-compat', 'animation-changer-compat', 'waydroid', 'overlay'}
MAX_FILE = 256 * 1024 * 1024
MAX_ARCHIVE = 1024 * 1024 * 1024


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise ValueError('Unsafe relative path: ' + repr(value))
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('Unsafe relative path: ' + value)
    return path.as_posix()


def _safe(base, relative):
    """Reject symlinks (including dangling ones) before any target/source read."""
    relative = _relative(relative)
    base = Path(base).absolute()
    current = base
    if base.is_symlink():
        raise ValueError('Symlink root is unsupported: ' + str(base))
    for index, part in enumerate(PurePosixPath(relative).parts):
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink target/source refused: ' + relative)
        if os.path.lexists(current) and index < len(PurePosixPath(relative).parts) - 1 and not current.is_dir():
            raise ValueError('Non-directory path ancestor: ' + relative)
    return current


def _read(base, relative):
    path = _safe(base, relative)
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError('Missing, special or oversized resource: ' + relative)
    return path.read_bytes()


def _existing(root, relative):
    path = _safe(root, relative)
    return _read(root, relative) if os.path.lexists(path) else None


def _trusted_executable(root, relative):
    """Resolve only trusted OS executable links, always inside the target root.

    General payload reads and transaction destinations remain symlink-free.
    Arch's /usr/bin/python3 is normally a root-owned link to python3.x.
    """
    root = Path(root).absolute()
    pending, resolved, hops = list(PurePosixPath(_relative(relative)).parts), [], 0
    if root.is_symlink():
        raise ValueError('Symlink executable root is unsupported')
    root_info = root.stat()
    if os.name == 'posix' and (root_info.st_uid != 0 or root_info.st_mode & 0o022):
        raise ValueError('Untrusted OS executable root')
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved:
                raise ValueError('Executable link escapes target root')
            resolved.pop()
            continue
        if '\\' in part or ':' in part or '\x00' in part:
            raise ValueError('Unsafe executable link')
        path = root.joinpath(*resolved, part)
        info = path.lstat()
        if os.name == 'posix' and (info.st_uid != 0 or not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
            raise ValueError('Untrusted OS executable path: ' + relative)
        if stat.S_ISLNK(info.st_mode):
            hops += 1
            if hops > 40:
                raise ValueError('Cyclic OS executable link: ' + relative)
            link = os.readlink(path)
            if link.startswith('/'):
                resolved = []
            pending = list(PurePosixPath(link).parts)[1 if link.startswith('/') else 0:] + pending
            continue
        if pending and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Non-directory OS executable ancestor: ' + relative)
        resolved.append(part)
        if not pending and (not stat.S_ISREG(info.st_mode) or os.name == 'posix' and not info.st_mode & 0o111):
            raise ValueError('OS executable dependency is not executable: ' + relative)
    if not resolved:
        raise ValueError('OS executable link has no file target')
    return root.joinpath(*resolved)


def _entry(data, mode=0o644, user=False, mutable=False):
    if not isinstance(data, bytes) or type(mode) is not int or mode not in (0o600, 0o644, 0o755):
        raise ValueError('Invalid component file metadata')
    return {'data': data, 'mode': mode, 'user': bool(user), 'mutable': bool(mutable)}


def _merge_group(data, group, values):
    """KConfig permits localized keys; preserve unrelated lines verbatim."""
    lines = (data or b'').decode('utf-8').splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == '[' + group + ']']
    if len(starts) > 1:
        raise ValueError('Ambiguous duplicate configuration group: ' + group)
    if starts:
        start = starts[0]
    else:
        lines += ['', '[' + group + ']']
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('[')), len(lines))
    body = lines[start + 1:end]
    for key, value in values.items():
        matches = [i for i, line in enumerate(body) if line.split('=', 1)[0].strip() == key]
        if len(matches) > 1:
            raise ValueError('Ambiguous duplicate configuration key: ' + key)
        if matches:
            body[matches[0]] = key + '=' + value
        else:
            body.append(key + '=' + value)
    return ('\n'.join(lines[:start + 1] + body + lines[end:]) + '\n').encode()


def _guard(data, target):
    if target.endswith('.service') and b'[Service]' in data:
        if not target.startswith('etc/systemd/system/'):
            # Match the installer system-unit boundary. A user manager cannot
            # run the root-only maintenance guard, even with the + prefix.
            # Remove only our previously injected complete command lines;
            # retain legacy device checks and third-party ExecCondition lines.
            return b''.join(line for line in data.splitlines(keepends=True)
                            if line.rstrip(b'\r\n') not in (SANDBOXED_GUARD, GUARD))
        data = data.replace(OLD_GUARD, GUARD).replace(SANDBOXED_GUARD, GUARD)
        if b'oxp3-integration/integration_runtime.py' in data:
            raise ValueError('Legacy activation reference in service: ' + target)
        if GUARD not in data:
            data = data.replace(b'[Service]', b'[Service]\n' + GUARD, 1)
    return data


def _tar_files(path, prefix, *, strip_top=False):
    output = {}
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Missing, special or oversized runtime archive')
    with tarfile.open(path) as archive:
        entries = archive.getmembers()
        if len(entries) > 12000 or sum(x.size for x in entries) > MAX_ARCHIVE:
            raise ValueError('Oversized runtime archive')
        members = {}
        for item in entries:
            name = item.name.removeprefix('./').rstrip('/')
            if name in ('', '.'):
                if item.isdir():
                    continue
                raise ValueError('Invalid runtime root entry')
            name = _relative(name)
            if name in members:
                raise ValueError('Duplicate runtime archive path')
            members[name] = item
        roots = {PurePosixPath(x).parts[0] for x in members}
        if strip_top and len(roots) != 1:
            raise ValueError('Host bundle requires one top-level directory')
        for name, item in members.items():
            if item.isdir():
                continue
            current, seen = item, set()
            while current.issym():
                if strip_top or current.name in seen:
                    raise ValueError('Unsupported or cyclic archive symlink')
                seen.add(current.name)
                link = _relative(current.linkname)
                destination = (PurePosixPath(current.name.removeprefix('./')).parent / link).as_posix()
                if destination not in members:
                    raise ValueError('Unresolved runtime symlink')
                current = members[destination]
            if not current.isfile() or current.size > MAX_FILE:
                raise ValueError('Special or oversized runtime member')
            relative = '/'.join(PurePosixPath(name).parts[1:]) if strip_top else name
            if not relative:
                raise ValueError('Runtime file has no destination')
            output[prefix + '/' + relative] = _entry(archive.extractfile(current).read(), 0o755 if current.mode & 0o111 else 0o644)
    return output


def _patch_animation_changer(files, prefix):
    """Mirror the maintained 1.3.2 canonical Steam path fix as a data edit.

    Decky may initialize before Steam creates ~/.steam/root. An upstream
    makedirs below that future link would create a directory and break Steam's
    bootstrap. No backend code is imported or executed to prepare this patch.
    """
    try:
        plugin = json.loads(files[prefix + 'plugin.json']['data'])
        package = json.loads(files[prefix + 'package.json']['data'])
        source = files[prefix + 'main.py']['data']
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Missing Animation Changer compatibility patch input') from error
    if (not isinstance(plugin, dict) or not isinstance(package, dict) or
            plugin.get('name') != 'Animation Changer' or
            package.get('name') != 'decky-animation-changer' or package.get('version') != '1.3.2'):
        raise ValueError('Unsupported Animation Changer identity or version for compatibility patch')
    original = b"OVERRIDE_PATH = os.path.expanduser('~/.steam/root/config/uioverrides/movies')"
    replacement = b"OVERRIDE_PATH = os.path.expanduser('~/.local/share/Steam/config/uioverrides/movies')"
    if not isinstance(source, bytes) or source.splitlines().count(original) != 1 or source.count(original) != 1:
        raise ValueError('Unsupported Animation Changer override path for compatibility patch')
    changed = dict(files)
    changed[prefix + 'main.py'] = dict(files[prefix + 'main.py'], data=source.replace(original, replacement, 1))
    return changed


def _zip_files(path, name, version):
    output, roots, seen = {}, set(), set()
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Missing, special or oversized plugin archive')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 3000 or sum(x.file_size for x in entries) > 128 * 1024 * 1024:
            raise ValueError('Oversized plugin archive')
        for item in entries:
            relative = _relative(item.filename.rstrip('/'))
            if relative in seen or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Duplicate or special plugin archive path')
            seen.add(relative)
            roots.add(PurePosixPath(relative).parts[0])
            if item.is_dir():
                continue
            if len(PurePosixPath(relative).parts) < 2:
                raise ValueError('Plugin file requires a root folder')
            output[PLUGIN_ROOT + '/' + relative] = _entry(archive.read(item))
    if len(roots) != 1:
        raise ValueError('Plugin must contain exactly one root folder')
    prefix = PLUGIN_ROOT + '/' + next(iter(roots)) + '/'
    # HLTB is a legitimate frontend-only plugin and has no Python backend.
    for required in ('plugin.json', 'package.json', 'dist/index.js'):
        if prefix + required not in output:
            raise ValueError('Plugin runtime file missing: ' + required)
    if name == 'animation-changer':
        output = _patch_animation_changer(output, prefix)
    if json.loads(output[prefix + 'plugin.json']['data']).get('name') != PLUGIN_NAMES[name]:
        raise ValueError('Selected plugin identity does not match archive')
    if json.loads(output[prefix + 'package.json']['data']).get('version') != version:
        raise ValueError('Pinned plugin version does not match the prepared profile')
    return output


def _hdr(payload):
    # Mirrors components/hdr/generate.py's maintained validation, reading Lua
    # as data rather than importing that generator from the selected bundle.
    data = _read(payload, 'components/hdr/upstream.lua')
    text = data.decode('utf-8')
    anchors = ('max_content_light_level = 1100,', 'max_frame_average_luminance = 472,',
               'min_content_light_level = 0.0005,', 'eotf = gamescope.eotf.gamma22,',
               'string.match(display.model, "^%s*(.-)%s*$") == "AMS881KB01-0"',
               'gamescope.hook("OnPostPaint", function()', 'local oxp3_gamma22_matched = false',
               '[60] = 1904', '[144] = 56')
    if any(text.count(x) != 1 for x in anchors) or text.count('gamescope.convars.composite_force.value = true') != 2 or 'max_frame_average_luminance = 475' in text:
        raise ValueError('Maintained HDR data is missing accepted anchors')
    return {'home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua': _entry(data, user=True)}


def _gm7(root, disk, planned):
    if not isinstance(disk, dict) or disk.get('bus') != 'NVMe' or not re.search(r'\bGM7\b', str(disk.get('model', '')), re.I):
        return None
    relative = 'efi/EFI/steamos/grub.cfg'
    source = planned[relative]['data'] if relative in planned else _read(root, relative)
    lines = source.decode().splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        if re.match(r'^\s*(?:steamenv_boot|linux|linuxefi)\s', line) and '/boot/vmlinuz-' in line:
            tokens = line.split()
            if any(x != 'nvme.noacpi=1' for x in tokens if x.startswith(('nvme.noacpi=', 'nvme.quirks='))):
                raise ValueError('Conflicting NVMe tuning; preserve for review')
            if 'nvme.noacpi=1' not in tokens:
                lines[index] = line.rstrip('\r\n') + ' nvme.noacpi=1\n'
            count += 1
    if not count:
        raise ValueError('GM7 repair requires a supported Valve boot entry in mounted slot EFI')
    dropin = b'# Selected destination: Predator GM7; accepted suspend workaround.\nGRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} nvme.noacpi=1"\n'
    grub = _entry(''.join(lines).encode(), mutable=True)
    info = _safe(root, relative).stat()
    grub.update(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)
    return {relative: grub,
            'etc/default/grub.d/oxp3-nvme.cfg': _entry(dropin)}


def _split_lock(payload, root, planned):
    from .split_lock import GRUB, DROPIN, DROPIN_DATA, patch_grub
    existing = _existing(root, DROPIN)
    if existing is not None and existing != DROPIN_DATA:
        raise ValueError('Existing split-lock drop-in differs; preserve it for review')
    source = planned[GRUB]['data'] if GRUB in planned else _read(root, GRUB)
    grub = _entry(patch_grub(source.decode()).encode(), mutable=True)
    info = _safe(root, GRUB).stat()
    grub.update(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)
    return {GRUB: grub, DROPIN: _entry(DROPIN_DATA),
            'usr/share/licenses/oxp3-split-lock/UPSTREAM_LICENSE':
                _entry(_read(payload, 'components/split-lock/UPSTREAM_LICENSE'))}


def _windows(payload, root):
    for required in ('python3', 'efibootmgr', 'systemctl', 'pkexec', 'kdialog'):
        _trusted_executable(root, 'usr/bin/' + required)
    source = payload / 'components/windows-reboot'
    metadata = json.loads(_read(source, 'plugin.json'))
    if metadata.get('name') != 'Restart into Windows' or metadata.get('flags') != ['root']:
        raise ValueError('Unexpected Windows restart plugin identity')
    output = {PLUGIN_ROOT + '/oxp3-restart-windows/' + name: _entry(_read(source, name))
              for name in ('main.py', 'plugin.json', 'package.json', 'dist/index.js')}
    for name in ('boot.py', 'desktop.py'):
        output['usr/local/lib/oxp3-windows-reboot/' + name] = _entry(_read(source, name))
    output['usr/local/bin/oxp3-reboot-windows'] = _entry(_read(source, 'oxp3-reboot-windows'), 0o755)
    for target in ('usr/share/polkit-1/actions/org.oxp3.restart-windows.policy', 'etc/polkit-1/rules.d/49-oxp3-restart-windows.rules'):
        output[target] = _entry(_read(source, target.rsplit('/', 1)[1]))
    for target in ('home/deck/Desktop/oxp3-reboot-windows.desktop', 'home/deck/.local/share/applications/oxp3-reboot-windows.desktop'):
        output[target] = _entry(_read(source, 'oxp3-reboot-windows.desktop'), 0o755, True)
    return output


def _slot_switch(payload, root, metadata, owned):
    """Update the recovery launcher as data; never invoke its boot helper."""
    if metadata.get('files') or metadata.get('runtime_archive') or metadata.get('units'):
        raise ValueError('Slot switch requires its fixed file-only maintenance adapter')
    for tool in ('python3', 'pkexec', 'kdialog', 'steamos-bootconf', 'systemctl', 'busctl'):
        _trusted_executable(root, 'usr/bin/' + tool)
    source = payload / 'components/slot-switch'
    files = {'home/.oxp3-slot-switch/' + name:
             _entry(_read(source, name), 0o755 if name == 'oxp3-switch-slot' else 0o644)
             for name in ('boot.py', 'desktop.py', 'oxp3-switch-slot')}
    files['etc/polkit-1/rules.d/49-oxp3-slot-switch.rules'] = _entry(_read(source, '49-oxp3-slot-switch.rules'))
    for target in ('home/deck/Desktop/oxp3-slot-switch.desktop',
                   'home/deck/.local/share/applications/oxp3-slot-switch.desktop'):
        files[target] = _entry(_read(source, 'oxp3-slot-switch.desktop'), 0o755, user=True)
    for relative, entry in files.items():
        target = _safe(root, relative)
        if os.path.lexists(target) and relative not in owned:
            raise ValueError('Unmanaged slot switch conflict; adopt the existing installation explicitly: ' + relative)
        if entry['user']:
            continue
        # Shared executable code and authorization rules must never inherit a
        # desktop user's writable ancestor. Store repeats path checks at write.
        for path in (target, *target.parents):
            if not path.is_relative_to(root):
                break
            if not os.path.lexists(path):
                continue
            info = path.lstat()
            if (not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or os.name == 'posix' and (info.st_uid != 0 or info.st_mode & 0o022)):
                raise ValueError('Untrusted slot switch code or authorization path: ' + relative)
    return files


def _partition_mount(payload, root, metadata, owned):
    """Update the KDE mount helper without touching its independent fstab state."""
    if metadata.get('files') or metadata.get('runtime_archive') or metadata.get('units'):
        raise ValueError('Partition mount requires its fixed file-only maintenance adapter')
    for tool in ('python3', 'pkexec', 'kdialog', 'lsblk', 'findmnt', 'systemctl', 'systemd-escape'):
        try:
            _trusted_executable(root, 'usr/bin/' + tool)
        except FileNotFoundError as error:
            raise ValueError('Partition mount dependency missing: /usr/bin/' + tool) from error
    source = payload / 'components/partition-mount'
    files = {'home/.oxp3-partition-mount/' + name:
             _entry(_read(source, name), 0o755 if name == 'oxp3-partition-mount' else 0o644)
             for name in ('mounts.py', 'desktop.py', 'oxp3-partition-mount')}
    for target in ('home/deck/Desktop/oxp3-partition-mount.desktop',
                   'home/deck/.local/share/applications/oxp3-partition-mount.desktop'):
        files[target] = _entry(_read(source, 'oxp3-partition-mount.desktop'), 0o755, user=True)
    for relative, entry in files.items():
        target = _safe(root, relative)
        if os.path.lexists(target) and relative not in owned:
            raise ValueError('Unmanaged partition mount conflict; adopt the existing installation explicitly: ' + relative)
        if entry['user']:
            continue
        for path in (target, *target.parents):
            if not path.is_relative_to(root):
                break
            if not os.path.lexists(path):
                continue
            info = path.lstat()
            if (not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or os.name == 'posix' and (info.st_uid != 0 or info.st_mode & 0o022)):
                raise ValueError('Untrusted partition mount code path: ' + relative)
    return files


def _flathub(payload, root):
    _trusted_executable(root, 'usr/bin/flatpak')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(_read(payload, 'components/flathub.flatpakrepo').decode())
    definition = parser['Flatpak Repo']
    if definition.get('Url') != 'https://dl.flathub.org/repo/' or len(base64.b64decode(definition['GPGKey'], validate=True)) < 1024:
        raise ValueError('Invalid bundled Flathub definition')
    definition['Url'] = 'https://mirrors.ustc.edu.cn/flathub'
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    files = {'etc/flatpak/remotes.d/flathub.flatpakrepo': _entry(stream.getvalue().encode(), mutable=True)}
    relative = 'var/lib/flatpak/repo/config'
    existing = _existing(root, relative)
    if existing is not None:
        parsed = configparser.ConfigParser(interpolation=None, strict=False)
        parsed.read_string(existing.decode())
        if parsed.has_section('remote "flathub"'):
            files[relative] = _entry(_merge_group(existing, 'remote "flathub"', {'url': definition['Url']}), mutable=True)
    return files


def _decky(payload, root):
    binary = _read(payload, 'plugins/decky/PluginLoader')
    if not binary.startswith(b'\x7fELF'):
        raise ValueError('Invalid Linux Decky binary')
    unit = b'''[Unit]
Description=Decky Loader (OXP3 managed)
After=network.target
[Service]
Type=simple
User=root
Restart=on-failure
KillMode=control-group
TimeoutStopSec=15
ExecStart=/var/lib/oxp3-installer/decky/runtime/services/PluginLoader
WorkingDirectory=/var/lib/oxp3-installer/decky/runtime/services
Environment=PRIVILEGED_PATH=/var/lib/oxp3-installer/decky/runtime
Environment=UNPRIVILEGED_PATH=/home/deck/homebrew
Environment=UNPRIVILEGED_USER=deck
Environment=CHOWN_PLUGIN_PATH=0
Environment=KEEP_SYSTEMD_SERVICE=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=LOG_LEVEL=INFO
[Install]
WantedBy=multi-user.target
'''
    output = {'var/lib/oxp3-installer/decky/runtime/services/PluginLoader': _entry(binary, 0o755),
              'etc/systemd/system/plugin_loader.service': _entry(unit)}
    marker = 'home/deck/.local/share/Steam/.cef-enable-remote-debugging'
    if _existing(root, marker) is None:
        output[marker] = _entry(b'', user=True)
    return output


def _materialize(name, payload, root, metadata, planned, probe, owned):
    if name == 'slot-switch':
        return _slot_switch(payload, root, metadata, owned)
    if name == 'partition-mount':
        return _partition_mount(payload, root, metadata, owned)
    if name == 'serial-console-policy':
        from .serial_console import DROPIN, files
        return files(_existing(root, DROPIN))
    if name == 'autoflatpaks-compat':
        from .autoflatpaks_compat import build_files
        return build_files(root)
    if name == 'animation-changer-compat':
        from .animation_changer_compat import build_files
        return build_files(root)
    files = {}
    for item in metadata.get('files', []):
        target = _relative(item['target'])
        if item.get('missing_only') and target not in owned:
            # Preserve image firmware, including compressed variants.
            part = PurePosixPath(target)
            parent = _safe(root, part.parent.as_posix())
            if any(os.path.lexists(parent / (part.name + suffix)) for suffix in ('', '.xz', '.zst')):
                continue
        files[target] = _entry(_read(payload / 'integration', item['source']), item.get('mode', 0o644), item.get('user', False))
    if metadata.get('runtime_archive'):
        prefixes = {'desktop-hdr': 'opt/oxp3-desktop-gamma22/6.7.3-1.6',
                    'opti2xmx': 'opt/oxp3-opti2xmx/20261005',
                    'opti2xmx-runtime': 'opt/oxp3-opti2xmx/20261005'}
        if name not in prefixes:
            raise ValueError('Unsupported runtime archive component')
        files.update(_tar_files(_safe(payload / 'integration', metadata['runtime_archive']), prefixes[name]))
    if name == 'gm7-resume':
        return _gm7(root, probe.get('target_disk'), planned)
    if name == 'split-lock':
        return _split_lock(payload, root, planned)
    if name == 'hdr':
        files = _hdr(payload)
    elif name == 'keyboard':
        _read(root, 'usr/share/applications/org.kde.plasma.keyboard.desktop')
        relative = 'home/deck/.config/kwinrc'
        files = {relative: _entry(_merge_group(_existing(root, relative), 'Wayland', {'InputMethod': '/usr/share/applications/org.kde.plasma.keyboard.desktop', 'VirtualKeyboardMode': '1'}), user=True, mutable=True)}
    elif name == 'gyro':
        helper = Path(__file__).with_name('gyro_binding.py').read_bytes()
        prefix = 'var/lib/oxp3-gyro-v1/'
        files[prefix + 'binding.py'] = _entry(helper)
        for filename, action in (('load.sh', 'start'), ('unload.sh', 'stop')):
            wrapper = '#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py ' + action + '\n'
            files[prefix + filename] = _entry(wrapper.encode(), 0o755)
        unit = files.get('etc/systemd/system/oxp3-gyro.service')
        if unit:
            unit['data'] = re.sub(rb'^TimeoutStartSec=.*$', b'TimeoutStartSec=40', unit['data'], flags=re.M)
            unit['data'] = re.sub(rb'^TimeoutStopSec=.*$', b'TimeoutStopSec=20', unit['data'], flags=re.M)
    elif name == 'multifunction':
        relative = 'etc/inputplumber/capability_maps.d/oxp3-installer.yaml'
        source = _existing(root, relative)
        if source is None:
            fallback = 'usr/share/inputplumber/capability_maps/oxp3-installer.yaml'
            source = planned[fallback]['data'] if fallback in planned else _read(root, fallback)
        text = source.decode()
        start = text.index('  - name: Keyboard key (Ctrl+Meta+O)')
        end = text.index('  - name: Orange Button', start)
        block = text[start:end]
        old = '    target_event:\n      gamepad:\n        button: Keyboard'
        new = old.replace('Keyboard', 'RightPaddle2')
        if block.count(old) + block.count(new) != 1:
            raise ValueError('Unsupported multifunction mapping; preserve custom profile for review')
        files = {relative: _entry((text[:start] + block.replace(old, new) + text[end:]).encode(), mutable=True)}
    elif name == 'flathub-ustc':
        files = _flathub(payload, root)
    elif name == 'decky':
        files = _decky(payload, root)
    elif name == 'windows-reboot':
        files = _windows(payload, root)
    elif name in PLUGIN_NAMES:
        source = 'plugins/plugins.json' if name in ('steamgriddb', 'protondb') else 'plugins/third-party.json'
        profiles = json.loads(_read(payload, source))
        matches = [profile for profile in profiles if profile.get('id') == name]
        if len(matches) != 1 or matches[0].get('name') != PLUGIN_NAMES[name] or not isinstance(matches[0].get('version'), str):
            raise ValueError('Prepared plugin profile is missing or ambiguous: ' + name)
        profile = matches[0]
        archive = _safe(payload, 'plugins/' + name + '/' + _relative(profile['archive']))
        if '/' in profile['archive']:
            raise ValueError('Prepared plugin archive must be a leaf filename')
        files = _zip_files(archive, name, profile['version'])
    elif name == 'waydroid':
        profile = json.loads(_read(payload, 'waydroid/profile.json'))
        expected = {'version': VERSION['VERSION_ID'], 'build': VERSION['BUILD_ID'], 'kernel': KERNEL}
        if profile.get('schema') != 1 or profile.get('id') != 'waydroid' or profile.get('system') != expected:
            raise ValueError('Waydroid profile does not match the accepted r2 host baseline')
        dependencies = profile.get('packages')
        if not isinstance(dependencies, dict) or not dependencies:
            raise ValueError('Waydroid host dependency fingerprint is missing')
        for package, version in dependencies.items():
            if probe.get('packages', {}).get(package) != version:
                raise ValueError('Waydroid incompatible host dependency: ' + package + ' requires ' + str(version))
        files = _tar_files(_safe(payload / 'waydroid', profile['archive']), 'usr/local/lib/oxp3-waydroid', strip_top=True)
        packages = [path for path in files if path.startswith('usr/local/lib/oxp3-waydroid/packages/') and path.endswith('.pkg.tar.zst')]
        if len(packages) != 5:
            raise ValueError('Waydroid requires the complete five-package r2 host bundle')
    if name in ('oxp3-fan', 'oxp3-cpu'):
        relative = 'var/lib/' + name + '/config.json'
        default = {'mode': 'auto'} if name == 'oxp3-fan' else {'enabled': False, 'epp': 'balance_performance', 'p_mhz': 4700, 'e_mhz': 3600, 'lp_mhz': 3100}
        existing = _existing(root, relative)
        files[relative] = _entry(existing if existing is not None else (json.dumps(default) + '\n').encode(), 0o600, mutable=True)
    if name == 'input':
        helper = Path(__file__).with_name('input_profile.py').read_bytes()
        files['usr/local/lib/oxp3-input/input_profile.py'] = _entry(helper)
        files['etc/systemd/system/inputplumber.service.d/oxp3-input-profile.conf'] = _entry(
            b'[Service]\nRuntimeDirectory=oxp3-input\nWorkingDirectory=/run/oxp3-input\n'
            b'ExecStartPre=/usr/bin/python3 -I -B /usr/local/lib/oxp3-input/input_profile.py\n')
        # A live accepted gyro profile must not be shadowed/replaced by the
        # generic input profile. The existing file retains device calibration.
        active_gyro = _existing(root, 'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml')
        if active_gyro is not None:
            files.pop('etc/inputplumber/devices.d/50-onexplayer_3.yaml', None)
    return files


def _mutable(path):
    return (path.startswith(('etc/inputplumber/', 'home/deck/.config/', 'home/deck/.local/share/opti2xmx/'))
            and not path.endswith(('.service', '.conf', '.lua')) or path == 'home/deck/.config/MangoHud/presets.conf'
            or path.startswith('etc/inputplumber/') or re.match(r'var/lib/oxp3-[^/]+/config\.json$', path) is not None)


def _decky_settings(root, planned, records):
    """Include ordering in the same transaction as newly deployed plugins."""
    from .decky_order import SETTINGS, ordered_settings
    for legacy in ('home/deck/homebrew/loader.json', 'home/deck/homebrew/settings/loader.json'):
        if _existing(root, legacy) is not None:
            return {}
    existing = _existing(root, SETTINGS)
    try:
        settings = json.loads(existing) if existing is not None else {}
        if not isinstance(settings, dict):
            return {}
        metadata = {}
        directory = _safe(root, PLUGIN_ROOT)
        if directory.is_dir():
            for plugin in sorted(directory.iterdir()):
                path = _safe(root, PLUGIN_ROOT + '/' + plugin.name)
                if path.is_dir():
                    relative = PLUGIN_ROOT + '/' + plugin.name + '/plugin.json'
                    data = _existing(root, relative)
                    if data is not None:
                        metadata[relative] = data
        metadata.update({path: entry['data'] for path, entry in planned.items()
                         if path.startswith(PLUGIN_ROOT + '/') and path.endswith('/plugin.json')})
        names = []
        for path in sorted(metadata):
            name = json.loads(metadata[path]).get('name')
            if not isinstance(name, str) or not name or name in names:
                return {}  # Preserve unfamiliar plugin metadata/settings.
            names.append(name)
        changed = ordered_settings(settings, names)
    except (ValueError, UnicodeError, AttributeError):
        return {}
    if changed is None:
        # Keep a previously managed mutable setting in its component's plan.
        # Omitting it would make reinstallation restore its original bytes.
        if existing is None or records.get(SETTINGS, {}).get('component') != 'decky':
            return {}
        data = existing
    else:
        data = (json.dumps(changed, ensure_ascii=False, indent=2) + '\n').encode()
    return {SETTINGS: dict(_entry(data, mutable=True), component='decky')}


def build_plan(payload: Path, root: Path, selected: list[str], probe: dict, managed: dict | None = None) -> dict:
    """Expand dependencies and materialize files without changing the system.

    ``ready`` means ready for a file transaction, never active. Waydroid is
    blocked unless the caller advertises transactional package setup. Ownership is
    established only by the caller's authenticated ``managed['paths']`` records.
    Unknown choices and malformed catalog structure fail the whole request;
    resource/compatibility failures block only the affected component/dependents.
    """
    payload, root = Path(payload).absolute(), Path(root).absolute()
    catalog = json.loads(_read(payload, 'components/options.json'))
    if catalog.get('schema') != 1:
        raise ValueError('Unsupported component catalog schema')
    items = {}
    for item in catalog['repairs'] + catalog['plugins']:
        name = item['id']
        if name in items or not isinstance(item.get('dependencies'), list) or any(not isinstance(x, str) for x in item['dependencies']):
            raise ValueError('Invalid or duplicate component catalog entry')
        items[name] = item
    if not isinstance(selected, list) or any(type(x) is not str for x in selected) or len(set(selected)) != len(selected):
        raise ValueError('Expected unique component choices')
    if set(selected) - set(items):
        raise ValueError('Unknown component: ' + ', '.join(sorted(set(selected) - set(items))))
    order, visiting = [], set()
    def visit(name):
        if name in visiting or name not in items:
            raise ValueError('Unknown or cyclic component dependency: ' + name)
        if name in order:
            return
        visiting.add(name)
        for dependency in items[name]['dependencies']:
            visit(dependency)
        visiting.remove(name)
        order.append(name)
    for name in selected:
        visit(name)
    manifests = json.loads(_read(payload, 'integration/manifest.json'))
    records = (managed or {}).get('paths', {})
    result = {'selected': order, 'components': {}, 'files': {}}
    for name in order:
        metadata = manifests.get(name, {})
        report = {'status': 'blocked', 'reason': '', 'dependencies': list(items[name]['dependencies']), 'units': [], 'restart_required': name in RESTART}
        result['components'][name] = report
        try:
            from .payload_policy import REMOVED_PLUGIN_IDS
            if name in REMOVED_PLUGIN_IDS:
                raise ValueError('Third-party plugins are installed by the user; maintenance leaves them unchanged')
            policy = compatibility.evaluate(name, probe, metadata)
            report['compatibility'] = policy
            if not items[name].get('available', True) or name == 'refind':
                report['separate_operation'] = name == 'refind'
                raise ValueError('rEFInd is a separate boot-manager operation; it is unavailable in maintenance')
            if not policy['supported']:
                raise ValueError(policy['reason'])
            if any(result['components'][d]['status'] != 'ready' for d in report['dependencies']):
                raise ValueError('Dependency is blocked or not applicable')
            if type(probe.get('uid')) is not int or type(probe.get('gid')) is not int or min(probe['uid'], probe['gid']) <= 0:
                raise ValueError('A non-root deck user and group are required')
            if metadata.get('missing'):
                raise ValueError('; '.join(metadata['missing']))
            for package, version in metadata.get('packages', {}).items():
                if probe.get('packages', {}).get(package) != version:
                    raise ValueError('Incompatible package: ' + package + ' requires ' + version)
            if name == 'hdr' and probe.get('packages', {}).get('gamescope') != '3.16.30-1':
                raise ValueError('HDR requires Gamescope 3.16.30-1')
            if name == 'gyro' and not re.fullmatch(r'0\.78\.0(?:-[^\s]+)?', str(probe.get('packages', {}).get('inputplumber', ''))):
                raise ValueError('Gyro requires InputPlumber 0.78.0')
            units = metadata.get('units', [])
            if not isinstance(units, list) or any(not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', unit) for unit in units):
                raise ValueError('Invalid component service unit list')
            if name in compatibility.PORTABLE and units:
                raise ValueError('Portable settings adapter cannot activate services')
            if name == 'waydroid' and probe.get('transactional_packages') is not True:
                report.update(setup_required=True, activation='unavailable')
                raise ValueError('Waydroid host package installation requires a transactional package journal; this maintenance version cannot install it. Android images and initialization are also required')
            own = {path for path, record in records.items() if isinstance(record, dict) and record.get('component') == name}
            files = _materialize(name, payload, root, metadata, result['files'], probe, own)
            if files is None:
                report.update(status='not_applicable', reason='Target SSD is not an NVMe GM7')
                continue
            if not files:
                raise ValueError('No prepared install payload; rebuild this component in the installer bundle')
            normalized = {}
            folders = set()
            for relative, entry in files.items():
                legacy = 'home/deck/homebrew/plugins/'
                if relative.startswith(legacy):
                    relative = PLUGIN_ROOT + '/' + relative[len(legacy):]
                    entry = dict(entry, user=False)
                if relative.startswith('home/deck/.local/lib/oxp3-desktop-hdr-runtime/'):
                    entry = dict(entry, user=True)
                relative = _relative(relative)
                shared_key = 'shared_os_compatible' if name in compatibility.PORTABLE else 'shared_compatible'
                if relative.startswith(('home/', 'opt/')) and probe.get(shared_key, probe.get('shared_compatible') if name in compatibility.PORTABLE else False) is not True:
                    raise ValueError('Shared home/opt compatibility is unverified; inspect the other SteamOS slot')
                target = _safe(root, relative)
                if os.path.lexists(target) and not target.is_file():
                    raise ValueError('Component target is not a regular file: ' + relative)
                if relative.startswith(PLUGIN_ROOT + '/'):
                    folders.add(relative[len(PLUGIN_ROOT) + 1:].split('/')[0])
                    repair_existing = name in ('autoflatpaks-compat', 'animation-changer-compat')
                    if repair_existing and records.get(relative, {}).get('component') not in (None, name):
                        raise ValueError('Installed plugin repair cannot take ownership from another component; preserve its original recovery records')
                    if os.path.lexists(target) and relative not in own and not repair_existing:
                        raise ValueError('Unmanaged plugin file conflict; adopt or remove explicitly: ' + relative)
                if name == 'decky' and os.path.lexists(target) and relative != 'home/deck/.local/share/Steam/.cef-enable-remote-debugging' and relative not in own:
                    raise ValueError('Unmanaged Decky conflict; adopt the existing installation explicitly: ' + relative)
                entry = dict(entry, component=name)
                from .split_lock import GRUB, BOOT_REPAIRS
                if relative == GRUB and name in BOOT_REPAIRS:
                    previous = records.get(relative, result['files'].get(relative, {}))
                    if previous and previous.get('component') not in BOOT_REPAIRS:
                        raise ValueError('Valve boot settings are managed by another component; preserve them for review')
                    if previous.get('component') in BOOT_REPAIRS:
                        entry['component'] = previous['component']
                # Merge operations deliberately modify only their documented
                # keys; all other mutable profiles/settings remain byte exact.
                if _mutable(relative):
                    entry['mutable'] = True
                    if name not in ('keyboard', 'multifunction', 'flathub-ustc'):
                        existing = _existing(root, relative)
                        if existing is not None:
                            entry['data'] = existing
                entry['data'] = _guard(entry['data'], relative)
                composed_boot = relative == GRUB and name in BOOT_REPAIRS and result['files'].get(relative, {}).get('component') in BOOT_REPAIRS
                if relative in result['files'] and result['files'][relative]['data'] != entry['data'] and not composed_boot:
                    raise ValueError('Conflicting selected component target: ' + relative)
                normalized[relative] = entry
            for folder in folders:
                if name in ('autoflatpaks-compat', 'animation-changer-compat'):
                    # The fixed adapter validates an existing canonical plugin;
                    # it never installs a directory or changes legacy aliases.
                    continue
                for prefix in ('home/deck/homebrew/plugins/', PLUGIN_ROOT + '/'):
                    path = _safe(root, prefix + folder)
                    if os.path.lexists(path) and not any(p.startswith(prefix + folder + '/') for p in own):
                        raise ValueError('Unmanaged plugin directory conflict; adopt explicitly: ' + prefix + folder)
            if name == 'decky':
                for relative in ('home/deck/homebrew/services/PluginLoader', 'home/deck/homebrew/services/plugin_loader.service'):
                    if os.path.lexists(_safe(root, relative)) and relative not in own:
                        raise ValueError('Unmanaged existing Decky installation; explicit adoption required: ' + relative)
            all_paths = set(result['files']) | set(normalized)
            for relative in normalized:
                if any(parent.as_posix() in all_paths for parent in PurePosixPath(relative).parents if parent.as_posix() != '.'):
                    raise ValueError('Component file conflicts with a planned directory: ' + relative)
            report.update(status='ready', reason='Ready for transactional file installation', units=list(metadata.get('units', [])))
            if name == 'decky':
                report['units'] = ['plugin_loader.service']
            if name == 'input':
                report['units'] = list(dict.fromkeys(report['units'] + ['inputplumber.service']))
            if name == 'waydroid':
                report.update(reason='Ready for transactional host package installation; Android image download and initialization are still required', setup_required=True, package_install_required=True, activation='host-packages-pending', units=[], package_files=sorted(path for path in normalized if path.startswith('usr/local/lib/oxp3-waydroid/packages/') and path.endswith('.pkg.tar.zst')))
            result['files'].update(normalized)
        except (ValueError, OSError, KeyError, TypeError, UnicodeError, tarfile.TarError, zipfile.BadZipFile, configparser.Error) as error:
            report.update(status='blocked', reason=str(error), units=[])
    if result['components'].get('decky', {}).get('status') == 'ready':
        result['files'].update(_decky_settings(root, result['files'], records))
    from .split_lock import GRUB, restore_group
    group = restore_group({**records, **result['files']})
    result['restore_groups'] = ([{'components': group, 'path': GRUB,
        'reason': 'These repairs share Valve boot settings and must be explicitly restored together'}] if group else [])
    for name in group:
        if name in result['components']:
            result['components'][name]['restore_with'] = group
    return result
