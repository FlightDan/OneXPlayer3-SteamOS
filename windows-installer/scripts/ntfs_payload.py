"""Prepare the fixed partition-mount source payload and record its provenance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile


def adapter(root):
    spec = importlib.util.spec_from_file_location('ntfs_payload_adapter', root / 'components/partition_mount.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(root, store, tools_source):
    root, store, tools_source = Path(root), Path(store), Path(tools_source)
    module = adapter(root)
    source = root / 'components/partition-mount'
    build = root / 'guest/ntfs-tools-build.sh'
    if build.is_symlink() or not build.is_file():
        raise RuntimeError('Missing NTFS tools build source')
    # Validate all fresh build outputs against current sources before replacing
    # generated resources. This never substitutes an old integration cache.
    with tempfile.TemporaryDirectory(prefix='ntfs-stage-', dir=root / 'work') as temporary:
        stage = Path(temporary)
        for name in ('ntfs_status.c', 'ntfs-tools-source.json'):
            shutil.copyfile(source / name, stage / name)
        shutil.copyfile(build, stage / 'ntfs-tools-build.sh')
        (stage / 'tools').mkdir()
        for name in module.RUNTIME_NAMES | {'manifest.json'}:
            path = tools_source / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Missing or unsafe NTFS build output: ' + name)
            shutil.copyfile(path, stage / 'tools' / name)
        verified = module.runtime_files(stage / 'tools')
        destination = source / 'tools'
        if destination.is_symlink():
            raise RuntimeError('Unsafe NTFS generated source directory')
        destination.mkdir(exist_ok=True)
        if set(path.name for path in destination.iterdir()) - set(verified):
            raise RuntimeError('Unexpected old NTFS generated resources')
        for name, data in verified.items():
            target = destination / name
            if target.is_symlink():
                raise RuntimeError('Unsafe NTFS generated resource')
            target.write_bytes(data)
        shutil.copyfile(build, source / 'ntfs-tools-build.sh')
    inventory = {}
    for name in (*module.ASSETS, *('tools/' + name for name in sorted(verified))):
        data = (source / name).read_bytes()
        inventory[name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    output = store / 'partition-mount'
    output.mkdir(parents=True, exist_ok=True)
    data = (json.dumps({'schema': 1, 'files': inventory}, sort_keys=True, indent=2) + '\n').encode()
    (output / 'source-manifest.json').write_bytes(data)
    tools = json.loads(verified['manifest.json'])
    return {'files': [], 'units': [], 'packages': {}, 'missing': [],
            'version': tools['version'], 'source_manifest': 'partition-mount/source-manifest.json',
            'source_manifest_sha256': hashlib.sha256(data).hexdigest(),
            'ntfs_tools': tools}
