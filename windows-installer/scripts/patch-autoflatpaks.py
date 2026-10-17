"""Build the minimal startup compatibility patch from pinned AutoFlatpaks 1.6.8."""
import argparse
import difflib
import json
from pathlib import Path
import zipfile

BASE_VERSION = '1.6.8'
VERSION = '1.6.8+oxp3.1'
ARCHIVE = 'autoflatpaks-' + VERSION + '.zip'
PREFIX = 'decky-autoflatpaks/'
MARKER = 'OXP3 AutoFlatpaks compatibility: Steam may expose the store late.'
ORIGINAL = '''          this.intervalID = setInterval(() => {
              // @ts-ignore
              let currentState = window.SystemPowerStore.batteryState;
              if (currentState != this.pseudoBatteryState)
                  this.setBatteryStateChange(currentState);
          }, 1000);'''
PATCH_DIRECTORY = Path(__file__).resolve().parent.parent / 'components' / 'autoflatpaks-compat'


def patch_text(text, patch_directory=PATCH_DIRECTORY):
    if text.count(ORIGINAL) != 1:
        raise RuntimeError('Unexpected AutoFlatpaks battery polling block')
    replacement = (patch_directory / 'poll-battery-state.js').read_text(encoding='utf-8').rstrip('\n')
    if MARKER not in replacement:
        raise RuntimeError('Missing AutoFlatpaks compatibility marker')
    return text.replace(ORIGINAL, replacement)


def build(source, destination, patch_directory=PATCH_DIRECTORY):
    source, destination, patch_directory = Path(source), Path(destination), Path(patch_directory)
    if source.resolve() == destination.resolve():
        raise RuntimeError('The patched archive must not replace the upstream archive')
    with zipfile.ZipFile(source) as upstream:
        entries = upstream.infolist()
        data = {item.filename: upstream.read(item) for item in entries}
        metadata = json.loads(data[PREFIX + 'package.json'])
        if metadata.get('version') != BASE_VERSION or metadata.get('name') != 'decky-autoflatpaks':
            raise RuntimeError('Unexpected upstream AutoFlatpaks version')
        original = data[PREFIX + 'dist/index.js'].decode('utf-8')
        changed = patch_text(original, patch_directory)
        metadata['version'] = VERSION
        metadata['oxp3_compatibility_patch'] = 'Defer battery polling until Steam power state is available'
        data[PREFIX + 'package.json'] = (json.dumps(metadata, indent=2) + '\n').encode()
        data[PREFIX + 'dist/index.js'] = changed.encode()
        diff = ''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
                                          fromfile='a/dist/index.js', tofile='b/dist/index.js'))
        additions = {
            PREFIX + 'oxp3-compat/dist-index.js.patch': diff.encode(),
            PREFIX + 'oxp3-compat/poll-battery-state.js': (patch_directory / 'poll-battery-state.js').read_bytes(),
            PREFIX + 'oxp3-compat/README.txt': (patch_directory / 'README.txt').read_bytes(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for item in entries:
                output.writestr(item, data[item.filename])
            # Fixed metadata makes repeated builds byte-for-byte reproducible.
            for name, content in additions.items():
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o100644 << 16
                output.writestr(item, content)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--patch-directory', type=Path, default=PATCH_DIRECTORY)
    arguments = parser.parse_args()
    print(build(arguments.source, arguments.destination, arguments.patch_directory))
