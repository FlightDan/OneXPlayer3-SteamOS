"""Refresh the maintained overlay files in an existing installer payload."""
import argparse
import json
import posixpath
from pathlib import Path, PurePosixPath
import stat

RUNTIME = {
    'var/lib/oxp3-overlay-telemetry/telemetry.py': 'telemetry.py',
    'var/lib/oxp3-overlay-telemetry/allow-read.py': 'allow-read.py',
}
SOURCE_NAMES = ('telemetry.py', 'allow-read.py', 'test_telemetry_fan.py', 'test_telemetry_gpu.py')
EXPECTED_SOURCES = dict(zip(RUNTIME, ('overlay/000.bin', 'overlay/001.bin')))

def refresh(source, store):
    source, store = Path(source).resolve(), Path(store).resolve()
    manifest = json.loads((store/'manifest.json').read_text(encoding='utf-8'))
    changes = {}
    for target, name in RUNTIME.items():
        entries = [e for e in manifest['overlay']['files'] if e['target'] == target]
        if len(entries) != 1:
            raise ValueError('Expected exactly one overlay target: ' + target)
        entry = entries[0]
        if entry['source'] != EXPECTED_SOURCES[target]:
            raise ValueError('Unexpected overlay runtime source mapping')
        references = [e for component in manifest.values() for e in component.get('files', [])
                      if posixpath.normpath(e.get('source', '').replace('\\', '/')) == entry['source']]
        if len(references) != 1:
            raise ValueError('Shared overlay payload source refused')
        path = PurePosixPath(entry['source'])
        if path.is_absolute() or '..' in path.parts or '\\' in str(path) or ':' in str(path):
            raise ValueError('Invalid overlay payload path')
        destination = store.joinpath(*path.parts)
        if (entry.get('user') is not False or entry.get('mode') != 0o644
                or not destination.resolve().is_relative_to(store)):
            raise ValueError('Unexpected overlay file policy')
        for p in (destination, *destination.parents):
            if p.is_symlink() or bool(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('Linked overlay payload refused')
            if p == store:
                break
        if not stat.S_ISREG(destination.stat().st_mode) or destination.stat().st_nlink != 1:
            raise ValueError('Overlay runtime payload must already exist')
        changes[destination] = (source/name).read_bytes()
    sources = store/'sources'/'overlay'
    for p in (store/'sources', sources):
        if p.exists() and (p.is_symlink() or bool(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)):
            raise ValueError('Linked source directory refused')
    for name in SOURCE_NAMES:
        destination = sources/name
        if (destination.is_symlink() or (destination.exists() and
                (not destination.is_file() or destination.stat().st_nlink != 1
                 or bool(getattr(destination.lstat(), 'st_file_attributes', 0) & 0x400)))):
            raise ValueError('Linked overlay source refused')
        changes[destination] = (source/name).read_bytes()
    for destination, data in changes.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return [p.relative_to(store).as_posix() for p in changes]

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root/'components/controls/overlay')
    parser.add_argument('--store', type=Path, default=root/'cache/integration')
    args = parser.parse_args()
    print(json.dumps({'updated': refresh(args.source, args.store)}, indent=2))
