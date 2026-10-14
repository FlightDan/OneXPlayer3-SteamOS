#!/bin/sh
set -eu
library=/mnt/root/usr/local/lib/oxp3-installer/firstboot-library
mkdir -p "$library/hdr"
for name in firstboot.py firstboot_stage.py file_transaction.py shared_state.py hdr/installer.py hdr/generate.py hdr/upstream.lua hdr/UPSTREAM_LICENSE; do
    test -f "/mnt/payload/components/$name"
    cp "/mnt/payload/components/$name" "$library/$name"
    chmod 0644 "$library/$name"
done
chmod 0755 "$library" "$library/hdr"
