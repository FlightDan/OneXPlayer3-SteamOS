#!/usr/bin/env python3
"""Build a self-contained installer using an explicitly supplied publisher key."""
from __future__ import annotations

import argparse
import base64
import io
from pathlib import Path
import sys
import zipfile

from build_bundle import _run
from oxp3_maintenance.bundle import BundleError

BOOTSTRAP_FILES = ('__init__.py', 'bundle.py', 'network.py', 'releases.py', 'catalog.py', 'distribution.py', 'downloads.py', 'bootstrap.py')
INSTALLER_NAME = 'install-oxp3-maintenance.sh'


def public_key_bytes(public_key: Path, *, openssl='openssl') -> bytes:
    """Accept only a real Ed25519 public key and emit canonical SPKI PEM."""
    public_key = Path(public_key)
    if public_key.is_symlink() or not public_key.is_file():
        raise BundleError('Publisher public key is unavailable or a symlink.')
    der = _run([str(openssl), 'pkey', '-pubin', '-in', str(public_key), '-outform', 'DER'])
    if len(der) != 44 or not der.startswith(bytes.fromhex('302a300506032b6570032100')):
        raise BundleError('Installer trust key must be an Ed25519 public key.')
    return b'-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(der) + b'\n-----END PUBLIC KEY-----\n'


def build_installer(source: Path, public_key: Path, output: Path, *, openssl='openssl') -> Path:
    """Embed only the audited bootstrap modules; never download Python to start."""
    source, output = Path(source), Path(output)
    key = public_key_bytes(public_key, openssl=openssl)
    package = source / 'oxp3_maintenance'
    if package.is_symlink() or not package.is_dir():
        raise BundleError('Maintenance bootstrap package is unavailable or a symlink.')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name in BOOTSTRAP_FILES:
            path = package / name
            if path.is_symlink() or not path.is_file():
                raise BundleError('Maintenance bootstrap module is missing or a symlink: ' + name)
            content = path.read_bytes()
            if any(marker in content for marker in (b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----', b'-----BEGIN OPENSSH PRIVATE KEY-----')):
                raise BundleError('Maintenance bootstrap contains private key material.')
            entry = zipfile.ZipInfo('oxp3_maintenance/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content)
    # The shell does no privilege escalation. -I ignores PYTHONPATH/site hooks;
    # -B avoids creating bytecode, and stdin carries only this local program.
    script = '''#!/bin/bash
set -eu
exec /usr/bin/python3 -I -B - "$@" <<'OXP3_EMBEDDED_PYTHON'
import base64
from pathlib import Path
import sys
import tempfile

ARCHIVE_B64 = %r
PUBLIC_KEY_B64 = %r

with tempfile.TemporaryDirectory(prefix='oxp3-installer-') as directory:
    root = Path(directory)
    archive = root / 'bootstrap.zip'
    key = root / 'trusted-public-key.pem'
    archive.write_bytes(base64.b64decode(ARCHIVE_B64, validate=True))
    key.write_bytes(base64.b64decode(PUBLIC_KEY_B64, validate=True))
    sys.path.insert(0, str(archive))
    from oxp3_maintenance.bootstrap import main
    result = main(sys.argv[1:], public_key=key)
raise SystemExit(result)
OXP3_EMBEDDED_PYTHON
''' % (base64.b64encode(buffer.getvalue()).decode('ascii'), base64.b64encode(key).decode('ascii'))
    created = False
    try:
        with output.open('xb') as target:
            created = True
            target.write(script.encode('utf-8'))
        output.chmod(0o755)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args(argv)
    try:
        build_installer(args.source, args.public_key, args.output, openssl=args.openssl)
    except (BundleError, OSError, ValueError) as error:
        parser.exit(1, 'Installer build failed: %s\n' % error)
    print('Built self-contained installer: ' + str(args.output))
    return 0


if __name__ == '__main__':
    sys.exit(main())
