import copy
import base64
import json
import os
from pathlib import Path
import tempfile
import stat
import shutil
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import adoption, catalog, cli, downloads, health, inventory, probe, releases, update_state
from oxp3_maintenance.desktop_service import DesktopService
from oxp3_maintenance.transactions import Store
from oxp3_maintenance.opti_migration import PLUGIN, RUNTIME, RUNTIME_PREFIX


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


class ReadOnlyInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'root'
        self.root.mkdir()
        self.system = {'slot': {'id': 'here', 'label': 'A'}, 'uid': 1000, 'gid': 1000}
        protection = mock.patch.object(inventory, '_protected', return_value=True)
        protection.start()
        self.addCleanup(protection.stop)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path

    def legacy(self):
        path = self.write('etc/inputplumber/project.yaml', b'installed code')
        info = path.stat()
        relative = path.relative_to(self.root).as_posix()
        snapshot = {'exists': True, 'data': base64.b64encode(b'original code').decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        self.write('home/.oxp3-installer/integration/A/input/state.json',
                   {'phase': 'installed', 'allowed': [relative], 'original': {relative: snapshot},
                    'applied': {relative: base64.b64encode(path.read_bytes()).decode()}})
        return path

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}

    def legacy_opti_runtime(self):
        binary = self.write(RUNTIME_PREFIX + 'bin/tool', b'original installed runtime')
        destination = self.root / RUNTIME_PREFIX.rstrip('/')
        state = destination.parent / '.installer-state'
        state.mkdir()
        shutil.copytree(destination, state / 'installed')
        metadata = {path.relative_to(destination).as_posix(): {
            'directory': path.is_dir(), 'mode': stat.S_IMODE(path.stat().st_mode),
            'uid': path.stat().st_uid, 'gid': path.stat().st_gid}
            for path in [destination, *destination.rglob('*')]}
        self.write(state.relative_to(self.root).as_posix() + '/state.json', {
            'destination': RUNTIME_PREFIX.rstrip('/'), 'phase': 'installed',
            'original_exists': False, 'original_metadata': None, 'installed_metadata': metadata})
        return binary

    def test_legacy_combined_opti_runtime_is_detected_from_verified_directory_journal(self):
        binary = self.legacy_opti_runtime()
        before = self.snapshot()
        store = mock.Mock()
        store.managed.return_value = {'components': {}, 'paths': {}}
        store._index.return_value = {'slots': {}}
        with mock.patch.object(adoption, '_trusted'):
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: True})
            self.assertEqual(cli.installed_component_states(self.root, self.system, store, [RUNTIME]), {RUNTIME: True})
            self.assertEqual(before, self.snapshot())
            binary.write_bytes(b'changed runtime')
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})
            self.assertEqual(cli.installed_component_states(self.root, self.system, store, [RUNTIME]), {RUNTIME: None})
            binary.unlink()
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})

    def test_unmanaged_runtime_directory_is_unknown_and_plugin_alone_proves_no_runtime(self):
        self.write('var/lib/oxp3-installer/decky/runtime/plugins/Opti2XMX/main.py', b'plugin')
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: False})
        self.write(RUNTIME_PREFIX + 'bin/tool', b'no trusted baseline')
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})

    def test_managed_old_opti_owner_proves_runtime_but_other_owner_and_runtime_tombstone_do_not(self):
        binary = self.write(RUNTIME_PREFIX + 'bin/tool', b'current managed runtime')
        info = binary.stat()
        relative = binary.relative_to(self.root).as_posix()
        snapshot = {'exists': True, 'data': base64.b64encode(binary.read_bytes()).decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        current = {'selected': [PLUGIN], 'paths': {relative: {
            'component': PLUGIN, 'mutable': False, 'user': False, 'snapshot': snapshot}}}
        index = {'format': 1, 'slots': {'here': {'current': current}}}
        self.write(health.STATE + '/lock', b'')
        for owner, retired, expected in ((PLUGIN, False, True), ('unrelated', False, None), (PLUGIN, True, False)):
            with self.subTest(owner=owner, retired=retired):
                current['selected'] = [owner]
                current['paths'][relative]['component'] = owner
                current['legacy_adopted'] = [RUNTIME] if retired else []
                self.write(health.STATE + '/index.json', index)
                self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: expected})
                store = mock.Mock()
                store.managed.return_value = {'components': {owner: {'slots': ['here']}}, 'paths': {}}
                store._index.return_value = index
                store._read.return_value = snapshot
                self.assertEqual(cli.installed_component_states(self.root, self.system, store, [RUNTIME]), {RUNTIME: expected})

    def test_legacy_opti_runtime_alias_never_bypasses_pending_or_unreadable_index(self):
        self.legacy_opti_runtime()
        self.write(health.STATE + '/pending.json', {'phase': 'applying'})
        with mock.patch.object(adoption, 'import_originals') as imported:
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})
        imported.assert_not_called()
        (self.root / health.STATE / 'pending.json').unlink()
        self.write(health.STATE + '/lock', b'')
        with mock.patch.object(health, 'read_index', side_effect=PermissionError('protected')), \
             mock.patch.object(adoption, 'import_originals') as imported:
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})
        imported.assert_not_called()

    def test_inline_opti_runtime_requires_installed_phase_and_complete_original_backups(self):
        binary = self.write(RUNTIME_PREFIX + 'bin/tool', b'inline legacy runtime')
        relative = binary.relative_to(self.root).as_posix()
        info = binary.stat()
        baseline = {'exists': True, 'data': base64.b64encode(b'original runtime').decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        valid = {'phase': 'installed', 'allowed': [relative], 'original': {relative: baseline},
                 'applied': {relative: base64.b64encode(binary.read_bytes()).decode()}}
        store = mock.Mock()
        store.managed.return_value = {'components': {}, 'paths': {}}
        store._index.return_value = {'slots': {}}
        for mutation, expected in (({}, True), ({'phase': 'installing'}, None),
                                   ({'original': {}}, None), ({'original': {relative: {'exists': True}}}, None)):
            with self.subTest(mutation=mutation), mock.patch.object(adoption, '_trusted'):
                self.write('home/.oxp3-installer/integration/A/' + PLUGIN + '/state.json', dict(valid, **mutation))
                self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: expected})
                self.assertEqual(cli.installed_component_states(self.root, self.system, store, [RUNTIME]), {RUNTIME: expected})

    def test_independent_directory_runtime_survives_plugin_only_journal_conflict(self):
        self.legacy_opti_runtime()
        plugin_path = 'var/lib/oxp3-installer/decky/runtime/plugins/Opti2XMX/main.py'
        self.write('home/.oxp3-installer/integration/A/' + PLUGIN + '/state.json', {
            'phase': 'installing', 'allowed': [plugin_path], 'original': {}, 'applied': {}})
        with mock.patch.object(adoption, '_trusted'):
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: True})

    def test_participating_runtime_journal_conflict_blocks_directory_alias(self):
        binary = self.legacy_opti_runtime()
        relative = binary.relative_to(self.root).as_posix()
        self.write('home/.oxp3-installer/integration/A/' + PLUGIN + '/state.json', {
            'phase': 'installing', 'allowed': [relative], 'original': {relative: {'exists': False}},
            'applied': {relative: base64.b64encode(binary.read_bytes()).decode()}})
        with mock.patch.object(adoption, '_trusted'):
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, [RUNTIME]), {RUNTIME: None})

    def test_empty_state_never_creates_lock_or_directory(self):
        before = self.snapshot()
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': False})
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / health.STATE).exists())

    def test_valid_legacy_requires_live_bytes_and_does_not_write(self):
        path = self.legacy()
        # Windows has no Unix owner/mode enforcement; production keeps _trusted.
        with mock.patch.object(adoption, '_trusted'):
            before = self.snapshot()
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': True})
            self.assertEqual(before, self.snapshot())
            path.write_bytes(b'changed code')
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': None})
            path.unlink()
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': None})

    def test_unreadable_current_index_never_falls_back_to_legacy(self):
        self.legacy()
        self.write(health.STATE + '/lock', b'')
        with mock.patch.object(health, 'read_index', side_effect=PermissionError('protected')), \
             mock.patch.object(adoption, 'import_originals') as imported:
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': None})
        imported.assert_not_called()

    def test_retired_component_does_not_revive_legacy_journal(self):
        self.legacy()
        self.write(health.STATE + '/lock', b'')
        self.write(health.STATE + '/index.json', {'format': 1, 'slots': {'here': {'current': {
            'selected': [], 'legacy_adopted': ['input'], 'paths': {}}}}})
        with mock.patch.object(adoption, 'import_originals') as imported:
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': False})
        imported.assert_not_called()

    def test_missing_managed_file_is_not_installed_even_for_absent_baseline(self):
        self.write(health.STATE + '/lock', b'')
        self.write(health.STATE + '/index.json', {'format': 1, 'slots': {'here': {'current': {
            'selected': ['keyboard'], 'paths': {'home/deck/.config/kwinrc': {
                'component': 'keyboard', 'mutable': True, 'snapshot': {'exists': False}}}}}}})
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['keyboard']), {'keyboard': None})

    def test_managed_files_are_checked_against_current_snapshot_without_writes(self):
        path = self.write('etc/project-code', b'current code')
        info = path.stat()
        snapshot = {'exists': True, 'data': base64.b64encode(path.read_bytes()).decode(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        self.write(health.STATE + '/lock', b'')
        self.write(health.STATE + '/index.json', {'format': 1, 'slots': {'here': {'current': {
            'selected': ['input'], 'paths': {'etc/project-code': {
                'component': 'input', 'mutable': False, 'snapshot': snapshot}}}}}})
        before = self.snapshot()
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': True})
        self.assertEqual(before, self.snapshot())
        path.write_bytes(b'changed code')
        self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': None})

    def test_pending_operation_does_not_report_partially_installed_files(self):
        self.write(health.STATE + '/lock', b'')
        self.write(health.STATE + '/pending.json', {'phase': 'applying'})
        with mock.patch.object(adoption, 'import_originals') as imported:
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input']), {'input': None})
        imported.assert_not_called()

    def test_first_interrupted_operation_without_lock_never_uses_legacy(self):
        self.legacy()
        for marker in ('pending.json', 'live-operation.json'):
            with self.subTest(marker=marker):
                path = self.write(health.STATE + '/' + marker, {'phase': 'applying'})
                with mock.patch.object(adoption, 'import_originals') as imported:
                    self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['input', 'keyboard']),
                                     {'input': None, 'keyboard': None})
                imported.assert_not_called()
                path.unlink()
        self.assertFalse((self.root / health.STATE / 'lock').exists())

    def test_original_preserved_configuration_uses_recorded_user_and_safe_current_metadata(self):
        relative = 'home/deck/.config/kwinrc'
        baseline = {'exists': True, 'data': base64.b64encode(b'original root config').decode(),
                    'mode': 0o600, 'uid': 0, 'gid': 0}
        index = {'format': 1, 'slots': {'here': {'current': {
            'selected': ['keyboard'], 'paths': {relative: {'component': 'keyboard', 'mutable': True,
                'user': True, 'snapshot': baseline}}}}},
            'originals': {'shared:' + relative: copy.deepcopy(baseline)}}
        self.write(health.STATE + '/lock', b'')
        self.write(health.STATE + '/index.json', index)
        current = {'exists': True, 'sha256': 'a' * 64, 'bytes': 5, 'mode': 0o644, 'uid': 1000, 'gid': 1000}
        with mock.patch.object(health, 'fingerprint', return_value=current):
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['keyboard']), {'keyboard': True})
        # A mismatched original is ordinary metadata drift, not preserve proof.
        index['originals']['shared:' + relative]['data'] = base64.b64encode(b'another original').decode()
        self.write(health.STATE + '/index.json', index)
        with mock.patch.object(health, 'fingerprint', return_value=current):
            self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['keyboard']), {'keyboard': None})
        index['originals']['shared:' + relative] = baseline
        self.write(health.STATE + '/index.json', index)
        for changes in ({'uid': 0, 'gid': 0, 'mode': 0o600}, {'uid': 0}, {'mode': 0o666}, {'mode': 0o755}):
            with self.subTest(changes=changes), mock.patch.object(health, 'fingerprint', return_value=dict(current, **changes)):
                self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['keyboard']), {'keyboard': None})

    def test_original_preservation_uses_slot_scope_and_absent_baseline_uses_recorded_owner(self):
        for relative, user, original_exists in (('etc/project/config', False, True),
                                               ('opt/project/config', False, True),
                                               ('home/deck/config', True, False),
                                               ('home/deck/config', False, False)):
            with self.subTest(relative=relative, user=user, original_exists=original_exists):
                baseline = {'exists': False}
                if original_exists:
                    baseline = {'exists': True, 'data': base64.b64encode(b'original').decode(),
                                'mode': 0o600, 'uid': 0, 'gid': 0}
                scope = ('shared' if relative.startswith(('home/', 'opt/')) else 'here') + ':' + relative
                index = {'format': 1, 'slots': {'here': {'current': {
                    'selected': ['keyboard'], 'paths': {relative: {'component': 'keyboard', 'mutable': True,
                        'user': user, 'snapshot': baseline}}}}}, 'originals': {scope: baseline}}
                self.write(health.STATE + '/lock', b'')
                self.write(health.STATE + '/index.json', index)
                owner = 1000 if user else 0
                current = {'exists': True, 'sha256': 'a' * 64, 'bytes': 5, 'mode': 0o644, 'uid': owner, 'gid': owner}
                with mock.patch.object(health, 'fingerprint', return_value=current):
                    self.assertEqual(cli.read_installed_component_states(self.root, self.system, ['keyboard']), {'keyboard': True})


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
        self.assertEqual({name for name, item in rows.items() if item['selected']}, {'new-repair'})
        self.assertIs(rows['installed-repair']['installed'], True)
        self.assertIsNone(rows['unknown-repair']['installed'])
        self.assertIn('Installation status needs checking', rows['unknown-repair']['detail'])
        self.assertIn('Installed.', rows['installed-repair']['detail'])
        self.assertEqual(rows['new-plugin']['category'], 'plugins')
        self.assertEqual(rows['new-repair']['category'], 'repairs')
        self.assertEqual(len(rows), 6)  # The UI alone decides whether to hide True.
        self.assertEqual([item['category'] for item in view['items']], ['repairs'] * 4 + ['plugins'] * 2)

    def test_review_uses_explicit_selection_instead_of_default_repair_choices(self):
        plan = self.plan()
        plan['selected'] = ['installed-repair', 'new-plugin']
        view = self.service._plan_view(plan, review=True)
        self.assertEqual({item['id'] for item in view['items'] if item['selected']}, {'installed-repair', 'new-plugin'})

    def test_online_unknown_repairs_and_plugins_unselected_without_privilege(self):
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
        self.assertFalse(rows['keyboard']['selected'])
        self.assertIn('Installation status needs checking', rows['keyboard']['detail'])
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

    def test_modular_installed_and_revision_status_are_independent(self):
        value = {'schema': 2, 'release': {'version': '1.1.0'}, 'bundle': {}, 'packages': {},
                 'component_packages': {'keyboard': []}, 'distribution_manifest_digest': 'fixture',
                 'components': [{'id': 'keyboard', 'kind': 'repairs', 'delivery': 'maintenance',
                                 'available': True, 'revision': 'new', 'dependencies': []}]}
        system = {'slot': {'id': 'here'}}
        with mock.patch.object(probe, 'live', return_value=system), \
             mock.patch('oxp3_maintenance.compatibility.evaluate', return_value={'supported': True, 'reason': 'fixture'}), \
             mock.patch.object(cli, 'read_installed_component_states', return_value={'keyboard': True}), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '1',
                 'component_revisions_by_slot': {'here': {'keyboard': 'old'}}}):
            row = self.service._distribution_view(value)['items'][0]
        self.assertIs(row['installed'], True)
        self.assertIs(row['update_available'], True)
        self.assertTrue(row['selected'])
        self.assertIn('Installed; update available', row['detail'])
        self.assertIs(update_state.available_updates(value, {}, 'here')['keyboard'], None)
        with mock.patch.object(probe, 'live', return_value=system), \
             mock.patch('oxp3_maintenance.compatibility.evaluate', return_value={'supported': True, 'reason': 'fixture'}), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '1'}):
            for state, selected in ((None, False), (True, False), (False, True)):
                with self.subTest(installed=state):
                    row = self.service._distribution_view(value, installation={'keyboard': state})['items'][0]
                    self.assertIs(row['selected'], selected)
                    self.assertIs(row['installed'], state)

    def test_known_update_is_selected_even_when_installation_cannot_be_read(self):
        result = self.plan()
        result['update_available'] = {'unknown-repair': True, 'unknown-plugin': True}
        rows = {item['id']: item for item in self.service._plan_view(result)['items']}
        self.assertTrue(rows['unknown-repair']['selected'])
        self.assertTrue(rows['unknown-plugin']['selected'])
        self.assertIn('Installation status needs checking', rows['unknown-repair']['detail'])
        self.assertIn('recorded revision', rows['unknown-repair']['detail'])

    def test_explicit_installed_check_refreshes_displayed_catalog_without_changing_source(self):
        value = {'release': {}, 'bundle': {}, 'components': [
            {'id': 'keyboard', 'kind': 'repairs', 'delivery': 'maintenance', 'available': True}]}
        self.service.installation_catalog = value
        original_source = self.service.source
        with mock.patch.object(self.service, '_backend', return_value={
                'system': {}, 'installed_states': {'keyboard': True}}) as backend:
            view = self.service.perform('check-installed')
        backend.assert_called_once_with('installation-status', ['keyboard'])
        self.assertEqual(self.service.source, original_source)
        self.assertIs(view['items'][0]['installed'], True)
        self.assertFalse(view['items'][0]['selected'])

    def test_schema_one_catalog_uses_safe_unprivileged_installation_evidence(self):
        value = {'release': {}, 'bundle': {}, 'components': [
            {'id': 'keyboard', 'kind': 'repairs', 'delivery': 'maintenance', 'available': True}]}
        with mock.patch.object(cli, 'read_installed_component_states', return_value={'keyboard': True}) as read:
            view = self.service._legacy_catalog_view(value, {})
        read.assert_called_once_with('/', {}, ['keyboard'])
        self.assertIs(view['items'][0]['installed'], True)
        self.assertFalse(view['items'][0]['selected'])


if __name__ == '__main__':
    unittest.main()
