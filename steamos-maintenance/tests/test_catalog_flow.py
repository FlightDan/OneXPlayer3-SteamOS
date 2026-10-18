import base64
import copy
import hashlib
import json
from pathlib import Path
from unittest import mock
import unittest

import build_bundle as builder
from oxp3_maintenance import bundle, catalog, downloads, releases, gui, cli
import test_bundle
from test_releases import Response, release


class CatalogFlowTests(unittest.TestCase):
    _openssl_adapter = test_bundle.BundleTests._openssl_adapter

    def setUp(self):
        test_bundle.BundleTests.setUp(self)
        self.archive = self.root / 'oxp3-maintenance-1.2.3-linux-x86_64.tar.gz'
        options = {'schema': 1, 'repairs': [
            {'id': 'keyboard', 'zh': '屏幕键盘', 'en': 'Touch keyboard', 'dependencies': []},
            {'id': 'slot-switch', 'zh': '切换槽位', 'en': 'Slot switch', 'dependencies': []}], 'plugins': []}
        (self.payload / 'components/options.json').write_text(json.dumps(options))
        (self.payload / 'integration').mkdir()
        (self.payload / 'integration/manifest.json').write_text('{}')
        self.manifest = builder.build_bundle(self.payload, self.source, self.key, self.archive, openssl=self.openssl)
        self.value = builder.write_catalog(self.payload, self.manifest, self.archive, self.key, openssl=self.openssl)
        self.raw = (self.root / catalog.names('1.2.3')[0]).read_bytes()
        self.signature = (self.root / catalog.names('1.2.3')[1]).read_bytes()

    def verify(self, raw=None, signature=None, **kwargs):
        return catalog.verify(self.raw if raw is None else raw, self.signature if signature is None else signature,
                              self.public, openssl=self.openssl, **kwargs)

    def test_catalog_round_trip_and_full_bundle_binding(self):
        self.assertEqual(self.verify(expected_version='1.2.3'), self.value)
        self.assertEqual(self.value['bundle']['sha256'], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(downloads._check(self.archive, {'version': '1.2.3'}, self.public, self.value), self.manifest)

    def test_modified_catalog_and_replayed_release_are_rejected(self):
        with self.assertRaises(bundle.BundleError):
            self.verify(self.raw.replace(b'Touch keyboard', b'Evil! keyboard'))
        with self.assertRaisesRegex(bundle.BundleError, 'wrong release'):
            self.verify(expected_version='1.2.4')

    def test_unknown_new_capability_stays_visible_without_adapter(self):
        value = copy.deepcopy(self.value)
        value['components'].append(dict(value['components'][0], id='future-driver', zh='未来', en='Future'))
        host = {'os': {'ID': 'steamos', 'VERSION_ID': '3.8'}, 'kernel': 'other',
                'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}}
        report = catalog.describe(value, host)
        entries = {x['id']: x for x in report['components']}
        self.assertEqual(entries['future-driver']['status'], 'incompatible')
        self.assertEqual(entries['keyboard']['status'], 'requires_preflight')
        self.assertEqual(entries['slot-switch']['status'], 'incompatible')
        self.assertIn('屏幕键盘', gui.catalog_text(report, gui.ZH))
        self.assertIn('Touch keyboard', gui.catalog_text(report, gui.EN))

    def test_signed_catalog_cannot_be_replaced_by_another_valid_same_version_bundle(self):
        self.value['bundle']['sha256'] = '0' * 64
        with self.assertRaisesRegex(bundle.BundleError, 'capability catalog'):
            downloads._check(self.archive, {'version': '1.2.3'}, self.public, self.value)

    def test_save_verifies_and_keeps_offline_bundle_without_installing(self):
        candidate = releases.release_candidates([release('1.2.3')], '0.0.0', 'stable')[0]
        data = self.archive.read_bytes()
        with mock.patch.object(downloads, 'inspect_bundle', side_effect=lambda path, key: bundle.inspect_bundle(path, key, openssl=self.openssl)), \
             mock.patch('oxp3_maintenance.operations.apply', side_effect=AssertionError('download installed system files')):
            output = downloads.save(candidate, self.root / 'downloads', key=self.public,
                                    opener=lambda *a, **kw: Response(data, url=candidate['download_url']))
            self.assertEqual(output['status'], 'downloaded')
            self.assertEqual(Path(output['path']).read_bytes(), data)
            self.assertEqual(downloads.save(candidate, self.root / 'downloads', key=self.public)['status'], 'cached')

    def test_invalid_download_removed_from_user_directory(self):
        candidate = releases.release_candidates([release('1.2.3')], '0.0.0', 'stable')[0]
        destination = self.root / 'downloads'
        with self.assertRaises(bundle.BundleError):
            downloads.save(candidate, destination, key=self.public,
                           opener=lambda *a, **kw: Response(b'bad', url=candidate['download_url']))
        self.assertEqual(list(destination.iterdir()), [])

    def test_latest_windows_release_is_not_reported_as_up_to_date(self):
        values = [release('1.2.3'), release('1.3.0', assets=[])]
        report = releases.check_releases('1.2.3', 'stable', opener=lambda *a, **kw: Response(json.dumps(values).encode()))
        self.assertEqual(report['status'], 'maintenance_package_pending')
        self.assertEqual(report['latest_project']['version'], '1.3.0')
        self.assertEqual(report['latest_maintenance']['version'], '1.2.3')
        self.assertEqual(report['candidates'], [])

    def test_same_version_catalog_can_add_uninstalled_components(self):
        report = releases.check_releases('1.2.3', 'stable', opener=lambda *a, **kw: Response(json.dumps([release('1.2.3')]).encode()))
        self.assertEqual(report['latest_maintenance']['version'], '1.2.3')
        self.assertEqual(report['candidates'], [])

    def test_catalog_asset_version_and_size_limits(self):
        candidate = releases.release_candidates([release('1.2.3')], '0.0.0', 'stable')[0]
        prefix = candidate['download_url'].rsplit('/', 1)[0] + '/oxp3-maintenance-1.2.3-catalog.'
        candidate['catalog_urls'] = {suffix: prefix + suffix for suffix in ('json', 'sig')}
        def opener(request, **kwargs):
            return Response(self.raw if request.full_url.endswith('.json') else self.signature, url=request.full_url)
        self.assertEqual(releases.fetch_catalog(candidate, self.public, opener=opener, openssl=self.openssl), self.value)
        candidate['catalog_urls']['json'] = prefix.replace('1.2.3-catalog', '1.2.4-catalog') + 'json'
        with self.assertRaises(releases.ReleaseError):
            releases.fetch_catalog(candidate, self.public, opener=opener, openssl=self.openssl)


if __name__ == '__main__':
    unittest.main()
