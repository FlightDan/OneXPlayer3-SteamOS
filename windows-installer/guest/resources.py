"""Stage selected public resources with atomic profile publication; never execute them."""
import json
import os
from pathlib import Path
import uuid


def directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RuntimeError('Unexpected resource directory')
    path.mkdir(exist_ok=True, parents=True)


def publish(path, data, immutable=False):
    if path.is_symlink() or (path.exists() and not path.is_file()): raise RuntimeError('Unexpected resource file')
    if path.exists():
        if path.read_bytes() == data: return
        if immutable: raise RuntimeError('An existing resource revision differs; choose a new revision')
    temporary = path.parent / ('.oxp3-resource-' + uuid.uuid4().hex)
    with temporary.open('xb') as output:
        output.write(data); output.flush(); os.fchmod(output.fileno(), 0o644); os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def stage_resources(selection, payload, home):
    resources = selection.get('resources', [])
    if not isinstance(resources, list) or any(item not in ('waydroid', 'oxp3-controls', 'hdr') for item in resources) or len(resources) != len(set(resources)):
        raise RuntimeError('Unsupported resource selection')
    # Validate and read every selected payload before changing the destination.
    prepared = []
    for resource in resources:
        source = payload / resource
        raw_profile = (source / 'profile.json').read_bytes()
        profile = json.loads(raw_profile)
        if resource == 'waydroid':
            if profile['bundle_version'] != 'steamos-3.10-b20260924.1000-wlroots0.20.2-oxp3-r2':
                raise RuntimeError('Unsupported Waydroid bundle')
            names = (profile['archive'], profile['source_archive'], 'intel-ibt-kernel-calls.patch')
        elif resource == 'hdr':
            if profile['version'] != '20261013-hdr-r3' or profile['deployment'] != 'configuration_files_only' or profile['default'] is not False:
                raise RuntimeError('Unsupported HDR configuration resource')
            names = (profile['archive'],)
        else:
            if profile['version'] not in ('20261013', '20261013-r2') or profile['deployment'] != 'resources_only' or profile['default'] is not False:
                raise RuntimeError('Unsupported control source bundle')
            names = (profile['archive'],)
        contents = []
        for name in names:
            if not isinstance(name, str) or Path(name).name != name or name in ('.', '..', 'profile.json'):
                raise RuntimeError('Unsafe resource filename')
            contents.append((name, (source / name).read_bytes()))
        prepared.append((resource, raw_profile, contents))
    for resource, raw_profile, contents in prepared:
        root = home / 'oxp3-resources'; directory(root)
        destination = root / resource; directory(destination)
        for name, data in contents: publish(destination / name, data, immutable=True)
        # The previous profile remains usable until all new files are durable.
        current = destination / 'profile.json'
        if current.exists():
            old = current.read_bytes()
            if old != raw_profile:
                publish(destination / ('profile-before-' + uuid.uuid4().hex + '.json'), old, immutable=True)
        publish(current, raw_profile)
