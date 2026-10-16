#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
cd /mnt/payload/components
python3 -B -m unittest -v test_windows_reboot.py
python3 -B -m unittest -v test_slot_switch.py
python3 -B -m unittest -v test_file_transaction.py
python3 -B -m unittest -v test_directory_transaction.py
python3 -B -m unittest -v test_shared_storage.py test_ntfs_steam.py
python3 -B -m unittest -v test_plugin_installer.py
python3 -B -m unittest -v test_animation_changer_compat.py
python3 -B -m unittest -v test_decky_order.py
python3 -B -m unittest -v test_update_hold.py test_update_hold_verify.py test_update_hold_integration.py
cd /mnt/payload/components/hdr
python3 -B -m unittest -v test_generate.py
cd /mnt/payload/components/waydroid
python3 -B -m unittest -v test_compatibility.py
cd /mnt/payload/components/controls
python3 -B -m unittest -v test_compatibility.py
python3 - <<'PY'
import json, zipfile
from pathlib import Path
profile = json.loads(Path('/mnt/payload/control-resources/profile.json').read_text())
archive = Path('/mnt/payload/control-resources') / profile['archive']
destination = Path('/tmp/oxp3-control-regression'); destination.mkdir()
with zipfile.ZipFile(archive) as package:
    if set(package.namelist()) != set(profile['source_files']): raise RuntimeError('Unexpected control bundle source file')
    for member in package.infolist():
        path = Path(member.filename)
        if path.is_absolute() or '..' in path.parts: raise RuntimeError('Unsafe source bundle path')
        target = destination / path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.read(member))
PY
cd /tmp/oxp3-control-regression/rapl
python3 -B -m unittest -v test_provider.py
cd /tmp/oxp3-control-regression/overlay
python3 -B -m unittest -v test_cpu_control.py test_power_control.py test_fan.py
printf '\nOXP_TASK_RESULT=passed\n'
