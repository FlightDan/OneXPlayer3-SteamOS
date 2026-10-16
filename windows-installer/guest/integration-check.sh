#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
mkfs.ext4 -q -F /dev/vda
mkdir -p /mnt/integration-test-scratch
mount /dev/vda /mnt/integration-test-scratch
export TMPDIR=/mnt/integration-test-scratch
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"log-spam"})'; then
    python3 -B /mnt/payload/components/test_integration.py -v \
        IntegrationChecks.test_serial_console_policy_repeat_and_restore_both_slots \
        IntegrationChecks.test_serial_console_policy_preserves_later_admin_edit \
        IntegrationChecks.test_autoflatpaks_pinned_patch_stages_and_restores \
        IntegrationChecks.test_disabled_items_do_not_install \
        IntegrationChecks.test_mandatory_update_hold_real_journals_restore_both_slots
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"maintenance-tool"})'; then
    python3 -B /mnt/payload/components/test_integration.py -v \
        IntegrationChecks.test_maintenance_tool_repeat_launch_and_restore \
        IntegrationChecks.test_maintenance_missing_payload_refuses_before_image_writes \
        IntegrationChecks.test_maintenance_manifest_tampering_is_refused \
        IntegrationChecks.test_desktop_language_presets_stage_and_restore \
        IntegrationChecks.test_cross_slot_home_original_and_recovery
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
# Exercise the required update hold through the real offline staging journal.
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"update-hold"})'; then
    python3 -B /mnt/payload/components/test_integration.py -v \
        IntegrationChecks.test_new_install_selections_preserve_system_updaters \
        IntegrationChecks.test_existing_administrator_update_configuration_is_preserved \
        IntegrationChecks.test_missing_vendor_update_units_refuse_before_new_writes \
        IntegrationChecks.test_mandatory_update_hold_real_journals_restore_both_slots \
        IntegrationChecks.test_incompatible_source_refuses_repairs \
        IntegrationChecks.test_disabled_items_do_not_install \
        IntegrationChecks.test_legacy_update_policy_journal_remains_restorable \
        IntegrationChecks.test_legacy_policy_marker_or_incomplete_journal_refuses_before_new_writes \
        IntegrationChecks.test_cross_slot_home_original_and_recovery \
        IntegrationChecks.test_dependency_and_unknown_language_rejected_before_write \
        IntegrationChecks.test_shared_storage_unmanaged_fstab_conflict_is_readonly_skip \
        IntegrationChecks.test_missing_decky_skips_dependents_and_keeps_independent_repair \
        IntegrationChecks.test_desktop_language_presets_stage_and_restore
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"shared-storage"})'; then
    python3 -B /mnt/payload/components/test_shared_storage.py -v
    python3 -B /mnt/payload/components/test_ntfs_steam.py -v
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"home-ownership"})'; then
    python3 -B /mnt/payload/components/test_integration.py -v \
        IntegrationChecks.test_fresh_home_allows_deck_to_create_steam \
        IntegrationChecks.test_root_owned_home_parents_are_repaired_without_recursive_chown \
        IntegrationChecks.test_user_directory_rejects_symlinks_and_foreign_owners
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
if [ -f /mnt/payload/selection.json ] && python3 -B -c 'import json,sys; sys.exit(json.load(open("/mnt/payload/selection.json"))!={"checks":"desktop-language"})'; then
    python3 -B /mnt/payload/components/test_integration.py \
        IntegrationChecks.test_desktop_language_presets_stage_and_restore \
        IntegrationChecks.test_kde_preserves_unrelated_settings \
        IntegrationChecks.test_disabled_items_do_not_install
    umount /mnt/integration-test-scratch
    printf '\nOXP_TASK_RESULT=passed\n'
    exit 0
fi
python3 -B /mnt/payload/tasks/test_offload_mounts.py
python3 -B /mnt/payload/components/test_file_transaction.py
python3 -B /mnt/payload/components/test_runtime_access.py
python3 -B /mnt/payload/components/test_runtime_activation.py
python3 -B /mnt/payload/components/test_system_update_policy.py
python3 -B /mnt/payload/components/test_slot_switch.py
python3 -B /mnt/payload/components/test_decky_order.py
if [ -f /mnt/payload/selection.json ]; then
    checks=$(python3 -B -c 'import json; value=json.load(open("/mnt/payload/selection.json")); assert value in ({"checks":"nonfatal"},{"checks":"permissions"},{"checks":"startup"},{"checks":"slot-switch"}); print(value["checks"])')
    if [ "$checks" = slot-switch ]; then
        python3 -B /mnt/payload/components/test_integration.py IntegrationChecks.test_slot_switch_shared_lifecycle
        test "$(cat /sys/block/vdc/ro)" = 1
        mkdir -p /mnt/official-slot-source
        mount -t btrfs -o ro,rescue=nologreplay /dev/vdc /mnt/official-slot-source
        mount --bind /mnt/integration-test-scratch /mnt/official-slot-source/tmp
        python3 -B /mnt/payload/components/test_official_slot_boot.py /mnt/official-slot-source
        umount /mnt/official-slot-source/tmp
        umount /mnt/official-slot-source
    elif [ "$checks" = startup ]; then
        python3 -B /mnt/payload/components/test_integration.py \
            IntegrationChecks.test_new_install_selections_preserve_system_updaters \
            IntegrationChecks.test_existing_administrator_update_configuration_is_preserved \
            IntegrationChecks.test_legacy_update_policy_journal_remains_restorable \
            IntegrationChecks.test_legacy_policy_marker_or_incomplete_journal_refuses_before_new_writes \
            IntegrationChecks.test_cross_slot_home_original_and_recovery \
            IntegrationChecks.test_directory_modes_do_not_inherit_secret_umask \
            IntegrationChecks.test_desktop_return_launcher_repeat_and_existing_marker
    elif [ "$checks" = permissions ]; then
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
        IntegrationChecks.test_shared_storage_preflight_failure_skips_both_slots_and_keeps_repair \
        IntegrationChecks.test_shared_storage_preflight_device_errors_remain_fatal \
        IntegrationChecks.test_shared_storage_unmanaged_fstab_conflict_is_readonly_skip \
        IntegrationChecks.test_shared_storage_existing_transaction_cannot_be_skipped \
        IntegrationChecks.test_shared_storage_partial_write_failure_remains_fatal \
        IntegrationChecks.test_dependency_and_unknown_language_rejected_before_write
    fi
else
    python3 -B /mnt/payload/components/test_integration.py
fi
umount /mnt/integration-test-scratch
printf '\nOXP_TASK_RESULT=passed\n'
