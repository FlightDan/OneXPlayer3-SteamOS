import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import prepare_release as prepare


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = self.root / 'payload'
        (self.payload / 'components').mkdir(parents=True)
        (self.payload / 'integration/opti2xmx').mkdir(parents=True)
        (self.payload / 'components/options.json').write_text(json.dumps({'schema': 1, 'repairs': [
            {'id': 'opti2xmx', 'dependencies': []}], 'plugins': []}))
        (self.payload / 'components/release.json').write_text('{"version":"0.1.3"}')
        (self.payload / 'integration/opti2xmx/000.bin').write_bytes(b'old plugin')
        (self.payload / 'integration/opti2xmx/008.bin').write_bytes(b'old runtime config')
        (self.payload / 'integration/manifest.json').write_text(json.dumps({'opti2xmx': {'files': [
            {'source': 'opti2xmx/000.bin', 'target': 'home/deck/homebrew/plugins/opti2xmx/main.py'},
            {'source': 'opti2xmx/008.bin', 'target': 'home/deck/.local/share/opti2xmx/runtime.json'}],
            'runtime_archive': 'opti2xmx/runtime.tar.gz'}}))
        self.metadata = self.root / 'release.json'
        self.metadata.write_text(json.dumps({'version': '0.1.4', 'display_version': '0.1.4', 'channel': 'stable'}))
        self.plugin = self.root / 'plugin.zip'
        with zipfile.ZipFile(self.plugin, 'w') as archive:
            for name in ('plugin.json', 'package.json', 'main.py', 'manager.py', 'opti.py', 'per_game.py',
                         'runtime_setup.py', 'runtime-source.json', 'dist/index.js'):
                content = {'plugin.json': '{"name":"Opti2XMX"}', 'package.json': '{"version":"0.2.2"}'}.get(name, '{}')
                archive.writestr('opti2xmx/' + name, content)

    def test_overlay_preserves_inputs_and_replaces_all_generated_plugin_sources(self):
        output = self.root / 'release'
        report = prepare.prepare_release(self.payload, self.metadata, self.plugin, output)
        self.assertEqual(report['release']['version'], '0.1.4')
        self.assertEqual(report['plugin_files'], 9)
        self.assertEqual(json.loads((self.payload / 'components/release.json').read_text())['version'], '0.1.3')
        self.assertFalse((output / 'integration/opti2xmx/000.bin').exists())
        self.assertEqual((output / 'integration/opti2xmx/008.bin').read_bytes(), b'old runtime config')
        items = json.loads((output / 'integration/manifest.json').read_text())['opti2xmx']['files']
        self.assertEqual(len(items), 10)
        self.assertTrue(any(item['target'].endswith('/runtime_setup.py') for item in items))
        with self.assertRaises(ValueError):
            prepare.prepare_release(self.payload, self.metadata, self.plugin, output)

    def test_bad_zip_path_or_runtime_binary_is_rejected_before_output(self):
        for name in ('opti2xmx/../../outside.py', 'opti2xmx/libxess.dll'):
            bad = self.root / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as archive:
                archive.writestr(name, 'bad')
            with self.assertRaises(ValueError):
                prepare.prepare_release(self.payload, self.metadata, bad, self.root / 'bad-output')
            self.assertFalse((self.root / 'bad-output').exists())

    def test_exported_preparation_metadata_contains_no_absolute_workspace_path(self):
        (self.payload / 'components/preparation-report.json').write_text(json.dumps({
            'schema': 1, 'coverage': {}, 'source_inventory': {}, 'release': {'version': '0.1.3'}}))
        output = self.root / 'release-private-path-check'
        report = prepare.prepare_release(self.payload, self.metadata, self.plugin, output)
        self.assertEqual(report['source_payload'], 'payload')
        for name in ('preparation-report.json', 'release-preparation.json'):
            value = json.loads((output / 'components' / name).read_text())
            self.assertNotIn(str(self.root), json.dumps(value))
        self.assertEqual(json.loads((output / 'components/preparation-report.json').read_text())['release_overlay']['source_payload'], 'payload')

    def test_explicit_runtime_overlay_is_pinned_and_leaves_cache_unchanged(self):
        runtime = self.root / 'published-runtime.tar.gz'
        runtime.write_bytes(b'reviewed runtime with license notices')
        descriptor = {'published': True, 'size_bytes': runtime.stat().st_size,
                      'sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
                      'url': 'https://github.com/FlightDan/Opti2XMX/releases/download/v0.2.3/runtime.tar.gz'}
        candidate = self.root / 'plugin-current.zip'
        with zipfile.ZipFile(self.plugin) as original, zipfile.ZipFile(candidate, 'w') as target:
            for entry in original.infolist():
                target.writestr(entry.filename, json.dumps(descriptor).encode() if entry.filename.endswith('/runtime-source.json') else original.read(entry))
        cached = self.payload / 'integration/opti2xmx/runtime.tar.gz'
        cached.write_bytes(b'old cached runtime')
        output = self.root / 'release-current'
        report = prepare.prepare_release(self.payload, self.metadata, candidate, output, opti_runtime=runtime)
        self.assertEqual((output / 'integration/opti2xmx/runtime.tar.gz').read_bytes(), runtime.read_bytes())
        self.assertEqual(cached.read_bytes(), b'old cached runtime')
        self.assertEqual(report['runtime_overlay']['sha256'], descriptor['sha256'])
        runtime.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'differs'):
            prepare.prepare_release(self.payload, self.metadata, candidate, self.root / 'bad-runtime', opti_runtime=runtime)
        self.assertFalse((self.root / 'bad-runtime').exists())


if __name__ == '__main__':
    unittest.main()
