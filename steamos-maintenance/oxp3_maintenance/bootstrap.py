"""Small, unprivileged installer entry embedded with a publisher-pinned key.

Only the verifier shipped inside the installer runs before authentication.
Downloaded code starts as the desktop user after signature and content checks;
the native UI retains its review, polkit and privileged re-verification steps.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile

from .bundle import BundleError, MAX_ARCHIVE_BYTES, _regular_input, verify_bundle
from .downloads import save
from .releases import ReleaseError, _Version, _release_order, check_releases, fetch_catalog

RUNTIME = Path('/usr/local/lib/oxp3-maintenance')
PYTHON = '/usr/bin/python3'


def parser():
    result = argparse.ArgumentParser(description=(
        'OXP3 一键安装入口：下载并验签维护包，打开原生安装窗口。'
        ' Download, verify and open OXP3 Maintenance; system changes require GUI confirmation.'))
    result.add_argument('--channel', choices=('stable', 'beta'), default='stable',
                        help='发行通道 / release channel (default: stable)')
    result.add_argument('--version', help='指定项目版本 / exact project version')
    result.add_argument('--bundle', type=Path, help='已有离线维护包 / local signed maintenance archive')
    result.add_argument('--download-only', action='store_true', help='仅下载和验签，不打开窗口 / verify without launching')
    result.add_argument('--output', type=Path, default=Path.home() / 'Downloads/OXP3',
                        help='维护入口保存目录 / download directory (default: ~/Downloads/OXP3)')
    return result


def message(zh, en):
    print(zh + '\n' + en, flush=True)


def public_der(path):
    with _regular_input(Path(path), 8192) as stream:
        raw = stream.read(8193)
    encoded = re.fullmatch(rb'\s*-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*', raw)
    try:
        der = base64.b64decode(re.sub(rb'\s', b'', encoded.group(1)), validate=True) if encoded else b''
    except ValueError as error:
        raise BundleError('Invalid installer public key') from error
    if len(der) != 44 or not der.startswith(bytes.fromhex('302a300506032b6570032100')):
        raise BundleError('Installer requires a pinned Ed25519 public key')
    return der


def _protected(path):
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise BundleError('Existing maintenance installation is not a protected root-owned path')


def installed_identity(public_key):
    """Read metadata, never import or execute an existing installation."""
    entry, metadata = RUNTIME / 'entry.py', RUNTIME / 'current-release.json'
    if not os.path.lexists(entry) and not os.path.lexists(metadata):
        return '0.0.0'
    _protected(entry)
    _protected(metadata)
    with _regular_input(metadata, 65536) as stream:
        current = json.load(stream)
    version = _Version(current['version']).text
    runtime = current.get('maintenance_runtime', version)
    if not isinstance(runtime, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,159}', runtime):
        raise BundleError('Invalid installed maintenance runtime')
    key = RUNTIME / 'releases' / runtime / 'trusted-public-key.pem'
    _protected(key)
    if public_der(key) != public_der(public_key):
        raise BundleError('Installer signing key differs from the installed trust anchor; use the existing maintenance tool')
    return version


def check_environment(download_only):
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        raise RuntimeError('请以桌面用户运行，不要使用 sudo。 Run as the desktop user, without sudo.')
    if sys.platform != 'linux':
        raise RuntimeError('请在 SteamOS/Linux 运行安装脚本。 This installer requires Linux.')
    if not Path('/usr/bin/openssl').is_file():
        raise RuntimeError('缺少系统 OpenSSL，无法验签。 System OpenSSL is required.')
    if download_only:
        return
    if platform.machine() not in ('x86_64', 'amd64'):
        raise RuntimeError('The native installer requires x86_64 SteamOS.')
    release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            name, value = line.split('=', 1)
            release[name] = value.strip().strip('\"').strip("'")
    if (release.get('ID') != 'steamos'
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'ONE-NETBOOK'
            or Path('/sys/class/dmi/id/product_name').read_text().strip() != 'ONEXPLAYER 3'):
        raise RuntimeError('请在 OXP3 SteamOS 上安装；其他电脑可使用 --download-only。 Use OXP3 SteamOS, or --download-only on another Linux computer.')
    import pwd
    if pwd.getpwuid(os.geteuid()).pw_name != 'deck':
        raise RuntimeError('当前安装适配要求 deck 桌面账户。 Use the deck desktop account.')
    if (os.environ.get('XDG_CURRENT_DESKTOP', '').lower() == 'gamescope'
            or 'gamescope' in os.environ.get('DESKTOP_SESSION', '').lower()
            or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))):
        raise RuntimeError('请切换到 SteamOS 桌面模式再运行。 Switch to SteamOS Desktop Mode first.')
    if not Path('/usr/bin/pkexec').is_file():
        raise RuntimeError('缺少系统认证工具 pkexec。 System pkexec is required.')
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        ready, _ = Gtk.init_check(None)
        if not ready:
            raise RuntimeError('Cannot connect to the desktop display')
    except (ImportError, ValueError, RuntimeError) as error:
        raise RuntimeError('无法打开原生 GTK 3 窗口，请在设备桌面模式重试。 GTK 3 desktop is unavailable.') from error


def _release_guard(release, args, installed):
    version = _Version(release['version'])
    expected_channel = 'beta' if version.pre else 'stable'
    if release.get('channel') != expected_channel or version.pre and (args.channel != 'beta' or version.pre[0] != 'beta'):
        raise BundleError('Package does not match the selected stable/beta channel')
    if args.version and version.text != _Version(args.version).text:
        raise BundleError('Package does not match the requested version')
    if _release_order(version.text) < _release_order(installed):
        raise BundleError('Refusing to downgrade the installed project; use its explicit rollback action')


def _copy_archive(source, destination):
    # Verification and launch use our private snapshot, never a mutable download.
    with _regular_input(Path(source), MAX_ARCHIVE_BYTES) as incoming, destination.open('xb') as output:
        total = 0
        while chunk := incoming.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise BundleError('Maintenance archive exceeds the size limit')
            output.write(chunk)


def launch(app, archive):
    return subprocess.run([PYTHON, '-I', '-B', str(app / 'entry.py'), 'gui', '--bundle', str(archive)], check=False).returncode


def run(args, public_key, *, opener=None):
    check_environment(args.download_only)
    public_key = Path(public_key)
    fingerprint = hashlib.sha256(public_der(public_key)).hexdigest()
    installed = installed_identity(public_key)
    if args.version:
        requested = _Version(args.version)
        _release_guard({'version': requested.text, 'channel': 'beta' if requested.pre else 'stable'}, args, installed)
    message('发行公钥 SHA-256：' + fingerprint, 'Publisher public key SHA-256 (DER): ' + fingerprint)
    candidate = catalog = None
    if args.bundle:
        archive = args.bundle.expanduser()
        message('正在验证离线维护包。', 'Verifying the offline maintenance archive.')
    else:
        message('正在查询项目维护包。', 'Looking up project maintenance releases.')
        def progress(event):
            if event.get('phase') == 'retrying_github':
                message('连接失败，正在重试。', 'Retrying the project release service.')
        report = check_releases(installed, args.channel, public_key=public_key, opener=opener, progress=progress)
        choices = report.get('maintenance_releases', [])
        if args.version:
            choices = [item for item in choices if item['version'] == _Version(args.version).text]
        if not choices:
            raise ReleaseError('尚未提供所选版本的维护包，请稍后重试。 No maintenance package is published for this selection.')
        candidate = choices[0]
        _release_guard(candidate, args, installed)
        if not candidate.get('catalog_urls'):
            raise ReleaseError('该版本缺少签名功能目录，无法在线安装。 This release has no signed capability catalog.')
        latest = report.get('latest_project')
        if latest and _release_order(latest['version']) > _release_order(candidate['version']):
            message('最新项目尚无对应维护包；将使用已发布的维护包 ' + candidate['version'] + '。',
                    'The newest project has no maintenance package; using published maintenance ' + candidate['version'] + '.')
        message('正在下载并验证维护包 ' + candidate['version'] + '，请稍候。',
                'Downloading and verifying maintenance ' + candidate['version'] + '; please wait.')
        catalog = fetch_catalog(candidate, public_key, opener=opener, progress=progress)
        result = save(candidate, args.output, key=public_key, opener=opener, progress=progress)
        archive = Path(result['path'])
    with tempfile.TemporaryDirectory(prefix='oxp3-install-') as temporary:
        directory = Path(temporary)
        snapshot = directory / 'maintenance.tar.gz'
        _copy_archive(archive, snapshot)
        extracted = directory / 'verified'
        extracted.mkdir(mode=0o700)
        manifest = verify_bundle(snapshot, public_key, extracted, openssl='/usr/bin/openssl')
        _release_guard(manifest['release'], args, installed)
        if candidate and manifest['release']['version'] != candidate['version']:
            raise BundleError('Verified archive differs from the selected online version')
        if catalog:
            digest = hashlib.sha256()
            with snapshot.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            manifest_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if (snapshot.stat().st_size != catalog['bundle']['size']
                    or digest.hexdigest() != catalog['bundle']['sha256']
                    or manifest_digest != catalog['bundle']['manifest_digest']):
                raise BundleError('Private archive snapshot differs from the signed capability catalog')
        app = extracted / 'app'
        if public_der(app / 'trusted-public-key.pem') != public_der(public_key):
            raise BundleError('Verified package attempts to change the pinned publisher key')
        if not (app / 'entry.py').is_file():
            raise BundleError('Verified package has no maintenance entry point')
        message('验签通过：' + manifest['release']['version'], 'Verified project release: ' + manifest['release']['version'])
        if args.download_only:
            message('已验证的维护入口包：' + str(archive.absolute()), 'Verified maintenance entry archive: ' + str(archive.absolute()))
            return 0
        message('正在打开安装窗口；选择组件并确认后才会修改系统。',
                'Opening the installer. Review components and authorize changes in the native window.')
        # The original archive stays available for offline use. The private
        # extracted source survives until the entire UI/authorization flow exits.
        return launch(app, snapshot)


def main(argv=None, *, public_key):
    args = parser().parse_args(argv)
    try:
        return run(args, public_key)
    except KeyboardInterrupt:
        message('已取消。', 'Cancelled.')
        return 130
    except (BundleError, ReleaseError, OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print('安装入口未完成 / Installer stopped: ' + str(error), file=sys.stderr, flush=True)
        return 1
