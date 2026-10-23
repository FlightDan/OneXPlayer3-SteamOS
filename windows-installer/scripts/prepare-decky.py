"""Prepare or verify the pinned official Linux x86_64 Decky payload and source."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verified(data, record):
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Decky artifact differs from its pinned size or SHA-256')
    return data


def contents(pin, read):
    binary = verified(read('PluginLoader', pin['binary']), pin['binary'])
    if (binary[:6] != b'\x7fELF\x02\x01' or int.from_bytes(binary[18:20], 'little') != 62):
        raise ValueError('Decky must be a Linux x86_64 ELF binary')
    source_name = 'source-v' + pin['version'] + '.zip'
    source = verified(read(source_name, pin['source']), pin['source'])
    prefix = 'decky-loader-' + pin['source_commit'] + '/'
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        service = archive.read(prefix + 'dist/plugin_loader-release.service')
        license_text = archive.read(prefix + 'LICENSE')
    return {'PluginLoader': binary, source_name: source,
            'plugin_loader-release.service': service, 'LICENSE': license_text,
            'VERSION': (pin['version'] + '\n').encode('ascii')}


def prepare(pin_path, output, *, downloads=None, check=False):
    pin = json.loads(Path(pin_path).read_text(encoding='utf-8'))
    if pin.get('schema') != 1:
        raise ValueError('Unsupported Decky release metadata')
    output = Path(output)

    def read(name, record):
        if check or downloads is not None:
            path = (output if check else Path(downloads)) / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != record['bytes']:
                raise ValueError('Missing or unexpected Decky artifact: ' + name)
            return path.read_bytes()
        request = urllib.request.Request(record['url'], headers={'User-Agent': 'OXP3-SteamOS-Installer/1.0.6'})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(record['bytes'] + 1)

    files = contents(pin, read)
    manifest = {'schema': 1, 'version': pin['version'], 'source_commit': pin['source_commit'],
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())}}
    if check:
        if {p.name for p in output.iterdir()} != set(files) | {'manifest.json'}:
            raise ValueError('Unexpected or stale Decky cache files')
        for name, data in files.items():
            path = output / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError('Stale Decky payload: ' + name)
        if (output / 'manifest.json').is_symlink() or json.loads(
                (output / 'manifest.json').read_text(encoding='utf-8')) != manifest:
            raise ValueError('Stale Decky manifest; regenerate the payload')
    else:
        output.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            (output / name).write_bytes(data)
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/plugins/decky')
    parser.add_argument('--downloads', type=Path, help='Previously downloaded official artifacts, still checked against the pins')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    pin_path = ROOT / 'components/decky-release.json'
    pin = json.loads(pin_path.read_text(encoding='utf-8'))
    catalog = json.loads((ROOT / 'components/catalog.json').read_text(encoding='utf-8'))
    component = next(x for group in ('components', 'plugins') for x in catalog.get(group, []) if x['id'] == 'decky')
    if component['version'] != pin['version']:
        raise ValueError('Decky catalog and pinned release versions differ')
    print(json.dumps(prepare(pin_path, args.output, downloads=args.downloads, check=args.check)))
