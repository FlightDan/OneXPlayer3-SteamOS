"""Copy only the reviewed r2 release and source material into the tool cache."""
import json
from pathlib import Path
import shutil
import tarfile

root = Path(__file__).resolve().parents[1]
upstream = root.parent / 'plugins/waydroid-adaptation/output/20261012-ibt-r2'
version = 'steamos-3.10-b20260924.1000-wlroots0.20.2-oxp3-r2'
archive = upstream / (version + '.tar.gz')
with tarfile.open(archive, 'r:gz') as package:
    metadata = package.extractfile(version + '/target-fingerprint.env').read().decode()
    fields = dict(line.split('=', 1) for line in metadata.splitlines() if '=' in line)
    if fields.get('KERNEL_RELEASE') != '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9' or fields.get('STEAMOS_BUILD_ID') != '20260924.1000':
        raise RuntimeError('Unexpected r2 target metadata')
profile = {
    'schema': 1, 'id': 'waydroid', 'bundle_version': version, 'archive': archive.name,
    'source_archive': 'waydroid-source-ibt-r2.tar',
    'system': {'version': fields['STEAMOS_VERSION_ID'], 'build': fields['STEAMOS_BUILD_ID'], 'kernel': fields['KERNEL_RELEASE']},
    'packages': {name.removeprefix('PKG_').lower().replace('_', '-'): value for name, value in fields.items() if name.startswith('PKG_')},
    'binder_package': '1-2', 'android': {'version': 13, 'variant': 'GApps', 'included': False},
    'acceptance': {'device_use': 'user_reported_passed', 'date': '2026-10-13', 'granular_features': 'not_separately_recorded'},
    'deployment': 'resources_only_until_repeat_restore_and_matching_new_system_acceptance',
    'source': 'https://github.com/pjohno/steamos-waydroid-bundle',
    'handoff': 'plugins/waydroid-adaptation/README.md', 'rollback': 'not_yet_integrated'
}
destination = root / 'cache/components/waydroid'; destination.mkdir(parents=True, exist_ok=True)
for filename in (archive.name, profile['source_archive'], 'intel-ibt-kernel-calls.patch'):
    shutil.copyfile(upstream / filename, destination / filename)
(destination / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
(root / 'components/waydroid/profile.json').write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'cache': str(destination), 'bundle_bytes': archive.stat().st_size, 'compatibility': profile['system'], 'android_included': False}, indent=2))
