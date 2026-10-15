"""Read-only verification of an already staged OS image update hold."""
import os
from pathlib import Path
import stat

from update_hold import files


def verify(root, report):
    root = Path(root)
    if (not isinstance(report, dict) or report.get('status') != 'files_installed'
            or report.get('os_image_updates') != 'held'
            or report.get('steam_client_updates') != 'unchanged'):
        raise RuntimeError('Required system update hold report is invalid')
    expected = files(root)
    paths = report.get('files')
    if (not isinstance(paths, list) or not all(isinstance(path, str) for path in paths)
            or len(paths) != len(expected) or set(paths) != set(expected)):
        raise RuntimeError('Required system update hold file list is invalid')
    for relative, metadata in expected.items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.read_bytes() != metadata['data']:
            raise RuntimeError('Required system update hold file is missing or changed: ' + relative)
        info = path.stat()
        if os.name == 'posix' and (info.st_uid != 0 or info.st_gid != 0
                                  or stat.S_IMODE(info.st_mode) != metadata['mode']):
            raise RuntimeError('Required system update hold file permissions changed: ' + relative)
    return len(expected)
