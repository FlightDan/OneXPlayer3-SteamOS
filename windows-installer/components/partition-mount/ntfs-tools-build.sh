#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Runs only inside the disposable, network-disabled Alpine VM.
set -eu
export LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1771977600
printf '%s\n' /media/sr0/apks > /etc/apk/repositories
mkdir -p /var/cache/apk
ln -s /var/cache/apk /etc/apk/cache
apk add --no-network --no-progress /mnt/payload/apks/*.apk
mkdir /build
cd /build
tar -xzf /mnt/payload/source.tar.gz
cd ntfs-3g-2026.2.25
export CFLAGS='-Os -fno-ident -ffile-prefix-map=/build=.'
export LDFLAGS='-static -no-pie -Wl,--build-id=none'
./configure --disable-shared --enable-static --enable-really-static \
    --disable-ntfs-3g --disable-crypto --without-uuid
make -j2 -C libntfs-3g
make -j2 -C ntfsprogs ntfsfix mkntfs ntfscp LDFLAGS='-all-static -no-pie -Wl,--build-id=none'
gcc $CFLAGS -DHAVE_CONFIG_H -I. -Iinclude/ntfs-3g -Iinclude \
    /mnt/payload/ntfs_status.c libntfs-3g/.libs/libntfs-3g.a \
    $LDFLAGS -o /build/ntfs_status
cp ntfsprogs/ntfsfix /build/ntfsfix
cp ntfsprogs/mkntfs /build/mkntfs
cp ntfsprogs/ntfscp /build/ntfscp
strip /build/ntfs_status /build/ntfsfix
readelf -h /build/ntfs_status /build/ntfsfix
if readelf -l /build/ntfs_status /build/ntfsfix | grep -E 'INTERP|DYNAMIC'; then
    echo 'Dynamic binary refused' >&2; exit 1
fi
printf 'NTFS_TOOLS_BUILD_PHASE=validation\n'
cd /build
truncate -s 64M clean.img
./mkntfs -F -Q clean.img >/dev/null
cp clean.img dirty.img
cp clean.img hibernated.img
cp clean.img mismatch.img
# Mutate only private test fixtures using the pinned source format. The dirty
# fixture changes both copies of the resident $Volume record consistently.
# The mismatch fixture changes only the mirror, recreating record-3 mismatch.
cat > fixture.py <<'PY'
import pathlib, struct
def record(data, mirror=False, index=3):
    sector=struct.unpack_from('<H',data,11)[0]
    cluster=sector*data[13]
    lcn=struct.unpack_from('<Q',data,56 if mirror else 48)[0]
    size=data[64]
    size=(1 << (256-size)) if size>127 else size*cluster
    return lcn*cluster+index*size,size
def dirty(path, mirror_only=False):
    p=pathlib.Path(path); data=bytearray(p.read_bytes())
    for mirror in ([True] if mirror_only else [False,True]):
        off,size=record(data,mirror)
        attr=off+struct.unpack_from('<H',data,off+20)[0]
        while struct.unpack_from('<I',data,attr)[0]!=0xffffffff:
            kind,length=struct.unpack_from('<II',data,attr)
            if kind==0x70:
                value=attr+struct.unpack_from('<H',data,attr+20)[0]
                flags=struct.unpack_from('<H',data,value+10)[0]
                struct.pack_into('<H',data,value+10,flags|1)
                break
            assert 24<=length<=size
            attr+=length
        else: raise AssertionError('missing Volume Information')
    p.write_bytes(data)
dirty('dirty.img')
dirty('mismatch.img',True)
pathlib.Path('hiberfil.sys').write_bytes(b'hibr'+b'\0'*4092)
def logfile(path, major=2, clean=True):
    p=pathlib.Path(path); data=bytearray(p.read_bytes())
    off,size=record(data,index=2)
    attr=off+struct.unpack_from('<H',data,off+20)[0]
    while struct.unpack_from('<I',data,attr)[0]!=0x80:
        attr+=struct.unpack_from('<I',data,attr+4)[0]
        assert attr<off+size
    assert data[attr+8]==1
    log_size=struct.unpack_from('<Q',data,attr+48)[0]
    runs=attr+struct.unpack_from('<H',data,attr+32)[0]
    width=data[runs]; n=width&15; m=width>>4
    length=int.from_bytes(data[runs+1:runs+1+n],'little')
    lcn=int.from_bytes(data[runs+1+n:runs+1+n+m],'little',signed=True)
    cluster=struct.unpack_from('<H',data,11)[0]*data[13]
    assert lcn>0 and length*cluster>=8192
    for index in range(2):
        page=bytearray(4096); page[:4]=b'RSTR'
        struct.pack_into('<HHQIIHHHH',page,4,32,9,0,4096,4096,56,0 if major==2 else 1,major,0)
        ra=56
        struct.pack_into('<QHHHHIHHQ',page,ra,0,1,0 if clean else 0xffff,0xffff if clean else 0,2 if clean else 0,67-log_size.bit_length(),208,48,log_size)
        struct.pack_into('<HH',page,ra+36,48,64)
        client=ra+48
        struct.pack_into('<HHH',page,client+16,0xffff,0xffff,1)
        struct.pack_into('<I',page,client+28,8)
        page[client+32:client+40]='NTFS'.encode('utf-16le')
        sequence=0xaaaa+index
        struct.pack_into('<H',page,32,sequence)
        for sector in range(8):
            trailer=(sector+1)*512-2
            page[34+sector*2:36+sector*2]=page[trailer:trailer+2]
            struct.pack_into('<H',page,trailer,sequence)
        start=lcn*cluster+index*4096
        data[start:start+4096]=page
    p.write_bytes(data)
PY
# Python comes from the existing pinned runtime payload, copied by the host.
python3 fixture.py
./ntfscp -f hibernated.img hiberfil.sys /hiberfil.sys >/dev/null
cp hibernated.img hibernated-dirty.img
python3 - <<'PY'
import fixture
fixture.dirty('hibernated-dirty.img')
from shutil import copyfile
copyfile('dirty.img','cached-metadata.img')
fixture.logfile('cached-metadata.img')
copyfile('dirty.img','unclean-journal.img')
fixture.logfile('unclean-journal.img',major=1,clean=False)
PY
truncate -s 8192 invalid.img
for state in clean dirty hibernated hibernated-dirty cached-metadata unclean-journal mismatch invalid; do
    before=$(sha256sum "$state.img" | cut -d' ' -f1)
    strace -o "$state.trace" -e trace=open,openat,pwrite64,write ./ntfs_status "$state.img" > "$state.json" || case "$state" in mismatch|invalid|unclean-journal) true;; *) exit 1;; esac
    after=$(sha256sum "$state.img" | cut -d' ' -f1)
    test "$before" = "$after"
    if grep -E 'open(at)?\(.*(O_RDWR|O_WRONLY)' "$state.trace"; then exit 1; fi
done
python3 - <<'PY'
import json, pathlib
for fixture,state in [('clean','clean'),('dirty','dirty'),('hibernated','hibernated'),('hibernated-dirty','hibernated'),('cached-metadata','hibernated'),('unclean-journal','unknown'),('mismatch','unknown'),('invalid','unknown')]:
    value=json.loads(pathlib.Path(fixture+'.json').read_text())
    assert value['schema']==1 and value['status']==state,value
    print('NTFS_TOOLS_TEST='+fixture+':'+state+':unchanged:readonly-open')
PY
for binary in ntfs_status ntfsfix; do
    printf '\nNTFS_TOOLS_FILE_BEGIN=%s\n' "$binary"
    base64 "/build/$binary"
    printf '\nNTFS_TOOLS_FILE_END=%s\n' "$binary"
done
printf '\nOXP_TASK_RESULT=passed\n'
