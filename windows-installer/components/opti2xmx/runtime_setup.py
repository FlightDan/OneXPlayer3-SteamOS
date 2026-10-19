"""Explicit, user-owned runtime provisioning from a hash pinned plugin asset.

No remote manifest, root commands, system driver replacement, or OptiScaler files.
The bundled source descriptor is the trust root and is updated with the plugin.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import ssl
import stat
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid

MAX_ARCHIVE = 200 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_MEMBERS = 512
UNPUBLISHED = '固定版本的 XMX 运行环境尚未发布。发布后请更新插件。'
REQUIRED = ('runtime/igdext64.dll', 'runtime/lib/libvulkan_intel.so',
            'runtime/tools/cm-compile.sh', 'runtime/tools/cmk_pack.py',
            'sdk/libxess.dll', 'runtime/LICENSE', 'runtime/THIRD_PARTY.md', 'sdk/XeSS-LICENSE.txt')


def download_ssl_context():
    """Use the OS trust bundle when Decky's frozen OpenSSL paths are absent."""
    if platform.system() == 'Linux':
        for name in ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt',
                     '/etc/pki/tls/certs/ca-bundle.crt'):
            if Path(name).is_file():
                # Explicit cafile avoids PyInstaller's build-host default paths.
                # Keep hostname and certificate verification; invalid CA files fail.
                return ssl.create_default_context(cafile=name)
    return ssl.create_default_context()


def source_descriptor():
    data = json.loads(Path(__file__).with_name('runtime-source.json').read_text(encoding='utf-8'))
    if (data.get('schema') != 1 or not re.fullmatch(r'[a-zA-Z0-9._-]{1,40}', data.get('version', ''))
            or type(data.get('size_bytes')) is not int or not 0 < data['size_bytes'] <= MAX_ARCHIVE
            or not re.fullmatch(r'[a-f0-9]{64}', data.get('sha256', ''))
            or type(data.get('published')) is not bool):
        raise RuntimeError('Invalid bundled XMX runtime descriptor')
    if data['published']:
        parsed = urllib.parse.urlparse(data.get('url') or '')
        if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
                or not re.fullmatch(r'/FlightDan/Opti2XMX/releases/download/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.tar\.gz', parsed.path)
                or parsed.query or parsed.fragment):
            raise RuntimeError('XMX runtime source must be an immutable FlightDan/Opti2XMX release asset')
    return data


def host_issue():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        return 'XMX runtime requires x86_64 Linux (SteamOS).'
    for command in ('bash', 'python3', 'ldd', 'vulkaninfo'):
        if not shutil.which(command):
            return 'Missing host dependency: ' + command + '. Install it using your OS tools, then retry.'
    vendors = []
    for path in Path('/sys/class/drm').glob('card*/device/vendor'):
        try:
            vendors.append(path.read_text().strip().lower())
        except OSError:
            pass
    if '0x8086' not in vendors:
        return 'No Intel GPU detected. XMX requires a supported Intel GPU and its kernel driver.'
    return ''


def validate_layout(root, pe_version):
    for name in REQUIRED:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('XMX runtime is incomplete: ' + name)
    for pattern in ('runtime/igc/neo/bin/ocloc*', 'runtime/igc/igc/local/lib/libigc.so*',
                    'runtime/igc/igc/local/lib/libigdfcl.so*'):
        if not any(p.is_file() and not p.is_symlink() for p in root.glob(pattern)):
            raise RuntimeError('XMX compiler bundle is incomplete: ' + pattern)
    if (pe_version(root / 'sdk/libxess.dll') or ()) < (2, 0, 2, 68):
        raise RuntimeError('XMX requires libxess.dll 2.0.2.68 or newer')


def unpack(archive, destination):
    """Extract regular files manually; never invoke tarfile.extract or follow links."""
    seen, expanded = set(), 0
    with tarfile.open(archive, 'r:gz') as tar:
        for count, member in enumerate(tar, 1):
            path = PurePosixPath(member.name)
            if (count > MAX_MEMBERS or not member.name or '\\' in member.name
                    or not path.parts or path.is_absolute() or '..' in path.parts or ':' in member.name
                    or path.parts[0] not in ('runtime', 'sdk')
                    or not (member.isdir() or member.isreg()) or member.name in seen):
                raise RuntimeError('Unsafe XMX runtime archive member')
            seen.add(member.name)
            expanded += member.size
            if member.size < 0 or expanded > MAX_EXPANDED:
                raise RuntimeError('XMX runtime archive exceeds extraction limits')
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            # Do not retain setuid, setgid or writable executable permissions.
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


@contextlib.contextmanager
def runtime_lock(path):
    import fcntl
    # O_NOFOLLOW also closes the final-component link race on our lock file.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if (os.fstat(fd).st_uid != os.getuid() or not stat.S_ISREG(os.fstat(fd).st_mode)
                or os.fstat(fd).st_mode & 0o022):
            raise RuntimeError('Invalid runtime install lock owner')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('An XMX runtime installation is already running')
        yield
    finally:
        os.close(fd)


class RuntimeMixin:
    def _runtime_private_directories(self, path):
        # A writable parent could allow another UID to swap staging after hash
        # verification, before the validated driver is loaded in a subprocess.
        for directory in (path, *path.parents):
            if directory.exists():
                self.runtime().owned_directory(directory)
                if directory.stat().st_mode & 0o022:
                    raise RuntimeError('Runtime data directories must not be group or world writable: ' + str(directory))
            if directory == self.home:
                return
        raise RuntimeError('Runtime staging must remain inside the user home')

    def _runtime_config_bytes(self):
        config = self.root / 'runtime.json'
        if config.is_symlink() or (config.exists() and (not config.is_file() or config.stat().st_uid != os.getuid())):
            raise RuntimeError('Runtime configuration must be a regular file owned by the current user')
        return config.read_bytes() if config.exists() else None

    def runtime_status(self):
        descriptor = source_descriptor()
        try:
            _, _, ready = self.dependencies()
            problem = ''
        except (OSError, ValueError, KeyError, TypeError) as error:
            ready, problem = False, 'Invalid runtime configuration: ' + str(error)
        return dict(ready=ready, available=descriptor['published'], version=descriptor['version'],
                    size_bytes=descriptor['size_bytes'], host_issue=host_issue(),
                    error=problem, availability_message='' if descriptor['published'] else
                    UNPUBLISHED)

    def runtime_install(self):
        descriptor = source_descriptor()
        identity = self.progress.begin(None, 'runtime_install', descriptor['version'])
        try:
            if not descriptor['published']:
                raise RuntimeError(UNPUBLISHED)
            issue = host_issue()
            if issue:
                raise RuntimeError(issue)
            rt = self.runtime()
            rt.ordinary_user()
            rt.no_symlink_parents(self.root / 'runtime.json')
            if (self.root / 'runtime.json').is_symlink():
                raise RuntimeError('Runtime configuration cannot be a symlink')
            self._runtime_private_directories(self.home)
            # Create each missing data parent privately even with a permissive
            # user umask, checking existing parents before descending into them.
            directory = self.home
            for part in self.root.relative_to(self.home).parts:
                directory /= part
                directory.mkdir(mode=0o700, exist_ok=True)
                self._runtime_private_directories(directory)
            self._runtime_private_directories(self.root)
            with runtime_lock(self.root / '.runtime-install.lock'):
                return self._runtime_install(descriptor, identity, self._runtime_config_bytes())
        except Exception as error:
            self.progress.finish(identity, error=error)
            raise

    def _runtime_install(self, descriptor, identity, previous_config):
        rt = self.runtime()
        parent = self.root / 'runtimes'
        rt.no_symlink_parents(parent / 'placeholder')
        parent.mkdir(mode=0o700, exist_ok=True)
        self._runtime_private_directories(parent)
        destination = parent / (descriptor['version'] + '-' + descriptor['sha256'][:16] + '-' + uuid.uuid4().hex)
        # No replacement of an existing runtime: launchers may still reference it.
        if destination.exists() or destination.is_symlink():
            raise RuntimeError('Runtime staging collision; retry the operation.')
        from manager import pe_version
        with tempfile.TemporaryDirectory(prefix='.runtime-', dir=parent) as temporary:
            staging = Path(temporary)
            archive, payload = staging / 'download.tar.gz', staging / 'payload'
            digest, count = hashlib.sha256(), 0
            self.progress.update(identity, 'downloading', 0, descriptor['size_bytes'])
            request = urllib.request.Request(descriptor['url'], headers={'User-Agent': 'Opti2XMX', 'Accept': 'application/octet-stream'})
            with urllib.request.urlopen(request, timeout=30, context=download_ssl_context()) as response, archive.open('xb') as output:
                if urllib.parse.urlparse(response.geturl()).scheme != 'https':
                    raise RuntimeError('XMX runtime download redirected to an insecure source')
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > descriptor['size_bytes']:
                        raise RuntimeError('XMX runtime download exceeds the pinned size')
                    output.write(chunk)
                    digest.update(chunk)
                    self.progress.update(identity, 'downloading', count, descriptor['size_bytes'])
            if count != descriptor['size_bytes'] or digest.hexdigest() != descriptor['sha256']:
                raise RuntimeError('XMX runtime integrity check failed. Retry the download.')
            self.progress.update(identity, 'extracting')
            payload.mkdir(mode=0o700)
            unpack(archive, payload)
            validate_layout(payload, pe_version)
            self.progress.update(identity, 'installing')
            icd = staging / 'intel_icd.json'
            icd.write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {
                'api_version': '1.4.348', 'library_arch': '64',
                'library_path': str(payload / 'runtime/lib/libvulkan_intel.so')}}))
            for check in (lambda: rt.driver_check(payload / 'runtime', icd),
                          lambda: rt.compiler_check(payload / 'runtime')):
                ok, detail = check()
                if not ok:
                    raise RuntimeError('XMX host validation failed. ' + detail)
            payload.rename(destination)
            try:
                if self._runtime_config_bytes() != previous_config:
                    raise RuntimeError('Runtime configuration changed during download. Refresh before retrying.')
                rt.atomic_text(self.root / 'runtime.json', json.dumps({
                    'package': str(destination / 'runtime'), 'sr': str(destination / 'sdk/libxess.dll'),
                    'version': descriptor['version'], 'sha256': descriptor['sha256']}, indent=2) + '\n')
            except Exception:
                # Destination was newly created by this locked operation only.
                shutil.rmtree(destination)
                raise
        self.progress.finish(identity)
        return self.runtime_status()
