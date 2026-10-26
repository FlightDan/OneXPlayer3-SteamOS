"""Prepare or verify the official LSFG-VK plugin, without paid DLLs or user state."""
import argparse
import json
from pathlib import Path
import urllib.request

from lsfg_payload import ROOT, cache_manifest, read_cache, read_pin, read_plugin_archive, check_integration


def prepare(output, archive=None, check=False):
    pin = read_pin()
    output = Path(output)
    if check:
        return cache_manifest(pin, read_cache(output, pin))
    if archive is not None:
        archive = Path(archive)
        files = read_plugin_archive(archive, pin)
        raw = archive.read_bytes()
    else:
        request = urllib.request.Request(pin['archive']['url'], headers={'User-Agent': 'OXP3-SteamOS-Installer/1.0.6'})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(pin['archive']['bytes'] + 1)
        # Verify the downloaded artifact before publishing a cache directory.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='oxp3-lsfg-download-') as temporary:
            downloaded = Path(temporary) / pin['archive']['filename']
            downloaded.write_bytes(raw)
            files = read_plugin_archive(downloaded, pin)
    manifest = cache_manifest(pin, files)
    if output.exists():
        if any(output.iterdir()):
            raise FileExistsError('Use a new LSFG-VK output directory or --check for an existing cache')
    else:
        output.mkdir(parents=True)
    (output / pin['archive']['filename']).write_bytes(raw)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/lsfg-vk')
    parser.add_argument('--archive', type=Path, help='Previously downloaded official ZIP; still checked against the pin')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--check-integration', type=Path, metavar='DIRECTORY')
    args = parser.parse_args()
    if args.check_integration:
        result = check_integration(args.check_integration, args.output)
    else:
        result = prepare(args.output, args.archive, args.check)
    print(json.dumps(result))
