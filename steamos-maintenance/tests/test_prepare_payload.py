import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from prepare_payload import PreparationError, prepare_payload, _current_source, _maintenance_options
from decky_fixture import decky_fixture


class PreparePayloadTests(unittest.TestCase):
    def test_maintenance_only_options_do_not_change_windows_input_or_default_plugins(self):
        source = {'schema': 1, 'repairs': [], 'plugins': []}
        config = json.loads((Path(__file__).resolve().parents[1] / 'release/maintenance-options.json').read_text(encoding='utf-8'))
        merged = _maintenance_options(source, config)
        self.assertEqual(source, {'schema': 1, 'repairs': [], 'plugins': []})
        self.assertEqual(merged['repairs'][0]['id'], 'serial-console-policy')
        self.assertEqual(merged['plugins'][0]['id'], 'autoflatpaks-compat')
        self.assertFalse(merged['plugins'][0]['default'])
        self.assertEqual(merged['plugins'][1]['id'], 'animation-changer-compat')
        self.assertFalse(merged['plugins'][1]['default'])
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
        for name in ('boot.py', 'desktop.py', 'oxp3-switch-slot', '49-oxp3-slot-switch.rules', 'oxp3-slot-switch.desktop'):
            self.put('components/slot-switch/' + name, b'# slot switch fixture\n')
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

    def test_decky_missing_pin_cannot_fall_back_to_old_cache(self):
        self.options(['decky'])
        self.put('cache/integration/manifest.json', {})
        self.put('cache/plugins/decky/PluginLoader', b'\x7fELFold')
        with self.assertRaisesRegex(PreparationError, 'Missing pinned Decky'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_decky_changed_source_cannot_enter_signed_payload(self):
        self.options(['decky'])
        self.put('cache/integration/manifest.json', {})
        decky_fixture(self.installer)
        self.put('cache/plugins/decky/source-v3.3.0.zip', b'old source fixture')
        with self.assertRaisesRegex(PreparationError, 'Stale Decky payload'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_old_model_locked_gyro_cannot_enter_maintenance_payload(self):
        self.options(['gyro'])
        self.put('cache/integration/manifest.json', {'gyro': {'files': [{
            'source': 'gyro/module.bin', 'target': 'var/lib/oxp3-gyro-v1/oxp3_bmi260.ko'}]}})
        self.put('cache/integration/gyro/module.bin', b'old model-locked fixture')
        with self.assertRaisesRegex(PreparationError, 'Rebuild the model-independent BMI260'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_stale_cached_gyro_binding_helper_is_rejected_before_output(self):
        self.options(['gyro'])
        self.put('steamos-maintenance/oxp3_maintenance/gyro_binding.py',
                 b'current canonical binding helper\n', workspace=True)
        self.put('cache/integration/manifest.json', {'gyro': {'files': [{
            'source': 'gyro/binding.bin', 'target': 'var/lib/oxp3-gyro-v1/binding.py'}]}})
        self.put('cache/integration/gyro/binding.bin', b'stale cached helper\n')

        with self.assertRaisesRegex(PreparationError, 'Rebuild gyro integration payload from the current binding helper'):
            prepare_payload(self.workspace, self.output)

        self.assertFalse(self.output.exists())

    def test_old_desktop_hdr_runtime_cannot_enter_maintenance_payload(self):
        self.options(['desktop-hdr'])
        self.put('cache/integration/manifest.json', {'desktop-hdr': {
            'files': [], 'runtime_archive': 'desktop-hdr/accepted-runtime.tar'}})
        runtime = self.installer / 'cache/integration/desktop-hdr/accepted-runtime.tar'
        runtime.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(runtime, 'w') as archive:
            for name, data in (
                ('bin/oxp3-mapped-hdr-control', b'OXP3_GAMMA22_POLICY_EDID_ONLY_V2 ONE-NETBOOK'),
                ('lib/libkwin.so.6.7.3', b'OXP3_GAMMA22_POLICY_EDID_ONLY_V2 /sys/class/dmi/id/product_name'),
            ):
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if name.startswith('bin/') else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        with self.assertRaisesRegex(PreparationError, 'EDID-only policy'):
            prepare_payload(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_hdr_trial_sources_refresh_cache_without_claiming_native_build(self):
        self.options(['desktop-hdr'])
        names = ('hdr_trial.py', 'x2mini_device.py', 'install-x2mini-hdr.sh', 'launch.sh')
        files = []
        for name in names:
            files.append({'source': 'desktop-hdr/' + name,
                          'target': 'home/deck/.local/lib/oxp3-desktop-hdr-runtime/' + name,
                          'user': True})
            self.put('cache/integration/desktop-hdr/' + name, b'stale fixture')
            self.put('components/desktop-hdr/' + name, ('current ' + name).encode())
        self.put('cache/integration/manifest.json', {'desktop-hdr': {
            'files': files, 'missing': ['native KWin trial runtime requires rebuild']}})
        report = prepare_payload(self.workspace, self.output)
        for name in names:
            self.assertEqual((self.output / 'integration/desktop-hdr' / name).read_bytes(),
                             ('current ' + name).encode())
            self.assertEqual((self.installer / 'cache/integration/desktop-hdr' / name).read_bytes(),
                             b'stale fixture')
        self.assertEqual(report['coverage']['desktop-hdr']['status'], 'missing')
        self.assertEqual(len(report['refreshed_integration']), 4)

    def test_current_sources_replace_stale_cache_without_mutating_it(self):
        report = prepare_payload(self.workspace, self.output)
        self.assertEqual((self.output / 'integration/opti2xmx/000.bin').read_bytes(), b'current source')
        self.assertEqual((self.installer / 'cache/integration/opti2xmx/000.bin').read_bytes(), b'old source')
        self.assertEqual(len(report['refreshed_integration']), 1)
        record = report['source_inventory']['integration/opti2xmx/000.bin']
        self.assertEqual(record['sha256'], hashlib.sha256(b'current source').hexdigest())
        self.assertEqual(set(report['coverage']), {'opti2xmx', 'refind', 'slot-switch'})
        self.assertEqual(report['coverage']['slot-switch']['status'], 'adapter_supported')
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

    def test_slot_switch_requires_every_current_source_resource(self):
        self.options(['slot-switch'])
        self.put('cache/integration/manifest.json', {})
        (self.installer / 'components/slot-switch/desktop.py').unlink()
        report = prepare_payload(self.workspace, self.output)
        self.assertFalse(report['resource_complete'])
        self.assertEqual(report['coverage']['slot-switch']['status'], 'missing')
        self.assertIn('components/slot-switch/desktop.py', report['coverage']['slot-switch']['missing'])

    def test_oxp3_cpu_targets_map_to_explicit_sources_without_running_generator(self):
        expected = {
            'var/lib/oxp3-cpu/cpu_control.py': 'components/controls/cpu/cpu_control.py',
            'var/lib/oxp3-cpu/power_control.py': 'components/controls/cpu/power_control.py',
            'var/lib/oxp3-cpu/test_cpu_control.py': 'components/controls/cpu/test_cpu_control.py',
            'var/lib/oxp3-cpu/test_power_control.py': 'components/controls/cpu/test_power_control.py',
            'var/lib/oxp3-cpu/gpu_priority.py': 'components/controls/cpu/gpu_priority.py',
            'var/lib/oxp3-cpu/gpu-priority-profile.json': 'components/controls/cpu/gpu-priority-profile.json',
            'var/lib/oxp3-cpu/test_gpu_priority.py': 'components/controls/cpu/test_gpu_priority.py',
            'var/lib/oxp3-cpu/test_cpu_gpu_ui.mjs': 'components/controls/cpu/test_cpu_gpu_ui.mjs',
            'etc/systemd/system/oxp3-gpu-priority.service': 'components/controls/cpu/gpu_priority.service',
            'home/deck/homebrew/plugins/OXP3-CPU/main.py': 'components/controls/cpu/cpu-plugin-main.py',
            'home/deck/homebrew/plugins/OXP3-CPU/dist/index.js': 'components/controls/cpu/cpu-plugin-index.js',
            'var/lib/oxp3-installer/decky/runtime/plugins/OXP3-CPU/main.py': 'components/controls/cpu/cpu-plugin-main.py',
            'var/lib/oxp3-installer/decky/runtime/plugins/OXP3-CPU/dist/index.js': 'components/controls/cpu/cpu-plugin-index.js',
        }
        for target, source in expected.items():
            with self.subTest(target=target):
                self.assertEqual(_current_source('oxp3-cpu', target), source)
        # The existing CPU service stays generated inline by deploy-cpu.py.
        self.assertIsNone(_current_source('oxp3-cpu', 'etc/systemd/system/oxp3-cpu.service'))

    def test_oxp3_gpu_priority_sources_refresh_stale_payload_without_generator(self):
        self.options(['oxp3-cpu'])
        entries = []
        targets = (
            ('var/lib/oxp3-cpu/gpu_priority.py', 'components/controls/cpu/gpu_priority.py', b'current controller'),
            ('var/lib/oxp3-cpu/gpu-priority-profile.json', 'components/controls/cpu/gpu-priority-profile.json', b'{"schema":1}'),
            ('var/lib/oxp3-cpu/test_gpu_priority.py', 'components/controls/cpu/test_gpu_priority.py', b'current test'),
            ('etc/systemd/system/oxp3-gpu-priority.service', 'components/controls/cpu/gpu_priority.service', b'[Unit]\nPartOf=oxp3-cpu.service\n'),
        )
        for index, (target, current, data) in enumerate(targets):
            source = 'oxp3-cpu/%03d.bin' % index
            entries.append({'source': source, 'target': target})
            self.put('cache/integration/' + source, b'stale ' + data)
            self.put(current, data)
        self.put('cache/integration/manifest.json', {'oxp3-cpu': {'files': entries}})
        report = prepare_payload(self.workspace, self.output)
        self.assertTrue(report['resource_complete'])
        self.assertEqual(len(report['refreshed_integration']), len(targets))
        for index, (target, current, data) in enumerate(targets):
            source = 'oxp3-cpu/%03d.bin' % index
            refreshed = self.output / 'integration' / source
            if target.endswith('.json'):
                self.assertEqual(json.loads(refreshed.read_text()), json.loads(data))
            else:
                self.assertEqual(refreshed.read_bytes(), data)
            self.assertEqual((self.installer / 'cache/integration' / source).read_bytes(), b'stale ' + data)

    def test_only_explicit_roots_and_own_plugin_platform_are_collected(self):
        self.options(['opti2xmx', 'decky', 'hltb'])
        self.put('cache/plugins/third-party.json', [{'id': 'hltb', 'version': '2.0.12', 'archive': 'selected.zip'}])
        self.put('cache/plugins/hltb/selected.zip', b'pinned archive')
        self.put('cache/plugins/hltb/old.zip', b'old archive')
        decky_fixture(self.installer, b'ELF fixture')
        self.put('cache/windows.exe', b'Windows')
        self.put('runtime/secret.json', b'private')
        self.put('research/secret.json', b'private', workspace=True)
        report = prepare_payload(self.workspace, self.output)
        paths = set(report['source_inventory'])
        self.assertIn('plugins/decky/PluginLoader', paths)
        self.assertIn('plugins/decky/VERSION', paths)
        self.assertIn('plugins/decky/LICENSE', paths)
        self.assertIn('plugins/decky/source-v3.3.0.zip', paths)
        self.assertIn('plugins/decky/manifest.json', paths)
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
