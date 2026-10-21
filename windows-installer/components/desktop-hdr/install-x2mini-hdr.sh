#!/bin/sh
# Called as the KDE user. The Python installer checks live DMI before any write.
set -eu
trial=/home/deck/.local/lib/oxp3-desktop-hdr-runtime/hdr_trial.py
if ! /usr/bin/python3 -I -B "$trial" --device-check; then
    printf '%s\n' 'X2mini not detected; HDR trial launcher was not installed.'
    exit 0
fi
exec /usr/bin/python3 -I -B "$trial" --install-launcher
