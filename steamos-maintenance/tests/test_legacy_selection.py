import base64
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import operations as op
from oxp3_maintenance.components import build_plan
from oxp3_maintenance.transactions import Store, TransactionError


class LegacySelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.state = self.root / 'home/.oxp3-maintenance'
        self.store = Store(self.root, self.state, enforce_owner=False)
        self.system = {'slot': {'id': 'current', 'label': 'A'}, 'os': dict(op.probe.BASE),
                       'kernel': op.probe.KERNEL, 'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'},
                       'packages': {}, 'bios': '5.09', 'uid': 1000, 'gid': 1000}
        self.payload = Path(self.temp.name) / 'payload'
        self.release = {'version': '0.2.0'}
        self.engine = {'usr/local/lib/test-maintenance/entry.py': {'data': b'engine', 'mode': 0o644,
                       'component': '_maintenance', 'user': False}}
        self.write(self.root, 'usr/share/applications/org.kde.plasma.keyboard.desktop', b'desktop')
        options = {'schema': 1, 'repairs': [
            {'id': 'input', 'dependencies': []}, {'id': 'keyboard', 'dependencies': []},
            {'id': 'manager', 'dependencies': []}, {'id': 'native-tdp', 'dependencies': ['manager']}], 'plugins': []}
        self.write(self.payload, 'components/options.json', json.dumps(options).encode())
        manifest = {}
        for name in ('input', 'manager', 'native-tdp'):
            self.write(self.payload, 'integration/' + name, b'new-' + name.encode())
            manifest[name] = {'files': [{'source': name, 'target': 'etc/test/' + name}], 'packages': {}, 'units': []}
        self.write(self.payload, 'integration/manifest.json', json.dumps(manifest).encode())

    def write(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def request(self, names):
        self.write(self.root, 'home/.oxp3-installer/integration/A/request.json',
                   json.dumps({'repairs': names, 'plugins': []}).encode())

    def selection(self):
        with mock.patch.object(op, 'STATE', self.state), mock.patch.object(op.adoption, '_trusted'):
            return op.current_selection(self.system, self.store)

    def current(self):
        return self.store.status()['slots']['current']['current']

    def prepare(self, selected, *, tool_only=False, selected_only=False, import_side_effect=None):
        packages = mock.Mock()
        packages._read.return_value = None
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(op, 'STATE', self.state))
            stack.enter_context(mock.patch.object(op, 'PackageStore', return_value=packages))
            stack.enter_context(mock.patch.object(op.probe, 'verify_shared', return_value=True))
            stack.enter_context(mock.patch.object(op.probe, 'verify_shared_os', return_value=True))
            stack.enter_context(mock.patch.object(op.adoption, '_trusted'))
            importer = stack.enter_context(mock.patch.object(op.adoption, 'import_originals', side_effect=import_side_effect, return_value={}))
            stack.enter_context(mock.patch.object(op, 'build_plan', side_effect=lambda payload, root, selected, system, managed: build_plan(payload, self.root, selected, system, managed)))
            plan, originals = op.prepare(self.payload, selected, dict(self.system), self.store,
                                         tool_only=tool_only, selected_only=selected_only)
            return plan, originals, importer.call_args_list

    def apply_plan(self, plan, originals=None):
        return self.store.apply(dict(self.engine, **plan['files']), self.release,
                                plan['selected'] + ['_maintenance'], 'current',
                                adopt=originals, legacy_selected=plan['legacy_selected'])

    def test_first_engine_only_install_preserves_old_request_without_claiming_ownership(self):
        self.request(['input', 'slot-switch'])
        plan, _, imported = self.prepare([], tool_only=True)
        self.assertEqual(plan['legacy_selected'], ['input', 'slot-switch'])
        self.assertEqual(imported, [])
        self.apply_plan(plan)
        self.assertEqual(self.selection(), ['input', 'slot-switch'])
        self.assertEqual(self.current()['selected'], ['_maintenance'])
        self.assertEqual(self.current()['legacy_selected'], ['input', 'slot-switch'])
        self.assertEqual(set(self.store.managed()['components']), {'_maintenance'})

    def test_older_engine_generation_without_field_migrates_once(self):
        self.request(['input'])
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current')
        self.assertNotIn('legacy_selected', self.current())
        self.assertEqual(self.selection(), ['input'])
        plan, _, _ = self.prepare([], tool_only=True)
        self.apply_plan(plan)
        self.assertEqual(self.current()['legacy_selected'], ['input'])
        self.request(['gyro'])
        self.assertEqual(self.selection(), ['input'])

    def test_selected_refresh_removes_only_chosen_and_dependencies_from_legacy(self):
        self.request(['input', 'manager', 'native-tdp'])
        plan, _, _ = self.prepare([], tool_only=True)
        self.apply_plan(plan)
        plan, originals, _ = self.prepare(['native-tdp'], selected_only=True)
        self.assertEqual(plan['selected'], ['manager', 'native-tdp'])
        self.assertEqual(plan['legacy_selected'], ['input'])
        self.apply_plan(plan, originals)
        self.assertEqual(set(self.selection()), {'input', 'manager', 'native-tdp'})
        self.assertNotIn('input', self.store.managed()['components'])
        self.assertIn('manager', self.store.managed()['components'])

    def test_explicit_empty_legacy_selection_never_reloads_stale_request(self):
        self.request(['input'])
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current', legacy_selected=[])
        self.assertEqual(self.selection(), [])

    def test_legacy_selection_validation_and_default_preservation(self):
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current', legacy_selected=['input'])
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current')
        self.assertEqual(self.current()['legacy_selected'], ['input'])
        for choices in (['input', 'input'], ['../escape'], ['_maintenance'], 'input', [3]):
            with self.subTest(choices=choices), self.assertRaises(TransactionError):
                self.store.apply(self.engine, self.release, ['_maintenance'], 'current', legacy_selected=choices)

    def test_rollback_restores_legacy_metadata_without_owning_legacy_files(self):
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current', legacy_selected=['input'])
        self.store.apply(self.engine, self.release, ['_maintenance'], 'current', legacy_selected=[])
        self.store.rollback('current')
        self.assertEqual(self.current()['legacy_selected'], ['input'])
        self.assertNotIn('input', self.store.managed()['components'])

    def test_adopt_restore_reselect_skips_stale_old_installer_journal(self):
        self.request(['input'])
        path = self.write(self.root, 'etc/test/input', b'legacy-installed')
        applied = self.store._read('etc/test/input')
        original = dict(applied, data=base64.b64encode(b'original-image').decode())
        record = {'component': 'input', 'original': original, 'applied': applied}
        files = dict(self.engine, **{'etc/test/input': {'data': b'new-input', 'mode': 0o644,
                     'component': 'input', 'user': False}})
        self.store.apply(files, self.release, ['input', '_maintenance'], 'current',
                         adopt={'etc/test/input': record}, legacy_selected=[])
        self.assertEqual(self.current()['legacy_adopted'], ['input'])
        self.store.restore('current', ['input'])
        self.assertEqual(path.read_bytes(), b'original-image')
        self.assertEqual(self.current()['legacy_adopted'], ['input'])
        self.assertNotIn('input', self.store.managed()['components'])
        self.assertEqual(self.selection(), [])
        plan, originals, calls = self.prepare(['input'], selected_only=True,
            import_side_effect=AssertionError('stale installer journal must not be read'))
        self.assertEqual(calls, [])
        self.assertEqual(plan['components']['input']['status'], 'ready')
        self.apply_plan(plan, originals)
        self.store.restore('current', ['input'])
        self.assertEqual(path.read_bytes(), b'original-image')
        self.assertEqual(self.selection(), [])


if __name__ == '__main__':
    unittest.main()
