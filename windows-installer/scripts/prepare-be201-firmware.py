"""Fetch only the accepted BE201 families from the pinned linux-firmware tree."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import urllib.request

REVISION = '2ab4ce216003ee2c2396c69e19455e4379b0e1f0'
BASE = 'https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/' + REVISION + '/'
FILES = {f'intel/iwlwifi/iwlwifi-sc-a0-fm-c0-c{v}.ucode': f'iwlwifi-sc-a0-fm-c0-c{v}.ucode' for v in (101, 102, 103, 106)}
FILES.update({f'intel/ibt-00a0-0291-{suffix}': f'intel/ibt-00a0-0291-{suffix}' for suffix in ('iml.sfi', 'pci.ddc', 'pci.sfi', 'usb.ddc', 'usb.sfi')})
FILES.update({f'LICENSES/{name}': f'licenses/{name}' for name in ('LICENCE.iwlwifi_firmware', 'LICENCE.ibt_firmware')})


def fetch(path, seen=None):
    seen = set() if seen is None else seen
    if path in seen or PurePosixPath(path).is_absolute() or path.startswith('../'):
        raise RuntimeError('Invalid firmware link')
    seen.add(path)
    parent, name = path.rsplit('/', 1)
    with urllib.request.urlopen(BASE + parent + '/?format=JSON', timeout=60) as response:
        entries = json.loads(response.read()[4:])['entries']
    entry = next(x for x in entries if x['name'] == name)
    with urllib.request.urlopen(BASE + path + '?format=TEXT', timeout=60) as response:
        data = base64.b64decode(response.read(), validate=True)
    if entry['mode'] == 0o120000:
        return fetch(posixpath.normpath(parent + '/' + data.decode().strip()), seen)
    if entry['mode'] != 0o100644 or not data:
        raise RuntimeError('Expected ordinary firmware/license blob')
    return data


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / 'cache/be201-firmware'
    records = []
    for source, target in FILES.items():
        data = fetch(source)
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        records.append({'source': source, 'target': target, 'url': BASE + source,
                        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        print(target, len(data), flush=True)
    (destination / 'provenance.json').write_text(json.dumps({'revision': REVISION, 'files': records}, indent=2) + '\n')
