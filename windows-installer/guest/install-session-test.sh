#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_fs_metadata.py
python3 -B /mnt/payload/tasks/test_media_layer.py
python3 -B /mnt/payload/tasks/test_install_session.py
python3 -B /mnt/payload/tasks/test_intent.py
OXP_INTENT_INITIALIZE=1 . /mnt/payload/tasks/mount-intent.sh
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '/mnt/payload/tasks')
from install_session import review, candidate, execute_virtual, handoff_to_esp
from intent_store import IntentStore
from deployment import table
selection = json.loads(Path('/mnt/payload/selection.json').read_text())
before = table('/dev/vdd')
if execute_virtual(selection, '/dev/vdc', '/dev/vdd', None) is not None or table('/dev/vdd') != before:
    raise RuntimeError('Declined confirmation wrote a partition')
accepted = review(selection, [candidate('/dev/vdd')])
print('OXP_INSTALL_REVIEW=' + json.dumps(accepted), flush=True)
journal = IntentStore(Path('/mnt/session-state/oxp3'))
result = execute_virtual(selection, '/dev/vdc', '/dev/vdd', accepted, journal=journal)
handoff_to_esp(result, journal)
Path('/tmp/session-deployment.json').write_text(json.dumps(result))
print('OXP_INSTALL_SESSION=windows-selection-to-confirmed-append', flush=True)
PY
python3 -B /mnt/payload/tasks/test_deployment_plan.py
python3 -B /mnt/payload/tasks/deployment-fixture.py
umount /mnt/session-state
printf '\nOXP_TASK_RESULT=passed\n'
