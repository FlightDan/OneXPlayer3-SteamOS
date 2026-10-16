import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from oxp3_maintenance.payload_policy import (
    REMOVED_PLUGIN_IDS, distributable_path, sanitize_options, sanitize_payload,
)


class PayloadPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'prepared'
        self.source.mkdir()
        self.output = self.root / 'sanitized'

    def put(self, relative, value):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(value).encode() if isinstance(value, (dict, list)) else value)
        return path

    def test_legacy_payload_is_filtered_without_mutating_original(self):
        own = {'decky', 'opti2xmx', 'oxp3-fan', 'oxp3-cpu', 'charging', 'oxp3-light', 'windows-reboot'}
        options = {'schema': 1, 'repairs': [
            {'id': x, 'dependencies': [] if x == 'decky' else ['decky']}
            for x in sorted(own | REMOVED_PLUGIN_IDS)], 'plugins': []}
        self.put('components/options.json', options)
        self.put('components/fulloptions.json', options)
        self.put('components/release.json', {'version': '1.2.3'})
        self.put('components/catalog.json', {'components': [{'id': x} for x in sorted(own | REMOVED_PLUGIN_IDS)]})
        self.put('plugins/plugins.json', [{'id': x, 'archive': 'old.zip'} for x in REMOVED_PLUGIN_IDS])
        self.put('plugins/third-party.json', [{'id': 'hltb'}])
        self.put('cache/plugins/unknown-source/archive.zip', b'stale source cache')
        self.put('components/tabmaster-compat/README.txt', b'patch')
        self.put('components/protondb-source-cache/main.py', b'stale source')
        self.put('licenses/HLTB-for-Deck-MIT.txt', b'third party license')
        for plugin in own | REMOVED_PLUGIN_IDS:
            self.put('plugins/' + plugin + '/archive.zip', plugin.encode())
        self.put('integration/unrelated/retired.bin', b'retired archive data')
        self.put('integration/manifest.json', {'hltb': {'files': [{'source': 'unrelated/retired.bin'}]},
            'opti2xmx': {'files': []}})
        old_options = (self.source / 'components/options.json').read_bytes()
        self.put('components/preparation-report.json', {
            'coverage': {x: {'status': 'adapter_supported', 'dependencies': []} for x in own | REMOVED_PLUGIN_IDS},
            'source_inventory': {'components/options.json': {'sha256': 'old', 'size': 0},
                                 'plugins/hltb/archive.zip': {'sha256': 'old', 'size': 0}},
            'refreshed_integration': [{'component': 'hltb'}, {'component': 'opti2xmx'}]})
        sanitize_payload(self.source, self.output)
        self.assertEqual((self.source / 'components/options.json').read_bytes(), old_options)
        self.assertTrue((self.source / 'plugins/hltb/archive.zip').is_file())
        for filename in ('options.json', 'fulloptions.json'):
            cleaned = json.loads((self.output / 'components' / filename).read_text())
            self.assertEqual({x['id'] for x in cleaned['repairs']}, own)
        for plugin in REMOVED_PLUGIN_IDS:
            self.assertFalse((self.output / 'plugins' / plugin).exists())
        for plugin in own:
            self.assertEqual((self.output / 'plugins' / plugin / 'archive.zip').read_bytes(), plugin.encode())
        self.assertFalse((self.output / 'integration/unrelated/retired.bin').exists())
        self.assertFalse((self.output / 'components/protondb-source-cache').exists())
        self.assertFalse((self.output / 'components/tabmaster-compat').exists())
        self.assertFalse((self.output / 'cache').exists())
        self.assertEqual(json.loads((self.output / 'plugins/plugins.json').read_text()), [])
        metadata = json.loads((self.output / 'components/preparation-report.json').read_text())
        self.assertEqual(set(metadata['coverage']), own)
        self.assertEqual(metadata['refreshed_integration'], [{'component': 'opti2xmx'}])
        inventory = metadata['source_inventory']
        self.assertEqual(set(inventory), {'components/options.json'})
        self.assertEqual(inventory['components/options.json']['sha256'],
                         hashlib.sha256((self.output / 'components/options.json').read_bytes()).hexdigest())

    def test_retained_dependency_on_removed_plugin_is_rejected(self):
        options = {'schema': 1, 'repairs': [{'id': 'opti2xmx', 'dependencies': ['hltb']}],
                   'plugins': [{'id': 'hltb', 'dependencies': []}]}
        with self.assertRaisesRegex(ValueError, 'Unknown option dependency'):
            sanitize_options(options)
        self.assertEqual(len(options['plugins']), 1)

    def test_matching_is_exact_and_paths_are_validated(self):
        self.assertFalse(distributable_path('plugins/HLTB/old.zip'))
        self.assertFalse(distributable_path('components/tabmaster-source-cache/main.py'))
        self.assertTrue(distributable_path('components/my-protondb-tool/main.py'))
        self.assertTrue(distributable_path('plugins/opti2xmx/dist/index.js'))
        with self.assertRaisesRegex(ValueError, 'Unsafe payload path'):
            distributable_path('../plugins/decky')

    def test_existing_and_overlapping_destinations_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            sanitize_payload(self.source, self.source / 'child')
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'new isolated'):
            sanitize_payload(self.source, self.output)


if __name__ == '__main__':
    unittest.main()
