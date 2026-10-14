#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
export PYTHONPATH=/mnt/payload/components
python3 -B /mnt/payload/components/test_file_transaction.py
python3 -B -m unittest -v \
 test_integration.IntegrationChecks.test_gm7_boot_entries_repeat_and_restore \
 test_integration.IntegrationChecks.test_gm7_does_not_tune_other_disks_or_override_conflicts \
 test_integration.IntegrationChecks.test_be201_missing_firmware_repeat_restore_preserves_stock \
 test_integration.IntegrationChecks.test_fresh_home_allows_deck_to_create_steam \
 test_integration.IntegrationChecks.test_root_owned_home_parents_are_repaired_without_recursive_chown \
 test_integration.IntegrationChecks.test_user_directory_rejects_symlinks_and_foreign_owners \
 test_integration.IntegrationChecks.test_disabled_items_do_not_install \
 test_integration.IntegrationChecks.test_incompatible_source_refuses_repairs \
 test_integration.IntegrationChecks.test_dependency_and_unknown_language_rejected_before_write \
 test_integration.IntegrationChecks.test_user_changes_block_restore \
 test_integration.IntegrationChecks.test_changed_request_is_preserved \
 test_integration.IntegrationChecks.test_kde_preserves_unrelated_settings \
 test_integration.IntegrationChecks.test_gamescope_environment_isolation_has_independent_restore \
 test_integration.IntegrationChecks.test_live_guard_refuses_this_virtual_machine \
 test_integration.IntegrationChecks.test_cross_slot_home_original_and_recovery
python3 -B - <<'PY'
import json, pathlib
base=pathlib.Path('/mnt/payload/integration')
manifest=json.loads((base/'manifest.json').read_text())
checked=0
for component,value in manifest.items():
 for item in value['files']:
  if item['target'].startswith('etc/systemd/system/') and item['target'].endswith('.service'):
   assert b'integration_runtime.py guard' in (base/item['source']).read_bytes()
   checked+=1
assert checked>=7
assert any(x['target'].endswith('sleep.target.d/90-oxp3-fan.conf') for x in manifest['oxp3-fan']['files'])
assert any(x['target'].endswith('default.target.d/90-oxp3-overlay.conf') for x in manifest['overlay']['files'])
presets=next(x for x in manifest['overlay']['files'] if x['target'].endswith('MangoHud/presets.conf'))
text=(base/presets['source']).read_text()
assert 'exec=/usr/bin/python3' not in text
assert text.count('exec=read -r oxp_now')==9
print('OXP_SERVICE_GUARDS=passed:'+str(checked))
PY
python3 -B /mnt/payload/integration/sources/overlay/test-layout-device.py
printf '\nOXP_TASK_RESULT=passed\n'
