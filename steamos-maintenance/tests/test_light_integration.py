"""Light payload, capability, ordering and transaction integration without hardware."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest

from prepare_payload import prepare_payload
from decky_fixture import decky_fixture
from oxp3_maintenance import catalog, compatibility
from oxp3_maintenance.components import build_plan, PLUGIN_ROOT
from oxp3_maintenance.decky_order import SETTINGS, PRIORITY, ordered_settings
from oxp3_maintenance.transactions import Store, TransactionError


class LightIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / 'workspace'
        self.installer = self.workspace / 'windows-installer'
        self.payload, self.root = self.base / 'payload', self.base / 'root'
        self.root.mkdir()
        self.put(self.workspace, 'LICENSE', b'project license')
        self.put(self.installer, 'components/release.json', {'schema': 1, 'version': '0.1.3', 'display_version': '0.1.3', 'channel': 'stable'})
        self.options = {'schema': 1, 'repairs': [{'id': 'oxp3-light', 'default': True, 'dependencies': ['decky']}],
                        'plugins': [{'id': 'decky', 'dependencies': []}]}
        self.put(self.installer, 'components/options.json', self.options)
        decky_fixture(self.installer)
        self.names = ('main.py', 'light_control.py', 'plugin.json', 'package.json', 'dist/index.js',
                      'LICENSE', 'LICENSE-HHD', 'LICENSE-HueSync', 'THIRD_PARTY_NOTICES.md', 'README.md')
        manifest = {'oxp3-light': {'files': [], 'units': [], 'packages': {}, 'missing': []}}
        for index, name in enumerate(self.names):
            data = (json.dumps({'name': 'OXP3 Light'}).encode() if name.endswith('.json')
                    else b'current ' + name.encode())
            self.put(self.installer, 'components/light/' + name, data)
            source = 'oxp3-light/' + str(index) + '.bin'
            self.put(self.installer, 'cache/integration/' + source, b'stale')
            manifest['oxp3-light']['files'].append({'source': source,
                'target': 'home/deck/homebrew/plugins/OXP3-Light/' + name, 'user': True})
        self.put(self.installer, 'cache/integration/manifest.json', manifest)
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'dmi': dict(compatibility.DEVICE), 'uid': 1000, 'gid': 1000, 'shared_compatible': True}

    def put(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(data).encode() if isinstance(data, (dict, list)) else data)
        return path

    def prepare(self):
        return prepare_payload(self.workspace, self.payload)

    def test_preparation_refreshes_light_with_licenses_and_catalog_advertises_it(self):
        self.put(self.installer, 'components/light/test_backend.py', b'test only')
        self.put(self.installer, 'components/light/__pycache__/backend.pyc', b'cache')
        report = self.prepare()
        self.assertTrue(report['resource_complete'])
        self.assertEqual(report['coverage']['oxp3-light']['status'], 'adapter_supported')
        self.assertEqual(len(report['refreshed_integration']), len(self.names))
        for name in self.names:
            self.assertTrue((self.payload / 'components/light' / name).is_file())
        self.assertFalse((self.payload / 'components/light/test_backend.py').exists())
        self.assertFalse((self.payload / 'components/light/__pycache__').exists())
        archive = self.put(self.base, 'bundle.tar.gz', b'archive fixture')
        value = catalog.create(self.payload, {'release': {'version': '0.1.3'}}, archive)
        light = next(x for x in value['components'] if x['id'] == 'oxp3-light')
        self.assertTrue(light['available'])
        self.assertTrue(light['default'])
        self.assertEqual(light['dependencies'], ['decky'])

    def test_exact_baseline_and_missing_native_led_do_not_broaden_adapter(self):
        self.prepare()
        plan = build_plan(self.payload, self.root, ['oxp3-light'], self.system)
        self.assertEqual(plan['selected'], ['decky', 'oxp3-light'])
        self.assertEqual(plan['components']['oxp3-light']['status'], 'ready')
        self.assertEqual(plan['components']['oxp3-light']['units'], [])
        for name in self.names:
            spec = plan['files'][PLUGIN_ROOT + '/OXP3-Light/' + name]
            self.assertFalse(spec['user'])
            self.assertEqual(spec['component'], 'oxp3-light')
        self.system['kernel'] = 'other-kernel'
        self.assertFalse(compatibility.evaluate('oxp3-light', self.system)['supported'])
        self.assertEqual(build_plan(self.payload, self.root, ['oxp3-light'], self.system)['files'], {})

    def test_custom_order_changes_once_and_transaction_rolls_back_light_and_order(self):
        self.prepare()
        original = {'pluginOrder': ['Custom', 'OXP3 Battery', 'OXP3 CPU'], 'sortPlugins': False, 'language': 'zh-CN'}
        loader = self.put(self.root, SETTINGS, original)
        before = loader.read_bytes()
        store = Store(self.root, self.base / 'state', uid=getattr(os, 'getuid', lambda: 0)(),
                      gid=getattr(os, 'getgid', lambda: 0)(), enforce_owner=False)
        store.apply({'etc/baseline': {'data': b'before', 'component': 'keyboard'}}, {'version': '0'}, ['keyboard'], 'A')
        plan = build_plan(self.payload, self.root, ['oxp3-light'], self.system)
        expected = ['Custom', 'OXP3 Battery', 'OXP3 Light', 'OXP3 CPU']
        self.assertEqual(json.loads(plan['files'][SETTINGS]['data'])['pluginOrder'], expected)
        self.assertEqual(loader.read_bytes(), before)  # Planning is read-only.
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        repeated = build_plan(self.payload, self.root, ['oxp3-light'], self.system, store.managed())
        self.assertEqual(json.loads(repeated['files'][SETTINGS]['data'])['pluginOrder'], expected)
        self.assertEqual(json.loads(loader.read_bytes())['pluginOrder'].count('OXP3 Light'), 1)
        store.rollback('A')
        self.assertEqual(loader.read_bytes(), before)
        self.assertFalse((self.root / PLUGIN_ROOT / 'OXP3-Light/main.py').exists())

    def test_new_install_order_includes_all_prospective_plugin_names(self):
        self.prepare()
        for index, name in enumerate(reversed(PRIORITY)):
            if name != 'OXP3 Light':
                self.put(self.root, PLUGIN_ROOT + '/' + str(index) + '/plugin.json', {'name': name})
        plan = build_plan(self.payload, self.root, ['oxp3-light'], self.system)
        self.assertEqual(json.loads(plan['files'][SETTINGS]['data'])['pluginOrder'], list(PRIORITY))

    def test_light_generator_is_explicit_and_recursive_without_running_whole_build(self):
        script = Path(__file__).resolve().parents[2] / 'windows-installer/scripts/prepare-integration.py'
        tree = ast.parse(script.read_text(encoding='utf-8'))
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in ('plugin_files', 'light_plugin_files')]
        self.assertEqual(len(selected), 2)
        scope = {}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(script), 'exec'), scope)
        self.put(self.installer, 'components/light/test_unwanted.py', b'test')
        self.put(self.installer, 'components/light/__pycache__/cached.pyc', b'cache')
        files = scope['light_plugin_files'](self.installer / 'components/light')
        self.assertEqual(set(files), {'/home/deck/homebrew/plugins/OXP3-Light/' + name for name in self.names})

    def test_installer_and_maintenance_order_policies_match_without_linux_imports(self):
        installer = Path(__file__).resolve().parents[2] / 'windows-installer/components'
        tree = ast.parse((installer / 'decky_order.py').read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'ordered_settings']
        scope = {'PRIORITY': PRIORITY}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'decky_order.py', 'exec'), scope)
        choices = ({}, {'pluginOrder': []}, {'sortPlugins': True}, {'sortPlugins': False},
                   {'pluginOrder': ['Custom', 'OXP3 Battery', 'OXP3 CPU'], 'language': 'zh-CN'},
                   {'pluginOrder': ['OXP3 Battery'], 'sortPlugins': True},
                   {'pluginOrder': ['OXP3 Light', 'OXP3 Battery']}, {'pluginOrder': 'unknown'})
        for settings in choices:
            for names in (list(PRIORITY), ['OXP3 CPU'], ['Custom']):
                with self.subTest(settings=settings, names=names):
                    self.assertEqual(scope['ordered_settings'](settings, names), ordered_settings(settings, names))
        options = json.loads((installer / 'options.json').read_text(encoding='utf-8'))
        light = next(x for x in options['repairs'] if x['id'] == 'oxp3-light')
        self.assertTrue(light['default'])
        self.assertEqual(light['dependencies'], ['decky'])

    def managed_custom_settings(self):
        self.prepare()
        store = Store(self.root, self.base / 'state', enforce_owner=False)
        seeded = {'pluginOrder': ['OXP3 CPU', 'OXP3 Battery'], 'sortPlugins': False}
        store.apply({SETTINGS: {'data': json.dumps(seeded).encode(), 'component': 'decky',
                               'mutable': True}}, {'version': '0'}, ['decky'], 'A')
        custom = {'pluginOrder': ['Custom', 'OXP3 Battery', 'OXP3 CPU'], 'sortPlugins': False,
                  'language': 'zh-CN', 'hiddenPlugins': ['Private'], 'extra': {'nested': [1, 2]}}
        raw = (json.dumps(custom, ensure_ascii=False) + '\n').encode()
        self.put(self.root, SETTINGS, raw)
        plan = build_plan(self.payload, self.root, ['oxp3-light'], self.system, store.managed())
        return store, custom, raw, plan

    def test_user_edited_managed_order_inserts_light_and_rollback_restores_custom_before(self):
        store, custom, raw, plan = self.managed_custom_settings()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        loader = self.root / SETTINGS
        expected = dict(custom, pluginOrder=['Custom', 'OXP3 Battery', 'OXP3 Light', 'OXP3 CPU'])
        self.assertEqual(json.loads(loader.read_bytes()), expected)
        self.assertNotIn(SETTINGS, store._index()['slots']['A']['current'].get('adoption_before', {}))
        self.assertNotIn('decky_order_edit', json.dumps(store.status()))
        self.assertNotIn('decky_order_edit', json.dumps(store.managed()))
        store.rollback('A')
        self.assertEqual(loader.read_bytes(), raw)
        store.rollback('A')
        self.assertEqual(json.loads(loader.read_bytes()), expected)
        store.restore('A', ['decky', 'oxp3-light'])
        self.assertEqual(loader.read_bytes(), raw)

    def test_managed_insertion_rejects_other_setting_changes_before_writes(self):
        store, custom, raw, plan = self.managed_custom_settings()
        value = json.loads(plan['files'][SETTINGS]['data'])
        value['language'] = 'changed'
        plan['files'][SETTINGS]['data'] = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        before = store._index()
        with self.assertRaisesRegex(TransactionError, 'other preferences'):
            store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        self.assertEqual(store._index(), before)
        self.assertEqual((self.root / SETTINGS).read_bytes(), raw)
        self.assertFalse((self.root / PLUGIN_ROOT / 'OXP3-Light/main.py').exists())

    def test_later_user_edits_survive_insertion_rollback_and_restore(self):
        store, custom, raw, plan = self.managed_custom_settings()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        later = b'{"pluginOrder":["Custom","OXP3 Light"],"language":"ja-JP"}\n'
        self.put(self.root, SETTINGS, later)
        store.rollback('A')
        self.assertEqual((self.root / SETTINGS).read_bytes(), later)
        store.restore('A', ['decky'])
        self.assertEqual((self.root / SETTINGS).read_bytes(), later)

    def test_insertion_provenance_survives_later_updates_and_a_second_custom_order(self):
        store, custom, raw, plan = self.managed_custom_settings()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        store.apply({'etc/unrelated': {'data': b'update', 'component': 'keyboard'}},
                    {'version': '2'}, ['keyboard'], 'A')
        store.rollback('A')
        self.assertIn('OXP3 Light', json.loads((self.root / SETTINGS).read_bytes())['pluginOrder'])
        later = b'{"pluginOrder":["Second","OXP3 Battery"],"sortPlugins":false,"language":"ko-KR"}\n'
        self.put(self.root, SETTINGS, later)
        updated = build_plan(self.payload, self.root, ['oxp3-light'], self.system, store.managed())
        store.apply(updated['files'], {'version': '3'}, updated['selected'], 'A')
        self.assertEqual(json.loads((self.root / SETTINGS).read_bytes())['pluginOrder'], ['Second', 'OXP3 Battery', 'OXP3 Light'])
        store.rollback('A')
        self.assertEqual((self.root / SETTINGS).read_bytes(), later)
        store.rollback('A')
        store.restore('A', ['decky', 'oxp3-light'])
        self.assertEqual((self.root / SETTINGS).read_bytes(), later)

    def test_distinct_insertion_provenance_with_later_edits_keeps_rollback_recoverable(self):
        store, custom, raw, plan = self.managed_custom_settings()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        second = b'{"pluginOrder":["Second","OXP3 Battery"],"sortPlugins":false}\n'
        self.put(self.root, SETTINGS, second)
        updated = build_plan(self.payload, self.root, ['oxp3-light'], self.system, store.managed())
        store.apply(updated['files'], {'version': '2'}, updated['selected'], 'A')
        third = b'{"pluginOrder":["Third","OXP3 Light","OXP3 Battery"],"language":"ja-JP"}\n'
        self.put(self.root, SETTINGS, third)
        store.rollback('A')
        self.assertEqual((self.root / SETTINGS).read_bytes(), third)
        self.assertIsNone(store.status()['pending'])
        store.rollback('A')
        self.assertEqual((self.root / SETTINGS).read_bytes(), third)
        store.restore('A', ['decky', 'oxp3-light'])
        self.assertEqual((self.root / SETTINGS).read_bytes(), third)

    def test_invalid_insertion_metadata_rejects_commit_before_queuing_pending(self):
        store, custom, raw, plan = self.managed_custom_settings()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        import copy
        before = store._index()
        index_bytes = (store.state / 'index.json').read_bytes()
        invalid = copy.deepcopy(before['slots']['A']['current'])
        invalid['decky_order_edit']['after'] = invalid['decky_order_edit']['before']
        with self.assertRaisesRegex(TransactionError, 'Invalid Decky insertion'):
            store._commit(copy.deepcopy(before), 'A', invalid, [])
        self.assertEqual(store._index(), before)
        self.assertEqual((store.state / 'index.json').read_bytes(), index_bytes)
        self.assertFalse((store.state / 'pending.json').exists())
        self.assertIsNone(store.status()['pending'])


if __name__ == '__main__':
    unittest.main()
