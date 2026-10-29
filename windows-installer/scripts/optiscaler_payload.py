"""Prepare original OptiScaler archives for the existing Opti2XMX cache.

Every archive declared by the release pins is required. Real original inputs
are checked for size and SHA-256 before copying and checked again afterwards;
the manifest records those verified pins. Nothing is downloaded, extracted or
executed, and no game configuration or privately imported FSR package is included.
"""
import json
from pathlib import Path
import shutil
import tempfile

from opti_payload import _hash, _regular

PINS = json.loads((Path(__file__).resolve().parents[1] /
                   'components/optiscaler-release.json').read_text(encoding='utf-8'))
CACHE_TARGET = '/home/deck/.local/share/opti2xmx/downloads/'


def validate_archive(path, pin):
    path = _regular(path)
    if path.stat().st_size != pin['size_bytes'] or _hash(path) != pin['sha256']:
        raise ValueError('OptiScaler archive differs from the pinned release: ' + pin['version'])
    return path


def prepare(archives, output):
    inputs = {Path(path).name: Path(path) for path in archives}
    if len(inputs) != len(archives) or set(inputs) != {pin['filename'] for pin in PINS['archives']}:
        raise ValueError('Provide exactly the pinned OptiScaler archives')
    for pin in PINS['archives']:
        validate_archive(inputs[pin['filename']], pin)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Use a fresh OptiScaler output directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(PINS, contains_game_state=False)
    with tempfile.TemporaryDirectory(prefix='.optiscaler-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'cache'
        for pin in PINS['archives']:
            target = stage / pin['tag'] / pin['filename']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inputs[pin['filename']], target)
            validate_archive(target, pin)
        (stage / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        stage.rename(output)
    return report


def read_cache(directory):
    directory = Path(directory)
    report = json.loads(_regular(directory / 'manifest.json').read_text(encoding='utf-8'))
    if report != dict(PINS, contains_game_state=False):
        raise ValueError('OptiScaler cache provenance differs from the pinned releases')
    files = {}
    for pin in PINS['archives']:
        relative = pin['tag'] + '/' + pin['filename']
        path = validate_archive(directory / relative, pin)
        files[CACHE_TARGET + relative] = path.read_bytes()
    return files
