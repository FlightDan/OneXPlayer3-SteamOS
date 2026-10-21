#!/usr/bin/env python3
"""Rebuild/check the allowlisted native HDR CI inputs from current source.

Text inputs use canonical LF, independent of Windows checkout autocrlf. No
directory walk is allowed here: research and local metadata outside this exact
public source list must never be added to the build archive.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

INPUTS = (
    'research/desktop-hdr/patch-kwin.py',
    'research/desktop-hdr/drm_output.candidate.cpp',
    'research/desktop-hdr/drm_output.candidate.h',
    'research/desktop-hdr/workspace.candidate.cpp',
    'research/desktop-hdr/oxp3_gamma22_policy.h',
    'research/desktop-hdr/mapped-hdr-control.cpp',
    'research/desktop-hdr/pattern-wayland.cpp',
    'research/desktop-hdr/presentation-proof.h',
    'research/desktop-hdr/test-presentation-proof.cpp',
    'research/desktop-hdr/compatible-packages.txt',
    'research/desktop-hdr/test-policy.cpp',
    'research/desktop-hdr/test-color-path.cpp',
    'research/desktop-hdr/launch-stable.sh',
    'research/desktop-hdr/disable-hdr.py',
    'research/display-source/kwin-6.7.3-1.6.src.tar.gz',
    'windows-installer/scripts/desktop_hdr_policy.py',
)
# The public checkout carries this unchanged upstream package only inside the
# input tar. Reuse that one pinned upstream blob, never cached renderer source.
PINNED_ARCHIVE_INPUTS = {
    'research/display-source/kwin-6.7.3-1.6.src.tar.gz':
        (9022061, 'b757e57c7ddb7a81b150ec6e45a79a1ef82205aa46889524723b9a4614536103'),
}


def source_bytes(root, archive):
    result = {}
    for name in INPUTS:
        path = root / name
        # The allowlist is fixed; reject links rather than following local data.
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise RuntimeError('Linked source input: ' + name)
        if path.is_file():
            data = path.read_bytes()
        elif name in PINNED_ARCHIVE_INPUTS and not path.exists():
            with tarfile.open(archive, 'r:') as previous:
                members = [member for member in previous.getmembers() if member.name == name]
                if len(members) != 1 or not members[0].isfile() or members[0].size != PINNED_ARCHIVE_INPUTS[name][0]:
                    raise RuntimeError('Missing or invalid pinned upstream archive input: ' + name)
                data = previous.extractfile(members[0]).read()
        else:
            raise RuntimeError('Missing or linked source input: ' + name)
        if name in PINNED_ARCHIVE_INPUTS:
            if (len(data), hashlib.sha256(data).hexdigest()) != PINNED_ARCHIVE_INPUTS[name]:
                raise RuntimeError('Pinned upstream archive hash mismatch: ' + name)
        if not name.endswith('.tar.gz'):
            data = data.replace(b'\r\n', b'\n')
        result[name] = data
    return result


def source_manifest(inputs):
    return [dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in inputs.items()]


def prepare(root, destination, write=False):
    archive = destination / 'source-inputs.tar'
    inputs = source_bytes(root, archive)
    manifest = source_manifest(inputs)
    manifest_path = destination / 'source-manifest.json'
    if write:
        temporary = archive.with_suffix('.tar.tmp')
        try:
            with tarfile.open(temporary, 'w', format=tarfile.USTAR_FORMAT) as output:
                for name, data in inputs.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o644
                    member.mtime = 0
                    output.addfile(member, io.BytesIO(data))
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8', newline='\n')
    if json.loads(manifest_path.read_text(encoding='utf-8-sig')) != manifest:
        raise RuntimeError('Stale source-manifest.json; run prepare-source-inputs.py --write')
    with tarfile.open(archive, 'r:') as source:
        members = source.getmembers()
        if [member.name for member in members] != list(INPUTS):
            raise RuntimeError('CI source archive differs from the explicit input allowlist')
        for member in members:
            if (not member.isfile() or member.mode != 0o644 or member.uid or member.gid
                    or member.mtime or member.uname or member.gname):
                raise RuntimeError('Noncanonical CI source archive member: ' + member.name)
            if source.extractfile(member).read() != inputs[member.name]:
                raise RuntimeError('Stale CI source archive member: ' + member.name)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true', help='Rebuild archive and manifest, then verify both')
    mode.add_argument('--check', action='store_true', help='Verify current source matches CI inputs (default)')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = prepare(here.parents[2], here, write=args.write)
    print('Verified %d allowlisted HDR build inputs' % len(manifest))
