import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import x2mini_device as device


class X2MiniDeviceTests(unittest.TestCase):
    def test_json_null_recovery_or_config_is_not_absence(self):
        for relative in ('.local/state/x2mini-hdr/trial.json', '.config/kwinoutputconfig.json'):
            with self.subTest(relative=relative):
                path = self.home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('null', encoding='utf8')
                path.chmod(0o600)
                with self.assertRaises(device.LauncherError):
                    device.cleanup_launchers(self.home)
                self.assertEqual(path.read_text(encoding='utf8'), 'null')
                path.unlink()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='x2mini-hdr-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / 'deck'
        self.home.mkdir()
        self.script = self.home.joinpath(*device.SCRIPT_RELATIVE.parts)
        self.script.parent.mkdir(parents=True)
        self.script.write_text('#!/usr/bin/python3\n# fixture\n', encoding='utf-8')

    def match_device(self):
        return {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER X2 Mini PRO',
                'board_name': 'unverified'}

    def test_exact_normalized_product_allowlist(self):
        self.assertTrue(device.device_matches({'sys_vendor': 'one_netbook',
                                               'product_name': 'OneXPlayer-X2_Mini'}))
        self.assertTrue(device.device_matches(self.match_device()))
        for fields in (
                {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER X2 MINI PRO MAX'},
                {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER X2'},
                {'sys_vendor': 'ONE|NETBOOK', 'product_name': 'ONEXPLAYER X2 MINI'},
                {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER| X2 MINI'},
                {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER\u200b X2 MINI'},
                {'sys_vendor': 'OTHER', 'product_name': 'ONEXPLAYER X2 MINI'},
                {'sys_vendor': 'ONE-NETBOOK', 'board_name': 'ONEXPLAYER X2 MINI'},
                {},
                None):
            with self.subTest(fields=fields):
                self.assertFalse(device.device_matches(fields))

    def test_read_device_reads_all_three_live_fields(self):
        values = {'sys_vendor': 'ONE-NETBOOK\n', 'product_name': 'ONEXPLAYER X2 MINI\n',
                  'board_name': 'board\n'}

        def read_text(path, encoding=None):
            return values[path.name]

        with mock.patch.object(device.Path, 'read_text', autospec=True, side_effect=read_text):
            result = device.read_device()
        self.assertEqual(result, {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER X2 MINI',
                                  'board_name': 'board'})

    def test_unknown_or_partial_device_fails_closed(self):
        with mock.patch.object(device, 'read_device', return_value={
                'sys_vendor': 'ONE-NETBOOK', 'product_name': '', 'board_name': 'ONEXPLAYER X2 MINI'}):
            self.assertFalse(device.is_x2mini())

    def test_install_checks_dmi_before_any_filesystem_write(self):
        with mock.patch.object(device, 'read_device', return_value={'sys_vendor': 'Other',
                                                                    'product_name': 'ONEXPLAYER X2 MINI'}):
            result = device.install_launchers(self.home, self.script)
        self.assertEqual(result, ())
        self.assertFalse(self.home.joinpath(*device.APPLICATION_RELATIVE.parts).exists())
        self.assertFalse(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())

    def test_install_creates_both_launchers_and_private_state(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        self.assertEqual(len(installed), 2)
        app = self.home.joinpath(*device.APPLICATION_RELATIVE.parts)
        desktop = self.home / 'Desktop' / device.LAUNCHER_NAME
        escaped_script = str(self.script).replace('\\', '\\\\').replace('%', '%%')
        for path in (app, desktop):
            text = path.read_text(encoding='utf-8')
            self.assertIn('Exec=/usr/bin/python3 -I -B ', text)
            self.assertIn(escaped_script, text)
            self.assertIn('Name[zh_CN]=', text)
            self.assertIn('Comment[zh_CN]=', text)
        state_path = self.home.joinpath(*device.STATE_RELATIVE.parts)
        state = json.loads(state_path.read_text(encoding='utf-8'))
        self.assertEqual(state['schema'], 1)
        self.assertEqual(set(state['launchers']), {'applications', 'desktop'})
        if os.name == 'posix':
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(app.stat().st_mode & 0o777, 0o755)

    def test_xdg_desktop_below_home_is_preferred(self):
        config = self.home / '.config' / 'user-dirs.dirs'
        config.parent.mkdir()
        config.write_text('XDG_DESKTOP_DIR="$HOME/桌面"\n', encoding='utf-8')
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            device.install_launchers(self.home, self.script)
        self.assertTrue((self.home / '桌面' / device.LAUNCHER_NAME).is_file())
        self.assertFalse((self.home / 'Desktop').exists())

    def test_invalid_xdg_desktop_falls_back_and_explicit_outside_path_fails(self):
        config = self.home / '.config' / 'user-dirs.dirs'
        config.parent.mkdir()
        config.write_text('XDG_DESKTOP_DIR="/tmp/elsewhere"\n', encoding='utf-8')
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            device.install_launchers(self.home, self.script)
        self.assertTrue((self.home / 'Desktop' / device.LAUNCHER_NAME).is_file())

        other = Path(self.temporary.name) / 'outside'
        other.mkdir()
        second_home = Path(self.temporary.name) / 'second'
        second_home.mkdir()
        second_script = second_home.joinpath(*device.SCRIPT_RELATIVE.parts)
        second_script.parent.mkdir(parents=True)
        second_script.write_text('fixture', encoding='utf-8')
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            with self.assertRaises(device.LauncherError):
                device.install_launchers(second_home, second_script, other)
        self.assertFalse(second_home.joinpath(*device.APPLICATION_RELATIVE.parts).exists())
        self.assertFalse(second_home.joinpath(*device.STATE_RELATIVE.parts).exists())

    def test_idempotent_repeat_does_not_rewrite_owned_files(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            first = device.install_launchers(self.home, self.script)
            paths = [Path(path) for path in first]
            mtimes = [path.stat().st_mtime_ns for path in paths]
            second = device.install_launchers(self.home, self.script)
        self.assertEqual(first, second)
        self.assertEqual([path.stat().st_mtime_ns for path in paths], mtimes)

    def test_user_edits_are_preserved_and_conflict_prevents_partial_update(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
            app, desktop = map(Path, installed)
            desktop.write_text('user edit\n', encoding='utf-8')
            before_app = app.read_bytes()
            with self.assertRaises(device.LauncherConflictError):
                device.install_launchers(self.home, self.script)
        self.assertEqual(app.read_bytes(), before_app)
        self.assertEqual(desktop.read_text(encoding='utf-8'), 'user edit\n')

    def test_cleanup_removes_only_unchanged_launchers_and_does_not_read_dmi(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        app, desktop = map(Path, installed)
        desktop.write_text('user edit\n', encoding='utf-8')
        with mock.patch.object(device, 'read_device', side_effect=AssertionError('cleanup must be offline')):
            removed = device.cleanup_launchers(self.home)
        self.assertEqual(removed, (str(app),))
        self.assertFalse(app.exists())
        self.assertEqual(desktop.read_text(encoding='utf-8'), 'user edit\n')
        self.assertTrue(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())

    def test_cleanup_removes_state_when_all_owned_files_are_unchanged(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        removed = device.cleanup_launchers(self.home)
        self.assertEqual(set(removed), set(installed))
        self.assertFalse(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())

    def test_cleanup_returns_when_launcher_ownership_record_is_absent(self):
        self.assertEqual(device.cleanup_launchers(self.home), ())

    def test_cleanup_persists_interlock_even_without_launcher_receipt(self):
        self.assertEqual(device.cleanup_launchers(self.home), ())
        marker = self.home.joinpath(*device.REMOVAL_RELATIVE.parts)
        self.assertEqual(json.loads(marker.read_text(encoding='utf8')),
                         {'schema': 1, 'state': 'disabled_for_removal'})
        with self.assertRaisesRegex(device.LauncherError, 'removal is pending'):
            device.assert_trial_available(self.home)

    def test_startup_install_cannot_clear_removal_interlock(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            device.install_launchers(self.home, self.script)
            device.cleanup_launchers(self.home)
            marker = self.home.joinpath(*device.REMOVAL_RELATIVE.parts)
            before = marker.read_bytes()
            with self.assertRaisesRegex(device.LauncherError, 'removal is pending'):
                device.install_launchers(self.home, self.script)
        self.assertEqual(marker.read_bytes(), before)
        self.assertFalse(self.home.joinpath(*device.APPLICATION_RELATIVE.parts).exists())

    def test_canonical_reset_allows_trial_and_launcher_after_full_install(self):
        device.cleanup_launchers(self.home)
        device.reset_after_install(self.home)
        device.assert_trial_available(self.home)
        self.assertFalse(self.home.joinpath(*device.REMOVAL_RELATIVE.parts).exists())
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            self.assertEqual(len(device.install_launchers(self.home, self.script)), 2)
        self.assertEqual(device.reset_after_install(self.home), ())

    def test_reset_preserves_interlock_when_trial_or_saved_hdr_becomes_unsafe(self):
        device.cleanup_launchers(self.home)
        marker = self.home.joinpath(*device.REMOVAL_RELATIVE.parts)
        trial = self.home.joinpath(*device.STATE_RELATIVE.parent.parts, 'trial.json')
        trial.write_text(json.dumps(self.valid_trial('enabled')), encoding='utf8')
        trial.chmod(0o600)
        with self.assertRaisesRegex(device.LauncherError, 'recovery is pending'):
            device.reset_after_install(self.home)
        self.assertTrue(marker.exists())
        trial.unlink()
        config = self.home / '.config/kwinoutputconfig.json'
        config.parent.mkdir()
        config.write_text(json.dumps([{'name': 'outputs', 'data': [
            {'connectorName': 'eDP-1', 'highDynamicRange': True}]}]), encoding='utf8')
        with self.assertRaisesRegex(device.LauncherError, 'still has HDR'):
            device.reset_after_install(self.home)
        self.assertTrue(marker.exists())

    def test_corrupt_interlock_is_preserved_and_fails_closed(self):
        device.cleanup_launchers(self.home)
        marker = self.home.joinpath(*device.REMOVAL_RELATIVE.parts)
        for content in ('null', '{broken', '{}'):
            marker.write_text(content, encoding='utf8')
            for action in (device.assert_trial_available, device.reset_after_install, device.cleanup_launchers):
                with self.subTest(content=content, action=action.__name__):
                    with self.assertRaises(device.LauncherError):
                        action(self.home)
                    self.assertEqual(marker.read_text(encoding='utf8'), content)

    def test_cleanup_uses_same_trial_lock_for_checks_and_durable_barrier(self):
        events = []
        from contextlib import contextmanager
        @contextmanager
        def locked(home, owner):
            events.append('lock')
            yield
            events.append('unlock')
        def terminal(home, owner):
            self.assertEqual(events, ['lock'])
            events.append('terminal')
        def saved_off(home, owner):
            self.assertEqual(events, ['lock', 'terminal'])
            events.append('off')
        original_atomic = device._atomic_write
        def write(*args, **kwargs):
            self.assertEqual(events, ['lock', 'terminal', 'off'])
            events.append('marker')
            return original_atomic(*args, **kwargs)
        # Prepare private state before replacing the lock implementation seam.
        device.reset_after_install(self.home)
        with mock.patch.object(device, '_trial_lock', side_effect=locked), \
             mock.patch.object(device, '_assert_trial_is_terminal', side_effect=terminal), \
             mock.patch.object(device, '_assert_persisted_hdr_is_off', side_effect=saved_off), \
             mock.patch.object(device, '_atomic_write', side_effect=write):
            device.cleanup_launchers(self.home)
        self.assertEqual(events, ['lock', 'terminal', 'off', 'marker', 'unlock'])

    def test_root_reset_delegates_trusted_source_to_target_user(self):
        with mock.patch.object(device, '_should_delegate_root_cleanup', return_value=True), \
             mock.patch.object(device, '_home_info', return_value=(self.home, (1234, 2345))), \
             mock.patch.object(device, '_cleanup_as_home_user', return_value=()) as worker:
            self.assertEqual(device.reset_after_install(self.home), ())
        worker.assert_called_once_with(self.home, (1234, 2345), reset=True)

    def test_missing_launcher_receipt_does_not_bypass_recovery_safety(self):
        trial_path = self.home.joinpath(*device.STATE_RELATIVE.parent.parts, 'trial.json')
        trial_path.parent.mkdir(parents=True, mode=0o700)
        trial_path.write_text('{corrupt but not ours}', encoding='utf-8')
        trial_path.chmod(0o600)
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        self.assertEqual(trial_path.read_text(encoding='utf-8'), '{corrupt but not ours}')
        trial_path.write_text(json.dumps(self.valid_trial('visible')), encoding='utf8')
        with self.assertRaisesRegex(device.LauncherError, 'recovery is pending'):
            device.cleanup_launchers(self.home)
        trial_path.unlink()
        config = self.home / '.config/kwinoutputconfig.json'
        config.parent.mkdir()
        config.write_text(json.dumps([{'name': 'outputs', 'data': [
            {'connectorName': 'eDP-1', 'highDynamicRange': True, 'wideColorGamut': True}]}]), encoding='utf8')
        with self.assertRaisesRegex(device.LauncherError, 'still has HDR'):
            device.cleanup_launchers(self.home)

    def test_canonical_renamed_module_is_allowed_for_root_delegation(self):
        canonical = self.home / 'x2mini_hdr_device.py'
        with mock.patch.object(device, '__file__', str(canonical)), \
             mock.patch.object(device, '_effective_uid', return_value=0), \
             mock.patch.object(device, '_root_trusted_file', return_value=b'# canonical source'):
            path, source = device._trusted_module_source()
        self.assertEqual(path, canonical)
        self.assertEqual(source, '# canonical source')

    @staticmethod
    def valid_trial(phase):
        return {'profile': 'X2MINI_HDR_TRIAL_475_700_V1', 'token': 'a' * 32,
                'phase': phase, 'deadline': 123.0, 'original': {'hdr': False, 'wcg': False},
                'boot': 'fixture'}

    def test_cleanup_refuses_pending_trial_without_deleting_anything(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        trial_path = self.home.joinpath(*device.STATE_RELATIVE.parent.parts, 'trial.json')
        trial_path.write_text(json.dumps(self.valid_trial('rollback_failed')), encoding='utf-8')
        trial_path.chmod(0o600)
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        self.assertTrue(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())
        self.assertTrue(all(Path(path).exists() for path in installed))

    def test_cleanup_refuses_corrupt_trial_or_kwin_state(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        trial_path = self.home.joinpath(*device.STATE_RELATIVE.parent.parts, 'trial.json')
        trial_path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        trial_path.unlink()
        config = self.home / '.config' / 'kwinoutputconfig.json'
        config.parent.mkdir()
        config.write_text('{broken', encoding='utf-8')
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        self.assertTrue(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())
        for field in ('highDynamicRange', 'wideColorGamut'):
            config.write_text(json.dumps([{'name': 'outputs', 'data': [
                {'connectorName': 'eDP-1', field: True}]}]), encoding='utf-8')
            with self.subTest(field=field):
                with self.assertRaises(device.LauncherError):
                    device.cleanup_launchers(self.home)
                self.assertTrue(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())
                self.assertTrue(all(Path(path).exists() for path in installed))

    def test_cleanup_rejects_symlinked_recovery_state(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        trial_path = self.home.joinpath(*device.STATE_RELATIVE.parent.parts, 'trial.json')
        target = Path(self.temporary.name) / 'external-trial.json'
        target.write_text(json.dumps(self.valid_trial('reverted')), encoding='utf-8')
        try:
            trial_path.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.skipTest('Symlink creation unavailable: ' + str(error))
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        self.assertTrue(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())
        self.assertTrue(all(Path(path).exists() for path in installed))

    def test_root_cleanup_drops_to_target_uid_gid_and_uses_trusted_source(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0,
                                                stdout=json.dumps({'removed': ['launcher.desktop']}),
                                                stderr='')
        with (mock.patch.object(device, '_should_delegate_root_cleanup', return_value=True),
              mock.patch.object(device, '_home_info', return_value=(self.home, (1234, 2345))),
              mock.patch.object(device, '_trusted_module_source',
                                return_value=(Path('/usr/lib/oxp3/x2mini_device.py'), 'trusted source')),
              mock.patch.object(device, '_trusted_python_executable', return_value='/usr/bin/python3'),
              mock.patch.object(device.subprocess, 'run', return_value=completed) as run):
            removed = device.cleanup_launchers(self.home)
        self.assertEqual(removed, ('launcher.desktop',))
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['/usr/bin/python3', '-I', '-B', '-c'])
        self.assertEqual(command[5], str(self.home))
        self.assertIn("source = 'trusted source'", command[4])
        self.assertIn("namespace[\"cleanup_launchers\"](sys.argv[1])", command[4])
        self.assertNotIn(str(self.script), command[4])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs['user'], 1234)
        self.assertEqual(kwargs['group'], 2345)
        self.assertEqual(kwargs['extra_groups'], [])
        self.assertEqual(kwargs['cwd'], '/')
        self.assertEqual(kwargs['env']['HOME'], str(self.home))

    def test_cleanup_rejects_unsafe_state_paths_before_removing_anything(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            installed = device.install_launchers(self.home, self.script)
        state_path = self.home.joinpath(*device.STATE_RELATIVE.parts)
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['launchers']['desktop']['path'] = '../../outside/x2mini-hdr.desktop'
        state_path.write_text(json.dumps(state), encoding='utf-8')
        with self.assertRaises(device.LauncherError):
            device.cleanup_launchers(self.home)
        self.assertTrue(Path(installed[0]).exists())
        self.assertTrue(Path(installed[1]).exists())

    def test_symlinked_managed_ancestor_is_refused(self):
        outside = Path(self.temporary.name) / 'outside'
        outside.mkdir()
        share = self.home / '.local' / 'share'
        try:
            share.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest('Symlink creation unavailable: ' + str(error))
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            with self.assertRaises(device.LauncherError):
                device.install_launchers(self.home, self.script)
        self.assertFalse((outside / 'applications').exists())

    def test_script_path_must_be_the_fixed_home_relative_runtime_path(self):
        with mock.patch.object(device, 'read_device', return_value=self.match_device()):
            with self.assertRaises(device.LauncherError):
                device.install_launchers(self.home, self.home / 'unexpected.py')
        self.assertFalse(self.home.joinpath(*device.APPLICATION_RELATIVE.parts).exists())
        self.assertFalse(self.home.joinpath(*device.STATE_RELATIVE.parts).exists())


if __name__ == '__main__':
    unittest.main()
