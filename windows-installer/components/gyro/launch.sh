#!/bin/bash
set -eu
if [[ "$(/usr/bin/inputplumber --version)" == 'inputplumber 0.78.0' ]] &&
   [[ -d /sys/module/oxp3_bmi260 ]] &&
   /var/lib/oxp3-gyro-v1/inputplumber --version >/dev/null 2>&1; then
    exec /var/lib/oxp3-gyro-v1/inputplumber "$@"
fi
exec /usr/bin/inputplumber "$@"
