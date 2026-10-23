"""A complete pinned Decky cache for isolated maintenance generator tests."""
import hashlib
import json
from pathlib import Path


def decky_fixture(installer, binary=b'\x7fELFfixture'):
    installer = Path(installer)
    files = {'PluginLoader': binary, 'VERSION': b'3.3.0\n', 'source-v3.3.0.zip': b'source fixture',
             'LICENSE': b'GPL-2.0 fixture', 'plugin_loader-release.service': b'upstream service fixture'}
    records = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
               for name, data in files.items()}
    manifest = {'schema': 1, 'version': '3.3.0', 'source_commit': 'a' * 40, 'files': records}
    pin = {'schema': 1, 'version': '3.3.0', 'source_commit': 'a' * 40,
           'binary': records['PluginLoader'], 'source': records['source-v3.3.0.zip']}
    files['manifest.json'] = json.dumps(manifest).encode()
    for name, data in files.items():
        path = installer / 'cache/plugins/decky' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    path = installer / 'components/decky-release.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pin), encoding='utf-8')
    return files
