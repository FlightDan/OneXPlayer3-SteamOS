"""Use the same persistent /opt mount as the installed SteamOS boot."""
from pathlib import Path
import subprocess


def mount_opt(root, mounts, readonly=False):
    root=Path(root)
    unit=root/'usr/lib/systemd/system/opt.mount'
    if not unit.is_file(): return False
    text=unit.read_text()
    if not all(line in text.splitlines() for line in
               ('What=/home/.steamos/offload/opt','Where=/opt','Options=bind')):
        raise RuntimeError('Unrecognized SteamOS /opt mount; preserve the image')
    override=root/'etc/systemd/system/opt.mount'
    if override.is_symlink() and str(override.readlink())=='/dev/null': return False
    if override.exists(): raise RuntimeError('Custom /opt mount requires review')
    source=root/'home/.steamos/offload/opt'
    target=root/'opt'
    if readonly:
        if not source.is_dir(): raise RuntimeError('The installed /opt offload directory is missing')
    else:
        from hdr.installer import ensure_directory
        ensure_directory(source,0o755)
        ensure_directory(target,0o755)
    if source.is_symlink() or target.is_symlink(): raise RuntimeError('Unexpected offload symlink')
    subprocess.run(['mount','--bind',str(source),str(target)],check=True)
    mounts.append(target)
    if readonly: subprocess.run(['mount','-o','remount,bind,ro',str(target)],check=True)
    return True
