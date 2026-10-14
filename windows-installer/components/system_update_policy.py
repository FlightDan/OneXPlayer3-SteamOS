"""Offline SteamOS update pause, deployed and restored by the file journal.

Only the OS image update services are masked. Steam client and game updates
are independent of these services. The caller selects supported repaired slots
and must reload systemd when applying/restoring this policy on a running system.
"""
import json
import os
from pathlib import Path
import stat

SERVICES = ('atomupd.service', 'rauc.service')
MARKER = 'var/lib/oxp3-installer/system-update-policy.json'
_ROOT_UID = 0


def _trusted_path(root, relative):
    """Refuse symlinks and writable privileged paths before journal staging."""
    path = root / relative
    for ancestor in (root, *(root / Path(*Path(relative).parts[:i])
                             for i in range(1, len(Path(relative).parts) + 1))):
        if not os.path.lexists(ancestor):
            continue
        info = ancestor.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('Untrusted system update policy path: ' + str(ancestor))
        # Windows fixture roots cannot represent Unix ownership/permissions.
        if os.name == 'posix' and (info.st_uid != _ROOT_UID or info.st_mode & 0o022):
            raise RuntimeError('Untrusted system update policy permissions: ' + str(ancestor))
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('System update policy ancestor is not a directory: ' + str(ancestor))
    return path


def _marker_bytes():
    return (json.dumps({
        'schema': 1,
        'policy': 'pause-steamos-system-updates',
        'services': list(SERVICES),
        'reason': 'Preserve the supported SteamOS image and its OXP3 repairs.',
        'steam_client_updates': 'unchanged',
        'steam_game_updates': 'unchanged',
        'restore': 'Restore the system-update-policy installer component in both slots, then reload systemd.',
    }, indent=2) + '\n').encode('utf-8')


def files(root):
    """Return regular files suitable for integration.apply_files.

    A zero-length unit in /etc masks the vendor unit in systemd. This avoids
    introducing symlinks into a transaction that only journals regular files.
    Existing masks are retained on rollback; custom unit overrides are refused.
    """
    root = Path(root).absolute()
    output = {}
    for service in SERVICES:
        vendor = _trusted_path(root, 'usr/lib/systemd/system/' + service)
        if not vendor.is_file() or not vendor.stat().st_size:
            raise RuntimeError('SteamOS OS update service is missing: ' + service)
        relative = 'etc/systemd/system/' + service
        mask = _trusted_path(root, relative)
        if mask.exists() and (not mask.is_file() or mask.stat().st_size):
            raise RuntimeError('Conflicting system update unit override: ' + service)
        output[relative] = {'data': b'', 'mode': 0o644}
    marker = _trusted_path(root, MARKER)
    expected = _marker_bytes()
    if marker.exists() and (not marker.is_file() or marker.stat().st_size != len(expected)
                            or marker.read_bytes() != expected):
        raise RuntimeError('Conflicting system update policy marker; preserve existing state')
    output[MARKER] = {'data': expected, 'mode': 0o644}
    return output


def status(root):
    """Read-only offline diagnostics; live LoadState must be checked separately."""
    root = Path(root).absolute()
    errors, services = [], {}
    for service in SERVICES:
        try:
            vendor = _trusted_path(root, 'usr/lib/systemd/system/' + service)
            if not vendor.is_file() or not vendor.stat().st_size:
                raise RuntimeError('SteamOS OS update service is missing: ' + service)
            mask = _trusted_path(root, 'etc/systemd/system/' + service)
            paused = mask.is_file() and mask.stat().st_size == 0
            if not paused:
                errors.append('Missing or changed system update mask: ' + service)
            services[service] = {'masked': paused}
        except (OSError, RuntimeError) as error:
            services[service] = {'masked': False}
            errors.append(str(error))
    try:
        marker = _trusted_path(root, MARKER)
        expected = _marker_bytes()
        recorded = (marker.is_file() and marker.stat().st_size == len(expected)
                    and marker.read_bytes() == expected)
        if not recorded:
            errors.append('Missing or changed system update policy marker')
    except (OSError, RuntimeError) as error:
        recorded = False
        errors.append(str(error))
    return {'paused': not errors, 'services': services, 'recorded': recorded,
            'steam_client_updates': 'unchanged', 'steam_game_updates': 'unchanged',
            'errors': errors}


def verify(root):
    """Raise when staging did not produce the expected offline pause policy."""
    result = status(root)
    if not result['paused']:
        raise RuntimeError('; '.join(result['errors']))
    return result
