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
        for name in ('opti2xmx/../../outside.py', 'opti2xmx/libxess.dll',
                     'opti2xmx/fsr_compat/bin/amd_fidelityfx_loader_xmx.dll',
                     'opti2xmx/fsr_compat/bin/unknown.dll',
                     'opti2xmx/fsr_compat/sources/private-model.tar.gz',
                     'opti2xmx/private-fsr.zip'):
            bad = self.root / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as archive:
                archive.writestr(name, 'bad')
            with self.assertRaises(ValueError):
                prepare.prepare_release(self.payload, self.metadata, bad, self.root / 'bad-output')
            self.assertFalse((self.root / 'bad-output').exists())

    def test_public_fsr_compatibility_sources_and_binaries_survive_overlay(self):
        candidate = self.root / 'public-fsr.zip'
        with zipfile.ZipFile(self.plugin) as original, zipfile.ZipFile(candidate, 'w') as target:
            for entry in original.infolist():
                target.writestr(entry.filename, original.read(entry))
            for name in sorted(prepare.PUBLIC_FSR_COMPAT_MEMBERS):
                content = b'{}' if name.endswith('.json') else b'public source or binary fixture'
                target.writestr('opti2xmx/' + name, content)
        output = self.root / 'public-fsr-release'
        report = prepare.prepare_release(self.payload, self.metadata, candidate, output)
        self.assertEqual(report['plugin_files'], 9 + len(prepare.PUBLIC_FSR_COMPAT_MEMBERS))
        items = json.loads((output / 'integration/manifest.json').read_text())['opti2xmx']['files']
        for name in prepare.PUBLIC_FSR_COMPAT_MEMBERS:
            content = b'{}' if name.endswith('.json') else b'public source or binary fixture'
            self.assertEqual((output / 'components/opti2xmx' / name).read_bytes(), content)
            self.assertTrue(any(item['target'] == 'home/deck/homebrew/plugins/opti2xmx/' + name for item in items))

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
