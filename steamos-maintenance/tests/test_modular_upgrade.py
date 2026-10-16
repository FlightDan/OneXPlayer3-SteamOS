import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import build_distribution
from oxp3_maintenance import bundle, cli, distribution, operations, releases, update_state
from oxp3_maintenance.desktop_service import DesktopService
import test_distribution
from test_releases import release


class ModularUpgradeTests(unittest.TestCase):
    setUp = test_distribution.DistributionTests.setUp
    _openssl_adapter = test_distribution.DistributionTests._openssl_adapter
    _sign = test_distribution.DistributionTests._sign
    _build = test_distribution.DistributionTests._build
    _seed = test_distribution.DistributionTests._seed

    def test_one_changed_plugin_release_still_upgrades_old_client_with_all_dependencies(self):
        # First full index; next release uploads only changed plugin bytes.
        first = self._build('first')
        (self.payload / 'components/release.json').write_text(json.dumps({
            'version': '1.2.4', 'display_version': '1.2.4', 'channel': 'stable'}))
        (self.payload / 'integration/opti2xmx/000.bin').write_bytes(b'new-plugin-code')
        second = build_distribution.build_distribution(self.payload, self.source, self.key, self.root / 'second',
            previous_catalog=Path(first['path']) / 'maintenance/oxp3-maintenance-1.2.3-catalog.json',
            previous_signature=Path(first['path']) / 'maintenance/oxp3-maintenance-1.2.3-catalog.sig', openssl=self.openssl)
        self.assertEqual(second['plan']['built_packages'], ['plugin-opti2xmx'])
        self.assertEqual(second['catalog']['packages']['runtime-opti2xmx'], first['catalog']['packages']['runtime-opti2xmx'])
        requests = []
        def opener(request, timeout):
            requests.append(request.full_url)
            name = request.full_url.rsplit('/', 1)[1]
            candidates = list((self.root / 'second').rglob(name)) + list((self.root / 'first').rglob(name))
            self.assertTrue(candidates)
            response = io.BytesIO(candidates[0].read_bytes())
            response.geturl = lambda: request.full_url
            return response
        selected = distribution.materialize(self._seed(second), ['wifi', 'opti2xmx-runtime'], self.root / 'old-client.tar.gz',
            self.public, opener=opener, openssl=self.openssl)
        self.assertEqual(len(requests), 4)
        self.assertEqual(set(selected['packages']), {'core', 'runtime-wifi', 'runtime-decky', 'plugin-opti2xmx', 'runtime-opti2xmx'})
        self.assertEqual(selected['manifest']['release']['version'], '1.2.4')
        operations.require_plan_packages(selected['manifest'], {'selected': ['wifi', 'opti2xmx', 'opti2xmx-runtime', 'decky']})
        old = {'version': '0.1.1'}
        self.assertTrue(all(state is None for state in update_state.component_states(second['catalog'], old, 'A').values()))
        prior_receipts = update_state.revisions(first['catalog'])
        existing = {'version': '1.2.4', 'component_revisions_by_slot': {'A': prior_receipts}}
        with mock.patch.object(update_state, '_receipt_matches', return_value=True):
            states = update_state.component_states(second['catalog'], existing, 'A')
        self.assertIs(states['wifi'], True)
        self.assertIs(states['decky'], True)
        self.assertIsNone(states['opti2xmx'])
        # A restored component has no receipt, even when old release metadata
        # remains. Do not hide it as an already installed/current repair.
        self.assertIsNone(update_state.component_states(second['catalog'], existing, 'A')['wifi'])
        self.assertTrue(all(state is None for state in update_state.component_states(second['catalog'], existing, 'B').values()))

    def test_missing_selected_package_is_rejected_even_if_core_verifies(self):
        built = self._build()
        sparse = distribution.materialize(self._seed(built), [], self.root / 'core-only.tar.gz',
                                         self.public, openssl=self.openssl)
        operations.require_plan_packages(sparse['manifest'], {'selected': []})
        with self.assertRaisesRegex(RuntimeError, 'package is missing'):
            operations.require_plan_packages(sparse['manifest'], {'selected': ['opti2xmx']})

    def test_core_seed_and_new_installer_modules_are_present(self):
        from build_installer import BOOTSTRAP_FILES
        self.assertIn('distribution.py', BOOTSTRAP_FILES)
        built = self._build()
        seed = bundle.inspect_bundle(self._seed(built), self.public, openssl=self.openssl)
        with self.assertRaisesRegex(RuntimeError, 'Download selected'):
            operations.require_plan_packages(seed, {'selected': ['wifi']})
        operations.require_plan_packages(seed, {'selected': []})


class ModularControllerTests(unittest.TestCase):
    def test_receipt_is_component_owned_and_restore_removes_it(self):
        from oxp3_maintenance.transactions import Store
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'
            root.mkdir()
            app = Path(directory) / 'app'
            app.mkdir()
            (app / 'entry.py').write_text('pass\n')
            (app / 'OXP3-Maintenance.desktop').write_text('[Desktop Entry]\n')
            runtime = root / 'usr/local/lib/oxp3-maintenance'
            plan = {'selected': ['wifi', 'gm7-resume'], 'revision_slot': 'A',
                    'component_revisions': {'wifi': 'a' * 64, 'gm7-resume': 'b' * 64},
                    'components': {'wifi': {'status': 'ready'}, 'gm7-resume': {'status': 'not_applicable'}}}
            with mock.patch.object(operations, 'RUNTIME', runtime):
                files = operations.runtime_files(app, {'version': '0.1.4'}, plan)
            receipt = 'usr/local/lib/oxp3-maintenance/component-receipts/A/wifi.json'
            self.assertEqual(files[receipt]['component'], 'wifi')
            self.assertFalse(any('gm7-resume.json' in name for name in files))
            state = json.loads(files['usr/local/lib/oxp3-maintenance/current-release.json']['data'])
            self.assertEqual(state['component_revisions_by_slot']['A'], {'wifi': 'a' * 64})
            store = Store(root, Path(directory) / 'state', uid=1000, gid=1000, enforce_owner=False)
            store.apply({receipt: files[receipt]}, {'version': '0.1.4'}, ['wifi'], 'A')
            with mock.patch('oxp3_maintenance.bootstrap._protected'):
                self.assertTrue(update_state._receipt_matches('wifi', 'a' * 64, 'A', runtime))
                store.restore('A', ['wifi'])
                self.assertFalse(update_state._receipt_matches('wifi', 'a' * 64, 'A', runtime))

    def test_legacy_engine_requires_review_before_any_component_write(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(Path, 'home', return_value=Path(directory)), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '0.1.1'}):
            service = DesktopService(SimpleNamespace(bundle='/seed.tar.gz', bundle_dir=None))
            plan = {'release': {'version': '0.1.5'}, 'manifest_digest': 'digest', 'components': {},
                    'selected': [], 'can_apply': True, 'file_count': 4, 'catalog': {}}
            applied = {'status': 'files_installed', 'operation': {'changed': True}}
            final_plan = dict(plan, selected=['wifi'], manifest_digest='selected-digest')
            with mock.patch.object(service, '_distribution', return_value={'schema': 2}), \
                 mock.patch.object(update_state, 'needs_engine_bridge', side_effect=[True, False]), \
                 mock.patch.object(bundle, 'inspect_bundle', return_value={'schema': 1}), \
                 mock.patch.object(service, '_materialize') as materialize, \
                 mock.patch.object(service, '_backend', side_effect=[plan, applied, final_plan]) as backend, \
                 mock.patch('oxp3_maintenance.gui._after_install'):
                first_review = service.perform('plan', selected=['wifi'])
                self.assertIn('First upgrade', first_review['message'])
                materialize.assert_not_called()
                backend.assert_called_once_with('plan', [], tool_only=True)
                next_review = service.perform('apply')
                self.assertTrue(next_review['review'])
                self.assertEqual(service.review['selected'], ['wifi'])
                self.assertEqual(backend.call_args_list[1].args, ('apply', []))
                self.assertTrue(backend.call_args_list[1].kwargs['tool_only'])
                self.assertEqual(backend.call_args_list[2].args, ('plan', ['wifi']))
                materialize.assert_called_once()

    def test_independent_tag_is_discovered_without_latest_and_legacy_tags_remain_supported(self):
        value = release('0.1.5')
        value['tag_name'] = 'maintenance-v0.1.5'
        for asset in value['assets']:
            asset['browser_download_url'] = asset['browser_download_url'].replace('/v0.1.5/', '/maintenance-v0.1.5/')
        candidates = releases.release_candidates([value, release('0.1.3')], '0.1.1', 'stable')
        self.assertEqual([candidate['version'] for candidate in candidates], ['0.1.5', '0.1.3'])
