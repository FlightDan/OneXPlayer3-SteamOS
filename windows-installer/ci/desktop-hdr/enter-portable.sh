#!/bin/bash
set -euo pipefail
root=$(realpath "$1")
case "$root" in /*/portable-root) ;; *) printf 'Unexpected chroot path\n' >&2; exit 1;; esac
mount --make-rprivate /
mount -t tmpfs tmpfs "$root/dev"
mknod -m 666 "$root/dev/null" c 1 3
mknod -m 666 "$root/dev/zero" c 1 5
mknod -m 666 "$root/dev/random" c 1 8
mknod -m 666 "$root/dev/urandom" c 1 9
mknod -m 666 "$root/dev/tty" c 5 0
mkdir -p "$root/dev/pts" "$root/dev/shm"
mount -t devpts devpts "$root/dev/pts"
mount -t tmpfs tmpfs "$root/dev/shm"
mount -t proc proc "$root/proc"
ln -s /proc/self/fd "$root/dev/fd"
ln -s /proc/self/fd/0 "$root/dev/stdin"
ln -s /proc/self/fd/1 "$root/dev/stdout"
ln -s /proc/self/fd/2 "$root/dev/stderr"
# Build as an ordinary user; only this empty package root and /build are exposed.
chroot --userspec=1000:1000 "$root" /usr/bin/env -i PATH=/usr/bin:/bin HOME=/home/builder USER=builder LOGNAME=builder LC_ALL=C.UTF-8 XDG_RUNTIME_DIR=/tmp/runtime-builder TMPDIR=/tmp /bin/bash /build/build-portable.sh
