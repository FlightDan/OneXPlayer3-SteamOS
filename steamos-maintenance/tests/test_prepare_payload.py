import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from prepare_payload import PreparationError, prepare_payload, _maintenance_options


class PreparePayloadTests(unittest.TestCase):
    def test_maintenance_only_options_do_not_change_windows_input_or_default_plugins(self):
        source = {'schema': 1, 'repairs': [], 'plugins': []}
        config = json.loads((Path(__file__).resolve().parents[1] / 'release/maintenance-options.json').read_text(encoding='utf-8'))
        merged = _maintenance_options(source, config)
        self.assertEqual(source, {'schema': 1, 'repairs': [], 'plugins': []})
        self.assertEqual(merged['repairs'][0]['id'], 'serial-console-policy')
        self.assertEqual(merged['plugins'][0]['id'], 'autoflatpaks-compat')
        self.assertFalse(merged['plugins'][0]['default'])
        with self.assertRaises(PreparationError):
            _maintenance_options(merged, config)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'source'
        self.installer = self.workspace / 'windows-installer'
        self.output = self.root / 'payload'
        self.put('LICENSE', b'project license', workspace=True)
        self.put('components/release.json', {'schema': 1, 'version': '0.1.3',
            'display_version': '0.1.3', 'channel': 'stable'})
        self.options(['opti2xmx', 'refind', 'slot-switch'])
        self.put('cache/integration/manifest.json', {'opti2xmx': {'files': [{
            'source': 'opti2xmx/000.bin',
            'target': 'home/deck/homebrew/plugins/opti2xmx/main.py'}]}})
        self.put('cache/integration/opti2xmx/000.bin', b'old source')
        self.put('components/opti2xmx/main.py', b'current source')
        self.put('cache/plugins/plugins.json', [])
        self.put('cache/plugins/third-party.json', [])

    def put(self, relative, value, *, workspace=False):
        path = (self.workspace if workspace else self.installer) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(value) + '\n').encode() if isinstance(value, (dict, list)) else value)
        return path

    def options(self, names):
        self.put('components/options.json', {'schema': 1,
            'repairs': [{'id': name, 'dependencies': []} for name in names], 'plugins': []})

    def test_current_sources_replace_stale_cache_without_mutating_it(self):
        report = prepare_payload(self.workspace, self.output)
        self.assertEqual((self.output / 'integration/opti2xmx/000.bin').read_bytes(), b'current source')
        self.assertEqual((self.installer / 'cache/integration/opti2xmx/000.bin').read_bytes(), b'old source')
        self.assertEqual(len(report['refreshed_integration']), 1)
        record = report['source_inventory']['integration/opti2xmx/000.bin']
        self.assertEqual(record['sha256'], hashlib.sha256(b'current source').hexdigest())
        self.assertEqual(set(report['coverage']), {'opti2xmx', 'refind', 'slot-switch'})
        self.assertEqual(report['coverage']['slot-switch']['status'], 'excluded')
        self.assertIn('shared-storage', report['separate_operations'])
        self.assertTrue(report['resource_complete'])

    def test_overlay_runtime_uses_canonical_sources_instead_of_stale_cache(self):
        self.options(['overlay'])
        entries=[]
        for index,name in enumerate(('telemetry.py','allow-read.py')):
            source='overlay/%03d.bin' % index
            entries.append({'source':source,'target':'var/lib/oxp3-overlay-telemetry/'+name})
            self.put('cache/integration/'+source,b'old '+name.encode())
            self.put('components/controls/overlay/'+name,b'current '+name.encode())
        self.put('cache/integration/manifest.json',{'overlay':{'files':entries}})
        report=prepare_payload(self.workspace,self.output)
        self.assertTrue(report['resource_complete'])
        self.assertEqual(len(report['refreshed_integration']),2)
        for index,name in enumerate(('telemetry.py','allow-read.py')):
            source='overlay/%03d.bin' % index
            self.assertEqual((self.output/'integration'/source).read_bytes(),b'current '+name.encode())
            self.assertEqual((self.installer/'cache/integration'/source).read_bytes(),b'old '+name.encode())

    def test_only_explicit_roots_and_own_plugin_platform_are_collected(self):
        self.options(['opti2xmx', 'decky', 'hltb'])
        self.put('cache/plugins/third-party.json', [{'id': 'hltb', 'version': '2.0.12', 'archive': 'selected.zip'}])
        self.put('cache/plugins/hltb/selected.zip', b'pinned archive')
        self.put('cache/plugins/hltb/old.zip', b'old archive')
        self.put('cache/plugins/decky/PluginLoader', b'ELF fixture')
        self.put('cache/windows.exe', b'Windows')
        self.put('runtime/secret.json', b'private')
        self.put('research/secret.json', b'private', workspace=True)
        report = prepare_payload(self.workspace, self.output)
        paths = set(report['source_inventory'])
        self.assertIn('plugins/decky/PluginLoader', paths)
        self.assertNotIn('hltb', report['coverage'])
        self.assertFalse(any('hltb' in x for x in paths))
        options = json.loads((self.output / 'components/options.json').read_text())
        self.assertEqual({x['id'] for x in options['repairs']}, {'opti2xmx', 'decky'})
        self.assertFalse(any('old.zip' in x or 'secret' in x or 'windows.exe' in x for x in paths))

    def test_missing_resources_and_unknown_adapters_are_reported(self):
        self.options(['opti2xmx', 'decky', 'new-capability'])
        report = prepare_payload(self.workspace, self.output)
        self.assertFalse(report['resource_complete'])
        self.assertEqual(report['coverage']['decky']['status'], 'missing')
        self.assertEqual(report['coverage']['new-capability']['status'], 'unsupported')

    def test_manifest_option_id_mismatch_fails_before_output(self):
        self.options(['decky'])
        with self.assertRaisesRegex(PreparationError, 'IDs disagree'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_cached_release_mismatch_fails(self):
        self.put('cache/components/release.json', {'version': '0.1.2'})
        with self.assertRaisesRegex(PreparationError, 'release disagrees'):
            prepare_payload(self.workspace, self.output)

    def test_duplicate_ids_and_dangling_dependencies_fail(self):
        self.options(['opti2xmx', 'opti2xmx'])
        with self.assertRaisesRegex(PreparationError, 'duplicate option'):
            prepare_payload(self.workspace, self.output)
        self.put('components/options.json', {'schema': 1, 'repairs': [
            {'id': 'opti2xmx', 'dependencies': ['missing']}], 'plugins': []})
        with self.assertRaisesRegex(PreparationError, 'Unknown option dependency'):
            prepare_payload(self.workspace, self.output)

    def test_retired_profile_is_never_read_or_distributed(self):
        self.options(['opti2xmx', 'hltb'])
        self.put('cache/plugins/third-party.json', [{'id': 'hltb', 'version': '1.0.0', 'archive': '../escape.zip'}])
        prepare_payload(self.workspace, self.output)
        self.assertFalse((self.output / 'plugins/third-party.json').exists())
        self.assertFalse(list(self.root.glob('oxp3-payload-*')))
        self.assertTrue((self.installer / 'components/options.json').is_file())

    def test_retired_source_and_metadata_are_excluded_even_with_stale_options(self):
        self.options(['opti2xmx', 'hltb'])
        self.put('components/hltb-source-cache/main.py', b'retired plugin')
        self.put('components/tabmaster-compat/README.txt', b'compatibility patch')
        self.put('components/catalog.json', {'components': [{'id': 'opti2xmx'}, {'id': 'hltb'}]})
        self.put('licenses/HLTB-for-Deck-MIT.txt', b'license')
        report = prepare_payload(self.workspace, self.output)
        self.assertEqual(set(report['coverage']), {'opti2xmx'})
        self.assertFalse((self.output / 'components/hltb-source-cache').exists())
        self.assertFalse((self.output / 'components/tabmaster-compat').exists())
        self.assertFalse((self.output / 'licenses/HLTB-for-Deck-MIT.txt').exists())
        self.assertEqual(json.loads((self.output / 'components/catalog.json').read_text()),
                         {'components': [{'id': 'opti2xmx'}]})

    def test_existing_or_overlapping_output_is_refused(self):
        self.output.mkdir()
        with self.assertRaisesRegex(PreparationError, 'new isolated'):
            prepare_payload(self.workspace, self.output)
        with self.assertRaisesRegex(PreparationError, 'overlaps'):
            prepare_payload(self.workspace, self.installer / 'cache/new-output')

    def test_private_key_material_is_refused(self):
        self.put('components/leak.json', b'-----BEGIN PRIVATE KEY-----')
        with self.assertRaisesRegex(PreparationError, 'Private key material'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_cycle_is_refused_before_staging(self):
        self.put('components/options.json', {'schema': 1, 'repairs': [
            {'id': 'opti2xmx', 'dependencies': ['decky']},
            {'id': 'decky', 'dependencies': ['opti2xmx']}], 'plugins': []})
        with self.assertRaisesRegex(PreparationError, 'Cyclic option dependency'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_special_adapter_missing_sources_are_not_reported_supported(self):
        self.options(['opti2xmx', 'windows-reboot'])
        report = prepare_payload(self.workspace, self.output)
        self.assertEqual(report['coverage']['windows-reboot']['status'], 'missing')
        self.assertIn('components/windows-reboot/boot.py', report['coverage']['windows-reboot']['missing'])

    def test_service_refresh_retains_existing_activation_guard(self):
        self.options(['gyro'])
        self.put('components/gyro/oxp3-gyro.service', b'[Service]\nExecStart=/new\n')
        from prepare_payload import OLD_GUARD
        self.put('cache/integration/manifest.json', {'gyro': {'files': [{
            'source': 'gyro/unit.bin', 'target': 'etc/systemd/system/oxp3-gyro.service'}]}})
        self.put('cache/integration/gyro/unit.bin', b'[Service]\n' + OLD_GUARD + b'\nExecStart=/old\n')
        report = prepare_payload(self.workspace, self.output)
        self.assertEqual((self.output / 'integration/gyro/unit.bin').read_bytes(), b'[Service]\n' + OLD_GUARD + b'\nExecStart=/new\n')
        self.assertEqual(len(report['refreshed_integration']), 1)


if __name__ == '__main__':
    unittest.main()
