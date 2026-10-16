import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_bundle
from oxp3_maintenance import bootstrap as boot
from oxp3_maintenance.bundle import BundleError
from oxp3_maintenance.releases import ReleaseError


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        # Existing fixture uses real Ed25519 on all hosts and native OpenSSL
        # on Linux. Its package initializer raises if ever imported too early.
        self.fixture = test_bundle.BundleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.public = self.fixture.public
        self.archive = self.fixture.archive
        self.manifest = self.fixture._build()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        if os.name == 'nt' and self.fixture.openssl != 'test-openssl-adapter':
            # Bootstrap's production verifier is intentionally pinned to the
            # Linux system binary. Route that one test call to native Windows
            # OpenSSL while retaining real signature/archive authentication.
            original_verify = boot.verify_bundle
            def native_verify(*args, openssl, **kwargs):
                self.assertEqual(openssl, '/usr/bin/openssl')
                return original_verify(*args, openssl=self.fixture.openssl, **kwargs)
            self.stack.enter_context(patch.object(boot, 'verify_bundle', side_effect=native_verify))
        self.stack.enter_context(patch.object(boot, 'check_environment'))
        self.stack.enter_context(patch.object(boot, 'RUNTIME', self.root / 'uninstalled'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.launch = self.stack.enter_context(patch.object(boot, 'launch', return_value=0))

    def args(self, *extra):
        return boot.parser().parse_args(['--bundle', str(self.archive), *extra])

    def catalog(self):
        return {'bundle': {'size': self.archive.stat().st_size,
                           'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                           'manifest_digest': hashlib.sha256(json.dumps(self.manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}}

    def online(self):
        candidate = {'version': '1.2.3', 'channel': 'stable', 'asset_name': 'oxp3-maintenance-1.2.3-linux-x86_64.tar.gz',
                     'catalog_urls': {'json': 'https://example.invalid/catalog', 'sig': 'https://example.invalid/sig'}}
        report = {'maintenance_releases': [candidate], 'latest_project': {'version': '1.2.3'}}
        discovery = self.stack.enter_context(patch.object(boot, 'check_releases', return_value=report))
        catalog = self.stack.enter_context(patch.object(boot, 'fetch_catalog', return_value=self.catalog()))
        download = self.stack.enter_context(patch.object(boot, 'save', return_value={'path': str(self.archive)}))
        return report, discovery, catalog, download

    def test_verified_offline_launch_uses_private_snapshot_alive_until_exit(self):
        captured = []
        def launch(app, archive):
            self.assertNotEqual(archive, self.archive)
            self.assertEqual(archive.read_bytes(), self.archive.read_bytes())
            self.assertTrue((app / 'entry.py').is_file())
            self.assertEqual(boot.public_der(app / 'trusted-public-key.pem'), boot.public_der(self.public))
            captured.append(archive.parent)
            return 0
        self.launch.side_effect = launch
        self.assertEqual(boot.run(self.args(), self.public), 0)
        self.assertFalse(captured[0].exists())
        self.assertTrue(self.archive.is_file())

    def test_download_only_authenticates_without_running_downloaded_initializer(self):
        self.assertEqual(boot.run(self.args('--download-only'), self.public), 0)
        self.launch.assert_not_called()

    def test_signature_or_archive_damage_never_launches(self):
        self.archive.write_bytes(b'invalid archive')
        with self.assertRaises(BundleError):
            boot.run(self.args(), self.public)
        self.launch.assert_not_called()

    def test_signed_bundle_cannot_replace_installer_public_key(self):
        (self.fixture.source / 'trusted-public-key.pem').write_bytes(self.public.read_bytes())
        # A valid signature is insufficient if the package swaps the key used
        # by its own future privileged bootstrap. Patch only the extracted key.
        original = boot.verify_bundle
        def altered(*args, **kwargs):
            value = original(*args, **kwargs)
            (args[2] / 'app/trusted-public-key.pem').write_bytes(
                b'-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(bytes.fromhex('302a300506032b6570032100') + b'x' * 32) + b'\n-----END PUBLIC KEY-----\n')
            return value
        with patch.object(boot, 'verify_bundle', side_effect=altered), self.assertRaisesRegex(BundleError, 'pinned publisher key'):
            boot.run(self.args(), self.public)
        self.launch.assert_not_called()

    def test_version_and_installed_downgrade_are_refused_before_launch(self):
        with self.assertRaisesRegex(BundleError, 'requested version'):
            boot.run(self.args('--version', '1.2.4'), self.public)
        with patch.object(boot, 'installed_identity', return_value='1.2.4'), self.assertRaisesRegex(BundleError, 'downgrade'):
            boot.run(self.args(), self.public)
        self.launch.assert_not_called()

    def test_stable_rejects_beta_and_beta_accepts_stable(self):
        with self.assertRaises(BundleError):
            boot._release_guard({'version': '1.3.0-beta.1', 'channel': 'beta'}, self.args(), '0.0.0')
        boot._release_guard({'version': '1.2.3', 'channel': 'stable'}, self.args('--channel', 'beta'), '0.0.0')
        with self.assertRaises(BundleError):
            boot._release_guard({'version': '1.2.3', 'channel': 'beta'}, self.args('--channel', 'beta'), '0.0.0')

    def test_online_version_and_catalog_are_bound_to_snapshot(self):
        report, discovery, catalog, download = self.online()
        args = boot.parser().parse_args(['--version', 'v1.2.3', '--download-only'])
        self.assertEqual(boot.run(args, self.public), 0)
        self.assertEqual(discovery.call_args.args, ('0.0.0', 'stable'))
        self.assertEqual(download.call_args.kwargs['key'], self.public)
        self.launch.assert_not_called()
        catalog.return_value['bundle']['sha256'] = '0' * 64
        with self.assertRaisesRegex(BundleError, 'snapshot differs'):
            boot.run(args, self.public)

    def test_catalog_failure_stops_before_large_download(self):
        report, discovery, catalog, download = self.online()
        catalog.side_effect = BundleError('bad signature')
        with self.assertRaises(BundleError):
            boot.run(boot.parser().parse_args([]), self.public)
        download.assert_not_called()
        self.launch.assert_not_called()

    def test_same_version_resigned_cache_replacement_is_rejected(self):
        report, discovery, catalog, download = self.online()
        release = self.fixture.payload / 'components/release.json'
        value = json.loads(release.read_text())
        value['notes'] = 'Another signed build of the same version'
        release.write_text(json.dumps(value))
        replacement = self.root / 'replacement.tar.gz'
        self.fixture._build(replacement)
        def replace(*args, **kwargs):
            self.archive.write_bytes(replacement.read_bytes())
            return {'path': str(self.archive)}
        download.side_effect = replace
        with self.assertRaisesRegex(BundleError, 'snapshot differs'):
            boot.run(boot.parser().parse_args([]), self.public)
        self.launch.assert_not_called()

    def test_no_release_and_missing_catalog_do_not_fallback_to_unverified_source(self):
        report, discovery, catalog, download = self.online()
        report['maintenance_releases'][0]['catalog_urls'] = {}
        with self.assertRaisesRegex(ReleaseError, 'signed capability catalog'):
            boot.run(boot.parser().parse_args([]), self.public)
        report['maintenance_releases'] = []
        with self.assertRaisesRegex(ReleaseError, 'No maintenance package'):
            boot.run(boot.parser().parse_args([]), self.public)
        catalog.assert_not_called()
        download.assert_not_called()

    def test_launch_failure_cleans_private_tree_and_preserves_archive(self):
        paths = []
        def fail(app, archive):
            paths.append(app.parent.parent)
            raise OSError('launch failed')
        self.launch.side_effect = fail
        with self.assertRaises(OSError):
            boot.run(self.args(), self.public)
        self.assertFalse(paths[0].exists())
        self.assertTrue(self.archive.exists())

    def test_installed_metadata_key_mismatch_is_refused_without_execution(self):
        runtime = self.root / 'runtime'
        release = runtime / 'releases/1.2.3'
        release.mkdir(parents=True)
        (runtime / 'entry.py').write_text('raise AssertionError("do not execute")')
        (runtime / 'current-release.json').write_text(json.dumps({'version': '1.2.3'}))
        key = release / 'trusted-public-key.pem'
        key.write_bytes(self.public.read_bytes())
        with patch.object(boot, 'RUNTIME', runtime), patch.object(boot, '_protected'):
            self.assertEqual(boot.installed_identity(self.public), '1.2.3')
            key.write_bytes(b'-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(bytes.fromhex('302a300506032b6570032100') + b'y' * 32) + b'\n-----END PUBLIC KEY-----\n')
            with self.assertRaisesRegex(BundleError, 'installed trust anchor'):
                boot.installed_identity(self.public)


class BootstrapBoundaryTests(unittest.TestCase):
    def test_root_is_refused_even_for_download_only(self):
        with patch.object(boot.os, 'geteuid', return_value=0, create=True), self.assertRaisesRegex(RuntimeError, 'without sudo'):
            boot.check_environment(True)

    def test_help_needs_no_key_network_or_platform_probe(self):
        with patch.object(boot, 'run') as run, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit:
            boot.main(['--help'], public_key=Path('/absent'))
        self.assertEqual(exit.exception.code, 0)
        run.assert_not_called()

    def test_launch_has_no_shell_or_privilege_escalation(self):
        with patch.object(boot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(boot.launch(Path('/private/app'), Path('/private/bundle.tar.gz')), 0)
        self.assertEqual(run.call_args.args[0], ['/usr/bin/python3', '-I', '-B', str(Path('/private/app/entry.py')), 'gui', '--bundle', str(Path('/private/bundle.tar.gz'))])
        self.assertEqual(run.call_args.kwargs, {'check': False})


if __name__ == '__main__':
    unittest.main()
