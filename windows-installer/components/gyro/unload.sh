#!/bin/bash
set -eu
if test -d /sys/module/oxp3_bmi260; then rmmod oxp3_bmi260; fi
