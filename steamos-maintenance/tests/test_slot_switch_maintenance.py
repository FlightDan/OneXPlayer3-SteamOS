"""Slot Switch maintenance is a fixed file transaction, never a boot operation."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import adoption, catalog, compatibility, operations
from oxp3_maintenance.components import build_plan
from oxp3_maintenance.transactions import Store, TransactionError


class SlotSwitchMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.payload = self.base / 'root', self.base / 'payload'
        self.root.mkdir()
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'dmi': dict(compatibility.DEVICE), 'uid': 1000, 'gid': 1000,
                       'slot': {'id': 'slot-A', 'label': 'A'}, 'shared_compatible': True,
                       'shared_os_compatible': True, 'packages': {}}
        self.options = {'schema': 1, 'repairs': [{'id': 'slot-switch', 'dependencies': [],
                        'zh': '槽位切换', 'en': 'Slot Switch', 'default': True}], 'plugins': []}
        self.write(self.payload, 'components/options.json', json.dumps(self.options).encode())
        self.write(self.payload, 'integration/manifest.json', b'{}')
        for name in ('boot.py', 'desktop.py', 'oxp3-switch-slot', '49-oxp3-slot-switch.rules', 'oxp3-slot-switch.desktop'):
            self.write(self.payload, 'components/slot-switch/' + name, b'new ' + name.encode())
        for name in ('python3', 'pkexec', 'kdialog', 'steamos-bootconf', 'systemctl', 'busctl'):
            self.write(self.root, 'usr/bin/' + name, b'# fixture, never executed').chmod(0o755)
        self.store = Store(self.root, self.base / 'state', uid=1000, gid=1000, enforce_owner=False)

    def write(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def plan(self, managed=None):
        with mock.patch('subprocess.run', side_effect=AssertionError('maintenance invoked a boot/service command')):
            return build_plan(self.payload, self.root, ['slot-switch'], self.system, managed)

    def ready(self, managed=None):
        plan = self.plan(managed)
        self.assertEqual(plan['components']['slot-switch']['status'], 'ready', plan)
        self.assertEqual(plan['components']['slot-switch']['units'], [])
        self.assertFalse(plan['components']['slot-switch']['restart_required'])
        self.assertEqual(len(plan['files']), 6)
        return plan

    def seed(self):
        files = {path: dict(entry, data=b'old ' + path.encode()) for path, entry in self.ready()['files'].items()}
        self.store.apply(files, {'version': '0.1.3'}, ['slot-switch'], 'slot-A')
        return files

    def test_fixed_plan_is_read_only_and_does_not_touch_boot_or_updates(self):
        plan = self.ready()
        self.assertFalse((self.root / 'home').exists())
        for path, entry in plan['files'].items():
            self.assertNotIn('SteamOS/conf', path)
            self.assertNotIn('atomupd', path)
            self.assertNotIn('rauc', path)
            self.assertEqual(entry['user'], path.startswith('home/deck/'))
        self.assertEqual(plan['files']['home/.oxp3-slot-switch/oxp3-switch-slot']['mode'], 0o755)

    def test_update_and_rollback_preserve_all_previous_bytes(self):
        before = self.seed()
        plan = self.ready(self.store.managed())
        self.store.apply(plan['files'], {'version': '0.1.4'}, ['slot-switch'], 'slot-A')
        for path, entry in plan['files'].items():
            self.assertEqual((self.root / path).read_bytes(), entry['data'])
        self.store.rollback('slot-A')
        for path, entry in before.items():
            self.assertEqual((self.root / path).read_bytes(), entry['data'])
        self.assertIsNone(self.store.status()['pending'])

    def test_interrupted_update_recovers_and_can_roll_back_all_files(self):
        before = self.seed()
        plan = self.ready(self.store.managed())
        def interrupted(path):
            raise RuntimeError('simulated power loss')
        with mock.patch.object(self.store, '_after_write', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'simulated power loss'):
                self.store.apply(plan['files'], {'version': '0.1.4'}, ['slot-switch'], 'slot-A')
        self.assertIsNotNone(self.store.status()['pending'])
        fresh = Store(self.root, self.base / 'state', uid=1000, gid=1000, enforce_owner=False)
        fresh.recover('slot-A')
        for path, entry in plan['files'].items():
            self.assertEqual((self.root / path).read_bytes(), entry['data'])
        fresh.rollback('slot-A')
        for path, entry in before.items():
            self.assertEqual((self.root / path).read_bytes(), entry['data'])
        self.assertIsNone(fresh.status()['pending'])

    def test_legacy_adoption_uses_existing_authenticated_snapshots(self):
        files = self.ready()['files']
        originals = {}
        for path, entry in files.items():
            self.write(self.root, path, b'legacy ' + path.encode()).chmod(entry['mode'])
            originals[path] = {'component': 'slot-switch', 'original': {'exists': False},
                               'applied': self.store._read(path, user=entry['user'])}
        managed = {'paths': {path: {'component': 'slot-switch'} for path in files}}
        plan = self.ready(managed)
        self.store.apply(plan['files'], {'version': '0.1.4'}, ['slot-switch'], 'slot-A', adopt=originals)
        self.store.restore('slot-A', ['slot-switch'])
        self.assertTrue(all(not (self.root / path).exists() for path in files))

    def legacy_journal_plan(self, *, drift=False):
        """Use real installer journal layout and readers inside an isolated root."""
        files = self.ready()['files']
        groups = {'A': {}, 'shared': {}}
        for path, entry in files.items():
            target = self.write(self.root, path, b'legacy ' + path.encode())
            target.chmod(entry['mode'])
            os.chown(target, 1000 if entry['user'] else 0, 1000 if entry['user'] else 0)
            groups['shared' if path.startswith('home/') else 'A'][path] = entry
        for group, entries in groups.items():
            snapshots = {path: self.store._read(path, user=entry['user']) for path, entry in entries.items()}
            record = {'phase': 'installed', 'allowed': list(entries),
                      'original': {path: {'exists': False} for path in entries},
                      'applied': {path: snapshot['data'] for path, snapshot in snapshots.items()},
                      'metadata': {path: {key: entry[key] for key in ('mode', 'user')} for path, entry in entries.items()}}
            self.write(self.root, 'home/.oxp3-installer/integration/' + group + '/slot-switch/state.json',
                       json.dumps(record).encode())
        self.write(self.root, 'home/.oxp3-installer/integration/A/request.json',
                   b'{"repairs":["slot-switch"],"plugins":[]}')
        if drift:
            self.write(self.root, 'home/.oxp3-slot-switch/boot.py', b'unknown legacy modification')
        packages = mock.Mock()
        packages._read.return_value = None
        import_originals, validate_current = adoption.import_originals, adoption.validate_current
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(operations, 'STATE', self.root / 'home/.oxp3-maintenance'))
            stack.enter_context(mock.patch.object(operations, 'PackageStore', return_value=packages))
            stack.enter_context(mock.patch.object(operations.probe, 'verify_shared', return_value=True))
            stack.enter_context(mock.patch.object(operations.probe, 'verify_shared_os', return_value=True))
            importer = stack.enter_context(mock.patch.object(adoption, 'import_originals', side_effect=lambda root, system, names:
                import_originals(self.root, system, names)))
            validator = stack.enter_context(mock.patch.object(adoption, 'validate_current', side_effect=lambda root, originals, system:
                validate_current(self.root, originals, system)))
            stack.enter_context(mock.patch.object(operations, 'build_plan', side_effect=lambda payload, root, selected, system, managed:
                build_plan(payload, self.root, selected, system, managed)))
            plan, originals = operations.prepare(self.payload, ['slot-switch'], dict(self.system), self.store, selected_only=True)
            importer.assert_called_once()
            validator.assert_called_once()
            return plan, originals

    @unittest.skipUnless(os.name == 'posix' and getattr(os, 'geteuid', lambda: -1)() == 0,
                         'Actual protected legacy journal migration requires Linux root fixture')
    def test_actual_legacy_journals_prepare_apply_and_restore(self):
        plan, originals = self.legacy_journal_plan()
        self.assertEqual(plan['components']['slot-switch']['status'], 'ready', plan)
        self.assertEqual(set(originals), set(plan['files']))
        self.assertEqual(plan['legacy_selected'], [])
        self.store.apply(plan['files'], {'version': '0.1.4'}, ['slot-switch'], 'slot-A',
                         adopt=originals, legacy_selected=plan['legacy_selected'])
        for path, entry in plan['files'].items():
            self.assertEqual((self.root / path).read_bytes(), entry['data'])
        self.store.restore('slot-A', ['slot-switch'])
        self.assertTrue(all(not (self.root / path).exists() for path in plan['files']))
        self.assertIsNone(self.store.status()['pending'])

    @unittest.skipUnless(os.name == 'posix' and getattr(os, 'geteuid', lambda: -1)() == 0,
                         'Actual protected legacy journal migration requires Linux root fixture')
    def test_actual_legacy_journal_drift_blocks_prepare_without_writes(self):
        plan, originals = self.legacy_journal_plan(drift=True)
        self.assertEqual(plan['components']['slot-switch']['status'], 'blocked')
        self.assertIn('Legacy installed target changed', plan['components']['slot-switch']['reason'])
        self.assertEqual(plan['files'], {})
        self.assertEqual(originals, {})
        self.assertEqual((self.root / 'home/.oxp3-slot-switch/boot.py').read_bytes(), b'unknown legacy modification')

    def test_unmanaged_or_foreign_owned_code_is_never_overwritten(self):
        relative = 'home/.oxp3-slot-switch/boot.py'
        self.write(self.root, relative, b'custom code')
        for managed in (None, {'paths': {relative: {'component': 'other'}}}):
            plan = self.plan(managed)
            self.assertEqual(plan['components']['slot-switch']['status'], 'blocked')
            self.assertEqual(plan['files'], {})
        self.assertEqual((self.root / relative).read_bytes(), b'custom code')

    def test_missing_dependency_and_unverified_other_slot_block_the_plan(self):
        (self.root / 'usr/bin/steamos-bootconf').unlink()
        self.assertEqual(self.plan()['components']['slot-switch']['status'], 'blocked')
        self.write(self.root, 'usr/bin/steamos-bootconf', b'fixture').chmod(0o755)
        self.system['shared_compatible'] = False
        self.assertEqual(self.plan()['components']['slot-switch']['status'], 'blocked')

    def test_manifest_cannot_add_service_or_generic_copy_side_effects(self):
        for metadata in ({'units': ['atomupd.service']}, {'runtime_archive': 'unexpected.tar.gz'},
                         {'files': [{'source': 'x', 'target': 'etc/unsafe-copy'}]}):
            self.write(self.payload, 'integration/manifest.json', json.dumps({'slot-switch': metadata}).encode())
            plan = self.plan()
            self.assertEqual(plan['components']['slot-switch']['status'], 'blocked')
            self.assertEqual(plan['files'], {})

    def test_shared_code_drift_is_rejected_by_existing_transaction(self):
        self.seed()
        plan = self.ready(self.store.managed())
        relative = 'home/.oxp3-slot-switch/boot.py'
        self.write(self.root, relative, b'concurrent edit')
        with self.assertRaises(TransactionError):
            self.store.apply(plan['files'], {'version': '0.1.4'}, ['slot-switch'], 'slot-A')
        self.assertEqual((self.root / relative).read_bytes(), b'concurrent edit')

    def test_selected_update_includes_adapter_but_engine_only_preserves_component(self):
        self.seed()
        packages = mock.Mock()
        packages._read.return_value = None
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(operations, 'current_selection', return_value=['slot-switch']))
            stack.enter_context(mock.patch.object(operations, 'PackageStore', return_value=packages))
            stack.enter_context(mock.patch.object(operations.probe, 'verify_shared', return_value=True))
            stack.enter_context(mock.patch.object(operations.probe, 'verify_shared_os', return_value=True))
            stack.enter_context(mock.patch.object(operations.adoption, 'import_originals', side_effect=AssertionError('already managed')))
            stack.enter_context(mock.patch.object(operations, 'build_plan', side_effect=lambda payload, root, selected, system, managed:
                build_plan(payload, self.root, selected, system, managed)))
            plan, _ = operations.prepare(self.payload, ['slot-switch'], dict(self.system), self.store, selected_only=True)
            self.assertEqual(plan['components']['slot-switch']['status'], 'ready')
            plan, originals = operations.prepare(self.payload, [], dict(self.system), self.store, tool_only=True)
            self.assertEqual(plan['files'], {})
            self.assertEqual(plan['selected'], [])
            self.assertIn('slot-switch', plan['retained'])
            self.assertEqual(originals, {})

    def test_complete_catalog_lists_slot_switch_as_maintenance(self):
        archive = self.write(self.base, 'fixture.tar.gz', b'archive')
        value = catalog.create(self.payload, {'release': {'version': '0.1.4'}}, archive)
        entry = next(x for x in value['components'] if x['id'] == 'slot-switch')
        self.assertEqual(entry['delivery'], 'maintenance')
        described = catalog.describe(value, self.system, {'slot-switch': True})
        self.assertEqual(described['components'][0]['status'], 'requires_preflight')

    @unittest.skipUnless(os.name == 'posix', 'Unix mode validation')
    def test_group_writable_shared_code_ancestor_is_refused(self):
        self.seed()
        (self.root / 'home/.oxp3-slot-switch').chmod(0o775)
        plan = self.plan(self.store.managed())
        self.assertEqual(plan['components']['slot-switch']['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
