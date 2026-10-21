#!/bin/bash
set -euo pipefail
work=$(cd "$(dirname "$0")" && pwd -P)
root="$work/portable-root"
packages="${PACKAGE_DIR:-$work/packages}"
if [ -e "$root" ] || [ -L "$root" ]; then echo "Refusing existing portable-root; run from a fresh workspace to preserve source provenance." >&2; exit 1; fi
for tool in python3 sudo tar zstd unshare chroot sha256sum; do command -v "$tool" >/dev/null || { echo "Required host tool unavailable: $tool" >&2; exit 1; }; done
python3 "$work/fetch-portable.py" "$work/portable-packages.json" "$packages"
sudo mkdir "$root"
# Only archive extraction occurs; package scripts, hooks and host package managers are never run.
python3 - "$work/portable-packages.json" "$packages" <<'PY' | while IFS= read -r archive; do
import json
from pathlib import Path
import sys
manifest=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
for package in manifest['packages']:
    print(Path(sys.argv[2]).resolve()/package['localFilename'])
PY
    sudo tar --zstd -xf "$archive" -C "$root" --exclude=.PKGINFO --exclude=.BUILDINFO --exclude=.MTREE --exclude=.INSTALL --exclude=usr/share/doc --exclude=usr/share/man --exclude=usr/share/licenses --exclude=usr/share/locale --exclude=usr/share/icons --exclude=usr/share/gtk-doc
done
sudo install -d -m 755 "$root/dev" "$root/proc" "$root/sys" "$root/home" "$root/tmp"
sudo chmod 1777 "$root/tmp"
sudo install -d -m 755 -o 1000 -g 1000 "$root/build" "$root/home/builder"
sudo install -d -m 700 -o 1000 -g 1000 "$root/tmp/runtime-builder"
printf 'builder:x:1000:1000:HDR builder:/home/builder:/bin/bash\n' | sudo tee -a "$root/etc/passwd" >/dev/null
printf 'builder:x:1000:\n' | sudo tee -a "$root/etc/group" >/dev/null
sudo install -m 644 "$work/build-portable.sh" "$root/build/build-portable.sh"
sudo install -m 644 "$work/source-inputs.tar" "$root/build/source-inputs.tar"
sudo chown -R 1000:1000 "$root/build"
sudo unshare --mount --pid --fork --net /bin/bash "$work/enter-portable.sh" "$root" 2>&1 | tee "$work/portable-build.log"
cp "$root/build/final-runtime.tar" "$work/portable-final-runtime.tar"
sha256sum "$work/portable-final-runtime.tar" | tee "$work/portable-final-runtime.sha256"
printf 'Build completed: %s\n' "$work/portable-final-runtime.tar"
