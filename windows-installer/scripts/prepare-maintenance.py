"""Stage only the GTK maintenance application, without component payloads or keys generated here."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import stat


def public_key(data):
    import re
    match = re.fullmatch(rb'\s*-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*', data)
    der = base64.b64decode(re.sub(rb'\s', b'', match[1]), validate=True) if match else b''
    if len(der) != 44 or not der.startswith(bytes.fromhex('302a300506032b6570032100')):
        raise ValueError('Provision a real Ed25519 publisher public key, not a placeholder')


def inputs(source):
    source = Path(source)
    names = ['entry.py', 'OXP3-Maintenance.desktop']
    names += ['oxp3_maintenance/' + path.name for path in sorted((source / 'oxp3_maintenance').glob('*.py'))]
    if (source / 'trusted-public-key.pem').exists() or (source / 'trusted-public-key.pem').is_symlink():
        names.append('trusted-public-key.pem')
    result = {}
    for name in names:
        path = source / name
        for ancestor in (path, *path.parents):
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked maintenance source refused')
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('Expected a regular maintenance source file: ' + name)
        data = path.read_bytes()
        if b'PRIVATE KEY-----' in data:
            raise ValueError('Private key material in maintenance source')
        if name == 'trusted-public-key.pem':
            public_key(data)
        result[name] = data
    if 'oxp3_maintenance/touch_ui.py' not in result or 'oxp3_maintenance/operations.py' not in result:
        raise ValueError('Maintenance GTK runtime is incomplete')
    return result


def prepare(source, output, *, check=False, require_key=False):
    source, output = Path(source), Path(output)
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError('Maintenance staging must be outside its source tree')
    content = inputs(source)
    if require_key and 'trusted-public-key.pem' not in content:
        raise ValueError('Public releases require steamos-maintenance/trusted-public-key.pem from the publisher')
    report = {'schema': 1, 'publisher_key': 'trusted-public-key.pem' in content,
              'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(content.items())}}
    if check:
        if json.loads((output / 'manifest.json').read_text(encoding='utf-8')) != report:
            raise ValueError('Stale maintenance staging; run prepare-maintenance.py again')
        if {p.relative_to(output / 'app').as_posix() for p in (output / 'app').rglob('*') if p.is_file()} != set(content):
            raise ValueError('Unexpected maintenance staging files')
        for name, data in content.items():
            path = output / 'app' / name
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError('Stale maintenance runtime: ' + name)
    else:
        # Refuse old/extraneous resources rather than deleting an existing tree.
        if output.exists():
            raise ValueError('Output must be a fresh directory; keep prior staging for review')
        for name, data in content.items():
            path = output / 'app' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (output / 'manifest.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root.parent / 'steamos-maintenance')
    parser.add_argument('--output', type=Path, default=root / 'cache/maintenance')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--require-key', action='store_true')
    args = parser.parse_args()
    report = prepare(args.source, args.output, check=args.check, require_key=args.require_key)
    print(json.dumps({'files': len(report['files']), 'bytes': sum(len(v) for v in inputs(args.source).values()),
                      'publisher_key': report['publisher_key']}))
