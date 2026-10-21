#!/bin/sh
set -eu
prefix=/opt/oxp3-desktop-gamma22/6.7.3-1.6
unset LD_LIBRARY_PATH KWIN_OXP3_GAMMA22_HDR KWIN_X2MINI_HDR_PROFILE
trial=/home/deck/.local/lib/oxp3-desktop-hdr-runtime/hdr_trial.py
current=$(/usr/bin/pacman -Q kwin qt6-base qt6-declarative 2>/dev/null || true)
expected=$(cat "$prefix/compatible-packages.txt" 2>/dev/null || true)
compatible=false
if [ -x "$prefix/bin/kwin_wayland_wrapper" ] && [ -f "$trial" ] && [ -f "${trial%/*}/x2mini_device.py" ] && [ -n "$expected" ] && [ "$current" = "$expected" ]; then compatible=true; fi
if [ "${1:-}" = --check ]; then
    printf 'stable_bundle_compatible=%s\n' "$compatible"
    [ "$compatible" = true ]
    exit
fi
if [ -f "$trial" ] && ! /usr/bin/python3 -I -B "$trial" --recover-startup; then
    /usr/bin/logger -t oxp3-desktop-hdr 'Unconfirmed HDR trial recovery failed; refusing the custom compositor'
    compatible=false
fi
if [ "$compatible" != true ]; then
    /usr/bin/logger -t oxp3-desktop-hdr 'Package versions changed; restoring SDR settings and using stock KWin'
    /usr/bin/python3 -I /home/deck/.local/lib/oxp3-desktop-hdr-runtime/disable-hdr.py
    export PATH=/usr/local/bin:/usr/bin
    exec /usr/bin/kwin_wayland_wrapper --xwayland
fi
export KWIN_OXP3_GAMMA22_HDR=1
if /usr/bin/python3 -I -B "$trial" --device-check; then
    export KWIN_X2MINI_HDR_PROFILE=1
    /usr/bin/python3 -I -B "$trial" --install-launcher || /usr/bin/logger -t oxp3-desktop-hdr 'X2mini HDR launcher installation skipped; preserve existing user files'
fi
export LD_LIBRARY_PATH="$prefix/lib"
export PATH="$prefix/bin:/usr/local/bin:/usr/bin"
exec "$prefix/bin/kwin_wayland_wrapper" --xwayland
