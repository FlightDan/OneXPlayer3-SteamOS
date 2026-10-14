#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
mkfs.ext4 -q -F /dev/vda
mkdir -p /mnt/integration-test-scratch
mount /dev/vda /mnt/integration-test-scratch
export TMPDIR=/mnt/integration-test-scratch
python3 -B /mnt/payload/tasks/test_offload_mounts.py
python3 -B /mnt/payload/components/test_file_transaction.py
python3 -B /mnt/payload/components/test_runtime_access.py
python3 -B /mnt/payload/components/test_runtime_activation.py
if [ -f /mnt/payload/selection.json ]; then
    checks=$(python3 -B -c 'import json; value=json.load(open("/mnt/payload/selection.json")); assert value in ({"checks":"nonfatal"},{"checks":"permissions"}); print(value["checks"])')
    if [ "$checks" = permissions ]; then
        python3 -B /mnt/payload/components/test_integration.py \
            IntegrationChecks.test_directory_modes_do_not_inherit_secret_umask \
            IntegrationChecks.test_runtime_bundle_directories_ignore_restrictive_umask \
            IntegrationChecks.test_decky_startup_paths_and_deck_read_access \
            IntegrationChecks.test_desktop_return_launcher_repeat_and_existing_marker
    else
        python3 -B /mnt/payload/components/test_integration.py \
        IntegrationChecks.test_missing_decky_skips_dependents_and_keeps_independent_repair \
        IntegrationChecks.test_invalid_plugin_archive_is_skipped \
        IntegrationChecks.test_component_write_failure_is_fatal \
        IntegrationChecks.test_resource_io_failure_is_fatal \
        IntegrationChecks.test_dependency_and_unknown_language_rejected_before_write
    fi
else
    python3 -B /mnt/payload/components/test_integration.py
fi
umount /mnt/integration-test-scratch
printf '\nOXP_TASK_RESULT=passed\n'
