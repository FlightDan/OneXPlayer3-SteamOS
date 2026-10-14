"""Extract a minimal DRM console from pinned Debian packages, without installation."""
import io
import json
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
cache = root / 'cache/console'
target = root / 'runtime/console'
target.mkdir(parents=True, exist_ok=True)

def contents(filename):
    data = (cache / filename).read_bytes()
    if data[:8] != b'!<arch>\n': raise ValueError('Not a Debian ar archive')
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if header[58:60] != b'`\n': raise ValueError('Invalid ar entry')
        size = int(header[48:58]); name = header[:16].decode().strip().rstrip('/')
        entry = data[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
        if name.startswith('data.tar'):
            return tarfile.open(fileobj=io.BytesIO(entry))
    raise ValueError('Missing Debian data archive')

selected = {
    'kmscon_9.0.0-4_amd64.deb': {
        './usr/libexec/kmscon/kmscon': 'kmscon',
        './usr/lib/x86_64-linux-gnu/kmscon/mod-bbulk.so': 'modules/mod-bbulk.so',
        './usr/share/doc/kmscon/copyright': 'licenses/kmscon-copyright',
    },
    'libtsm4_4.0.2-0.4_amd64.deb': {
        './usr/lib/x86_64-linux-gnu/libtsm.so.4.0.2': 'libtsm.so.4',
        './usr/share/doc/libtsm4/copyright': 'licenses/libtsm-copyright',
    },
}
files = []
for package, entries in selected.items():
    with contents(package) as archive:
        for member, name in entries.items():
            info = archive.getmember(member)
            if not info.isfile(): raise ValueError('Expected regular package file')
            file = target / name; file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(archive.extractfile(info).read())
            files.append({'path': name, 'bytes': file.stat().st_size, 'package': package})
# Carry matching upstream and Debian source archives alongside the small binaries.
for name in ('kmscon_9.0.0.orig.tar.xz', 'kmscon_9.0.0-4.debian.tar.xz',
             'libtsm_4.0.2.orig.tar.gz', 'libtsm_4.0.2-0.4.debian.tar.xz'):
    file = target / 'sources' / name; file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes((cache / name).read_bytes())
    files.append({'path': 'sources/' + name, 'bytes': file.stat().st_size})
metadata = {'schema': 1, 'purpose': 'read-only preview on DRM without fbdev',
            'source': 'https://deb.debian.org/debian/pool/main/', 'files': files,
            'module_directory': '/usr/lib/x86_64-linux-gnu/kmscon',
            'system_package_installation': False,
            'validation': 'See IMPLEMENTATION_STATUS.md: exact target dependency probe and visible UEFI boot; hardware display pending'}
(target / 'inventory.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'files': len(files), 'bytes': sum(f['bytes'] for f in files)}, indent=2))
