"""Explicit version gates for the accepted Waydroid r2 artifact; read-only."""
import json
from pathlib import Path
import platform
import subprocess


def evaluate(profile, system, kernel, packages):
    errors = []
    for field in ('version', 'build'):
        if system.get(field) != profile['system'][field]:
            errors.append(f"SteamOS {field}: expected {profile['system'][field]}, found {system.get(field, 'unknown')}")
    if kernel != profile['system']['kernel']:
        errors.append(f"Kernel: expected {profile['system']['kernel']}, found {kernel}")
    for package, version in profile['packages'].items():
        if packages.get(package) != version:
            errors.append(f"{package}: expected {version}, found {packages.get(package, 'missing')}")
    return {'compatible': not errors, 'reasons': errors, 'installation_allowed': False,
            'reason': 'File/package restoration and first-start integration require validation before automated deployment'}


def inspect_system(root, profile):
    root = Path(root)
    release = dict(line.split('=', 1) for line in (root / 'etc/os-release').read_text().splitlines() if '=' in line)
    system = {'version': release.get('VERSION_ID', '').strip('"'), 'build': release.get('BUILD_ID', '').strip('"')}
    query = subprocess.run(['chroot', str(root), 'pacman', '-Q', *profile['packages']], text=True, capture_output=True)
    packages = dict(line.split(' ', 1) for line in query.stdout.splitlines() if ' ' in line)
    return evaluate(profile, system, platform.release(), packages)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3: raise SystemExit('Usage: compatibility.py SYSTEM_ROOT profile.json')
    result = inspect_system(sys.argv[1], json.loads(Path(sys.argv[2]).read_text()))
    print(json.dumps(result, indent=2)); raise SystemExit(0 if result['compatible'] else 2)
