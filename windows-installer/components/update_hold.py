"""SteamOS 3.10 OS image update hold for offline installation.

files() only reads an offline root and returns regular files for apply_files.
The integration requires this policy for both system slots. It leaves Steam
client updates unchanged. Unattended first-boot completion remains unverified.
"""
import configparser
import json
import os
from pathlib import Path
import re
import stat

_ROOT_UID = 0
_ROOT_GID = 0
SUPPORTED = {'ID': 'steamos', 'VERSION_ID': '3.10', 'BUILD_ID': '20260924.1000'}
BRANCHES = ('stable', 'rc', 'beta', 'bc', 'preview', 'pc', 'main')
DEV_BRANCHES = ('main', 'staging')
BASE = 'etc/oxp3-installer/update-hold'
CLIENT = BASE + '/client.conf'
FEED_URL = 'file:///' + BASE + '/feed'
VENDOR_CLIENT = 'usr/lib/steamos-atomupd/client.conf'
STANDARD_CLIENT = 'etc/steamos-atomupd/client.conf'
VENDOR_MANIFEST = 'usr/lib/steamos-atomupd/manifest.json'
STANDARD_MANIFEST = 'etc/steamos-atomupd/manifest.json'
DROPIN = 'etc/systemd/system/atomupd.service.d/90-oxp3-update-hold.conf'
DROPIN_DATA = ('[Service]\nExecStart=\n'
               'ExecStart=/usr/lib/atomupd-daemon --config-directory=/' + BASE + '\n').encode()
# Exact original SteamOS 3.10 build 20260924.1000 vendor drop-in, read-only
# evidence: logs/official-update-unit-profile-20261015.json. Its 461 bytes have
# SHA256 23e934bae09de74267a26c6ea9f4856a43ecac8acb876b0bce01d27bca4f5f7c.
STOCK_RAUC = 'usr/lib/systemd/system/rauc.service.d/override.conf'
STOCK_RAUC_DATA = b'''#  SPDX-License-Identifier: LGPL-2.1+
#
#  This file is part of steamos-customizations.
#
#  steamos-customizations is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public License as
#  published by the Free Software Foundation; either version 2.1 of the License,
#  or (at your option) any later version.

[Service]
ExecStart=
ExecStart=/usr/lib/rauc/rauc-override.sh
LogFilterPatterns=~_DO_NOT_SHARE_URL
'''
SERVICES = ('atomupd.service', 'rauc.service')
UNIT_DIRS = ('etc/systemd/system.control', 'run/systemd/system.control',
             'run/systemd/transient', 'run/systemd/generator.early',
             'etc/systemd/system', 'etc/systemd/system.attached',
             'run/systemd/system', 'run/systemd/system.attached',
             'run/systemd/generator', 'usr/local/lib/systemd/system',
             'usr/lib/systemd/system', 'run/systemd/generator.late')


def _trusted(root, relative, allow_link=False):
    path = root / relative
    parts = Path(relative).parts
    for item in (root, *(root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1))):
        try: info = item.lstat()
        except FileNotFoundError: continue
        is_link = stat.S_ISLNK(info.st_mode)
        if is_link and item == path and allow_link:
            if os.name == 'posix' and info.st_uid != _ROOT_UID:
                raise RuntimeError('Untrusted update hold link owner: ' + str(item))
            continue
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('Untrusted update hold path: ' + str(item))
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('Update hold ancestor is not a directory: ' + str(item))
        if os.name == 'posix' and (info.st_uid != _ROOT_UID or info.st_mode & 0o022):
            raise RuntimeError('Untrusted update hold permissions: ' + str(item))
    return path


def _read(root, relative):
    path = _trusted(root, relative)
    if not path.is_file(): raise RuntimeError('Required official file is missing: ' + relative)
    # Final-component O_NOFOLLOW also rejects replacement with a link after lstat.
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode): raise RuntimeError('Expected a regular official file: ' + relative)
        if os.name == 'posix' and (info.st_uid != _ROOT_UID or info.st_mode & 0o022):
            raise RuntimeError('Untrusted update hold permissions: ' + str(path))
        data = source.read(65537)
    if len(data) > 65536: raise RuntimeError('Official update hold input is oversized: ' + relative)
    return data


def _link_target(path):
    target = os.readlink(path)
    return target.replace('\\', '/') if os.name == 'nt' else target


def _expected_link(root, relative, targets, required=True):
    path = _trusted(root, relative, allow_link=True)
    if not os.path.lexists(path):
        if not required: return
        raise RuntimeError('Required official link is missing: ' + relative)
    if not path.is_symlink() or _link_target(path) not in targets:
        raise RuntimeError('Unexpected official link: ' + relative)


def _image(root):
    # /etc/os-release is authoritative when it is a regular file. The original
    # supported image's /usr/lib/os-release is generic and omits build/version.
    # Only an explicitly accepted /etc link selects the image-owned vendor file.
    release = _trusted(root, 'etc/os-release', allow_link=True)
    if release.is_symlink():
        _expected_link(root, 'etc/os-release', {'../usr/lib/os-release', '/usr/lib/os-release'})
        raw = _read(root, 'usr/lib/os-release')
    else:
        raw = _read(root, 'etc/os-release')
    values = {}
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith('#'): continue
        key, sep, value = line.partition('=')
        if not sep or key in values: raise RuntimeError('Ambiguous official image identity')
        values[key] = value.strip('"\'')
    if any(values.get(key) != value for key, value in SUPPORTED.items()):
        raise RuntimeError('Unsupported image for update hold; require SteamOS 3.10 build 20260924.1000')


def _configuration(root):
    _expected_link(root, STANDARD_CLIENT,
                   {'/usr/lib/steamos-atomupd/client.conf', '../../usr/lib/steamos-atomupd/client.conf'})
    raw = _read(root, VENDOR_CLIENT)
    text = raw.decode('utf-8')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    expected = {'ImagesUrl': 'https://steamdeck-images.steamos.cloud/',
                'MetaUrl': 'https://steamdeck-atomupd.steamos.cloud/meta',
                'Variants': 'steamdeck', 'Branches': ';'.join(BRANCHES),
                'BranchesDev': ';'.join(DEV_BRANCHES)}
    if (parser.defaults() or parser.sections() != ['Server'] or set(parser['Server']) != set(expected)
            or any(parser['Server'].get(k) != v for k, v in expected.items())):
        raise RuntimeError('Unsupported official updater configuration')
    matches = list(re.finditer(r'^([ \t]*MetaUrl[ \t]*=[ \t]*)([^\r\n]+)', text, re.M))
    if len(matches) != 1 or matches[0][2].strip() != expected['MetaUrl']:
        raise RuntimeError('Ambiguous official MetaUrl setting')
    match = matches[0]
    # Retain every other official byte, including comments and branch settings.
    return (text[:match.start(2)] + FEED_URL + text[match.end(2):]).encode('utf-8')


def _manifest(root):
    _expected_link(root, STANDARD_MANIFEST, {'../../lib/steamos-atomupd/manifest.json',
                   '../../usr/lib/steamos-atomupd/manifest.json', '/usr/lib/steamos-atomupd/manifest.json'})
    # The actual image's manifest link passes through /lib. Verify that alias
    # independently; never ask the host to resolve an image-absolute symlink.
    if _link_target(root / STANDARD_MANIFEST) == '../../lib/steamos-atomupd/manifest.json':
        _expected_link(root, 'lib', {'usr/lib', '/usr/lib'})
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise RuntimeError('Duplicate official manifest field')
            result[key] = value
        return result
    data = json.loads(_read(root, VENDOR_MANIFEST), object_pairs_hook=unique)
    expected = {'product': 'steamos', 'release': 'holo', 'variant': 'steamdeck',
                'arch': 'amd64', 'version': '3.10.0', 'buildid': '20260924.1000'}
    optional = {'branch', 'default_update_branch', 'introduces_checkpoint', 'requires_checkpoint',
                'shadow_checkpoint', 'estimated_size', 'skip', 'checkpoint', 'legacyvariant'}
    if not isinstance(data, dict) or set(data) - set(expected) - optional or any(data.get(k) != v for k,v in expected.items()):
        raise RuntimeError('Unsupported official manifest identity or schema')
    if data.get('legacyvariant', '') != '':
        raise RuntimeError('Unsupported official manifest legacy variant')
    for key in ('introduces_checkpoint', 'requires_checkpoint'):
        if type(data.get(key, 0)) is not int or data.get(key, 0) != 0:
            raise RuntimeError('Unsupported official manifest checkpoint')
    for key in ('shadow_checkpoint', 'skip', 'checkpoint'):
        if type(data.get(key, False)) is not bool or data.get(key, False):
            raise RuntimeError('Unsupported official manifest checkpoint or skip state')
    if type(data.get('estimated_size', 0)) is not int or data.get('estimated_size', 0) < 0:
        raise RuntimeError('Unsupported official manifest size')
    branch = data.get('branch') or data.get('default_update_branch')
    if branch not in (*BRANCHES, *DEV_BRANCHES) or data.get('default_update_branch', branch) not in (*BRANCHES, *DEV_BRANCHES):
        raise RuntimeError('Unsupported official manifest branch or legacy schema')


def _units(root):
    for service in SERVICES:
        vendor = 'usr/lib/systemd/system/' + service
        raw = _read(root, vendor)
        if not raw.strip(): raise RuntimeError('Official updater unit is masked: ' + service)
        if service == 'atomupd.service':
            text = raw.decode('utf-8')
            starts = re.findall(r'^ExecStart\s*=\s*(.*)$', text, re.M)
            kinds = re.findall(r'^Type\s*=\s*(.*)$', text, re.M)
            names = re.findall(r'^BusName\s*=\s*(.*)$', text, re.M)
            if starts != ['/usr/lib/atomupd-daemon'] or kinds != ['dbus'] or names != ['com.steampowered.Atomupd1']:
                raise RuntimeError('Unsupported official atomupd unit semantics')
        for directory in UNIT_DIRS:
            relative = directory + '/' + service
            path = _trusted(root, relative)
            if relative != vendor and os.path.lexists(path):
                raise RuntimeError('Conflicting updater unit or mask: ' + relative)
            # Preserve only the exact known vendor RAUC drop-in. Candidate-owned
            # drop-in reuse is separately checked against expected output bytes.
            for name in (service + '.d', 'service.d'):
                folder = _trusted(root, directory + '/' + name)
                if not folder.exists(): continue
                if not folder.is_dir(): raise RuntimeError('Conflicting updater drop-in directory: ' + str(folder))
                for entry in folder.iterdir():
                    candidate = entry.relative_to(root).as_posix()
                    _trusted(root, candidate)
                    if candidate == STOCK_RAUC:
                        if _read(root, candidate) != STOCK_RAUC_DATA:
                            raise RuntimeError('Conflicting stock RAUC drop-in contents')
                        info = entry.stat()
                        if os.name == 'posix' and (info.st_gid != _ROOT_GID or stat.S_IMODE(info.st_mode) != 0o644):
                            raise RuntimeError('Untrusted stock RAUC drop-in ownership or mode')
                        continue
                    if candidate != DROPIN:
                        raise RuntimeError('Conflicting updater drop-in: ' + candidate)


def files(root):
    """Read-only, deterministic regular-file map for integration.apply_files.

    The fixed supported image identity is never rewritten. Preferences, manifest,
    official client.conf and its symlink are not transaction targets. Runtime
    application/restart and real Steam OOBE acceptance belong to later testing.
    """
    root = Path(root).absolute()
    _image(root)
    _manifest(root)
    client = _configuration(root)
    _units(root)
    output = {CLIENT: {'data': client, 'mode': 0o644},
              DROPIN: {'data': DROPIN_DATA, 'mode': 0o644}}
    prefix = BASE + '/feed/holo/steamos/amd64/steamdeck/'
    for branch in dict.fromkeys((*BRANCHES, *DEV_BRANCHES)):
        for suffix in (branch + '/3.10.0/20260924.1000.json', branch + '.json'):
            output[prefix + suffix] = {'data': b'{}\n', 'mode': 0o644}
    for relative, metadata in output.items():
        path = _trusted(root, relative)
        if os.path.lexists(path):
            if not path.is_file() or _read(root, relative) != metadata['data']:
                raise RuntimeError('Conflicting candidate-owned update hold file: ' + relative)
            if os.name == 'posix' and stat.S_IMODE(path.stat().st_mode) != metadata['mode']:
                raise RuntimeError('Conflicting candidate-owned update hold file mode: ' + relative)
    # Unknown files could change config-directory or feed behavior. Refuse to
    # adopt a preexisting directory with data outside this candidate's file set.
    folder = _trusted(root, BASE)
    if folder.exists():
        if not folder.is_dir(): raise RuntimeError('Conflicting update hold directory')
        for entry in folder.rglob('*'):
            relative = entry.relative_to(root).as_posix()
            _trusted(root, relative)
            if entry.is_file() and relative not in output:
                raise RuntimeError('Conflicting unknown update hold file: ' + relative)
    return output
