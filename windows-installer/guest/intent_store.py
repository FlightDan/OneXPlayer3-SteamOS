"""Durable root-owned intent file on a separately mounted staging filesystem."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid


class IntentStore:
    def __init__(self, root):
        self.root = Path(root)
        for path in (self.root, *self.root.parents):
            if path.is_symlink(): raise RuntimeError('Intent path cannot be redirected')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Intent directory must be root-owned and not user-writable')
        self.path = self.root / 'installation-intent.json'

    @staticmethod
    def check_file(info):
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Intent file must be root-owned and not user-writable')

    @contextmanager
    def locked(self):
        descriptor = os.open(self.root / '.controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self.check_file(os.fstat(descriptor))
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('Another controller owns this installation intent') from None
            yield self
        finally: os.close(descriptor)

    def load(self):
        try: descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError: return None
        with os.fdopen(descriptor, 'rb') as file:
            self.check_file(os.fstat(file.fileno()))
            content = file.read(4 * 1024**2 + 1)
            if len(content) > 4 * 1024**2: raise RuntimeError('Installation intent is too large')
        value = json.loads(content)
        if not isinstance(value, dict): raise RuntimeError('Invalid installation intent')
        return value

    def require_durable_mount(self, target):
        matches = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            left, right = line.split(' - ', 1); fields = left.split(); extra = right.split()
            mount = Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4]))
            try: self.root.relative_to(mount)
            except ValueError: continue
            matches.append((len(mount.parts), fields, extra))
        if not matches: raise RuntimeError('Intent staging mount is unavailable')
        _, fields, extra = max(matches, key=lambda item: item[0])
        if extra[0] not in ('ext4', 'btrfs') or 'rw' not in fields[5].split(','):
            raise RuntimeError('Intent must be on a writable persistent Linux filesystem')
        staging = Path('/sys/dev/block', fields[2]).resolve(strict=True)
        disk = Path('/sys/class/block', Path(target).name).resolve(strict=True)
        if staging == disk or disk in staging.parents:
            raise RuntimeError('Pre-append intent must be stored outside the target disk')
        if self.root.stat().st_dev != os.makedev(*(int(p) for p in fields[2].split(':'))):
            raise RuntimeError('Intent directory mount identity changed')

    def save(self, value, create=False):
        prior = self.load()
        if create and prior is not None: raise RuntimeError('An installation intent already exists')
        if not create and (prior is None or prior.get('id') != value.get('id')):
            raise RuntimeError('Installation intent identity changed')
        temporary = self.root / ('.intent-' + uuid.uuid4().hex)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as file:
                json.dump(value, file, indent=2); file.flush(); os.fsync(file.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if temporary.exists(): temporary.unlink()
