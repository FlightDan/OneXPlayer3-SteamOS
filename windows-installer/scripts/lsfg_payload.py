"""Read the unchanged, hash-pinned Decky LSFG-VK release for both installers."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / 'components/lsfg-vk-release.json'
PLUGIN_ROOT = 'var/lib/oxp3-installer/decky/runtime/plugins/Decky LSFG-VK/'


def read_pin(path=PIN_PATH):
    pin = json.loads(Path(path).read_text(encoding='utf-8'))
    if (pin.get('schema') != 1 or pin.get('id') != 'lsfg-vk' or
            pin.get('name') != 'Decky LSFG-VK' or pin.get('version') != '0.14.4' or
            pin.get('folder') != 'Decky LSFG-VK' or
            pin.get('deployment') != 'plugin-only-with-bundled-runtime'):
        raise ValueError('Unsupported LSFG-VK release pin')
    return pin


def read_plugin_archive(path, pin=None):
    pin = read_pin() if pin is None else pin
    path = Path(path)
    record = pin['archive']
    if path.is_symlink() or not path.is_file() or path.stat().st_size != record['bytes']:
        raise ValueError('Missing or unexpected LSFG-VK release archive')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('LSFG-VK archive SHA-256 does not match the pinned release')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if ('\\' in entry.filename or name.is_absolute() or '..' in name.parts or
                    not name.parts or name.parts[0] != pin['folder'] or stat.S_ISLNK(mode)):
                raise ValueError('Unexpected LSFG-VK archive path')
            if entry.is_dir():
                continue
            relative = PurePosixPath(*name.parts[1:]).as_posix()
            if relative in files or relative.lower().endswith('.dll'):
                raise ValueError('Unexpected LSFG-VK payload file')
            files[relative] = archive.read(entry)
    required = {'LICENSE', 'README.md', 'plugin.json', 'package.json', 'main.py',
                'dist/index.js', 'py_modules/lsfg_vk/installation.py', pin['runtime']['member']}
    if not required <= files.keys():
        raise ValueError('Incomplete LSFG-VK plugin release')
    plugin, package = (json.loads(files[name]) for name in ('plugin.json', 'package.json'))
    if (plugin.get('name') != pin['name'] or plugin.get('flags') != [] or
            package.get('version') != pin['version'] or package.get('name') != 'decky-lsfg-vk'):
        raise ValueError('Pinned LSFG-VK plugin identity/version/privileges differ')
    runtime = pin['runtime']
    if hashlib.sha256(files[runtime['member']]).hexdigest() != runtime['sha256']:
        raise ValueError('Bundled LSFG-VK runtime differs from its pinned SHA-256')
    remote = package.get('remote_binary', [])
    if (len(remote) != 1 or remote[0].get('sha256hash') != runtime['sha256'] or
            remote[0].get('name') != PurePosixPath(runtime['member']).name):
        raise ValueError('Upstream runtime descriptor differs from the bundled LSFG-VK resource')
    return files


def cache_manifest(pin, files):
    return {'schema': 1, 'id': pin['id'], 'name': pin['name'], 'version': pin['version'],
            'release_url': pin['release_url'], 'archive': pin['archive'], 'runtime': pin['runtime'],
            'deployment': pin['deployment'],
            'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                      for name, data in sorted(files.items())}}


def read_cache(directory=ROOT / 'cache/lsfg-vk', pin=None):
    pin = read_pin() if pin is None else pin
    directory = Path(directory)
    files = read_plugin_archive(directory / pin['archive']['filename'], pin)
    manifest = directory / 'manifest.json'
    if manifest.is_symlink() or json.loads(manifest.read_text(encoding='utf-8')) != cache_manifest(pin, files):
        raise ValueError('Stale LSFG-VK cache manifest; regenerate with prepare-lsfg-vk.py')
    return files


def integration_files(directory=ROOT / 'cache/lsfg-vk'):
    return {'/' + PLUGIN_ROOT + name: data for name, data in sorted(read_cache(directory).items())}


def check_integration(directory=ROOT / 'cache/integration', cache=ROOT / 'cache/lsfg-vk'):
    directory = Path(directory)
    expected = integration_files(cache)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    component = manifest.get('lsfg-vk', {})
    entries = component.get('files', [])
    if (component.get('missing') or component.get('units') or component.get('packages') or
            len(entries) != len(expected) or len({entry['target'] for entry in entries}) != len(expected)):
        raise ValueError('Incomplete LSFG-VK integration component')
    for entry in entries:
        target = '/' + entry['target']
        relative = PurePosixPath(entry['source'])
        if (target not in expected or relative.is_absolute() or '..' in relative.parts or
                relative.parts[0] != 'lsfg-vk' or entry.get('user') is not False or
                entry.get('mode') != 0o644 or (directory / str(relative)).is_symlink() or
                (directory / str(relative)).read_bytes() != expected[target]):
            raise ValueError('LSFG-VK integration bytes, targets or ownership differ from the pinned release')
    return {'component': 'lsfg-vk', 'version': read_pin()['version'], 'files': len(entries),
            'runtime_version': read_pin()['runtime']['version'], 'paid_dll_included': False,
            'user_configuration_changed': False}
