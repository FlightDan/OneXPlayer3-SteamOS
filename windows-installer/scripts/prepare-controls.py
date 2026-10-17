"""Stage narrowly selected maintained control sources; never device snapshots."""
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
research = root.parent / 'research'
controls = root / 'components/controls'
destination = root / 'cache/components/oxp3-controls'; destination.mkdir(parents=True, exist_ok=True)
archive = destination / 'oxp3-controls-20261017-r7.zip'
selected = {
    'rapl/provider.py': 'rapl/provider.py', 'rapl/test_provider.py': 'rapl/test_provider.py',
    'manager/tdp-error-propagation.patch': 'manager/tdp-error-propagation.patch',
    'manager/tdp-live-state-cache.patch': 'manager/tdp-live-state-cache.patch',
    **{f'overlay/{name}': f'overlay/{name}' for name in (
        'telemetry.py', 'allow-read.py', 'test_telemetry_fan.py', 'test_telemetry_gpu.py',
        'presets.conf', 'update-layout.py', 'test-layout-device.py',
        'cpu_control.py', 'cpu-plugin-main.py', 'cpu-plugin-index.js', 'test_cpu_control.py',
        'fan.py', 'fan-plugin-main.py', 'fan-plugin-index.js', 'fan-sleep.py', 'load-fan-module.py', 'test_fan.py')},
    **{f'charging/{name}': f'charging/{name}' for name in (
        'battery_control.py', 'battery_provider.py', 'battery-plugin-main.py', 'battery-plugin-index.js',
        'deploy-battery.py', 'update-battery-ui.py', 'check-battery-ui.mjs')},
    'PLUGIN_LANGUAGES.md': 'PLUGIN_LANGUAGES.md',
    'check-plugin-i18n.mjs': 'check-plugin-i18n.mjs',
}
selected.update({f'overlay/{name}': f'overlay/{name}' for name in (
    'power_control.py', 'test_power_control.py', 'test_cpu_power_ui.mjs')})

def source_path(source):
    if source in ('overlay/telemetry.py', 'overlay/allow-read.py',
                  'overlay/test_telemetry_fan.py', 'overlay/test_telemetry_gpu.py'):
        return controls / source
    if source.startswith('rapl/'):
        return controls / source
    if source.startswith('overlay/') and source.split('/', 1)[1] in (
            'cpu_control.py', 'cpu-plugin-main.py', 'cpu-plugin-index.js', 'test_cpu_control.py',
            'power_control.py', 'test_power_control.py', 'test_cpu_power_ui.mjs'):
        return controls / 'cpu' / source.split('/', 1)[1]
    return research / source

with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
    for target, source in selected.items():
        entry = zipfile.ZipInfo(target, date_time=(2026, 10, 17, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED; entry.external_attr = 0o100644 << 16
        package.writestr(entry, source_path(source).read_bytes())
profile = {
    'schema': 1, 'id': 'oxp3-controls', 'version': '20261017-r7', 'archive': archive.name,
    'source_files': list(selected), 'deployment': 'resources_only', 'default': False,
    'target': {'vendor': 'ONE-NETBOOK', 'product': 'ONEXPLAYER 3', 'cpu': 'Intel Arc G3 Extreme',
               'system_version': '3.10', 'system_build': '20260924.1000',
               'kernel': '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9', 'manager': '26.4.1-2',
               'mangoapp': '0.8.3.rc1.r24.g33c2c7dd-4', 'core_groups': [2, 8, 4]},
    'components': ['native-tdp', 'manager', 'overlay', 'oxp3-fan', 'oxp3-cpu', 'charging'],
    'reference_only': ['charging/deploy-battery.py', 'charging/update-battery-ui.py'],
    'tdp': {'min_watts': 10, 'max_watts': 40, 'pl2_max_watts': 80,
            'independent_pl2': True, 'steam_pl1_sync': True,
            'default_power_change': False, 'long_40w_thermal_acceptance': False},
    'fan': {'default': 'firmware_auto', 'driver_binary_included': False, 'driver_rebuild_and_module_restore': 'pending'},
    'cpu': {'default_enabled': False, 'independent_watt_limit': False, 'ibc_manual_control': False,
            'first_load_error_root_cause': 'not_confirmed'},
    'battery': {'min_percent': 60, 'max_percent': 100, 'default_policy_change': False,
                'shared_validated_fan_module_required': True, 'boot_policy_reapplication': False,
                'electrical_bypass_accepted': False, 'exact_raw_behaviour_restore': False,
                'charge_effect_and_sleep_reboot_acceptance': 'pending'},
    'plugin_languages': {'plugins': ['OXP3 CPU', 'OXP3 Fan', 'OXP3 Battery'],
                         'bundled': ['zh', 'en'], 'source': 'navigator.language',
                         'chinese_language_codes': 'zh and zh-* (case-insensitive; underscores accepted)',
                         'other_languages_and_missing_locale': 'en', 'missing_translation': 'en',
                         'install_time_language_selection': False},
    'desktop_hdr': {'state': 'research_pending', 'safe_recovery': ['hdr_off', 'wcg_off', 'dpms_on'],
                    'gamma22_window_highlights': 'not_accepted', 'hide_unsafe_internal_toggle_if_not_adaptable': True},
    'acceptance': 'TDP and fan user-confirmed; CPU prototype readback/restore/reload passed; new-install and lifecycle acceptance pending',
    'handoff': ['RESEARCH_GOAL.md', 'DEVICE_CHANGES.md', 'research/REMAINING_ACCEPTANCE.md'],
    'note': 'No automatic deployment, kernel binary, device configuration, credentials or private screenshot is included.'
}
(destination / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
source_profile = root / 'components/controls/profile.json'; source_profile.parent.mkdir(parents=True, exist_ok=True)
source_profile.write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'source_files': len(selected), 'deployment': 'resources_only'}, indent=2))
