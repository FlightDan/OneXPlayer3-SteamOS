import copy
import gzip
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest import mock

import build_distribution as builder
from oxp3_maintenance import bundle, catalog, distribution
import test_bundle


class DistributionTests(unittest.TestCase):
    setUp = test_bundle.BundleTests.setUp
    _openssl_adapter = test_bundle.BundleTests._openssl_adapter
    _sign = test_bundle.BundleTests._sign

    def _build(self, output='distribution', previous=None, extra_plugins=()):
        # The fixture source stays unexecuted. Bootstrap builder only needs files.
        from build_installer import BOOTSTRAP_FILES
        for name in BOOTSTRAP_FILES:
            (self.source / 'oxp3_maintenance' / name).touch(exist_ok=True)
        options = {'schema': 1, 'repairs': [
            {'id': 'wifi', 'en': 'WiFi', 'zh': 'WiFi', 'default': True, 'dependencies': []},
            {'id': 'opti2xmx', 'en': 'Opti', 'zh': 'Opti', 'default': True, 'dependencies': ['decky']}],
            'plugins': [{'id': 'decky', 'en': 'Decky', 'zh': 'Decky', 'default': True, 'dependencies': []}]}
        options['plugins'].extend(extra_plugins)
        (self.payload / 'components/options.json').write_text(json.dumps(options))
        (self.payload / 'components/common.txt').write_bytes(b'common helper')
        integration = self.payload / 'integration'
        (integration / 'opti2xmx').mkdir(parents=True, exist_ok=True)
        (integration / 'opti2xmx/runtime.tar.gz').write_bytes(b'large-runtime-fixture')
        (integration / 'opti2xmx/000.bin').write_bytes(b'plugin-code')
        (integration / 'wifi').mkdir(exist_ok=True)
        (integration / 'wifi/000.bin').write_bytes(b'firmware')
        (self.payload / 'plugins/decky').mkdir(parents=True, exist_ok=True)
        (self.payload / 'plugins/decky/PluginLoader').write_bytes(b'decky-loader')
        (integration / 'manifest.json').write_text(json.dumps({
            'opti2xmx': {'files': [{'source': 'opti2xmx/000.bin', 'target': 'home/deck/plugin', 'mode': 420}],
                         'runtime_archive': 'opti2xmx/runtime.tar.gz', 'missing': []},
            'wifi': {'files': [{'source': 'wifi/000.bin', 'target': 'lib/firmware/wifi.bin', 'mode': 420}], 'missing': []}}))
        kwargs = {}
        if previous:
            kwargs = {'previous_catalog': previous / 'maintenance/oxp3-maintenance-1.2.3-catalog.json',
                      'previous_signature': previous / 'maintenance/oxp3-maintenance-1.2.3-catalog.sig'}
        return builder.build_distribution(self.payload, self.source, self.key, self.root / output,
                                          openssl=self.openssl, **kwargs)

    def _seed(self, result):
        return Path(result['path']) / result['plan']['core']

    def _opener(self, result, requests):
        def open(request, timeout):
            requests.append(request.full_url)
            name = request.full_url.rsplit('/', 1)[1]
            candidates = list(Path(result['path']).rglob(name))
            self.assertEqual(len(candidates), 1)
            response = io.BytesIO(candidates[0].read_bytes())
            response.geturl = lambda: request.full_url
            return response
        return open

    def test_core_is_legacy_compatible_and_full_metadata_is_available(self):
        result = self._build()
        seed = self._seed(result)
        view = bundle.inspect_bundle(seed, self.public, openssl=self.openssl)
        self.assertEqual(view['schema'], 1)
        self.assertIn(distribution.BRIDGE_MANIFEST, view['files'])
        self.assertNotIn('payload/integration/opti2xmx/runtime.tar.gz', view['files'])
        descriptor = distribution.describe_source(seed, self.public, openssl=self.openssl)
        self.assertEqual(len(descriptor['components']), 4)
        self.assertEqual(descriptor['component_packages']['opti2xmx'], ['core', 'plugin-opti2xmx'])
        self.assertEqual(descriptor['component_packages']['opti2xmx-runtime'], ['core', 'runtime-opti2xmx'])
        runtime = next(item for item in descriptor['components'] if item['id'] == 'opti2xmx-runtime')
        self.assertFalse(runtime['default'])
        self.assertEqual(runtime['dependencies'], ['opti2xmx'])
        self.assertIn('/Opti2XMX/', descriptor['packages']['runtime-opti2xmx']['url'])

    def test_common_repairs_stay_in_core_and_only_large_or_owned_components_split(self):
        for component in ('input', 'fan-driver', 'gamescope-env', 'hdr', 'native-tdp', 'xe-dsb', 'legacy-runtime'):
            for tree in ('integration', 'components'):
                self.assertEqual(builder._group('payload/' + tree + '/' + component + '/000.bin', {component}), ('core', None))
        self.assertEqual(builder._group('payload/integration/wifi/000.bin', {'wifi'}), ('runtime-wifi', 'wifi'))
        self.assertEqual(builder._group('payload/integration/oxp3-fan/000.bin', {'oxp3-fan'}), ('plugin-oxp3-fan', 'oxp3-fan'))

    def test_slot_switch_has_explicit_package_and_never_enters_engine_only_seed(self):
        option = {'id': 'slot-switch', 'en': 'Slot Switch', 'zh': '槽位切换',
                  'default': False, 'dependencies': []}
        directory = self.payload / 'components/slot-switch'
        directory.mkdir(parents=True)
        for name in ('boot.py', 'desktop.py', 'oxp3-switch-slot', '49-oxp3-slot-switch.rules', 'oxp3-slot-switch.desktop'):
            (directory / name).write_bytes(b'fixture ' + name.encode())
        (self.payload / 'components/slot_switch.py').write_bytes(b'installer data only')
        result = self._build('slot-switch-distribution', extra_plugins=[option])
        self.assertEqual(result['catalog']['component_packages']['slot-switch'], ['core', 'repair-slot-switch'])
        item = next(x for x in result['catalog']['components'] if x['id'] == 'slot-switch')
        self.assertEqual(item['delivery'], 'maintenance')
        self.assertTrue(item['available'])
        seed = bundle.inspect_bundle(self._seed(result), self.public, openssl=self.openssl)
        self.assertFalse(any(name.startswith('payload/components/slot-switch/')
                             or name == 'payload/components/slot_switch.py' for name in seed['files']))

    def test_animation_repair_is_optional_core_only_and_tracks_its_adapter_revision(self):
        option = {'id': 'animation-changer-compat', 'en': 'Animation Changer path repair',
                  'zh': 'Animation Changer 路径修复', 'default': False, 'dependencies': []}
        adapter = self.source / 'oxp3_maintenance/animation_changer_compat.py'
        adapter.write_bytes(b'# narrow installed-plugin adapter version one\n')
        first = self._build('animation-first', extra_plugins=[option])
        adapter.write_bytes(b'# narrow installed-plugin adapter version two\n')
        second = self._build('animation-second', extra_plugins=[option])
        first_item = next(x for x in first['catalog']['components'] if x['id'] == option['id'])
        second_item = next(x for x in second['catalog']['components'] if x['id'] == option['id'])
        self.assertFalse(first_item['default'])
        self.assertTrue(first_item['available'])
        self.assertEqual(first['catalog']['component_packages'][option['id']], ['core'])
        self.assertNotEqual(first_item['revision'], second_item['revision'])
        seed = bundle.inspect_bundle(self._seed(first), self.public, openssl=self.openssl)
        self.assertIn('app/oxp3_maintenance/animation_changer_compat.py', seed['files'])
        self.assertFalse(any(name.endswith('.zip') for name in seed['files']))

    def test_dependency_closure_downloads_only_required_groups_and_cache_reuses(self):
        result, requests = self._build(), []
        selected = self.root / 'selected.tar.gz'
        cache = self.root / 'cache'
        actual = distribution.materialize(self._seed(result), ['opti2xmx-runtime'], selected, self.public,
            catalog=result['catalog'], cache=cache, opener=self._opener(result, requests), openssl=self.openssl)
        self.assertEqual(actual['packages'], ['core', 'plugin-opti2xmx', 'runtime-decky', 'runtime-opti2xmx'])
        self.assertEqual(len(requests), 3)
        manifest = bundle.inspect_bundle(selected, self.public, openssl=self.openssl)
        self.assertEqual(manifest['schema'], 2)
        self.assertNotIn('payload/integration/wifi/000.bin', manifest['files'])
        self.assertIn('payload/integration/wifi/000.bin', manifest['signed_files'])
        self.assertEqual(bundle.manifest_digest(manifest), result['catalog']['distribution_manifest_digest'])
        distribution.materialize(self._seed(result), ['opti2xmx-runtime'], self.root / 'cached.tar.gz', self.public,
            cache=cache, opener=lambda *a, **kw: self.fail('network used for cached asset'), openssl=self.openssl)
        self.assertEqual(selected.read_bytes(), (self.root / 'cached.tar.gz').read_bytes())
        private = self.root / 'private'
        private.mkdir(mode=0o700)
        self.assertEqual(bundle.verify_bundle(selected, self.public, private, openssl=self.openssl)['files'], manifest['files'])

    def test_plugin_selection_never_downloads_optional_xmx_runtime(self):
        result, requests = self._build(), []
        actual = distribution.materialize(self._seed(result), ['opti2xmx'], self.root / 'plugin-only.tar.gz',
            self.public, opener=self._opener(result, requests), openssl=self.openssl)
        self.assertEqual(actual['packages'], ['core', 'plugin-opti2xmx', 'runtime-decky'])
        self.assertEqual(len(requests), 2)
        self.assertNotIn('payload/integration/opti2xmx/runtime.tar.gz', actual['manifest']['files'])
        ref = result['catalog']['packages']['runtime-opti2xmx']['raw_asset']
        self.assertTrue(distribution.runtime_asset_url(ref['url']))
        self.assertTrue((Path(result['path']) / 'opti2xmx' / ref['name']).is_file())

    def test_corrupt_cache_and_catalog_mismatch_fail_closed(self):
        result = self._build()
        cache = self.root / 'cache'
        cache.mkdir()
        ref = result['catalog']['packages']['runtime-wifi']
        (cache / (ref['sha256'] + '.tar.gz')).write_bytes(b'bad')
        output = self.root / 'bad-selected.tar.gz'
        with self.assertRaisesRegex(bundle.BundleError, 'corrupt'):
            distribution.materialize(self._seed(result), ['wifi'], output, self.public, cache=cache, openssl=self.openssl)
        self.assertFalse(output.exists())
        index = copy.deepcopy(result['catalog'])
        index['components'][0]['en'] = 'changed'
        with self.assertRaisesRegex(bundle.BundleError, 'does not match'):
            distribution.materialize(self._seed(result), [], output, self.public, catalog=index, openssl=self.openssl)

    def test_previous_signed_index_reuses_exact_immutable_assets(self):
        first = self._build('first')
        second = self._build('second', Path(first['path']))
        self.assertEqual(second['plan']['built_packages'], [])
        self.assertEqual(set(second['plan']['reused_packages']), set(first['catalog']['packages']))
        self.assertEqual(second['catalog']['packages'], first['catalog']['packages'])
        self.assertFalse(list((Path(second['path']) / 'opti2xmx').glob('*.tar.gz')))

    def test_component_revisions_ignore_tool_changes_and_core_only_requires_no_download(self):
        first = self._build('first')
        (self.source / 'oxp3_maintenance/tool.py').write_bytes(b'new maintenance implementation')
        second = self._build('second', Path(first['path']))
        first_revisions = {item['id']: item['revision'] for item in first['catalog']['components']}
        second_revisions = {item['id']: item['revision'] for item in second['catalog']['components']}
        self.assertEqual(first_revisions, second_revisions)
        self.assertNotEqual(first['catalog']['bundle']['sha256'], second['catalog']['bundle']['sha256'])
        actual = distribution.materialize(self._seed(second), [], self.root / 'core-only.tar.gz', self.public,
            opener=lambda *a, **kw: self.fail('core-only selection used network'), openssl=self.openssl)
        self.assertEqual(actual['packages'], ['core'])
        annotated = dict(actual['manifest'], _review_digest='caller-provided review annotation')
        self.assertEqual(distribution.index_from_manifest(annotated)['distribution_manifest_digest'],
                         second['catalog']['distribution_manifest_digest'])

    def test_component_adapter_changes_invalidate_receipts_without_reuploading_runtime(self):
        adapter = self.source / 'oxp3_maintenance/components.py'
        adapter.write_bytes(b'original generated units')
        first = self._build('first')
        adapter.write_bytes(b'changed generated units')
        second = self._build('second', Path(first['path']))
        for before, after in zip(first['catalog']['components'], second['catalog']['components']):
            self.assertNotEqual(before['revision'], after['revision'])
        self.assertEqual(first['catalog']['packages'], second['catalog']['packages'])
        self.assertEqual(second['plan']['built_packages'], [])

    def test_unknown_selection_and_oversized_download_rejected(self):
        result = self._build()
        for selected in (['unknown-component'], [False]):
            with self.assertRaises(bundle.BundleError):
                distribution.materialize(self._seed(result), selected, self.root / 'rejected.tar.gz',
                    self.public, opener=lambda *a, **kw: self.fail('invalid selection used network'), openssl=self.openssl)
        ref = result['catalog']['packages']['runtime-wifi']
        oversized = io.BytesIO(b'x' * (ref['size'] + 1))
        oversized.geturl = lambda: ref['url']
        target = self.root / 'oversized.tar.gz'
        with self.assertRaisesRegex(bundle.BundleError, 'signed size'):
            distribution._download(ref, target, opener=lambda *a, **kw: oversized)
        self.assertFalse(target.exists())

    def test_partial_group_and_bad_membership_rejected(self):
        result = self._build()
        manifest = copy.deepcopy(result['manifest'])
        # Two files in one group permits a genuine partial-group test.
        core_name = 'payload/components/common.txt'
        manifest['packages']['core']['files'].remove(core_name)
        manifest['packages']['runtime-wifi']['files'].append(core_name)
        # Keep index file binding consistent, then sign this intentionally bad archive.
        records = {name: manifest['files'][name] for name in manifest['packages']['runtime-wifi']['files']}
        manifest['package_refs']['runtime-wifi']['files_digest'] = distribution.files_digest(records)
        raw = catalog.canonical(manifest)
        sig = self._sign(raw)
        extracted = self.root / 'extracted'
        extracted.mkdir(mode=0o700)
        bundle.verify_bundle(self._seed(result), self.public, extracted, openssl=self.openssl)
        (extracted / 'payload/integration/wifi').mkdir(parents=True, exist_ok=True)
        (extracted / 'payload/integration/wifi/000.bin').write_bytes(b'firmware')
        present = {name: manifest['files'][name] for name in manifest['packages']['core']['files']}
        present['payload/integration/wifi/000.bin'] = manifest['files']['payload/integration/wifi/000.bin']
        bad = self.root / 'partial.tar.gz'
        distribution._write_archive(bad, extracted, present, raw, sig)
        with self.assertRaisesRegex(bundle.BundleError, 'partial'):
            bundle.inspect_bundle(bad, self.public, openssl=self.openssl)

    def test_cycles_missing_dependencies_and_untrusted_origins_rejected(self):
        result = self._build()
        index = copy.deepcopy(result['catalog'])
        index['components'][0]['dependencies'] = [index['components'][0]['id']]
        with self.assertRaises(bundle.BundleError):
            distribution.validate_index(index)
        for url in ('http://github.com/FlightDan/Opti2XMX/releases/download/v1/a.tar.gz',
                    'https://github.com/attacker/Opti2XMX/releases/download/v1/a.tar.gz',
                    'https://github.com/FlightDan/Opti2XMX/releases/download/latest/oxp3-package-x-0123456789abcdef.tar.gz'):
            self.assertFalse(distribution.asset_url(url))


if __name__ == '__main__':
    unittest.main()
