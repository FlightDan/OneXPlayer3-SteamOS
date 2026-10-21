"""Validate the fixed KWin mapped-HDR runtime before it enters a payload."""
from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
import tarfile


POLICY_MARKER = b'OXP3_GAMMA22_POLICY_EDID_ONLY_V2'
TRIAL_MARKER = b'X2MINI_HDR_TRIAL_475_700_V1'
PRESENTATION_MARKER = b'HDR_TRIAL_PRESENT_WAIT_V2'
REQUIRED_BINARIES = (
    'bin/oxp3-mapped-hdr-control',
    'lib/libkwin.so.6.7.3',
    'bin/oxp3-hdr-pattern',
)
KWIN_SONAME = 'lib/libkwin.so.6'
KWIN_LINKS = (KWIN_SONAME, 'lib/libkwin.so')
MODEL_GATE_MARKERS = (
    b'/sys/class/dmi/id/sys_vendor',
    b'/sys/class/dmi/id/product_name',
    b'ONE-NETBOOK',
    b'ONEXPLAYER 3',
)


class DesktopHdrPolicyError(ValueError):
    pass


def _encoded(token: bytes):
    yield token
    try:
        text = token.decode('ascii')
    except UnicodeDecodeError:
        return
    yield text.encode('utf-16le')
    yield text.encode('utf-16be')


def _contains(data: bytes, token: bytes) -> bool:
    return any(needle in data for needle in _encoded(token))


def _safe_name(raw: str, is_directory: bool) -> str | None:
    if raw in ('.', './'):
        return None
    name = raw.removeprefix('./')
    if is_directory:
        name = name.rstrip('/')
    if (not name or name.startswith('/') or '\\' in name or ':' in name
            or any(ord(char) < 32 for char in name)):
        raise DesktopHdrPolicyError('Unsafe desktop-HDR runtime archive path')
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise DesktopHdrPolicyError('Unsafe desktop-HDR runtime archive path')
    return name


def _read_runtime(path: Path, include_payloads: bool):
    files = {}
    modes = {}
    try:
        with tarfile.open(path, mode='r:*') as archive:
            members = {}
            for item in archive.getmembers():
                name = _safe_name(item.name, item.isdir())
                if name is None:
                    if not item.isdir():
                        raise DesktopHdrPolicyError('Unexpected root entry in desktop-HDR runtime archive')
                    continue
                if name in members:
                    raise DesktopHdrPolicyError('Duplicate desktop-HDR runtime archive path')
                members[name] = item

            for name, item in members.items():
                if name in REQUIRED_BINARIES and not item.isfile():
                    raise DesktopHdrPolicyError('Required desktop-HDR binary must be a regular file')
                if name in REQUIRED_BINARIES and name.startswith('bin/') and not item.mode & 0o111:
                    raise DesktopHdrPolicyError('Required desktop-HDR program must be executable')
                if name in KWIN_LINKS and not item.issym():
                    raise DesktopHdrPolicyError('KWin SONAME entry must be a symbolic link to the validated compositor')
                if item.isdir():
                    continue
                resolved = item
                resolved_name = name
                visited = set()
                while resolved.issym():
                    if resolved_name in visited:
                        raise DesktopHdrPolicyError('Cyclic desktop-HDR runtime link')
                    visited.add(resolved_name)
                    link = PurePosixPath(resolved.linkname)
                    if (not resolved.linkname or link.is_absolute() or '\\' in resolved.linkname
                            or ':' in resolved.linkname
                            or any(part in ('', '.', '..') for part in resolved.linkname.split('/'))):
                        raise DesktopHdrPolicyError('External desktop-HDR runtime link')
                    resolved_name = str(PurePosixPath(resolved_name).parent / link)
                    resolved = members.get(resolved_name)
                    if resolved is None:
                        raise DesktopHdrPolicyError('Dangling desktop-HDR runtime link')
                if not resolved.isfile():
                    raise DesktopHdrPolicyError('Special desktop-HDR runtime archive entry')
                if name in KWIN_LINKS and resolved_name != REQUIRED_BINARIES[1]:
                    raise DesktopHdrPolicyError('KWin SONAME entry does not resolve to the validated compositor')
                if not include_payloads and name not in REQUIRED_BINARIES:
                    continue
                stream = archive.extractfile(resolved)
                if stream is None:
                    raise DesktopHdrPolicyError('Unreadable desktop-HDR runtime entry')
                data = stream.read()
                if name in REQUIRED_BINARIES:
                    if name != 'bin/oxp3-hdr-pattern' and not _contains(data, POLICY_MARKER):
                        raise DesktopHdrPolicyError('Desktop-HDR runtime is missing the EDID-only policy marker')
                    if any(_contains(data, marker) for marker in MODEL_GATE_MARKERS):
                        raise DesktopHdrPolicyError('Desktop-HDR runtime still contains an OP3 model hard gate')
                    if not _contains(data, TRIAL_MARKER):
                        raise DesktopHdrPolicyError('Desktop-HDR runtime is missing the 475/700 trial marker')
                    if name == 'bin/oxp3-hdr-pattern' and not _contains(data, PRESENTATION_MARKER):
                        raise DesktopHdrPolicyError('Desktop-HDR renderer is missing the presentation completion marker')
                if include_payloads:
                    files[name] = data
                    modes[name] = item.mode

        missing = set(REQUIRED_BINARIES) - set(members)
        if missing:
            raise DesktopHdrPolicyError('Desktop-HDR runtime is missing required binaries')
        missing_links = set(KWIN_LINKS) - set(members)
        if missing_links:
            raise DesktopHdrPolicyError('Desktop-HDR runtime is missing a KWin SONAME link')
        if any(not members[name].issym() for name in KWIN_LINKS):
            raise DesktopHdrPolicyError('Desktop-HDR runtime is missing a KWin SONAME link')
        return files, modes
    except DesktopHdrPolicyError:
        raise
    except (OSError, tarfile.TarError, KeyError, ValueError) as exc:
        raise DesktopHdrPolicyError('Invalid desktop-HDR runtime archive') from exc


def validate_desktop_hdr_runtime(path) -> None:
    """Reject stale model-locked binaries without extracting the archive."""
    _read_runtime(Path(path), include_payloads=False)


def read_desktop_hdr_runtime(path):
    """Return validated relative-path bytes and original modes for staging."""
    return _read_runtime(Path(path), include_payloads=True)
