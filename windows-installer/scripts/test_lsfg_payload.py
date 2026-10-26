"""Verify the pinned plugin, generated payload and targeted preparation boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lsfg_payload import ROOT, check_integration, integration_files, read_cache, read_pin, read_plugin_archive

ARCHIVE = ROOT / 'cache/lsfg-vk' / read_pin()['archive']['filename']


class TargetedPreparationTests(unittest.TestCase):
    def test_missing_manifest_does_not_create_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'missing'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/prepare-integration.py'),
                '--lsfg-only', '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('existing integration manifest', result.stderr)
            self.assertFalse(output.exists())


@unittest.skipUnless(ARCHIVE.is_file(), 'Prepare the pinned official LSFG-VK archive first')
class OfficialPayloadTests(unittest.TestCase):
    def test_official_payload_is_unprivileged_and_has_no_user_state(self):
        files = read_plugin_archive(ARCHIVE)
        self.assertEqual(json.loads(files['plugin.json'])['flags'], [])
        self.assertEqual(json.loads(files['package.json'])['version'], '0.14.4')
        self.assertIn('bin/lsfg-vk-2.0.0.tar.xz', files)
        self.assertIn('LICENSE', files)
        self.assertFalse(any(path.endswith(('.dll', 'conf.toml', 'localconfig.vdf')) for path in files))
        for path in integration_files():
            self.assertTrue(path.startswith('/var/lib/oxp3-installer/decky/runtime/plugins/Decky LSFG-VK/'))

    def test_corrupt_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'modified.zip'
            data = bytearray(ARCHIVE.read_bytes())
            data[len(data) // 2] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                read_plugin_archive(path)

    def test_stale_cache_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / ARCHIVE.name).write_bytes(ARCHIVE.read_bytes())
            (cache / 'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Stale'):
                read_cache(cache)

    def test_targeted_generation_preserves_other_components_and_checks_every_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            other = {'files': [], 'units': [], 'packages': {}, 'missing': [], 'marker': 'keep-current-payload'}
            (output / 'manifest.json').write_text(json.dumps({'other': other}))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/prepare-integration.py'),
                '--lsfg-only', '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest['other'], other)
            self.assertEqual(check_integration(output)['files'], len(read_cache()))
            entry = manifest['lsfg-vk']['files'][0]
            (output / entry['source']).write_bytes(b'stale payload')
            with self.assertRaisesRegex(ValueError, 'differ'):
                check_integration(output)


if __name__ == '__main__':
    unittest.main()
