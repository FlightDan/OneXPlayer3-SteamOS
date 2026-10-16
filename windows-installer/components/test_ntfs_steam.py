"""No live disks, mounts, Steam processes, or network connections are used."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import ntfs_steam as runtime

SELECTION = {'partuuid': '11111111-2222-3333-4444-555555555555', 'mount_name': 'share-d0-p4', 'filesystem': 'ntfs', 'steam_library': True}


def config():
    return {'schema': 1, 'user': 'deck', 'uid': 1000, 'gid': 1000, 'mounts': [runtime.entry(SELECTION)]}


def parent():
    return {'target': config()['mounts'][0]['parent'], 'source': '/dev/test4', 'fstype': 'ntfs3', 'fsroot': '/', 'maj:min': '8:4', 'id': 123,
            'options': 'rw,noexec,nosuid,nodev,uid=1000,gid=1000,fmask=0133,dmask=0022,windows_names'}


def alias():
    result = parent(); result.update(target=config()['mounts'][0]['alias'], fsroot='/SteamLibrary', source='/dev/test4[/SteamLibrary]', id=124)
    result['options'] = result['options'].replace(',noexec', '')
    return result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(runtime, 'visible_mount_id', return_value=None)
        guard.start(); self.addCleanup(guard.stop)

    def test_offline_opt_in_and_timer_scopes(self):
        self.assertEqual(runtime.runtime_files([{k: v for k, v in SELECTION.items() if k != 'steam_library'}], (1000, 1000)), {})
        files = runtime.runtime_files([SELECTION], (1000, 1000))
        data = json.loads(files[runtime.CONFIG_RELATIVE]['data'])
        self.assertEqual(data, config())
        self.assertTrue(all(not item.get('user', False) and item.get('mode', 0o644) == 0o644 for item in files.values()))
        self.assertFalse(any('home/' in path for path in files))
        root_service = files['etc/systemd/system/oxp3-ntfs-steam-prepare.service']['data']
        self.assertNotIn(b'CDP', root_service)
        self.assertIn(b'OnUnitInactiveSec=60', files['etc/systemd/system/oxp3-ntfs-steam-prepare.timer']['data'])
        self.assertIn(b'ConditionUser=deck', files['etc/systemd/user/oxp3-ntfs-steam-register.service']['data'])
        self.assertEqual(runtime.unit('/var/mnt/shared/share-d0-p4'), r'var-mnt-shared-share\x2dd0\x2dp4.mount')

    def test_config_cannot_redirect_root_operations(self):
        for change in ({'alias': '/home/deck'}, {'source': '/SteamLibrary'}, {'parent': '/mnt/shared/else'}, {'mount_name': '../x'}):
            value = config(); value['mounts'][0].update(change)
            with self.assertRaises(ValueError): runtime.validate_config(value)
        value = config(); value['uid'] = True
        with self.assertRaises(ValueError): runtime.validate_config(value)
        value = config(); value['mounts'] *= 2
        with self.assertRaises(ValueError): runtime.validate_config(value)

    def test_strict_parent_and_alias_safety(self):
        runtime.parent_policy(parent(), config()); runtime.alias_policy(alias(), parent())
        for options in ('rw,exec,nosuid,nodev,uid=1000,gid=1000,fmask=0133', 'ro,noexec,nosuid,nodev,uid=1000,gid=1000,fmask=0133',
                        'rw,noexec,nosuid,nodev,uid=1000,gid=1000,fmask=0022'):
            value = parent(); value['options'] = options
            with self.assertRaises((ValueError, RuntimeError)): runtime.parent_policy(value, config())
        for change in ({'fsroot': '/'}, {'maj:min': '8:5'}, {'options': alias()['options'] + ',noexec'}):
            value = alias(); value.update(change)
            with self.assertRaises(RuntimeError): runtime.alias_policy(value, parent())

    def test_prepare_commands_only_selected_normal_mounts(self):
        calls = []
        def runner(args, timeout=30):
            calls.append(args)
            if args[0] == 'blkid': return types.SimpleNamespace(stdout='PARTUUID=' + SELECTION['partuuid'] + '\nTYPE=ntfs\n')
            if args[0] == 'findmnt':
                row = parent() if args[3] == config()['mounts'][0]['parent'] else alias()
                return types.SimpleNamespace(stdout=json.dumps({'filesystems': [row]}))
            return types.SimpleNamespace(stdout='')
        with patch.object(runtime, 'device_number', return_value='8:4'):
            result = runtime.prepare_one(config()['mounts'][0], config(), runner)
        self.assertEqual(result['status'], 'prepared')
        self.assertIn(['systemctl', 'start', '--no-block', runtime.unit(config()['mounts'][0]['parent'])], calls)
        self.assertTrue(all('--types' not in args for args in calls if args[0] == 'findmnt'))
        self.assertEqual([args[8] for args in calls if args[0] == 'runuser'], ['make-directory', 'probe'])
        self.assertFalse(any(word in {'mount', 'umount', 'ntfsfix', 'fsck', 'force', 'remove_hiberfile', 'mkfs'} for args in calls for word in args))

    def test_wrong_device_refused_before_mount_and_retry_pending(self):
        calls = []; reports = []
        def runner(args, timeout=30):
            calls.append(args); return types.SimpleNamespace(stdout='PARTUUID=' + SELECTION['partuuid'] + '\nTYPE=ext4\n')
        with patch.object(runtime.os, 'geteuid', return_value=0, create=True):
            result = runtime.prepare(config(), runner, lambda value: reports.append(copy.deepcopy(value)))
        self.assertEqual(result['mounts'][SELECTION['partuuid']]['status'], 'pending')
        self.assertEqual([args[0] for args in calls], ['blkid'])
        self.assertEqual(reports[0]['mounts'][SELECTION['partuuid']], {'status': 'pending'})

    def test_registration_requires_current_prepared_device_and_deck(self):
        value = config(); state = {'schema': 1, 'config': value, 'mounts': {SELECTION['partuuid']: {'status': 'prepared', 'device': '8:4', 'mount_id': 124}}}
        queries = []
        with patch.object(runtime.os, 'geteuid', return_value=1000, create=True), patch.object(runtime.os, 'getegid', return_value=1000, create=True), patch.object(runtime, 'find_mount', side_effect=[parent(), alias()]):
            result = runtime.register(value, state, lambda expression: queries.append(expression) or [{'status': 'existing'}])
        self.assertEqual(result['status'], 'registered'); self.assertEqual(len(queries), 1)
        self.assertIn('if(found)', queries[0]); self.assertIn("status:'existing'});continue", queries[0])
        self.assertIn('found.bIsMounted!==true', queries[0]); self.assertNotIn('RemoveInstallFolder', queries[0])
        self.assertIn("Existing library is not mounted", queries[0])
        self.assertNotIn('libraryfolders.vdf', queries[0]); self.assertNotIn('SetDefault', queries[0])
        state['config'] = 'outdated'
        with patch.object(runtime.os, 'geteuid', return_value=1000, create=True), patch.object(runtime.os, 'getegid', return_value=1000, create=True):
            with self.assertRaises(RuntimeError): runtime.register(value, state, lambda expression: self.fail('Stale report queried Steam'))

    def test_stop_only_our_units_preserves_parents_and_data(self):
        calls = []
        with patch.object(runtime.os, 'geteuid', return_value=0, create=True), patch.object(Path, 'is_socket', return_value=False), patch.object(Path, 'exists', return_value=False):
            runtime.stop(config(), lambda args, timeout=30: calls.append(args))
        self.assertEqual(calls[0][:2], ['systemctl', 'stop'])
        self.assertIn(runtime.unit(config()['mounts'][0]['alias']), calls[-1])
        self.assertNotIn(runtime.unit(config()['mounts'][0]['parent']), calls[-1])
        def busy(args, timeout=30):
            if args[-1].endswith('.mount'): raise subprocess.CalledProcessError(1, args)
        with patch.object(runtime.os, 'geteuid', return_value=0, create=True), patch.object(Path, 'is_socket', return_value=False):
            with self.assertRaises(subprocess.CalledProcessError): runtime.stop(config(), busy)

    def test_transport_rejects_remote_targets_before_connect(self):
        for url in ('ws://example.com:8080/devtools/page/1', 'ws://127.0.0.1:9999/devtools/page/1', 'ws://user@127.0.0.1:8080/devtools/page/1', 'ws://127.0.0.1:8080/path\r\nInjected: 1'):
            with patch.object(runtime.socket, 'create_connection', side_effect=AssertionError('Network forbidden')):
                with self.assertRaises(RuntimeError): runtime.WebSocket(url, 100)

    def test_execution_probe_only_removes_its_own_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); existing = folder / 'game.exe'; existing.write_bytes(b'untouched')
            item = {'alias': temporary, 'source': '/var/mnt/shared/share-d0-p4/SteamLibrary'}
            calls = []
            def execute(args, **kwargs):
                calls.append(args[0])
                if len(calls) == 2: raise PermissionError('parent noexec')
                self.assertTrue(Path(args[0]).read_bytes().startswith(b'#!/bin/sh'))
                return types.SimpleNamespace(returncode=0)
            with patch.object(runtime.os, 'fchmod', create=True), patch.object(runtime.subprocess, 'run', side_effect=execute):
                runtime.probe(item)
            self.assertEqual([path.name for path in folder.iterdir()], ['game.exe'])
            self.assertEqual(existing.read_bytes(), b'untouched')
            self.assertEqual(Path(calls[0]).name, Path(calls[1]).name)
            with patch.object(runtime.os, 'fchmod', create=True), patch.object(runtime.subprocess, 'run', side_effect=PermissionError('alias denied')):
                with self.assertRaises(PermissionError): runtime.probe(item)
            self.assertEqual([path.name for path in folder.iterdir()], ['game.exe'])

    def test_transport_rejects_oversized_frames_before_reading_body(self):
        websocket = runtime.WebSocket.__new__(runtime.WebSocket)
        chunks = iter([bytes([129, 127]), (runtime.MAXIMUM + 1).to_bytes(8, 'big')])
        websocket.read = lambda size: next(chunks)
        with self.assertRaisesRegex(RuntimeError, 'limit'): websocket.receive()

    def test_idle_autofs_stopped_before_inspecting_uncovered_directory(self):
        calls = []
        def runner(args, timeout=30):
            calls.append(args)
            if args[0] == 'findmnt': raise subprocess.CalledProcessError(1, args)
        with patch.object(runtime, 'alias_directory', side_effect=lambda path: calls.append(['inspect', path])):
            runtime.uncovered_alias(config()['mounts'][0], runner)
        self.assertEqual(calls[0], ['systemctl', 'stop', r'var-mnt-steam\x2dlibraries-share\x2dd0\x2dp4.automount'])
        self.assertEqual(calls[1][0], 'findmnt'); self.assertEqual(calls[2][0], 'inspect')
        def mounted(args, timeout=30):
            return types.SimpleNamespace(stdout=json.dumps({'filesystems': [{'target': config()['mounts'][0]['alias'], 'fstype': 'autofs'}]}))
        with patch.object(runtime, 'alias_directory', side_effect=AssertionError('Mounted contents must never be inspected')):
            with self.assertRaises(RuntimeError): runtime.uncovered_alias(config()['mounts'][0], mounted)

    def test_same_mount_skips_repeated_probe_but_changed_id_reprobes(self):
        def runner(args, timeout=30):
            if args[0] == 'blkid': return types.SimpleNamespace(stdout='PARTUUID=' + SELECTION['partuuid'] + '\nTYPE=ntfs\n')
            if args[0] == 'findmnt': return types.SimpleNamespace(stdout=json.dumps({'filesystems': [parent() if args[3] == config()['mounts'][0]['parent'] else alias()]}))
            return types.SimpleNamespace(stdout='')
        previous = {'status': 'prepared', 'mount_id': 124, 'device': '8:4'}
        with patch.object(runtime, 'device_number', return_value='8:4'), patch.object(runtime, 'as_deck') as deck:
            runtime.prepare_one(config()['mounts'][0], config(), runner, previous)
            self.assertEqual([call.args[0] for call in deck.call_args_list], ['make-directory'])
            deck.reset_mock(); previous['mount_id'] = 100
            runtime.prepare_one(config()['mounts'][0], config(), runner, previous)
            self.assertEqual([call.args[0] for call in deck.call_args_list], ['make-directory', 'probe'])

    def test_parent_additional_safety_flags_are_mandatory(self):
        for remove in (',windows_names', ',dmask=0022'):
            row = parent(); row['options'] = row['options'].replace(remove, '')
            with self.assertRaises((ValueError, RuntimeError)): runtime.parent_policy(row, config())
        for unsafe in ('force', 'remove_hiberfile'):
            row = parent(); row['options'] += ',' + unsafe
            with self.assertRaises(RuntimeError): runtime.parent_policy(row, config())

    def test_mount_parser_accepts_only_expected_autofs_and_visible_ntfs(self):
        row = parent()
        auto = {'target': row['target'], 'source': 'systemd-1', 'fstype': 'autofs', 'fsroot': '/', 'options': 'rw,relatime,direct', 'id': 122}
        def inspect(rows, visible=123):
            runner = lambda args, timeout=30: types.SimpleNamespace(stdout=json.dumps({'filesystems': rows}))
            with patch.object(runtime, 'visible_mount_id', return_value=visible): return runtime.find_mount(row['target'], runner)
        self.assertEqual(inspect([auto, row]), row)
        nested = dict(auto, children=[row])
        self.assertEqual(inspect([nested]), row)
        foreign = dict(row, fstype='tmpfs', source='tmpfs', id=125)
        for rows in ([auto, row, foreign], [row, dict(foreign, fstype='ext4')], [row, row], [auto], [dict(auto, source='untrusted'), row], [dict(auto, options='rw'), row], [auto, auto, row]):
            with self.assertRaises(RuntimeError): inspect(rows)
        with self.assertRaisesRegex(RuntimeError, 'visible'): inspect([auto, row], visible=125)

    def test_only_new_unsafe_binds_are_stopped_and_async_pending_is_retained(self):
        item = config()['mounts'][0]
        for failure, must_stop in ((RuntimeError('Covering foreign filesystem'), True), (runtime.MountPending('Still mounting'), False)):
            calls = []
            with patch.object(runtime, 'check_device'), patch.object(runtime, 'device_number', return_value='8:4'), patch.object(runtime, 'as_deck'), patch.object(runtime, 'uncovered_alias'), patch.object(runtime.os, 'lstat', return_value=types.SimpleNamespace(st_mode=0o040755)), patch.object(runtime, 'find_mount', side_effect=[parent(), runtime.MountPending('Uncovered'), parent(), failure]):
                with self.assertRaises(RuntimeError): runtime.prepare_one(item, config(), lambda args, timeout=30: calls.append(args))
            self.assertEqual(['systemctl', 'stop', runtime.unit(item['alias'])] in calls, must_stop)
        bad_alias = alias(); bad_alias['fsroot'] = '/'
        calls = []
        with patch.object(runtime, 'check_device'), patch.object(runtime, 'device_number', return_value='8:4'), patch.object(runtime, 'as_deck'), patch.object(runtime, 'find_mount', side_effect=[parent(), bad_alias]):
            with self.assertRaises(RuntimeError): runtime.prepare_one(item, config(), lambda args, timeout=30: calls.append(args))
        self.assertFalse(any(args[:2] == ['systemctl', 'stop'] for args in calls))


if __name__ == '__main__': unittest.main()
