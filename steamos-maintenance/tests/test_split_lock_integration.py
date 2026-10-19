"""Boot repairs compose in one file transaction, with explicit joint restoration."""
import ast
import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from prepare_payload import prepare_payload
from oxp3_maintenance import adoption, compatibility, operations
from oxp3_maintenance.components import build_plan
from oxp3_maintenance.desktop_service import DesktopService
from oxp3_maintenance.split_lock import GRUB, DROPIN, DROPIN_DATA, patch_grub
from oxp3_maintenance.transactions import Store, TransactionError


class SplitLockIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace, self.payload, self.root = (self.base / name for name in ('workspace', 'payload', 'root'))
        self.root.mkdir()
        self.installer = self.workspace / 'windows-installer'
        self.options = {'schema': 1, 'repairs': [
            {'id': 'gm7-resume', 'dependencies': [], 'default': True},
            {'id': 'split-lock', 'dependencies': [], 'default': True}], 'plugins': []}
        self.put(self.installer, 'components/options.json', self.options)
        self.put(self.installer, 'components/release.json', {'schema': 1, 'version': '0.1.3', 'display_version': '0.1.3', 'channel': 'stable'})
        self.put(self.installer, 'cache/integration/manifest.json', {'gm7-resume': {'files': []}})
        source = Path(__file__).resolve().parents[2] / 'windows-installer/components/split-lock/UPSTREAM_LICENSE'
        self.license = source.read_bytes()
        self.put(self.installer, 'components/split-lock/UPSTREAM_LICENSE', self.license)
        self.put(self.workspace, 'LICENSE', b'project license')
        self.original = b'# preserve\nsteamenv_boot /boot/vmlinuz-linux quiet root=UUID=keep\nlinuxefi /boot/vmlinuz-linux-fallback loglevel=3\n'
        self.put(self.root, GRUB, self.original)
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'dmi': dict(compatibility.DEVICE), 'uid': 1000, 'gid': 1000,
                       'target_disk': {'bus': 'NVMe', 'model': 'Predator GM7 2TB'}}
        self.store = Store(self.root, self.base / 'state', enforce_owner=False)

    def put(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(data).encode() if isinstance(data, (dict, list)) else data)
        return path

    def prepare(self):
        return prepare_payload(self.workspace, self.payload)

    def plan(self, selected):
        result = build_plan(self.payload, self.root, selected, self.system, self.store.managed())
        for name in selected:
            self.assertEqual(result['components'][name]['status'], 'ready', result['components'][name])
        # NTFS fixture modes do not model the target's protected Linux EFI file.
        if os.name != 'posix' and GRUB in result['files']:
            result['files'][GRUB]['mode'] = 0o644
        return result

    def apply(self, plan, version):
        return self.store.apply(plan['files'], {'version': version}, plan['selected'], 'A')

    def test_special_payload_stages_full_upstream_license_and_no_generator_execution(self):
        self.put(self.installer, 'components/split_lock.py', b'raise AssertionError("do not execute")\n')
        report = self.prepare()
        self.assertTrue(report['resource_complete'])
        self.assertEqual(report['coverage']['split-lock']['status'], 'adapter_supported')
        self.assertEqual((self.payload / 'components/split-lock/UPSTREAM_LICENSE').read_bytes(), self.license)
        plan = self.plan(['split-lock'])
        self.assertEqual(plan['files']['usr/share/licenses/oxp3-split-lock/UPSTREAM_LICENSE']['data'], self.license)
        self.assertTrue(plan['components']['split-lock']['restart_required'])
        self.assertEqual((self.root / GRUB).read_bytes(), self.original)

    def test_split_only_apply_repeat_and_restore(self):
        self.prepare()
        plan = self.plan(['split-lock'])
        expected = plan['files'][GRUB]['data']
        self.assertIn(b'root=UUID=keep', expected)
        self.assertEqual(expected.count(b'split_lock_detect=off'), 2)
        self.apply(plan, '1')
        repeated = self.plan(['split-lock'])
        self.assertEqual(repeated['files'][GRUB]['data'], expected)
        self.assertFalse(self.apply(repeated, '1')['changed'])
        self.store.restore('A', ['split-lock'])
        self.assertEqual((self.root / GRUB).read_bytes(), self.original)
        self.assertFalse((self.root / DROPIN).exists())

    def test_both_selection_orders_compose_once_preserve_owner_and_reject_partial_restore(self):
        self.prepare()
        for first, second in (('gm7-resume', 'split-lock'), ('split-lock', 'gm7-resume')):
            with self.subTest(first=first):
                initial = self.plan([first])
                self.apply(initial, '1')
                first_bytes = (self.root / GRUB).read_bytes()
                second_plan = self.plan([second])
                self.assertEqual(second_plan['files'][GRUB]['component'], first)
                self.assertEqual(second_plan['restore_groups'][0]['components'], ['gm7-resume', 'split-lock'])
                self.apply(second_plan, '2')
                both_bytes = (self.root / GRUB).read_bytes()
                self.assertEqual(both_bytes.count(b'split_lock_detect=off'), 2)
                self.assertEqual(both_bytes.count(b'nvme.noacpi=1'), 2)
                self.assertIn(b'root=UUID=keep', both_bytes)
                before = self.store._index()
                for selected in ([first], [second]):
                    with self.assertRaisesRegex(TransactionError, 'explicitly select both'):
                        self.store.restore('A', selected)
                    self.assertEqual(self.store._index(), before)
                    self.assertEqual((self.root / GRUB).read_bytes(), both_bytes)
                    self.assertIsNone(self.store.status()['pending'])
                self.store.rollback('A')
                self.assertEqual((self.root / GRUB).read_bytes(), first_bytes)
                # Reapply the second repair, then restore both explicitly.
                self.apply(self.plan([second]), '2')
                self.store.restore('A', ['gm7-resume', 'split-lock'])
                self.assertEqual((self.root / GRUB).read_bytes(), self.original)
                self.assertFalse((self.root / DROPIN).exists())
                self.assertFalse((self.root / 'etc/default/grub.d/oxp3-nvme.cfg').exists())

    def test_simultaneous_plan_composes_both_orders_without_duplicate_options(self):
        self.prepare()
        for selected in (['gm7-resume', 'split-lock'], ['split-lock', 'gm7-resume']):
            plan = self.plan(selected)
            expected = plan['files'][GRUB]['data']
            self.assertEqual(expected.count(b'nvme.noacpi=1'), 2)
            self.assertEqual(expected.count(b'split_lock_detect=off'), 2)
            self.assertEqual(plan['components']['split-lock']['restore_with'], ['gm7-resume', 'split-lock'])

    def test_explicit_joint_restore_keeps_nvme_option_that_existed_before_project(self):
        self.prepare()
        original = self.original.replace(b' quiet ', b' quiet nvme.noacpi=1 ')
        self.put(self.root, GRUB, original)
        self.apply(self.plan(['gm7-resume', 'split-lock']), '1')
        self.store.restore('A', ['split-lock', 'gm7-resume'])
        self.assertEqual((self.root / GRUB).read_bytes(), original)

    def test_conflicts_unsupported_boots_and_baselines_fail_closed(self):
        self.prepare()
        for data in (b'not a supported boot entry\n', b'linux /boot/vmlinuz-linux split_lock_detect=warn\n',
                     b'linux /boot/vmlinuz-linux split_lock_detect=off split_lock_detect=off\n',
                     b'linux /boot/vmlinuz-linux quiet # keep\n'):
            self.put(self.root, GRUB, data)
            plan = build_plan(self.payload, self.root, ['split-lock'], self.system)
            self.assertEqual(plan['components']['split-lock']['status'], 'blocked')
            self.assertEqual(plan['files'], {})
        self.put(self.root, GRUB, self.original)
        self.put(self.root, DROPIN, b'user customization')
        self.assertIn('drop-in differs', build_plan(self.payload, self.root, ['split-lock'], self.system)['components']['split-lock']['reason'])
        self.system['kernel'] = 'newer-kernel'
        self.assertFalse(compatibility.evaluate('split-lock', self.system)['supported'])

    def test_external_managed_boot_edit_rejects_new_option_before_any_write(self):
        self.prepare()
        self.apply(self.plan(['gm7-resume']), '1')
        edited = (self.root / GRUB).read_bytes().replace(b'quiet', b'quiet user_option=keep')
        self.put(self.root, GRUB, edited)
        plan = self.plan(['split-lock'])
        before = self.store._index()
        with self.assertRaisesRegex(TransactionError, 'changed externally'):
            self.apply(plan, '2')
        self.assertEqual(self.store._index(), before)
        self.assertEqual((self.root / GRUB).read_bytes(), edited)
        self.assertFalse((self.root / DROPIN).exists())

    def test_public_plan_and_touch_review_explain_joint_restore(self):
        self.prepare()
        plan = self.plan(['split-lock', 'gm7-resume'])
        self.system['slot'] = {'id': 'A'}
        summary = operations.summarize(plan, {'version': '1'}, self.system)
        self.assertEqual(summary['restore_groups'], plan['restore_groups'])
        with patch.object(Path, 'home', return_value=self.base), patch('oxp3_maintenance.cli.installed_release', return_value={'channel': 'stable'}):
            service = DesktopService(SimpleNamespace(bundle='fixture', bundle_dir=None))
        summary['catalog'] = self.options
        view = service._plan_view(summary, review=True)
        self.assertIn(('Restore together', '2 items'), view['facts'])
        self.assertEqual({item['id'] for item in view['items']}, {'gm7-resume', 'split-lock'})

    def test_live_orchestrator_rejects_partial_restore_before_any_commands(self):
        self.prepare()
        self.apply(self.plan(['gm7-resume', 'split-lock']), '1')
        runtime = self.base / 'runtime'
        self.put(runtime, 'activation.json', {'components': {name: {'units': []} for name in ('gm7-resume', 'split-lock')}})
        self.system['slot'] = {'id': 'A'}
        before = self.store._index()
        with patch.object(operations, 'require_root'), patch.object(operations, 'trusted_code'), \
             patch.object(operations.probe, 'live', return_value=self.system), \
             patch.object(operations, 'store_for', return_value=self.store), \
             patch.object(operations, 'RUNTIME', runtime), patch.object(operations, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'explicitly select both'):
                operations.restore(SimpleNamespace(select=['split-lock']))
        command.assert_not_called()
        self.assertEqual(self.store._index(), before)

    def test_missing_license_blocks_resources_and_boot_allowlist_remains_narrow(self):
        (self.installer / 'components/split-lock/UPSTREAM_LICENSE').unlink()
        report = self.prepare()
        self.assertEqual(report['coverage']['split-lock']['status'], 'missing')
        self.assertIn('components/split-lock/UPSTREAM_LICENSE', report['coverage']['split-lock']['missing'])
        self.assertEqual(Store._path(DROPIN), DROPIN)
        for path in ('etc/default/grub', DROPIN + '.custom', 'etc/default/grub.d/custom.cfg'):
            with self.assertRaisesRegex(TransactionError, 'Protected boot'):
                Store._path(path)

    def test_installer_single_owner_journals_adopt_and_restore_true_original(self):
        self.prepare()
        initial = self.plan(['gm7-resume', 'split-lock'])
        originals = {path: self.store._read(path) for path in initial['files']}
        journals = {}
        for path, entry in initial['files'].items():
            self.put(self.root, path, entry['data'])
            actual = self.store._read(path)
            journal = journals.setdefault(entry['component'], {'phase': 'installed', 'allowed': [],
                'original': {}, 'applied': {}, 'metadata': {}})
            journal['allowed'].append(path)
            journal['original'][path] = originals[path]
            journal['applied'][path] = base64.b64encode(entry['data']).decode()
            journal['metadata'][path] = {'mode': actual['mode'], 'user': False}
        self.assertIn(GRUB, journals['gm7-resume']['allowed'])
        self.assertNotIn(GRUB, journals['split-lock']['allowed'])
        for name, journal in journals.items():
            self.put(self.root, 'home/.oxp3-installer/integration/A/' + name + '/state.json', journal)
        self.system['slot'] = {'id': 'A', 'label': 'A'}
        # Only protected owner/mode checks are mocked for native Windows fixtures;
        # parsing, before-images, current-byte checks and adoption are real.
        with patch.object(adoption, '_trusted'):
            adopted = adoption.import_originals(self.root, self.system, ['gm7-resume', 'split-lock'])
            adoption.validate_current(self.root, adopted, self.system)
        owned = {'paths': {path: {'component': record['component']} for path, record in adopted.items()}}
        plan = build_plan(self.payload, self.root, ['gm7-resume', 'split-lock'], self.system, owned)
        self.assertTrue(all(item['status'] == 'ready' for item in plan['components'].values()))
        if os.name != 'posix':
            plan['files'][GRUB]['mode'] = 0o644
        self.store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A', adopt=adopted)
        with self.assertRaisesRegex(TransactionError, 'explicitly select both'):
            self.store.restore('A', ['split-lock'])
        self.store.restore('A', ['gm7-resume', 'split-lock'])
        self.assertEqual((self.root / GRUB).read_bytes(), self.original)
        self.assertFalse((self.root / DROPIN).exists())

    def test_first_adoption_user_edited_gm7_boot_refuses_new_split_before_writes(self):
        self.prepare()
        installed = self.original.replace(b' quiet ', b' quiet nvme.noacpi=1 ')
        current = installed.replace(b'quiet', b'quiet user_option=keep')
        self.put(self.root, GRUB, current)
        applied = self.store._read(GRUB)
        baseline = dict(applied, data=base64.b64encode(installed).decode())
        original = dict(applied, data=base64.b64encode(self.original).decode())
        adopted = {GRUB: {'component': 'gm7-resume', 'original': original,
                         'applied': applied, 'baseline': baseline, 'preserve': True}}
        plan = build_plan(self.payload, self.root, ['gm7-resume', 'split-lock'], self.system,
                          {'paths': {GRUB: {'component': 'gm7-resume'}}})
        if os.name != 'posix':
            plan['files'][GRUB]['mode'] = 0o644
        self.assertTrue(all(item['status'] == 'ready' for item in plan['components'].values()))
        before = self.store._index()
        with self.assertRaisesRegex(TransactionError, 'Adopted Valve boot settings changed externally'):
            self.store.apply(plan['files'], {'version': '1'}, plan['selected'], 'A', adopt=adopted)
        self.assertEqual(self.store._index(), before)
        self.assertEqual((self.root / GRUB).read_bytes(), current)
        self.assertFalse((self.root / DROPIN).exists())

    def test_trusted_transformation_matches_installer_without_importing_its_code(self):
        source = Path(__file__).resolve().parents[2] / 'windows-installer/components/split_lock.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'patch_grub']
        import re
        scope = {'re': re}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        for text in (self.original.decode(), self.original.decode().replace('\n', '\r\n'),
                     'linux /boot/vmlinuz-linux split_lock_detect=off nvme.noacpi=1\n'):
            self.assertEqual(scope['patch_grub'](text), patch_grub(text))
        self.assertEqual(DROPIN_DATA, ast.literal_eval(next(node.value for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'DROPIN_DATA' for target in node.targets))))
        options = json.loads((source.parent / 'options.json').read_text(encoding='utf-8'))
        selected = next(item for item in options['repairs'] if item['id'] == 'split-lock')
        self.assertTrue(selected['default'])
        self.assertEqual(selected['dependencies'], [])


if __name__ == '__main__':
    unittest.main()
