"""Current-slot planner, runtime receipts, and real file recovery together."""
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from oxp3_maintenance import autoflatpaks_compat as repair, compatibility, operations
from oxp3_maintenance.components import build_plan
from oxp3_maintenance.transactions import Store, TransactionError
import test_autoflatpaks_compat as auto_fixture


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'Real protected plugin transaction requires isolated root Linux fixtures')
class LogRepairIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixture = auto_fixture.SurgicalRepairTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.base = fixture.root
        self.root = self.base / 'system'
        self.root.mkdir()
        for name, data in {**fixture.before, **fixture.witnesses, 'settings.json': b'{"user":true}\n'}.items():
            target = self.root / repair.PREFIX / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        self.payload = self.base / 'payload'
        (self.payload / 'components').mkdir(parents=True)
        (self.payload / 'integration').mkdir()
        (self.payload / 'components/options.json').write_text(json.dumps({'schema': 1,
            'repairs': [], 'plugins': [{'id': repair.COMPONENT, 'dependencies': []}]}))
        (self.payload / 'integration/manifest.json').write_text('{}')
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'dmi': dict(compatibility.DEVICE), 'uid': 1000, 'gid': 1000}
        self.store = Store(self.root, self.base / 'state', uid=1000, gid=1000)

    def plan(self, managed=None):
        plan = build_plan(self.payload, self.root, [repair.COMPONENT], self.system, managed)
        self.assertEqual(plan['components'][repair.COMPONENT]['status'], 'ready', plan)
        return plan

    def with_runtime(self, plan):
        app = self.base / 'app'
        app.mkdir()
        (app / 'entry.py').write_text('# fixture, never executed\n')
        (app / 'OXP3-Maintenance.desktop').write_text('[Desktop Entry]\n')
        plan.update(revision_slot='slot-B', component_revisions={repair.COMPONENT: 'a' * 64})
        files = dict(plan['files'])
        files.update(operations.runtime_files(app, {'version': '0.1.4', 'channel': 'stable'}, plan,
                                             installed_runtime=self.base / 'uninstalled'))
        return files

    def test_real_apply_receipt_and_restore_preserve_existing_plugin(self):
        plan = self.plan()
        self.assertTrue(plan['components'][repair.COMPONENT]['restart_required'])
        files = self.with_runtime(plan)
        self.store.apply(files, {'version': '0.1.4'}, [repair.COMPONENT, '_maintenance'], 'slot-B')
        receipt = self.root / 'usr/local/lib/oxp3-maintenance/component-receipts/slot-B/autoflatpaks-compat.json'
        self.assertEqual(json.loads(receipt.read_text())['revision'], 'a' * 64)
        for name, expected in self.fixture.after.items():
            self.assertEqual((self.root / repair.PREFIX / name).read_bytes(), expected)
        self.store.restore('slot-B', [repair.COMPONENT])
        for name, expected in self.fixture.before.items():
            self.assertEqual((self.root / repair.PREFIX / name).read_bytes(), expected)
        self.assertFalse(receipt.exists())
        self.assertEqual((self.root / repair.PREFIX / 'settings.json').read_bytes(), b'{"user":true}\n')
        for name, expected in self.fixture.witnesses.items():
            self.assertEqual((self.root / repair.PREFIX / name).read_bytes(), expected)
        self.assertIsNone(self.store.status()['pending'])

    def test_external_edit_between_plan_and_apply_is_not_adopted(self):
        files = self.plan()['files']
        target = self.root / repair.PREFIX / 'dist/index.js'
        target.write_bytes(b'user customization')
        with self.assertRaises(TransactionError):
            self.store.apply(files, {'version': '0.1.4'}, [repair.COMPONENT], 'slot-B')
        self.assertEqual(target.read_bytes(), b'user customization')
        self.assertIsNone(self.store.status()['pending'])

    def test_edit_between_validation_and_before_capture_is_refused(self):
        files = self.plan()['files']
        relative = repair.PREFIX + '/dist/index.js'
        original_read, calls = self.store._read, []
        def read(path, **kwargs):
            if path == relative:
                calls.append(path)
                if len(calls) == 2:
                    (self.root / relative).write_bytes(b'concurrent customization')
            return original_read(path, **kwargs)
        with mock.patch.object(self.store, '_read', side_effect=read):
            with self.assertRaises(TransactionError):
                self.store.apply(files, {'version': '0.1.4'}, [repair.COMPONENT], 'slot-B')
        self.assertEqual((self.root / relative).read_bytes(), b'concurrent customization')
        self.assertIsNone(self.store.status()['pending'])

    def test_legacy_component_ownership_cannot_lose_true_originals(self):
        files = self.plan()['files']
        original = {path: dict(entry, component='autoflatpaks') for path, entry in files.items()}
        for name, data in self.fixture.before.items():
            original[repair.PREFIX + '/' + name]['data'] = data
        self.store.apply(original, {'version': '0.1.3'}, ['autoflatpaks'], 'slot-B')
        managed = self.store.managed()
        blocked = build_plan(self.payload, self.root, [repair.COMPONENT], self.system, managed)
        self.assertEqual(blocked['components'][repair.COMPONENT]['status'], 'blocked')
        with self.assertRaises(TransactionError):
            self.store.apply(files, {'version': '0.1.4'}, [repair.COMPONENT], 'slot-B')
        self.assertIsNone(self.store.status()['pending'])

    def test_receipt_cannot_target_another_slot_or_unrelated_path(self):
        files = self.with_runtime(self.plan())
        receipt = 'usr/local/lib/oxp3-maintenance/component-receipts/slot-B/autoflatpaks-compat.json'
        for target in ('usr/local/lib/oxp3-maintenance/component-receipts/slot-A/autoflatpaks-compat.json',
                       'etc/unrelated.json'):
            changed = dict(files)
            changed[target] = changed.pop(receipt)
            with self.subTest(target=target), self.assertRaises(TransactionError):
                self.store.apply(changed, {'version': '0.1.4'}, [repair.COMPONENT, '_maintenance'], 'slot-B')
        self.assertIsNone(self.store.status()['pending'])
