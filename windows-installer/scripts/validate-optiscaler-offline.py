"""Exercise the shipped plugin's archive cache and extraction without networking.

Uses disposable directories and the real pinned archives from the integration
manifest. This checks package preparation, not game installation or device QA.
On Windows only the POSIX path guard is replaced for the disposable test tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/opti2xmx'))
from manager import Manager
import opti


def validate(sevenzip):
    pins = json.loads((ROOT / 'components/optiscaler-release.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'cache/integration/manifest.json').read_text(encoding='utf-8'))
    real_run = subprocess.run
    calls = []

    def extract(args, **kwargs):
        if args[0] != '7z':
            raise AssertionError('Unexpected command during offline extraction')
        calls.append(args[0])
        return real_run([str(sevenzip), *args[1:]], **kwargs)

    results = []
    with tempfile.TemporaryDirectory(prefix='opti-offline-') as temporary:
        # per_game.py requires Linux fcntl; no game or Proton methods are used.
        manager = Manager(temporary, engine=SimpleNamespace(no_symlink_parents=lambda path: None))
        with mock.patch.object(opti.urllib.request, 'urlopen', side_effect=AssertionError('Network attempted')):
            for pin in pins['archives']:
                relative = 'home/deck/.local/share/opti2xmx/downloads/' + pin['tag'] + '/' + pin['filename']
                entry = next(item for item in manifest['opti2xmx']['files'] if item['target'] == relative)
                source = ROOT / 'cache/integration' / entry['source']
                if source.stat().st_size != pin['size_bytes'] or hashlib.sha256(source.read_bytes()).hexdigest() != pin['sha256']:
                    raise ValueError('Stale generated OptiScaler archive')
                archive = manager.root / 'downloads' / pin['tag'] / pin['filename']
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, archive)
                print('Checking offline extraction: ' + pin['version'], flush=True)
                with mock.patch.object(opti.subprocess, 'run', side_effect=extract):
                    payload = manager.opti_package(pin['version'], 'github')
                xess = 'OptiScaler/libxess.dll' if pin['version'].startswith('10.') else 'libxess.dll'
                for name in ('OptiScaler.dll', xess):
                    with (payload / name).open('rb') as stream:
                        if stream.read(2) != b'MZ':
                            raise ValueError('Invalid extracted DLL: ' + name)
                if not (payload / 'OptiScaler.ini').is_file() or not (payload / 'Licenses/XeSS_LICENSE.txt').is_file():
                    raise ValueError('Missing extracted configuration or license')
                with mock.patch.object(opti.subprocess, 'run', side_effect=AssertionError('Cache hit re-extracted')):
                    if manager.opti_package(pin['version'], 'github') != payload:
                        raise AssertionError('Prepared cache was not reused')
                results.append({'version': pin['version'], 'archive_sha256': pin['sha256'],
                                'extracted_files': sum(path.is_file() for path in payload.rglob('*')),
                                'no_network': True, 'repeat_reused_payload': True})
    plugin_version = json.loads((ROOT / 'components/opti2xmx/package.json').read_text(encoding='utf-8'))['version']
    return {'passed': True, 'plugin_version': plugin_version, 'versions': results,
            'real_extraction_commands': len(calls), 'game_installation_tested': False,
            'device_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sevenzip', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.sevenzip.resolve())
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
