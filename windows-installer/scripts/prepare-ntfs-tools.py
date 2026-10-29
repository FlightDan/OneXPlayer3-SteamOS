"""Build pinned static NTFS tools in a disposable offline Alpine/QEMU guest.

The source lock records every downloaded byte. No target device is attached.
Each invocation rebuilds; --check verifies an existing build against all inputs.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'components/partition-mount/ntfs-tools-source.json'
CACHE = ROOT / 'cache/ntfs-tools'
TOOLS = CACHE / 'tools'
INPUTS = {'ntfs_status.c': ROOT / 'components/partition-mount/ntfs_status.c',
          'ntfs-tools-build.sh': ROOT / 'guest/ntfs-tools-build.sh',
          'prepare-ntfs-tools.py': Path(__file__).resolve(),
          'ntfs-tools-source.json': SOURCE}
FILES = ('ntfs_status', 'ntfsfix', 'COPYING', 'source.tar.gz')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(path):
    return {'sha256': digest(path), 'size': path.stat().st_size}


def verify(path, item):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing ordinary pinned input: ' + str(path))
    if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
        raise ValueError('Pinned input mismatch: ' + str(path))


def fetch(path, item, offline):
    if path.exists():
        verify(path, item)
        return
    if offline:
        raise ValueError('Offline input missing: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in [item['url'], *item.get('mirrors', [])]:
        if not url.startswith('https://'):
            raise ValueError('HTTPS required')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'OXP3-NTFS-Tools/1'})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read(item['bytes'] + 1)
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Downloaded pinned input mismatch')
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
            return
        except (OSError, ValueError) as error:
            errors.append(str(error))
    raise RuntimeError('Cannot retrieve pinned input ' + path.name + ': ' + '; '.join(errors))


def static_elf(path):
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 62:
        raise ValueError('Expected x86_64 ELF: ' + str(path))
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if size < 56 or count < 1 or offset + size * count > len(data):
        raise ValueError('Malformed ELF program headers')
    if any(struct.unpack_from('<I', data, offset + size * n)[0] in (2, 3) for n in range(count)):
        raise ValueError('Dynamic ELF refused: ' + str(path))


def inputs():
    return {name: digest(path) for name, path in INPUTS.items()}


def check(spec):
    manifest = json.loads((TOOLS / 'manifest.json').read_text())
    if (manifest.get('schema') != 1 or manifest.get('version') != spec['version'] or
            manifest.get('architecture') != 'x86_64' or manifest.get('static') is not True or
            manifest.get('inputs') != inputs() or set(manifest.get('files', {})) != set(FILES)):
        raise ValueError('Stale or invalid NTFS tool manifest; rebuild required')
    for name in FILES:
        if (TOOLS / name).is_symlink() or record(TOOLS / name) != manifest['files'][name]:
            raise ValueError('NTFS tool hash mismatch: ' + name)
    for name in ('ntfs_status', 'ntfsfix'):
        static_elf(TOOLS / name)
    if digest(TOOLS / 'source.tar.gz') != spec['upstream']['sha256']:
        raise ValueError('Corresponding source mismatch')
    return manifest


def build(spec, offline):
    CACHE.mkdir(parents=True, exist_ok=True)
    source = CACHE / spec['upstream']['file']
    fetch(source, spec['upstream'], offline)
    for item in spec['alpine']['packages']:
        fetch(CACHE / item['file'], item, offline)
    iso = ROOT / 'cache' / spec['alpine']['iso']['file']
    verify(iso, spec['alpine']['iso'])
    input_hashes = inputs()
    work = ROOT / 'work' / ('ntfs-tools-build-' + uuid.uuid4().hex)
    payload = work / 'payload'
    (payload / 'apks').mkdir(parents=True)
    for item in spec['alpine']['packages']:
        shutil.copyfile(CACHE / item['file'], payload / 'apks' / Path(item['file']).name)
    shutil.copyfile(source, payload / 'source.tar.gz')
    shutil.copyfile(INPUTS['ntfs_status.c'], payload / 'ntfs_status.c')
    shutil.copyfile(INPUTS['ntfs-tools-build.sh'], payload / 'build.sh')
    qemu = ROOT / 'runtime/qemu-min/qemu-system-x86_64.exe'
    boot = ROOT / 'runtime/alpine/boot'
    def option(path):
        return str(path).replace('\\', '/').replace(',', ',,')
    args = [str(qemu), '-accel', 'tcg', '-m', '2048', '-smp', '2',
            '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-no-reboot', '-nic', 'none',
            '-kernel', str(boot / 'vmlinuz-virt'), '-initrd', str(boot / 'initramfs-virt'),
            '-append', 'console=ttyS0,115200 modules=loop,squashfs,sd-mod,virtio_pci,virtio_blk,vfat alpine_dev=cdrom:iso9660',
            '-drive', 'file=' + option(iso) + ',format=raw,media=cdrom,readonly=on',
            '-drive', 'file=fat:ro:' + option(payload) + ',format=raw,if=virtio,readonly=on']
    print('Building static NTFS tools in offline Alpine; log: ' + str(work / 'serial.log'), flush=True)
    child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    chunks = queue.Queue()
    def read():
        while True:
            data = os.read(child.stdout.fileno(), 65536)
            if not data:
                break
            chunks.put(data)
        chunks.put(None)
    threading.Thread(target=read, daemon=True).start()
    transcript = bytearray()
    phase = 'login'
    deadline = time.monotonic() + 1800
    try:
        with (work / 'serial.log').open('wb') as log:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('NTFS build exceeded 30 minutes')
                try:
                    chunk = chunks.get(timeout=1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                transcript.extend(chunk)
                log.write(chunk)
                log.flush()
                terminal = re.sub(rb'\x1b\[[0-9;?]*[A-Za-z]', b'', bytes(transcript[-8192:]))
                if phase == 'login' and re.search(rb'login:\s*$', terminal):
                    phase = 'shell'
                    child.stdin.write(b'root\n')
                    child.stdin.flush()
                elif phase == 'shell' and re.search(rb'~\s*#\s*$', terminal):
                    phase = 'build'
                    command = b'( mkdir -p /mnt/payload && mount -t vfat -o ro /dev/vda1 /mnt/payload && sh /mnt/payload/build.sh ); poweroff\n'
                    for start in range(0, len(command), 8):
                        child.stdin.write(command[start:start + 8])
                        child.stdin.flush()
                        time.sleep(0.025)
        code = child.wait(timeout=30)
        text = transcript.decode('utf-8', errors='replace').replace('\r', '')
        if code != 0 or not re.search(r'^OXP_TASK_RESULT=passed$', text, re.M):
            raise RuntimeError('NTFS build failed; inspect ' + str(work / 'serial.log') + '\n' + text[-3500:])
        output = work / 'tools'
        output.mkdir()
        for name in ('ntfs_status', 'ntfsfix'):
            matches = re.findall(r'^NTFS_TOOLS_FILE_BEGIN=' + name + r'\n([A-Za-z0-9+/=\n]+)\nNTFS_TOOLS_FILE_END=' + name + r'$', text, re.M)
            if len(matches) != 1:
                raise ValueError('Missing binary transfer: ' + name)
            (output / name).write_bytes(base64.b64decode(matches[0].replace('\n', ''), validate=True))
            static_elf(output / name)
        with tarfile.open(source) as archive:
            (output / 'COPYING').write_bytes(archive.extractfile('ntfs-3g-' + spec['upstream']['version'] + '/COPYING').read())
        shutil.copyfile(source, output / 'source.tar.gz')
        tests = re.findall(r'^NTFS_TOOLS_TEST=(.+)$', text, re.M)
        if inputs() != input_hashes:
            raise ValueError('Build inputs changed during compilation; rebuild required')
        manifest = {'schema': 1, 'version': spec['version'], 'architecture': 'x86_64', 'static': True,
                    'source': {'url': spec['upstream']['url'], 'sha256': spec['upstream']['sha256']},
                    'build_inputs': {name: input_hashes[name] for name in ('ntfs_status.c', 'ntfs-tools-build.sh')},
                    'inputs': input_hashes, 'files': {name: record(output / name) for name in FILES},
                    'validation': {'network': 'disabled', 'fixtures': tests},
                    'build': {'alpine': spec['alpine']['version'], 'network': 'disabled',
                              'compiler': 'Alpine gcc 15.2.0-r2; musl 1.2.5-r24'}}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        TOOLS.mkdir(exist_ok=True)
        for name in (*FILES, 'manifest.json'):
            shutil.copyfile(output / name, TOOLS / name)
        check(spec)
        print(json.dumps({'tools': str(TOOLS), 'version': spec['version'], 'validation': tests}, indent=2))
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Require all hash-pinned inputs in cache')
    parser.add_argument('--check', action='store_true', help='Verify current tools and exact source/build inputs')
    options = parser.parse_args()
    specification = json.loads(SOURCE.read_text(encoding='utf-8'))
    if options.check:
        check(specification)
        print('NTFS tool payload and build inputs verified')
    else:
        build(specification, options.offline)
