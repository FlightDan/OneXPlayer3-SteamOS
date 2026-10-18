import base64
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oxp3_maintenance import inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.system = {'slot': {'label': 'A', 'id': 'partuuid-current'}}
        # Windows has no Unix owner/group modes. Simulate protected and
        # unprotected inode metadata while exercising all path/file checks.
        self.untrusted = set()
        self.protection = patch.object(inventory, '_protected', side_effect=lambda info: info.st_ino not in self.untrusted)
        self.protection.start()
        self.addCleanup(self.protection.stop)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path

    def request(self, group='A', names=('input',)):
        return self.write('home/.oxp3-installer/integration/' + group + '/request.json',
                          {'schema': 1, 'repairs': list(names), 'plugins': [],
                           'set_deck_password': 'secret-never-return'})

    def journal(self, name='input', group='A', **changes):
        relative = 'etc/inputplumber/example.yaml'
        value = {'phase': 'installed', 'allowed': [relative],
                 'original': {relative: {'exists': True, 'data': base64.b64encode(b'PRIVATE ORIGINAL').decode(),
                                         'mode': 0o644, 'uid': 0, 'gid': 0}},
                 'applied': {relative: base64.b64encode(b'applied bytes').decode()}}
        value.update(changes)
        path = self.write('home/.oxp3-installer/integration/' + group + '/' + name + '/state.json', value)
        return path, value

    def inspect(self, managed=None):
        return inventory.inspect(self.root, self.system, managed)

    def test_empty_inventory_is_read_only_and_has_no_invented_release(self):
        before = list(self.root.iterdir())
        result = self.inspect()
        self.assertIsNone(result['release'])
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['components']['input']['state'], 'absent')
        self.assertEqual(before, list(self.root.iterdir()))

    def test_stale_public_component_report_is_ignored(self):
        self.request(names=('input',))
        self.write('usr/local/lib/oxp3-maintenance/current-components.json',
                   {'schema': 1, 'components': {'keyboard': {'project_version': '0.1.3', 'status': 'ready'}}})
        result = self.inspect()
        self.assertIn('input', result['selected'])
        self.assertEqual(inventory.installed_components(result), [])
        self.assertEqual(result['components']['keyboard']['state'], 'absent')
        self.assertNotIn('keyboard', result['selected'])
        self.assertNotIn('project_version', result['components']['keyboard'])

    def test_protected_legacy_backups_are_historical_not_current_installation(self):
        self.request()
        self.journal()
        result = self.inspect()
        self.assertEqual(result['components']['input']['state'], 'legacy_with_backups')
        self.assertFalse(result['components']['input']['adoption_verified'])
        self.assertEqual(inventory.installed_components(result), [])

    def test_restored_component_with_old_journals_and_empty_store_is_not_installed(self):
        self.request()
        self.journal()
        self.write('usr/local/lib/oxp3-maintenance/current-components.json',
                   {'schema': 1, 'components': {'input': {'project_version': '0.1.3', 'status': 'ready'}}})
        self.write('etc/inputplumber/example.yaml', b'PRIVATE ORIGINAL')
        managed = {'components': {}, 'paths': {}}
        before = copy.deepcopy(managed)
        result = self.inspect(managed)
        self.assertEqual(result['components']['input']['state'], 'legacy_with_backups')
        self.assertEqual(inventory.installed_components(result), [])
        self.assertEqual(managed, before)
        self.assertEqual((self.root / 'etc/inputplumber/example.yaml').read_bytes(), b'PRIVATE ORIGINAL')

    def test_protected_installer_version_selection_and_backups_are_sanitized(self):
        self.write('usr/local/lib/oxp3-integration/release.json',
                   {'version': '0.1.3', 'channel': 'stable', 'secret': 'not public'})
        self.request()
        self.journal()
        result = self.inspect()
        self.assertEqual(result['release']['version'], '0.1.3')
        self.assertEqual(result['release']['trust'], 'protected_project_metadata')
        self.assertEqual(result['selected'], ['input'])
        self.assertEqual(result['components']['input']['state'], 'legacy_with_backups')
        self.assertFalse(result['components']['input']['adoption_verified'])
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE ORIGINAL', serialized)
        self.assertNotIn(base64.b64encode(b'PRIVATE ORIGINAL').decode(), serialized)
        self.assertNotIn('secret-never-return', serialized)
        self.assertNotIn('not public', serialized)
        self.assertNotIn('applied bytes', serialized)

    def test_maintenance_release_and_current_slot_managed_records_take_precedence(self):
        self.write('usr/local/lib/oxp3-integration/release.json', {'version': '0.1.3'})
        self.write('usr/local/lib/oxp3-maintenance/current-release.json', {'version': '0.2.0-beta.1'})
        self.journal()
        managed = {'components': {'input': {'slots': ['partuuid-current']},
                                  'gyro': {'slots': ['partuuid-other']}}}
        before = copy.deepcopy(managed)
        result = self.inspect(managed)
        self.assertEqual(result['release']['version'], '0.2.0-beta.1')
        self.assertEqual(result['components']['input']['state'], 'managed')
        self.assertEqual(result['components']['gyro']['state'], 'absent')
        self.assertEqual(result['selected'], ['input'])
        self.assertEqual(inventory.installed_components(result), ['input'])
        self.assertEqual(managed, before)

    def test_untrusted_release_and_request_do_not_establish_provenance(self):
        release = self.write('usr/local/lib/oxp3-integration/release.json', {'version': 'invented'})
        request = self.request()
        self.untrusted.update((release.stat().st_ino, request.stat().st_ino))
        result = self.inspect()
        self.assertIsNone(result['release'])
        self.assertEqual(result['selected'], [])
        self.assertFalse(result['complete'])
        self.assertIn('untrusted_metadata', [item['reason'] for item in result['conflicts']])

    def test_unreadable_private_metadata_is_not_claimed_absent_with_certainty(self):
        self.request()
        original = inventory._Reader.read
        def read(reader, relative, **kwargs):
            if relative.endswith('/request.json'):
                raise PermissionError('private')
            return original(reader, relative, **kwargs)
        with patch.object(inventory._Reader, 'read', read):
            result = self.inspect()
        self.assertEqual(result['selected'], [])
        self.assertFalse(result['components']['input']['absence_verified'])
        self.assertIn('unreadable_metadata', [item['reason'] for item in result['conflicts']])

    def test_missing_originals_and_interrupted_journals_are_never_adoptable(self):
        for changes in ({'original': {}}, {'phase': 'installing'}, {'applied': {}}):
            with self.subTest(changes=changes):
                self.journal(**changes)
                result = self.inspect()
                self.assertEqual(result['components']['input']['state'], 'unmanaged')
                self.assertFalse(result['components']['input']['adoption_verified'])
                self.assertTrue(result['components']['input']['conflicts'])

    def test_rolled_back_journal_is_absent_and_result_only_is_unmanaged(self):
        self.journal(phase='rolled_back')
        self.assertEqual(self.inspect()['components']['input']['state'], 'absent')
        self.write('home/.oxp3-installer/integration/A/result.json',
                   {'slot': 'A', 'release': {'version': '0.1.2'}, 'options': {'repairs': ['gyro']},
                    'components': {'gyro': {'status': 'files_installed'}}})
        result = self.inspect()
        self.assertEqual(result['components']['gyro']['state'], 'unmanaged')
        self.assertEqual(result['slots']['A']['release']['version'], '0.1.2')

    def test_other_slot_is_described_without_becoming_current_or_mapping_unknown_slot(self):
        self.request('B', ('gyro',))
        self.journal('gyro', 'B')
        result = self.inspect()
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['slots']['B']['selected'], ['gyro'])
        self.assertEqual(result['components']['gyro']['state'], 'absent')
        self.system['slot']['label'] = None
        self.request('A')
        self.assertEqual(self.inspect()['selected'], [])

    def test_large_current_journals_use_bounded_digest_projection(self):
        relative = 'etc/inputplumber/example.yaml'
        payload = base64.b64encode(b'x' * (7 * 1024 * 1024)).decode()
        path, _ = self.journal(applied={relative: payload})
        self.assertGreater(path.stat().st_size, inventory.MAX_JSON)
        with patch.object(inventory, 'MAX_TOTAL', 1024):
            result = self.inspect()
        self.assertTrue(result['complete'], result['conflicts'])
        self.assertEqual(result['components']['input']['state'], 'legacy_with_backups')
        self.assertNotIn(payload, json.dumps(result))

    def test_inactive_journal_payload_is_not_opened(self):
        self.request('B', ('gyro',))
        self.journal('gyro', 'B')
        original = inventory._Reader.journal
        def journal(reader, relative):
            if '/B/' in relative:
                raise AssertionError('inactive slot payload read')
            return original(reader, relative)
        with patch.object(inventory._Reader, 'journal', journal):
            result = self.inspect()
        self.assertTrue(result['complete'], result['conflicts'])
        self.assertEqual(result['slots']['B']['selected'], ['gyro'])

    def test_activation_files_are_not_mistaken_for_component_journals(self):
        for group in ('A', 'B'):
            self.write('home/.oxp3-installer/integration/' + group + '/activation.json', {'phase': 'complete'})
            self.write('home/.oxp3-installer/integration/' + group + '/.activation.lock', b'')
        self.assertTrue(self.inspect()['complete'])
        self.write('home/.oxp3-installer/integration/A/.unexpected/state.json', {})
        self.assertIn('unsafe_journal_name', [item['reason'] for item in self.inspect()['conflicts']])

    def test_journal_budget_and_untrusted_files_fail_closed(self):
        path, _ = self.journal()
        with patch.object(inventory, 'MAX_JOURNAL', path.stat().st_size - 1):
            result = self.inspect()
        self.assertIn('metadata_limit', [item['reason'] for item in result['conflicts']])
        self.assertEqual(result['components']['input']['state'], 'absent')
        self.untrusted.add(path.stat().st_ino)
        self.assertIn('untrusted_metadata', [item['reason'] for item in self.inspect()['conflicts']])

    def test_current_journal_invalid_base64_and_forged_digest_are_rejected(self):
        relative = 'etc/inputplumber/example.yaml'
        for applied in ('not base64!', {'sha256': 'a' * 64, 'size': 1}):
            with self.subTest(applied=applied):
                self.journal(applied={relative: applied})
                result = self.inspect()
                self.assertFalse(result['complete'])
                self.assertNotEqual(result['components']['input']['state'], 'legacy_with_backups')

    def test_shared_journal_and_unknown_journal_are_identified(self):
        self.journal('keyboard', 'shared')
        self.journal('future-component')
        result = self.inspect()
        self.assertEqual(result['components']['keyboard']['state'], 'legacy_with_backups')
        self.assertEqual(result['unknown_journals'][0]['component'], 'future-component')

    def test_invalid_wrong_slot_and_oversized_metadata_do_not_supply_selection(self):
        self.write('home/.oxp3-installer/integration/A/result.json',
                   {'slot': 'B', 'options': {'repairs': ['gyro']}})
        result = self.inspect()
        self.assertEqual(result['selected'], [])
        self.assertIn('legacy_slot_mismatch', [item['reason'] for item in result['conflicts']])
        self.write('usr/local/lib/oxp3-integration/release.json', b'{' + b'x' * 65536)
        self.assertIsNone(self.inspect()['release'])

    def test_disagreeing_request_result_is_reported_without_adding_result_choices(self):
        self.request(names=('input',))
        self.write('home/.oxp3-installer/integration/A/result.json',
                   {'slot': 'A', 'options': {'repairs': ['gyro']}})
        result = self.inspect()
        self.assertEqual(result['selected'], ['input'])
        self.assertIn('legacy_selection_mismatch', [item['reason'] for item in result['conflicts']])

    def test_external_plugins_are_manifest_only_untrusted_observations(self):
        base = 'home/deck/homebrew/plugins/SteamGridDB'
        self.write(base + '/plugin.json', {'name': 'SteamGridDB', 'author': 'ignored private metadata'})
        self.write(base + '/package.json', {'version': '1.2.3', 'scripts': {'install': 'NEVER EXECUTE'}})
        code = self.write(base + '/main.py', b'raise RuntimeError("never load me")')
        self.untrusted.add((self.root / 'home/deck').stat().st_ino)
        result = self.inspect()
        observed = result['observed_plugins'][0]
        self.assertEqual(observed['trust'], 'untrusted_observed_only')
        self.assertEqual(observed['version'], '1.2.3')
        self.assertEqual(result['components']['steamgriddb']['state'], 'unmanaged')
        self.assertEqual(result['selected'], [])
        self.assertNotIn('NEVER EXECUTE', json.dumps(result))
        self.assertNotIn('ignored private metadata', json.dumps(result))
        self.assertEqual(code.read_bytes(), b'raise RuntimeError("never load me")')

    def test_external_decky_binary_presence_never_executes_or_claims_ownership(self):
        self.write('home/deck/homebrew/services/PluginLoader', b'not executed')
        result = self.inspect()
        self.assertEqual(result['components']['decky']['state'], 'unmanaged')
        self.assertEqual(len(result['observed_decky']), 1)

    def test_hardlinked_metadata_is_rejected(self):
        source = self.write('usr/local/lib/oxp3-integration/release.json', {'version': 'invented'})
        try:
            os.link(source, self.root / 'copy')
        except OSError:
            self.skipTest('hardlinks unavailable')
        result = self.inspect()
        self.assertIsNone(result['release'])
        self.assertIn('unsafe_file', [item['reason'] for item in result['conflicts']])

    def test_symlink_ancestor_never_reads_outside_root(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'release.json').write_text('{"version":"ESCAPED"}')
        parent = self.root / 'usr/local/lib'
        parent.mkdir(parents=True)
        try:
            (parent / 'oxp3-integration').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        result = self.inspect()
        self.assertIsNone(result['release'])
        self.assertNotIn('ESCAPED', json.dumps(result))

    def test_duplicate_json_and_entry_limits_fail_closed(self):
        self.write('usr/local/lib/oxp3-integration/release.json', b'{"version":"first","version":"second"}')
        result = self.inspect()
        self.assertIsNone(result['release'])
        self.assertIn('duplicate_json_key', [item['reason'] for item in result['conflicts']])
        base = self.root / 'home/deck/homebrew/plugins'
        base.mkdir(parents=True)
        for number in range(4):
            (base / ('plugin' + str(number))).mkdir()
        with patch.object(inventory, 'MAX_ENTRIES', 3):
            result = self.inspect()
        self.assertEqual(result['observed_plugins'], [])
        self.assertIn('entry_limit', [item['reason'] for item in result['conflicts']])


class ProtectionTests(unittest.TestCase):
    def test_windows_reparse_directories_are_links(self):
        self.assertTrue(inventory._linked(SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)))

    def test_only_root_owned_non_writable_metadata_is_protected(self):
        self.assertTrue(inventory._protected(SimpleNamespace(st_uid=0, st_mode=0o100644)))
        self.assertFalse(inventory._protected(SimpleNamespace(st_uid=1000, st_mode=0o100644)))
        self.assertFalse(inventory._protected(SimpleNamespace(st_uid=0, st_mode=0o100664)))
        self.assertFalse(inventory._protected(SimpleNamespace(st_uid=0, st_mode=0o100646)))


if __name__ == '__main__':
    unittest.main()
