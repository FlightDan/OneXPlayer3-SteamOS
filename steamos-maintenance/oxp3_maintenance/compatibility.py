"""Reviewed component policies; release metadata cannot broaden these adapters."""

BASE = {'ID': 'steamos', 'VERSION_ID': '3.10', 'BUILD_ID': '20260924.1000'}
KERNEL = '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9'
DEVICE = {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}
PORTABLE = frozenset({'keyboard', 'flathub-ustc', 'partition-mount'})
BASELINE = frozenset({
    'slot-switch', 'refind', 'opti2xmx', 'opti2xmx-runtime', 'gamescope-env', 'hdr', 'desktop-hdr',
    'input', 'multifunction', 'gyro', 'xe-dsb', 'gm7-resume', 'split-lock', 'wifi', 'manager',
    'native-tdp', 'overlay', 'fan-driver', 'oxp3-fan', 'oxp3-cpu', 'charging', 'oxp3-light',
    'legacy-runtime', 'windows-reboot', 'decky', 'steamgriddb', 'protondb',
    'tabmaster', 'css-loader', 'autoflatpaks', 'deck-settings', 'hltb',
    'animation-changer', 'waydroid', 'serial-console-policy', 'autoflatpaks-compat', 'animation-changer-compat',
})


def device_supported(system):
    # Model names are diagnostic facts, not permission to use an adapter.
    return system.get('os', {}).get('ID') == 'steamos'


def baseline_supported(system):
    return (device_supported(system) and system.get('kernel') == KERNEL
            and all(system.get('os', {}).get(key) == value for key, value in BASE.items()))


def evaluate(name, system, metadata=None):
    """Return serializable requirements and the current host policy decision.

    File/dependency validity, shared-slot policy and runtime-specific checks are
    still required by the planner. Boolean probe flags never override facts.
    """
    metadata = metadata or {}
    if name not in PORTABLE | BASELINE:
        return {'supported': False, 'profile': 'unsupported-adapter',
                'reason': 'This maintenance version has no reviewed adapter for ' + name,
                'requirements': {}}
    portable = name in PORTABLE
    requirements = {'os': {'ID': 'steamos'} if portable else dict(BASE),
                    'packages': dict(metadata.get('packages', {})),
                    'shared_policy': 'steamos' if portable else 'exact-baseline'}
    if portable:
        requirements['resources'] = (
            ['usr/share/applications/org.kde.plasma.keyboard.desktop'] if name == 'keyboard'
            else ['usr/bin/' + tool for tool in ('python3', 'pkexec', 'kdialog', 'lsblk', 'findmnt', 'systemctl', 'systemd-escape')]
            if name == 'partition-mount'
            else ['usr/bin/flatpak'])
    else:
        requirements['kernel'] = KERNEL
    if name == 'hdr':
        requirements['packages']['gamescope'] = '3.16.30-1'
    if name == 'gyro':
        requirements.update(package_patterns={'inputplumber': r'0\.78\.0(?:-[^\s]+)?'})
    if name == 'slot-switch':
        requirements['resources'] = ['usr/bin/' + tool for tool in (
            'python3', 'pkexec', 'kdialog', 'steamos-bootconf', 'systemctl', 'busctl')]
    supported = device_supported(system) if portable else baseline_supported(system)
    reason = ('Supported SteamOS adapter; required resources are checked during planning'
              if portable else 'Supported exact SteamOS baseline') if supported else (
                  'Requires SteamOS' if portable else
                  'Requires SteamOS 3.10 build 20260924.1000 and kernel ' + KERNEL)
    return {'supported': supported, 'profile': 'portable-settings-v1' if portable else 'oxp3-r2-exact-v1',
            'reason': reason, 'requirements': requirements}
