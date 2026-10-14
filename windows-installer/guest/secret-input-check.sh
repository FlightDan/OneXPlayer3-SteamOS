#!/bin/sh
set -eu
# Isolated regression: no system image or physical disk attached.
if test -f /tmp/oxp-deck-initial-password; then
    test "$(stat -c '%a' /tmp/oxp-deck-initial-password)" = 600
    expected='Handshake-r-中文-42!'
    while test "$(printf '%s' "$expected" | wc -c)" -lt 255; do expected="${expected}x"; done
    test "$(cat /tmp/oxp-deck-initial-password)" = "$expected"
    su -s /bin/sh nobody -c 'test ! -r /tmp/oxp-deck-initial-password'
    unset expected
    printf '\nOXP_SECRET_CHECK=passed\n'
fi

# The following task must create user-readable system files even when a
# password was supplied. This catches the old inherited umask 077 bug.
probe=$(mktemp -d /tmp/oxp-task-permissions.XXXXXX)
trap 'rm -rf "$probe"' EXIT
chmod 755 "$probe"
mkdir -p "$probe/etc/dbus-1/session.d" "$probe/opt/runtime/lib"
printf 'public configuration\n' > "$probe/etc/dbus-1/session.d/probe.conf"
for directory in "$probe/etc" "$probe/etc/dbus-1" "$probe/etc/dbus-1/session.d" "$probe/opt/runtime/lib"; do
    test "$(stat -c '%a' "$directory")" = 755 || {
        printf 'OXP_TASK_PERMISSIONS=failed: directory mode %s\n' "$(stat -c '%a' "$directory")"
        exit 1
    }
done
test "$(stat -c '%a' "$probe/etc/dbus-1/session.d/probe.conf")" = 644
su -s /bin/sh nobody -c "cat '$probe/etc/dbus-1/session.d/probe.conf' >/dev/null && test -x '$probe/opt/runtime/lib'"
mkdir -m 700 "$probe/private"
(umask 077; printf 'private state\n' > "$probe/private/state")
test "$(stat -c '%a' "$probe/private/state")" = 600
su -s /bin/sh nobody -c "test ! -r '$probe/private/state'"
printf '\nOXP_TASK_PERMISSIONS=passed\nOXP_TASK_RESULT=passed\n'
