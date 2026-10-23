"""Reject stale, mismatched and wrong-platform Decky delivery inputs."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('prepare_decky', Path(__file__).with_name('prepare-decky.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeckyPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.downloads = self.root / 'downloads'
        self.downloads.mkdir()
        self.output = self.root / 'payload'
        binary = bytearray(64)
        binary[:6] = b'\x7fELF\x02\x01'
        binary[18:20] = (62).to_bytes(2, 'little')
        self.binary = bytes(binary)
        archive = io.BytesIO()
        self.commit = 'a' * 40
        with zipfile.ZipFile(archive, 'w') as package:
            prefix = 'decky-loader-' + self.commit + '/'
            package.writestr(prefix + 'dist/plugin_loader-release.service', b'[Service]\n')
            package.writestr(prefix + 'LICENSE', b'GPL-2.0\n')
        source = archive.getvalue()
        self.pin = {'schema': 1, 'version': '3.3.0', 'source_commit': self.commit,
                    'binary': self.record(self.binary), 'source': self.record(source)}
        self.pin_path = self.root / 'release.json'
        self.write_pin()
        (self.downloads / 'PluginLoader').write_bytes(self.binary)
        (self.downloads / 'source-v3.3.0.zip').write_bytes(source)

    def record(self, data):
        return {'url': 'https://example.invalid/artifact', 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}

    def write_pin(self):
        self.pin_path.write_text(json.dumps(self.pin), encoding='utf-8')

    def prepare(self):
        return module.prepare(self.pin_path, self.output, downloads=self.downloads)

    def test_prepared_payload_is_complete_and_verified_offline(self):
        report = self.prepare()
        self.assertEqual(module.prepare(self.pin_path, self.output, check=True), report)
        self.assertEqual((self.output / 'VERSION').read_bytes(), b'3.3.0\n')
        self.assertIn('source-v3.3.0.zip', report['files'])

    def test_changed_binary_is_rejected_before_staging(self):
        (self.downloads / 'PluginLoader').write_bytes(self.binary[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_wrong_architecture_is_rejected_even_when_digest_matches(self):
        binary = bytearray(self.binary)
        binary[18:20] = (183).to_bytes(2, 'little')
        self.pin['binary'] = self.record(binary)
        self.write_pin()
        (self.downloads / 'PluginLoader').write_bytes(binary)
        with self.assertRaisesRegex(ValueError, 'x86_64'):
            self.prepare()

    def test_old_source_archive_cannot_leak_into_delivery(self):
        self.prepare()
        (self.output / 'source-v3.2.10.zip').write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'stale'):
            module.prepare(self.pin_path, self.output, check=True)

    def test_stale_version_marker_is_rejected(self):
        self.prepare()
        (self.output / 'VERSION').write_bytes(b'3.2.10\n')
        with self.assertRaisesRegex(ValueError, 'VERSION'):
            module.prepare(self.pin_path, self.output, check=True)


if __name__ == '__main__':
    unittest.main()
