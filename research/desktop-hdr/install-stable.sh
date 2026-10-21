#!/bin/bash
set -eu
b=/home/deck/oxp3-research/kde-gamma22-build-v1
prefix=/opt/oxp3-desktop-gamma22/6.7.3-1.6
r=/var/lib/oxp3-desktop-gamma22-v1
u(){ /usr/sbin/runuser -u deck -- env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "$@"; }
[ "$(u systemctl --user show oxp3-gamma22-stable-build-v1.service -p ActiveState --value)" = inactive ]
[ "$(u systemctl --user show oxp3-gamma22-stable-build-v1.service -p Result --value)" = success ]
[ ! -e "$prefix" ]
[ -x "$b/stable-stage$prefix/bin/kwin_wayland_wrapper" ]
install -d -m 755 "$prefix"
cp -a "$b/stable-stage$prefix/." "$prefix/"
chown -R root:root "$prefix"
chmod -R go-w "$prefix"
install -m 755 "$b/launch-stable.sh" "$prefix/bin/oxp3-kwin-launch"
install -m 644 "$b/disable-hdr.py" "$prefix/disable-hdr.py"
install -m 644 "$b/compatible-packages.txt" "$prefix/compatible-packages.txt"
install -m 755 "$b/oxp3-mapped-hdr-control" "$prefix/bin/oxp3-mapped-hdr-control"
boot=/home/deck/.local/lib/oxp3-desktop-hdr-runtime
install -d -o root -g root -m 755 "$boot"
install -o root -g root -m 755 "$b/launch-stable.sh" "$boot/launch.sh"
install -o root -g root -m 644 "$b/disable-hdr.py" "$boot/disable-hdr.py"
u "$prefix/bin/oxp3-kwin-launch" --check
sh -n "$prefix/bin/oxp3-kwin-launch"
LD_LIBRARY_PATH="$prefix/lib" "$prefix/bin/kwin_wayland" --version
LD_LIBRARY_PATH="$prefix/lib" ldd "$prefix/bin/kwin_wayland" > "$r/stable-ldd.txt"
if grep -q 'not found' "$r/stable-ldd.txt"; then exit 1; fi
cp -a /home/deck/.config/systemd/user/plasma-kwin_wayland.service.d/90-oxp3-gamma22.conf "$r/candidate-dropin-before-stable"
cp -a /home/deck/.local/share/applications/oxp3-mapped-hdr.desktop "$r/launcher-before-stable"
cat > "$r/stable-activate.sh" <<'ACT'
#!/bin/bash
set -eu
u(){ /usr/sbin/runuser -u deck -- env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "$@"; }
p=/home/deck/.config/systemd/user/plasma-kwin_wayland.service.d/90-oxp3-gamma22.conf
cat > "$p" <<'UNIT'
[Service]
UnsetEnvironment=LD_LIBRARY_PATH KWIN_OXP3_GAMMA22_HDR
ExecStart=
ExecStart=/home/deck/.local/lib/oxp3-desktop-hdr-runtime/launch.sh
UNIT
chown deck:deck "$p"
game=/home/deck/.config/systemd/user/gamescope-session.service.d/90-oxp3-desktop-env-isolation.conf
r=/var/lib/oxp3-desktop-gamma22-v1
if [ ! -e "$r/game-env-before-recorded" ]; then
 if [ -e "$game" ]; then cp -a "$game" "$r/game-env-before.conf"; else touch "$r/game-env-before-absent"; fi
 touch "$r/game-env-before-recorded"
fi
if [ -e "$r/game-env-installed.conf" ] && [ -e "$game" ] && ! cmp -s "$game" "$r/game-env-installed.conf"; then
 echo 'Game environment override changed; preserve user changes' >&2
 exit 1
fi
install -d -o deck -g deck -m 755 /home/deck/.config/systemd/user/gamescope-session.service.d
cat > "$game" <<'GAME'
[Service]
# Clear KDE client sockets before starting the native game-mode compositor.
ExecStartPre=/usr/bin/systemctl --user unset-environment WAYLAND_DISPLAY WAYLAND_SOCKET
UnsetEnvironment=WAYLAND_DISPLAY WAYLAND_SOCKET
GAME
chown deck:deck "$game"
cp -a "$game" "$r/game-env-installed.conf"
u systemctl --user daemon-reload
u steamosctl switch-to-game-mode
sleep 12
u steamosctl switch-to-desktop-mode plasma.desktop
ACT
chmod 700 "$r/stable-activate.sh"
systemd-run --unit=oxp3-gamma22-stable-rollback --on-active=180s "$r/restore.sh"
systemd-run --unit=oxp3-gamma22-stable-activate "$r/stable-activate.sh"
