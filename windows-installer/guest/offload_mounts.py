"""Use the same persistent /opt mount as the installed SteamOS boot."""
from pathlib import Path
import os
import subprocess


def mount_etc(root, mounts, readonly=False):
    """Prepare/verify through SteamOS's actual per-slot persistent /etc view."""
    root=Path(root)
    unit=root/'usr/lib/systemd/system/etc.mount'
    if not unit.is_file(): return False
    text=unit.read_text()
    required=('Where=/etc','What=overlay','Type=overlay',
              'Options=lowerdir=/etc,upperdir=/var/lib/overlays/etc/upper,workdir=/var/lib/overlays/etc/work,index=off')
    if not all(line in text.splitlines() for line in required):
        raise RuntimeError('Unrecognized SteamOS /etc overlay; preserve the image')
    vendor_dropins=unit.with_name('etc.mount.d')
    if vendor_dropins.exists() or vendor_dropins.is_symlink():
        raise RuntimeError('Custom vendor /etc overlay requires review')
    override=root/'etc/systemd/system/etc.mount'
    dropins=override.with_name('etc.mount.d')
    if override.exists() or override.is_symlink() or dropins.exists() or dropins.is_symlink():
        raise RuntimeError('Custom /etc overlay requires review')
    upper=root/'var/lib/overlays/etc/upper'
    work=root/'var/lib/overlays/etc/work'
    target=root/'etc'
    if any(char in str(root) for char in ',:\\'):
        raise RuntimeError('Unsupported overlay mount path')
    from file_transaction import directory_fd
    if readonly:
        # Two read-only layers respect overlay whiteouts without needing a
        # writable workdir on the independently read-only var filesystem.
        if not upper.is_dir(): raise RuntimeError('Persistent /etc overlay is missing')
    else:
        from hdr.installer import ensure_directory
        for path in (upper,work): ensure_directory(path,0o755)
    for path in (upper/'systemd/system/etc.mount',upper/'systemd/system/etc.mount.d'):
        if path.exists() or path.is_symlink():
            raise RuntimeError('Custom persistent /etc overlay requires review')
    for path in (upper,target):
        descriptor=directory_fd(path); os.close(descriptor)
    if not readonly:
        descriptor=directory_fd(work); os.close(descriptor)
    subprocess.run(['modprobe','overlay'],check=True)
    flags=('lowerdir='+str(upper)+':'+str(target)+',ro' if readonly else
           'lowerdir='+str(target)+',upperdir='+str(upper)+',workdir='+str(work)+',index=off')
    subprocess.run(['mount','-t','overlay','overlay','-o',flags,str(target)],check=True)
    mounts.append(target)
    return True


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
