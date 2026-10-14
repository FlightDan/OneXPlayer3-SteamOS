"""Per-component read-only gates for the research control handoff."""


def evaluate(profile, component, system, hardware, packages, features):
    if component not in profile['components']: raise ValueError('Unsupported control component')
    target = profile['target']; reasons = []
    for key, source in (('system_version', 'version'), ('system_build', 'build'), ('kernel', 'kernel')):
        if system.get(source) != target[key]: reasons.append(f'{source}: requires {target[key]}')
    for key in ('vendor', 'product'):
        if hardware.get(key) != target[key]: reasons.append(f'{key}: requires {target[key]}')
    if component in ('native-tdp', 'manager', 'charging') and packages.get('steamos-manager') != target['manager']:
        reasons.append('Requires the exact SteamOS Manager version and patch baseline')
    if component == 'overlay' and packages.get('mangoapp') != target['mangoapp']:
        reasons.append('Requires the tested MangoApp version/layout')
    if component == 'oxp3-cpu':
        if features.get('core_groups') != target['core_groups']: reasons.append('Expected 2P/8E/4LP-E topology')
        if features.get('intel_pstate') != 'active': reasons.append('intel_pstate active is required')
    if component in ('oxp3-fan', 'charging') and features.get('fan_driver_validated') is not True:
        reasons.append('Exact-kernel fan driver and module restoration have not been validated for this installation')
    if component == 'charging' and features.get('battery_standard_controls_validated') is not True:
        reasons.append('Supported battery threshold/behaviour attributes and enum semantics have not been verified')
    return {'component': component, 'compatible': not reasons, 'reasons': reasons,
            'installation_allowed': False, 'deployment': 'resources_only',
            'pending': 'Independent file/service/runtime recovery and matching new-system acceptance'}
