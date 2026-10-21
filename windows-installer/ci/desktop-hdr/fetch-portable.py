#!/usr/bin/env python3
"""Download exact official build packages into this task's local workspace."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
cache = Path(sys.argv[2]).resolve()
cache.mkdir(parents=True, exist_ok=True)

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()

def fetch(package):
    filename = package['localFilename']
    if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename or ':' in filename:
        raise ValueError('Unsafe local package filename')
    if not package['url'].startswith('https://steamdeck-packages.steamos.cloud/archlinux-mirror/'):
        raise ValueError('Non-official package source refused')
    target = cache / filename
    if target.is_file() and digest(target) == package['sha256']:
        return package['name']
    partial = target.with_suffix(target.suffix + '.partial')
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(package['url'], timeout=120) as source, partial.open('wb') as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
            if digest(partial) != package['sha256']:
                raise ValueError('Package SHA-256 mismatch: ' + package['name'])
            partial.replace(target)
            return package['name']
        except Exception as error:
            last_error = error
    raise RuntimeError('Download failed: ' + package['name']) from last_error

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    for index, name in enumerate(executor.map(fetch, manifest['packages']), start=1):
        if index % 20 == 0 or index == len(manifest['packages']):
            print(f'Verified {index}/{len(manifest["packages"])} packages; latest {name}', flush=True)
source = Path(sys.argv[1]).parent / manifest['sourceInputs']
if digest(source) != manifest['sourceInputsSHA256']:
    raise ValueError('Source input archive SHA-256 mismatch')
print('All packages and source input archive verified.', flush=True)
