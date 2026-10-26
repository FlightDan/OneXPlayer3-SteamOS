"""LSFG plugin-only maintenance delivery without executing upstream code."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import runpy
import stat
from types import SimpleNamespace
from unittest import mock
import zipfile

from build_distribution import _group
from prepare_payload import PreparationError, prepare_payload
from decky_fixture import decky_fixture
from oxp3_maintenance import catalog, compatibility
from oxp3_maintenance.components import build_plan, PLUGIN_ROOT, _empty_plugin_tree
from oxp3_maintenance.transactions import Store
from oxp3_maintenance import bundle, distribution
import test_bundle
import test_distribution


class LsfgIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / 'workspace'
        self.installer = self.workspace / 'windows-installer'
        self.payload, self.root = self.base / 'payload', self.base / 'root'
        self.root.mkdir()
        self.put(self.workspace, 'LICENSE', b'project license')
        self.put(self.installer, 'components/release.json', {
            'schema': 1, 'version': '0.1.4', 'display_version': '0.1.4', 'channel': 'stable'})
        self.options = {'schema': 1, 'repairs': [], 'plugins': [
            {'id': 'decky', 'en': 'Decky', 'zh': 'Decky', 'default': True, 'dependencies': []},
            {'id': 'lsfg-vk', 'en': 'LSFG-VK: install the layer in Decky on first use',
             'zh': 'LSFG-VK：首次使用在 Decky 安装运行层', 'default': False,
             'dependencies': ['decky']}]}
        self.put(self.installer, 'components/options.json', self.options)
        decky_fixture(self.installer)
        self.plugin = PLUGIN_ROOT + '/Decky LSFG-VK/'
        # Deliberate JSON whitespace checks the integration bin remains exact.
        self.files = {
            'plugin.json': b'{ "name": "Decky LSFG-VK", "flags": [] }\n',
            'package.json': b'',
            'main.py': b'# upstream fixture: must never execute\n',
            'dist/index.js': b'// frontend fixture\n',
            'bin/lsfg-vk-2.0.0.tar.xz': b'offline runtime archive fixture',
            'LICENSE': b'upstream license',
            'README.md': b'First use: Install LSFG-VK in Decky. Supply your own licensed DLL.\n',
            'py_modules/lsfg_vk/installation.py': b'# upstream installation fixture\n',
        }
        runtime_member = 'bin/lsfg-vk-2.0.0.tar.xz'
        runtime_sha = hashlib.sha256(self.files[runtime_member]).hexdigest()
        self.files['package.json'] = json.dumps({
            'name': 'decky-lsfg-vk', 'version': '0.14.4', 'remote_binary': [{
                'name': 'lsfg-vk-2.0.0.tar.xz', 'sha256hash': runtime_sha}]}).encode()
        # Match the upstream release's complete 27-file membership.
        for number in range(27 - len(self.files)):
            self.files['py_modules/lsfg_vk/fixture_%02d.py' % number] = b'# fixture module\n'
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr('Decky LSFG-VK/' + name, data)
        archive_data = archive_buffer.getvalue()
        self.pin = {
            'schema': 1, 'id': 'lsfg-vk', 'name': 'Decky LSFG-VK', 'version': '0.14.4',
            'folder': 'Decky LSFG-VK', 'deployment': 'plugin-only-with-bundled-runtime',
            'release_url': 'https://example.invalid/fixture-release',
            'archive': {'filename': 'decky-lsfg-vk-0.14.4.zip', 'bytes': len(archive_data),
                        'sha256': hashlib.sha256(archive_data).hexdigest()},
            'runtime': {'member': runtime_member, 'version': '2.0.0', 'sha256': runtime_sha},
        }
        self.put(self.installer, 'components/lsfg-vk-release.json', self.pin)
        self.put(self.installer, 'cache/lsfg-vk/' + self.pin['archive']['filename'], archive_data)
        helper_source = Path(__file__).resolve().parents[2] / 'windows-installer/scripts/lsfg_payload.py'
        helper_path = self.put(self.installer, 'scripts/lsfg_payload.py', helper_source.read_bytes())
        helper = runpy.run_path(str(helper_path))
        self.put(self.installer, 'cache/lsfg-vk/manifest.json', helper['cache_manifest'](self.pin, self.files))
        self.entries = []
        for index, (name, data) in enumerate(self.files.items()):
            source = 'lsfg-vk/%03d.bin' % index
            self.put(self.installer, 'cache/integration/' + source, data)
            self.entries.append({'source': source, 'target': self.plugin + name,
                                 'mode': 0o644, 'user': False})
        self.manifest = {'lsfg-vk': {'files': self.entries, 'units': [],
                                     'packages': {}, 'missing': []}}
        self.put(self.installer, 'cache/integration/manifest.json', self.manifest)
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'uid': 1000, 'gid': 1000, 'shared_compatible': True}

    def put(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(data).encode() if isinstance(data, (dict, list)) else data)
        return path

    def prepare(self):
        return prepare_payload(self.workspace, self.payload)

    def plan(self, managed=None):
        return build_plan(self.payload, self.root, ['lsfg-vk'], self.system, managed)

    def test_preparation_and_catalog_preserve_optional_plugin_and_offline_bytes(self):
        report = self.prepare()
        self.assertTrue(report['resource_complete'])
        self.assertEqual(report['coverage']['lsfg-vk']['status'], 'adapter_supported')
        for entry, data in zip(self.entries, self.files.values()):
            self.assertEqual((self.payload / 'integration' / entry['source']).read_bytes(), data)
        self.assertEqual(json.loads((self.payload / 'components/lsfg-vk-release.json').read_bytes()), self.pin)
        archive = self.put(self.base, 'bundle.tar.gz', b'catalog fixture')
        index = catalog.create(self.payload, {'release': {'version': '0.1.4'}}, archive)
        item = next(x for x in index['components'] if x['id'] == 'lsfg-vk')
        self.assertTrue(item['available'])
        self.assertFalse(item['default'])
        self.assertEqual(item['dependencies'], ['decky'])

    def test_plan_only_installs_plugin_tree_and_expands_decky_dependency(self):
        self.prepare()
        plan = self.plan()
        self.assertEqual(plan['selected'], ['decky', 'lsfg-vk'])
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'ready')
        self.assertEqual(plan['components']['lsfg-vk']['units'], [])
        deployed = {path: spec for path, spec in plan['files'].items()
                    if spec['component'] == 'lsfg-vk'}
        self.assertEqual(set(deployed), {self.plugin + name for name in self.files})
        self.assertTrue(all(not spec['user'] for spec in deployed.values()))
        self.assertFalse(any(path.startswith('home/deck/') for path in deployed))
        self.assertFalse(any(self.root.rglob('main.py')))  # Planning has no writes.

    def test_other_system_baseline_is_blocked(self):
        self.prepare()
        self.system['kernel'] = 'unreviewed-kernel'
        plan = self.plan()
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'blocked')
        self.assertEqual(plan['files'], {})

    def test_existing_unmanaged_plugin_is_preserved_and_blocked(self):
        self.prepare()
        existing = self.put(self.root, self.plugin + 'main.py', b'custom existing plugin')
        plan = self.plan()
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'blocked')
        self.assertIn('Unmanaged plugin', plan['components']['lsfg-vk']['reason'])
        self.assertEqual(existing.read_bytes(), b'custom existing plugin')

    def restored_store(self):
        self.prepare()
        store = Store(self.root, self.base / 'state',
                      uid=getattr(os, 'getuid', lambda: 0)(),
                      gid=getattr(os, 'getgid', lambda: 0)(), enforce_owner=False)
        plan = self.plan()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        store.restore('A', ['lsfg-vk'])
        plugin = self.root / self.plugin
        self.assertTrue(plugin.is_dir())
        self.assertTrue(all(path.is_dir() for path in plugin.rglob('*')))
        return store

    def test_restore_then_reinstall_reuses_retained_empty_directories(self):
        store = self.restored_store()
        plan = self.plan(store.managed())
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'ready', plan['components']['lsfg-vk'])
        store.apply(plan['files'], {'version': '2'}, plan['selected'], 'A')
        for name, data in self.files.items():
            self.assertEqual((self.root / self.plugin / name).read_bytes(), data)

    def test_restored_tree_with_unknown_empty_file_is_not_reused(self):
        store = self.restored_store()
        occupied = self.put(self.root, self.plugin + 'dist/assets/unknown', b'')
        plan = self.plan(store.managed())
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'blocked')
        self.assertIn('Unmanaged plugin directory conflict', plan['components']['lsfg-vk']['reason'])
        self.assertTrue(occupied.is_file())

    def test_restored_tree_with_nested_directory_link_is_not_reused(self):
        store = self.restored_store()
        outside = self.base / 'outside'
        outside.mkdir()
        link = self.root / self.plugin / 'dist/assets'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Directory symlinks unavailable: ' + str(exc))
        plan = self.plan(store.managed())
        self.assertEqual(plan['components']['lsfg-vk']['status'], 'blocked')
        self.assertIn('Unmanaged plugin directory conflict', plan['components']['lsfg-vk']['reason'])
        self.assertTrue(link.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    def test_empty_tree_requires_root_owned_nonwritable_directories(self):
        def directory(mode=0o755, uid=0, children=(), reparse=0):
            return SimpleNamespace(
                lstat=lambda: SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid,
                                               st_file_attributes=reparse),
                iterdir=lambda: iter(children))
        with mock.patch('oxp3_maintenance.components.os', SimpleNamespace(name='posix')):
            self.assertTrue(_empty_plugin_tree(directory(children=[directory()])))
            for child in (directory(uid=1000), directory(mode=0o775),
                          directory(mode=0o757), directory(reparse=0x400)):
                self.assertFalse(_empty_plugin_tree(directory(children=[child])))
            link = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFLNK | 0o755,
                                                                  st_uid=0, st_file_attributes=0))
            self.assertFalse(_empty_plugin_tree(directory(children=[link])))

    def test_missing_manifest_is_rejected_before_preparation(self):
        self.put(self.installer, 'cache/integration/manifest.json', {})
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_changed_integration_bytes_are_rejected_before_preparation(self):
        self.put(self.installer, 'cache/integration/' + self.entries[0]['source'], b'corrupted plugin')
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_changed_official_archive_is_rejected_before_preparation(self):
        self.put(self.installer, 'cache/lsfg-vk/' + self.pin['archive']['filename'], b'changed archive')
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_changed_cache_manifest_is_rejected_before_preparation(self):
        self.put(self.installer, 'cache/lsfg-vk/manifest.json', {})
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_user_configuration_target_is_rejected_before_preparation(self):
        self.entries[0].update(target='home/deck/.config/lsfg-vk/conf.toml', user=True)
        self.put(self.installer, 'cache/integration/manifest.json', self.manifest)
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_user_owned_plugin_code_is_rejected_before_preparation(self):
        self.entries[0]['user'] = True
        self.put(self.installer, 'cache/integration/manifest.json', self.manifest)
        with self.assertRaisesRegex(PreparationError, 'Rebuild LSFG-VK integration'):
            self.prepare()
        self.assertFalse(self.payload.exists())

    def test_restore_and_rollback_leave_user_layer_config_and_dll_untouched(self):
        self.prepare()
        user_files = {
            'home/deck/.local/lib/liblsfg-vk.so': b'user-owned layer',
            'home/deck/.config/lsfg-vk/conf.toml': b'user game configuration',
            'home/deck/.local/share/lsfg-vk/Lossless.dll': b'user supplied licensed DLL',
        }
        for path, data in user_files.items():
            self.put(self.root, path, data)
        store = Store(self.root, self.base / 'state',
                      uid=getattr(os, 'getuid', lambda: 0)(),
                      gid=getattr(os, 'getgid', lambda: 0)(), enforce_owner=False)
        store.apply({'etc/baseline': {'data': b'before', 'component': 'keyboard'}},
                    {'version': '0'}, ['keyboard'], 'A')
        plan = self.plan()
        store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A')
        self.assertTrue((self.root / (self.plugin + 'main.py')).exists())
        repeated = self.plan(store.managed())
        self.assertEqual(repeated['components']['lsfg-vk']['status'], 'ready')
        store.rollback('A')
        self.assertFalse((self.root / (self.plugin + 'main.py')).exists())
        for path, data in user_files.items():
            self.assertEqual((self.root / path).read_bytes(), data)
        store.rollback('A')
        store.restore('A', ['lsfg-vk'])
        self.assertFalse((self.root / (self.plugin + 'main.py')).exists())
        self.assertTrue((self.root / 'var/lib/oxp3-installer/decky/runtime/services/PluginLoader').exists())
        for path, data in user_files.items():
            self.assertEqual((self.root / path).read_bytes(), data)

    def test_offline_plugin_resources_and_pin_are_outside_core(self):
        ids = {'decky', 'lsfg-vk'}
        for name in ('payload/components/lsfg-vk-release.json',
                     'payload/licenses/lsfg-vk-LICENSE',
                     'payload/integration/lsfg-vk/004.bin'):
            self.assertEqual(_group(name, ids), ('plugin-lsfg-vk', 'lsfg-vk'))
        self.assertEqual(_group('payload/components/options.json', ids), ('core', None))


class LsfgDistributionTests(unittest.TestCase):
    setUp = test_bundle.BundleTests.setUp
    _openssl_adapter = test_bundle.BundleTests._openssl_adapter
    _sign = test_bundle.BundleTests._sign
    _build = test_distribution.DistributionTests._build
    _seed = test_distribution.DistributionTests._seed
    _opener = test_distribution.DistributionTests._opener

    def test_signed_seed_downloads_lsfg_and_decky_without_unselected_components(self):
        pin = self.payload / 'components/lsfg-vk-release.json'
        pin.write_text(json.dumps({'schema': 1, 'version': '0.14.4'}))
        code = self.payload / 'integration/lsfg-vk/000.bin'
        code.parent.mkdir(parents=True)
        code.write_bytes(b'upstream plugin with embedded offline archive fixture')
        result = self._build('lsfg-distribution', extra_plugins=[{
            'id': 'lsfg-vk', 'en': 'LSFG-VK', 'zh': 'LSFG-VK',
            'default': False, 'dependencies': ['decky']}])
        seed = self._seed(result)
        descriptor = distribution.describe_source(seed, self.public, openssl=self.openssl)
        item = next(x for x in descriptor['components'] if x['id'] == 'lsfg-vk')
        self.assertFalse(item['default'])
        self.assertEqual(item['dependencies'], ['decky'])
        self.assertEqual(descriptor['component_packages']['lsfg-vk'], ['core', 'plugin-lsfg-vk'])
        seed_view = bundle.inspect_bundle(seed, self.public, openssl=self.openssl)
        self.assertNotIn('payload/integration/lsfg-vk/000.bin', seed_view['files'])
        self.assertNotIn('payload/components/lsfg-vk-release.json', seed_view['files'])
        requests = []
        output = self.root / 'lsfg-selected.tar.gz'
        distribution.materialize(seed, ['lsfg-vk'], output, self.public,
                                 opener=self._opener(result, requests), openssl=self.openssl)
        view = bundle.inspect_bundle(output, self.public, openssl=self.openssl)
        self.assertEqual(set(view['present_packages']), {'core', 'plugin-lsfg-vk', 'runtime-decky'})
        self.assertIn('payload/components/lsfg-vk-release.json', view['files'])
        self.assertIn('payload/integration/lsfg-vk/000.bin', view['files'])
        self.assertEqual(len(requests), 2)


if __name__ == '__main__':
    unittest.main()
