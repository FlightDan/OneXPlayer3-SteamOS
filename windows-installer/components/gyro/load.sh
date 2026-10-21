#!/bin/bash
set -euo pipefail
test "$(uname -r)" = '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9'
test "$(/usr/bin/inputplumber --version)" = 'inputplumber 0.78.0'
test ! -e /sys/bus/i2c/devices/i2c-10EC5280:00/driver
modprobe bmi270_core
insmod /var/lib/oxp3-gyro-v1/oxp3_bmi260.ko
test "$(basename "$(readlink /sys/bus/i2c/devices/i2c-10EC5280:00/driver)")" = oxp3_bmi260
