import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import publisher


class PublisherTests(unittest.TestCase):
    @staticmethod
    def descriptor(**overrides):
        return dict({'schema': 1, 'version': '20261005', 'published': True,
                     'size_bytes': 1, 'sha256': 'a' * 64,
                     'url': 'https://github.com/FlightDan/Opti2XMX/releases/download/v0.2.3/'
                            'opti2xmx-xmx-runtime-20261005-aaaaaaaaaaaaaaaa.tar.gz'}, **overrides)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_canonical_public_key_is_idempotent_and_cannot_be_replaced(self):
        public = self.root / 'public.pem'
        destination = self.root / 'canonical.pem'
        public.write_bytes(b'-----BEGIN PUBLIC KEY-----\nfirst\n-----END PUBLIC KEY-----\n')
        status = {'public_key': str(public)}
        publisher.install_public_key(status, destination)
        publisher.install_public_key(status, destination)
        before = destination.read_bytes()
        public.write_bytes(b'-----BEGIN PUBLIC KEY-----\nsecond\n-----END PUBLIC KEY-----\n')
        with self.assertRaisesRegex(ValueError, 'refusing replacement'):
            publisher.install_public_key(status, destination)
        self.assertEqual(destination.read_bytes(), before)
        public.write_bytes(b'-----BEGIN PRIVATE KEY-----\nsecret\n')
        with self.assertRaisesRegex(ValueError, 'public PEM'):
            publisher.install_public_key(status, destination)

    def test_runtime_cache_must_match_published_size_and_digest(self):
        payload = self.root / 'payload'
        integration = payload / 'integration'
        integration.mkdir(parents=True)
        archive = integration / 'runtime.tar.gz'
        archive.write_bytes(b'current licensed runtime')
        (integration / 'manifest.json').write_text(json.dumps({
            'opti2xmx': {'runtime_archive': archive.name}}))
        descriptor = self.descriptor(size_bytes=archive.stat().st_size,
                                     sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        with mock.patch('prepare_release.plugin_files', return_value={
                'runtime-source.json': json.dumps(descriptor).encode()}):
            publisher.validate_runtime(payload, self.root / 'plugin.zip')
            archive.write_bytes(b'stale runtime')
            with self.assertRaisesRegex(ValueError, 'differs'):
                publisher.validate_runtime(payload, self.root / 'plugin.zip')

    def test_runtime_reference_cannot_escape_integration(self):
        integration = self.root / 'integration'
        integration.mkdir()
        for reference in ('../outside', 'C:/outside', '/outside', 'a\\b'):
            (integration / 'manifest.json').write_text(json.dumps({
                'opti2xmx': {'runtime_archive': reference}}))
            descriptor = self.descriptor()
            with mock.patch('prepare_release.plugin_files', return_value={
                    'runtime-source.json': json.dumps(descriptor).encode()}):
                with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, 'Unsafe'):
                    publisher.validate_runtime(self.root, self.root / 'plugin.zip')

    def test_missing_dependencies_fail_before_any_preparation_or_key_access(self):
        output = self.root / 'must-not-exist'
        with mock.patch.object(publisher, 'preflight', return_value={
                'ready': False, 'blockers': ['No final plugin']}), \
                mock.patch('prepare_payload.prepare_payload') as stage:
            with self.assertRaisesRegex(ValueError, 'No final plugin'):
                publisher.prepare('0.1.4', self.root / 'store', output=output)
            stage.assert_not_called()
        self.assertFalse(output.exists())

    def test_reference_reuse_requires_catalog_and_signature_before_preflight(self):
        with mock.patch.object(publisher,'preflight') as check:
            for arguments in ({'previous_catalog':self.root/'catalog.json'},
                              {'previous_signature':self.root/'catalog.sig'}):
                with self.assertRaisesRegex(ValueError,'supplied together'):
                    publisher.prepare('0.1.4+maintenance.5',self.root/'store',**arguments)
            check.assert_not_called()

    def test_version_rejects_path_traversal_before_file_access(self):
        for value in ('../0.1.4', 'v0.1.4', '0.1.4/../../secrets'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                publisher.metadata(value)

    def test_output_dotdot_cannot_escape_work_directory(self):
        output = self.root / '.release-work' / '..' / 'outside'
        with mock.patch.object(publisher, 'WORKSPACE', self.root), \
                mock.patch.object(publisher, 'preflight', return_value={'ready': True}):
            with self.assertRaisesRegex(ValueError, 'fresh child'):
                publisher.prepare('0.1.4', self.root / 'store', output=output)
        self.assertFalse((self.root / 'outside').exists())

    def test_runtime_descriptor_cannot_claim_unusable_publication(self):
        for overrides in ({'schema': 2}, {'schema': True}, {'version': '../oops'},
                          {'published': 'true'}, {'size_bytes': True}, {'sha256': 'a'},
                          {'url': 'https://invalid.example/runtime.tar.gz'},
                          {'url': 'https://github.com/FlightDan/Opti2XMX/releases/download/latest/'
                                  'opti2xmx-xmx-runtime-20261005-aaaaaaaaaaaaaaaa.tar.gz'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                publisher.runtime_descriptor({'runtime-source.json': json.dumps(self.descriptor(**overrides))})

    def test_packaging_requires_real_supported_openssl(self):
        with mock.patch.object(publisher.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'OpenSSL'):
                publisher.openssl_path('missing')
        with mock.patch.object(publisher.shutil, 'which', return_value='openssl'), \
                mock.patch.object(publisher.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, b'OpenSSL 1.1.1\n')):
            with self.assertRaisesRegex(ValueError, '3.x'):
                publisher.openssl_path('openssl')

    def test_preflight_missing_identity_is_actionable_and_forwards_openssl(self):
        with mock.patch('publisher_keys.key_status', return_value={'status': 'missing'}) as status, \
                mock.patch.object(publisher, 'openssl_path', return_value='openssl'):
            result = publisher.preflight('0.1.4', self.root / 'store', openssl='explicit-openssl')
        self.assertFalse(result['ready'])
        self.assertTrue(any('init-key' in item for item in result['blockers']))
        status.assert_called_once_with(self.root / 'store', openssl='explicit-openssl')
