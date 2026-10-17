import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import adoption, catalog, cli, downloads, inventory, probe, releases
from oxp3_maintenance.desktop_service import DesktopService
from oxp3_maintenance.transactions import Store


class InstalledEvidenceTests(unittest.TestCase):
    def test_selection_alone_does_not_prove_installation_and_restored_journals_stay_retired(self):
        store = mock.Mock()
        store.managed.return_value = {'components': {'managed': {'slots': ['here']}}, 'paths': {}}
        snapshot = {'exists': True, 'data': 'bytes', 'mode': 0o644, 'uid': 0, 'gid': 0}
        store._index.return_value = {'slots': {'here': {'current': {'legacy_adopted': ['restored'], 'paths': {
            'etc/managed': {'component': 'managed', 'user': False, 'mutable': False, 'snapshot': snapshot}}}}}}
        store._read.return_value = snapshot
        evidence = {'components': {
            'requested-only': {'state': 'absent', 'selected': True, 'absence_verified': True},
            'old-valid': {'state': 'legacy_with_backups', 'conflicts': []},
            'old-changed': {'state': 'legacy_with_backups', 'conflicts': []},
            'restored': {'state': 'legacy_with_backups', 'conflicts': []},
            'external-plugin': {'state': 'unmanaged'},
            'unreadable': {'state': 'absent', 'absence_verified': False}}}
        def import_records(root, system, names):
            return {'etc/old': {'component': names[0], 'private': 'NEVER RETURN'}}
        def validate(root, records, system):
            if records['etc/old']['component'] == 'old-changed':
                raise RuntimeError('changed current code')
            return records
        names = ['managed', *evidence['components'], 'unknown-new']
        with mock.patch.object(inventory, 'inspect', return_value=evidence), \
             mock.patch.object(adoption, 'import_originals', side_effect=import_records) as imported, \
             mock.patch.object(adoption, 'validate_current', side_effect=validate):
            states = cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, names)
        self.assertEqual(states, {'managed': True, 'requested-only': False, 'old-valid': True,
            'old-changed': None, 'restored': False, 'external-plugin': None, 'unreadable': None, 'unknown-new': None})
        self.assertEqual([call.args[2] for call in imported.call_args_list], [['old-valid'], ['old-changed']])

    def test_successful_preflight_originals_are_reused_without_duplicate_validation(self):
        store = mock.Mock()
        store.managed.return_value = {'components': {}, 'paths': {}}
        store._index.return_value = {'slots': {}}
        with mock.patch.object(inventory, 'inspect', return_value={'components': {}}), \
             mock.patch.object(adoption, 'import_originals') as imported, \
             mock.patch.object(adoption, 'validate_current') as validate:
            states = cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, ['old-valid'],
                validated_originals={'etc/old': {'component': 'old-valid', 'original': {'data': 'private'}}})
        self.assertEqual(states, {'old-valid': True})
        imported.assert_not_called()
        validate.assert_not_called()

    def test_current_management_wins_over_ever_adopted_history(self):
        store = mock.Mock()
        store.managed.return_value = {'components': {'input': {'slots': ['here']}}, 'paths': {}}
        snapshot = {'exists': True, 'data': 'bytes', 'mode': 0o644, 'uid': 0, 'gid': 0}
        store._index.return_value = {'slots': {'here': {'current': {'legacy_adopted': ['input'], 'paths': {
            'etc/input': {'component': 'input', 'user': False, 'mutable': False, 'snapshot': snapshot}}}}}}
        store._read.return_value = snapshot
        with mock.patch.object(inventory, 'inspect', return_value={'components': {}}):
            self.assertEqual(cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, ['input']), {'input': True})

    def test_missing_or_modified_managed_code_stays_visible_while_custom_settings_remain_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            root.mkdir()
            store = Store(root, Path(temporary) / 'state', enforce_owner=False)
            files = {'etc/code': {'component': 'input', 'data': b'original-code', 'mode': 0o644},
                     'etc/settings': {'component': 'keyboard', 'data': b'default-config', 'mode': 0o644, 'mutable': True}}
            store.apply(files, {'version': '1'}, ['input', 'keyboard'], 'here')
            (root / 'etc/settings').write_bytes(b'legitimate custom configuration')
            with mock.patch.object(inventory, 'inspect', return_value={'components': {}}):
                states = cli.installed_component_states(root, {'slot': {'id': 'here'}}, store, ['input', 'keyboard'])
                self.assertEqual(states, {'input': True, 'keyboard': True})
                (root / 'etc/code').write_bytes(b'corrupt-code')
                states = cli.installed_component_states(root, {'slot': {'id': 'here'}}, store, ['input', 'keyboard'])
                self.assertEqual(states, {'input': None, 'keyboard': True})
                (root / 'etc/code').unlink()
                states = cli.installed_component_states(root, {'slot': {'id': 'here'}}, store, ['input', 'keyboard'])
                self.assertEqual(states, {'input': None, 'keyboard': True})

    def test_reapplied_custom_setting_with_absent_original_is_installed_but_missing_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            root.mkdir()
            store = Store(root, Path(temporary) / 'state', enforce_owner=False)
            relative = 'home/deck/.config/kwinrc'
            spec = {'component': 'keyboard', 'data': b'default-config', 'mode': 0o644,
                    'mutable': True, 'user': True}
            store.apply({relative: spec}, {'version': '1'}, ['keyboard'], 'here')
            path = root / relative
            path.write_bytes(b'legitimate custom configuration')
            store.restore('here', ['keyboard'])
            store.apply({relative: dict(spec, data=path.read_bytes())}, {'version': '1'}, ['keyboard'], 'here')
            baseline = store._index()['slots']['here']['current']['paths'][relative]['snapshot']
            self.assertEqual(baseline, {'exists': False})
            actual_read = store._read
            def read(relative, **kwargs):
                actual = actual_read(relative, **kwargs)
                if actual['exists'] and os.name != 'posix':
                    # Windows fixtures have no Unix file modes. Model the
                    # device's regular 0644 desktop-user file after safe read.
                    actual.update(mode=0o644, uid=store.uid, gid=store.gid)
                return actual
            with mock.patch.object(inventory, 'inspect', return_value={'components': {}}), \
                 mock.patch.object(store, '_read', side_effect=read):
                self.assertEqual(cli.installed_component_states(root, {'slot': {'id': 'here'}}, store, ['keyboard']), {'keyboard': True})
                path.unlink()
                self.assertEqual(cli.installed_component_states(root, {'slot': {'id': 'here'}}, store, ['keyboard']), {'keyboard': None})

    def test_absent_mutable_baseline_requires_correct_owner_and_safe_config_mode(self):
        store = mock.Mock(uid=1000, gid=1000)
        store.managed.return_value = {'components': {'keyboard': {'slots': ['here']}}, 'paths': {}}
        store._index.return_value = {'slots': {'here': {'current': {'paths': {
            'home/deck/.config/kwinrc': {'component': 'keyboard', 'user': True,
                'mutable': True, 'snapshot': {'exists': False}}}}}}}
        safe = {'exists': True, 'data': 'custom', 'mode': 0o644, 'uid': 1000, 'gid': 1000}
        with mock.patch.object(inventory, 'inspect', return_value={'components': {}}):
            for changes, expected in (({}, True), ({'mode': 0o600}, True), ({'uid': 0}, None),
                                      ({'gid': 0}, None), ({'mode': 0o666}, None), ({'mode': 0o755}, None),
                                      ({'mode': 0o4644}, None), ({'exists': False}, None)):
                store._read.return_value = dict(safe, **changes)
                with self.subTest(changes=changes):
                    self.assertEqual(cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, ['keyboard']), {'keyboard': expected})

    def test_preserved_existing_original_metadata_is_not_current_config_ownership(self):
        store = mock.Mock(uid=1000, gid=1000)
        relative = 'home/deck/.config/kwinrc'
        baseline = {'exists': True, 'data': 'original bytes', 'mode': 0o600, 'uid': 0, 'gid': 0}
        store.managed.return_value = {'components': {'keyboard': {'slots': ['here']}}, 'paths': {}}
        index = {'slots': {'here': {'current': {'paths': {relative: {'component': 'keyboard',
            'user': True, 'mutable': True, 'snapshot': baseline}}}}},
            'originals': {'shared:' + relative: copy.deepcopy(baseline)}}
        store._index.return_value = index
        store._read.return_value = {'exists': True, 'data': 'current custom bytes', 'mode': 0o644, 'uid': 1000, 'gid': 1000}
        with mock.patch.object(inventory, 'inspect', return_value={'components': {}}):
            self.assertEqual(cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, ['keyboard']), {'keyboard': True})
            # An arbitrary applied baseline is not proof of original-preserve
            # semantics; metadata drift remains visible for review.
            index['originals']['shared:' + relative]['data'] = 'different original'
            self.assertEqual(cli.installed_component_states('/', {'slot': {'id': 'here'}}, store, ['keyboard']), {'keyboard': None})


class SelectionDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = mock.patch.object(Path, 'home', return_value=Path(self.temp.name))
        self.home.start()
        self.addCleanup(self.home.stop)
        self.release = mock.patch.object(cli, 'installed_release', return_value={'version': '1.0.0', 'channel': 'stable'})
        self.release.start()
        self.addCleanup(self.release.stop)
        self.service = DesktopService(SimpleNamespace(bundle='/fixture.tar.gz', bundle_dir=None))

    def plan(self):
        repairs = ['new-repair', 'installed-repair', 'unknown-repair', 'blocked-repair']
        plugins = ['new-plugin', 'unknown-plugin']
        return {'release': {'version': '1.1.0'}, 'can_apply': True, 'file_count': 1,
            'catalog': {'repairs': [{'id': name} for name in repairs], 'plugins': [{'id': name} for name in plugins]},
            'components': {name: {'status': 'blocked' if name == 'blocked-repair' else 'ready'} for name in repairs + plugins},
            'selected': repairs + plugins, 'installed_states': {'new-repair': False, 'installed-repair': True,
                'unknown-repair': None, 'blocked-repair': False, 'new-plugin': False, 'unknown-plugin': None}}

    def test_offline_available_repairs_default_selected_and_plugins_never_default_selected(self):
        view = self.service._plan_view(self.plan())
        rows = {item['id']: item for item in view['items']}
        self.assertEqual({name for name, item in rows.items() if item['selected']}, {'new-repair', 'unknown-repair'})
        self.assertIs(rows['installed-repair']['installed'], True)
        self.assertIsNone(rows['unknown-repair']['installed'])
        self.assertEqual(rows['new-plugin']['category'], 'plugins')
        self.assertEqual(rows['new-repair']['category'], 'repairs')
        self.assertEqual(len(rows), 6)  # The UI alone decides whether to hide True.
        self.assertEqual([item['category'] for item in view['items']], ['repairs'] * 4 + ['plugins'] * 2)

    def test_review_uses_explicit_selection_instead_of_default_repair_choices(self):
        plan = self.plan()
        plan['selected'] = ['installed-repair', 'new-plugin']
        view = self.service._plan_view(plan, review=True)
        self.assertEqual({item['id'] for item in view['items'] if item['selected']}, {'installed-repair', 'new-plugin'})

    def test_online_unknown_repairs_selected_without_privilege_and_plugins_unselected(self):
        candidate = {'version': '1.1.0', 'size': 1024}
        report = {'latest_project': {'version': '1.1.0'}, 'latest_maintenance': candidate}
        value = {'release': {'version': '1.1.0'}, 'bundle': {}, 'components': [
            {'id': 'keyboard', 'kind': 'repairs', 'delivery': 'maintenance', 'available': True, 'en': 'Keyboard'},
            {'id': 'decky', 'kind': 'plugins', 'delivery': 'maintenance', 'available': True, 'en': 'Decky'}]}
        with mock.patch.object(releases, 'check_releases', return_value=report), \
             mock.patch.object(releases, 'fetch_catalog', return_value=value), \
             mock.patch.object(downloads, 'trusted_key', return_value=Path('/trusted.pem')), \
             mock.patch.object(probe, 'live', side_effect=RuntimeError('fixture host')), \
             mock.patch.object(self.service, '_backend') as backend, \
             mock.patch('subprocess.run') as run:
            view = self.service.perform('discover')
        rows = {item['id']: item for item in view['items']}
        self.assertTrue(rows['keyboard']['selected'])
        self.assertFalse(rows['decky']['selected'])
        self.assertTrue(all(item['installed'] is None for item in rows.values()))
        backend.assert_not_called()
        run.assert_not_called()

    def test_catalog_supports_tristate_mapping_without_treating_false_as_membership(self):
        value = {'release': {}, 'bundle': {}, 'components': [
            {'id': 'keyboard', 'kind': 'repairs', 'delivery': 'maintenance', 'available': True},
            {'id': 'input', 'kind': 'repairs', 'delivery': 'maintenance', 'available': True},
            {'id': 'decky', 'kind': 'plugins', 'delivery': 'maintenance', 'available': True}]}
        rows = {item['id']: item for item in catalog.describe(value, installed={'keyboard': True, 'input': False, 'decky': None})['components']}
        self.assertFalse(rows['keyboard']['selected'])
        self.assertTrue(rows['input']['selected'])
        self.assertFalse(rows['decky']['selected'])
        self.assertIs(rows['input']['installed'], False)
        self.assertIsNone(rows['decky']['installed'])


if __name__ == '__main__':
    unittest.main()
