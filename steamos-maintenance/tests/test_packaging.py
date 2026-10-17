import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
from unittest import mock
import zipfile

import build_bundle
import build_installer
import build_distribution
import package_release
from oxp3_maintenance.bundle import BundleError
import test_bundle


REAL_RUN = subprocess.run
SOURCE = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing real Ed25519/OpenSSL adapter fixture. Its private
        # test key is created only in a temporary directory, never shipped.
        self.fixture = test_bundle.BundleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.fixture.source
        self.payload = self.fixture.payload
        self.public = self.fixture.public
        self.private = self.fixture.key
        self.openssl = self.fixture.openssl
        package = self.source / 'oxp3_maintenance'
        for name in build_installer.BOOTSTRAP_FILES:
            target = package / name
            original = SOURCE / 'oxp3_maintenance' / name
            if name == 'bootstrap.py':
                target.write_text('''import json
import sys
from pathlib import Path
def main(argv=None, *, public_key):
    assert public_key.is_file()
    assert public_key.parent == Path(__file__).parent.parent.parent
    if argv and argv[0] == '--help':
        print('installer help')
        return 0
    Path(argv[0]).write_text(json.dumps({'args': argv[1:], 'key': public_key.read_text(), 'temporary': str(public_key.parent)}))
    if '--fail' in argv:
        raise RuntimeError('intentional bootstrap failure')
    return 7
''', encoding='utf-8')
            else:
                target.write_bytes(original.read_bytes())
        (package / 'unwanted.py').write_text('SECRET_UNRELATED_MODULE = True\n', encoding='utf-8')
        (self.source / 'windows-installer.exe').write_bytes(b'WINDOWS_EXCLUDED')
        (self.payload / 'components/options.json').write_text(json.dumps({'repairs': [{'id': 'repair', 'zh': 'Repair', 'en': 'Repair'}], 'plugins': []}))
        (self.payload / 'integration').mkdir()
        (self.payload / 'integration/manifest.json').write_text('{}')

    def installer(self, name='installer.sh'):
        output = self.root / name
        build_installer.build_installer(self.source, self.public, output, openssl=self.openssl)
        return output

    def package(self, name='release'):
        return package_release.package_release(self.payload, self.public, self.private,
                                               self.root / name, self.source, openssl=self.openssl)

    def body(self, path):
        text = path.read_text(encoding='utf-8')
        return text.split("<<'OXP3_EMBEDDED_PYTHON'\n", 1)[1].rsplit('OXP3_EMBEDDED_PYTHON', 1)[0]

    def test_installer_is_reproducible_and_whitelisted(self):
        first, second = self.installer(), self.installer('second.sh')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        body = ast.parse(self.body(first))
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in body.body
                  if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(values['ARCHIVE_B64']))) as archive:
            self.assertEqual(set(archive.namelist()), {'oxp3_maintenance/' + name for name in build_installer.BOOTSTRAP_FILES})
        key = base64.b64decode(values['PUBLIC_KEY_B64'])
        # Native Windows OpenSSL writes PEM with CRLF; release PEM is canonical
        # LF. Compare exact canonical bytes, retaining the original key content.
        self.assertEqual(key, self.public.read_bytes().replace(b'\r\n', b'\n'))
        self.assertNotIn(b'PRIVATE KEY', first.read_bytes())
        self.assertIn(b'exec /usr/bin/python3 -I -B - "$@"', first.read_bytes())

    def test_embedded_runner_is_isolated_and_cleans_up_on_success_and_failure(self):
        script = self.installer()
        for failing in (False, True):
            report = self.root / ('failure.json' if failing else 'success.json')
            args = [sys.executable, '-I', '-B', '-', str(report), 'argument with spaces']
            if failing:
                args.append('--fail')
            result = REAL_RUN(args, input=self.body(script), capture_output=True, text=True)
            self.assertEqual(result.returncode, 1 if failing else 7, result.stderr)
            record = json.loads(report.read_text())
            self.assertEqual(record['args'][0], 'argument with spaces')
            self.assertFalse(Path(record['temporary']).exists())
        result = REAL_RUN([sys.executable, '-I', '-B', '-', '--help'], input=self.body(script), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('installer help', result.stdout)

    def test_installer_rejects_invalid_key_and_preserves_existing_output(self):
        output = self.installer()
        initial = output.read_bytes()
        with self.assertRaises(FileExistsError):
            build_installer.build_installer(self.source, self.public, output, openssl=self.openssl)
        self.assertEqual(output.read_bytes(), initial)
        self.public.write_bytes(b'not a public key')
        with self.assertRaises(BundleError):
            self.installer('invalid.sh')
        self.assertFalse((self.root / 'invalid.sh').exists())

    def test_installer_removes_output_when_final_permission_step_fails(self):
        output = self.root / 'installer.sh'
        with mock.patch.object(Path, 'chmod', side_effect=OSError('permission failure')):
            with self.assertRaisesRegex(OSError, 'permission failure'):
                self.installer()
        self.assertFalse(output.exists())

    def test_packaging_reproducible_complete_and_no_private_key(self):
        original_key = (self.source / 'trusted-public-key.pem').read_bytes()
        canonical_key = original_key.replace(b'\r\n', b'\n')
        # The explicit publisher public key wins without modifying source.
        (self.source / 'trusted-public-key.pem').write_text('old checkout key')
        first, second = self.package(), self.package('second-release')
        self.assertEqual((self.source / 'trusted-public-key.pem').read_text(), 'old checkout key')
        expected = {'oxp3-maintenance-1.2.3-linux-x86_64.tar.gz', 'oxp3-maintenance-1.2.3-catalog.json',
                    'oxp3-maintenance-1.2.3-catalog.sig', 'install-oxp3-maintenance.sh', 'trusted-public-key.pem', 'SHA256SUMS'}
        self.assertEqual({p.name for p in first.iterdir()}, expected)
        for name in expected:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            self.assertNotIn(self.private.read_bytes(), (first / name).read_bytes())
        self.assertEqual(self.public.read_bytes(), original_key)
        self.assertEqual((first / 'trusted-public-key.pem').read_bytes(), canonical_key)
        for line in (first / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(digest, hashlib.sha256((first / name).read_bytes()).hexdigest())
        with tarfile.open(first / 'oxp3-maintenance-1.2.3-linux-x86_64.tar.gz') as archive:
            self.assertFalse(any('windows-installer' in n or 'private' in n for n in archive.getnames()))
            self.assertEqual(archive.extractfile('app/trusted-public-key.pem').read(), canonical_key)

    def test_failure_leaves_no_output_or_staging_and_calls_builder_once(self):
        with mock.patch.object(build_bundle, 'build_bundle', wraps=build_bundle.build_bundle) as build, \
             mock.patch.object(build_bundle, 'write_catalog', side_effect=BundleError('catalog failed')) as catalog:
            with self.assertRaisesRegex(BundleError, 'catalog failed'):
                self.package()
        self.assertEqual(build.call_count, 1)
        self.assertEqual(catalog.call_count, 1)
        self.assertFalse((self.root / 'release').exists())
        self.assertFalse(list(self.root.glob('.oxp3-release-*')))

    def test_modular_packaging_uses_explicit_key_and_complete_output_layout(self):
        from oxp3_maintenance import bundle, distribution
        (self.source / 'trusted-public-key.pem').write_text('old checkout key')
        (self.payload / 'components/options.json').write_text(json.dumps({'schema': 1,
            'repairs': [{'id': 'repair', 'zh': 'Repair', 'en': 'Repair', 'dependencies': []}], 'plugins': []}))
        output = package_release.package_release(self.payload, self.public, self.private,
            self.root / 'modular', self.source, openssl=self.openssl, modular=True,
            tag='maintenance-v1.2.3', opti_tag='maintenance-assets-v1.2.3')
        self.assertEqual((self.source / 'trusted-public-key.pem').read_text(), 'old checkout key')
        self.assertEqual({path.name for path in output.iterdir()}, {'maintenance', 'opti2xmx', 'release-plan.json'})
        seed = output / 'maintenance/oxp3-maintenance-1.2.3-linux-x86_64.tar.gz'
        self.assertEqual(bundle.inspect_bundle(seed, self.public, openssl=self.openssl)['schema'], 1)
        self.assertEqual(distribution.describe_source(seed, self.public, openssl=self.openssl)['schema'], 2)
        self.assertTrue((output / 'maintenance/install-oxp3-maintenance.sh').is_file())
        second = package_release.package_release(self.payload, self.public, self.private,
            self.root / 'modular-second', self.source, openssl=self.openssl, modular=True,
            previous_catalog=output / 'maintenance/oxp3-maintenance-1.2.3-catalog.json',
            previous_signature=output / 'maintenance/oxp3-maintenance-1.2.3-catalog.sig')
        self.assertTrue((second / 'release-plan.json').is_file())
        for path in output.rglob('*'):
            if path.is_file():
                self.assertNotIn(self.private.read_bytes(), path.read_bytes())

    def test_modular_failure_removes_staging_and_legacy_mode_rejects_modular_options(self):
        with mock.patch.object(build_distribution, 'build_distribution', side_effect=BundleError('modular build failed')):
            with self.assertRaisesRegex(BundleError, 'modular build failed'):
                package_release.package_release(self.payload, self.public, self.private,
                    self.root / 'failed', self.source, openssl=self.openssl, modular=True)
        self.assertFalse((self.root / 'failed').exists())
        self.assertFalse(list(self.root.glob('.oxp3-release-*')))
        with self.assertRaisesRegex(BundleError, 'require --modular'):
            package_release.package_release(self.payload, self.public, self.private,
                self.root / 'wrong-mode', self.source, openssl=self.openssl, tag='maintenance-v1.2.3')

    def test_mismatched_signing_key_fails_and_existing_release_is_preserved(self):
        encoded = b''.join(self.public.read_bytes().splitlines()[1:-1])
        der = bytearray(base64.b64decode(encoded))
        der[-1] ^= 1
        self.public.write_bytes(b'-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(der) + b'\n-----END PUBLIC KEY-----\n')
        with self.assertRaisesRegex(BundleError, 'match'):
            self.package()
        self.assertFalse((self.root / 'release').exists())
        self.private.write_bytes(b'not a key')
        with self.assertRaises(BundleError):
            self.package()
        self.assertFalse((self.root / 'release').exists())
        self.assertFalse(list(self.root.glob('.oxp3-release-*')))
        output = self.root / 'release'
        output.mkdir()
        (output / 'keep').write_text('original')
        with self.assertRaises(BundleError):
            self.package()
        self.assertEqual((output / 'keep').read_text(), 'original')

    def test_private_material_disguised_as_source_fails_before_release_appears(self):
        (self.source / 'oxp3_maintenance' / 'leak.py').write_bytes(self.private.read_bytes())
        with self.assertRaisesRegex(BundleError, 'private key material'):
            self.package()
        self.assertFalse((self.root / 'release').exists())
        self.assertFalse(list(self.root.glob('.oxp3-release-*')))

    def test_input_output_boundaries(self):
        for output in (self.source / 'release', self.payload / 'release'):
            with self.assertRaisesRegex(BundleError, 'outside'):
                package_release.package_release(self.payload, self.public, self.private, output, self.source, openssl=self.openssl)
        private = self.source / 'private.pem'
        private.write_bytes(self.private.read_bytes())
        with self.assertRaisesRegex(BundleError, 'outside'):
            package_release.package_release(self.payload, self.public, private, self.root / 'release', self.source, openssl=self.openssl)

    def test_command_line_help(self):
        for name in ('build_installer.py', 'package_release.py'):
            result = REAL_RUN([sys.executable, str(SOURCE / name), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--public-key', result.stdout)


if __name__ == '__main__':
    unittest.main()
