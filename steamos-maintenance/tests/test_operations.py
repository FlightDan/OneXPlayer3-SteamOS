from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import cli, gui, operations as op


class OperationTests(unittest.TestCase):
    def test_upgrade_retains_old_thirdparty_selection_files_and_managed_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, payload = base / 'root', base / 'payload'
            root.mkdir()
            store = op.Store(root, base / 'state', enforce_owner=False)
            relative = 'home/deck/homebrew/plugins/decky-steamgriddb/main.py'
            store.apply({relative: {'data': b'previously installed plugin', 'component': 'steamgriddb',
                                    'mode': 0o644, 'mutable': False, 'user': True}},
                        {'version': 'old'}, ['steamgriddb'], 'here', legacy_selected=[])
            before = store.managed()
            plugin_record = store._index()['slots']['here']['current']['paths'][relative]
            (payload / 'components').mkdir(parents=True)
            (payload / 'integration').mkdir()
            # Even an older authenticated payload still advertising this plugin
            # must leave it outside the automatic update scope.
            (payload / 'components/options.json').write_text(json.dumps({'schema': 1, 'repairs': [],
                'plugins': [{'id': 'steamgriddb', 'dependencies': []}]}))
            (payload / 'integration/manifest.json').write_text('{}')
            system = {'slot': {'id': 'here'}, 'os': dict(op.probe.BASE), 'kernel': op.probe.KERNEL,
                      'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}}
            packages = mock.Mock()
            packages._read.return_value = None
            with mock.patch.object(op, 'PackageStore', return_value=packages), \
                 mock.patch.object(op.probe, 'verify_shared', return_value=True), \
                 mock.patch.object(op.probe, 'verify_shared_os', return_value=True), \
                 mock.patch.object(op.adoption, 'import_originals') as adoption:
                plan, originals = op.prepare(payload, [], system, store)
            self.assertEqual(plan['selected'], [])
            self.assertIn('steamgriddb', plan['retained'])
            self.assertEqual(plan['files'], {})
            self.assertEqual(originals, {})
            adoption.assert_not_called()
            self.assertEqual(store.managed(), before)
            # Exercise the real transaction commit to ensure an engine upgrade
            # cannot turn omission from the catalog into an uninstall.
            store.apply(plan['files'], {'version': 'new'}, plan['selected'], 'here',
                        legacy_selected=plan['legacy_selected'])
            self.assertEqual((root / relative).read_bytes(), b'previously installed plugin')
            self.assertEqual(store.managed(), before)
            self.assertEqual(store._index()['slots']['here']['current']['paths'][relative], plugin_record)

    def test_plans_keep_prior_selection_and_filter_other_slot_root_ownership(self):
        store = mock.Mock()
        store.managed.return_value = {'paths': {
            'var/lib/foreign': {'component': 'decky', 'slots': ['other'], 'scope': 'slot'},
            'var/lib/own': {'component': 'input', 'slots': ['here'], 'scope': 'slot'},
            'opt/shared': {'component': 'opti2xmx', 'slots': ['other'], 'scope': 'shared'}}, 'components': {}}
        system = {'slot': {'id': 'here'}, 'os': dict(op.probe.BASE), 'kernel': op.probe.KERNEL,
                  'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}}
        packages = mock.Mock()
        packages._read.return_value = None
        with tempfile.TemporaryDirectory() as temporary:
            payload = Path(temporary)
            (payload / 'components').mkdir()
            (payload / 'components/options.json').write_text(json.dumps({'schema': 1, 'repairs': [
                {'id': name, 'dependencies': []} for name in ('input', 'hdr')], 'plugins': []}))
            with mock.patch.object(op, 'current_selection', return_value=['input']), \
                 mock.patch.object(op, 'PackageStore', return_value=packages), \
                 mock.patch.object(op.probe, 'verify_shared', return_value=True), \
                 mock.patch.object(op.probe, 'verify_shared_os', return_value=True), \
                 mock.patch.object(op.adoption, 'import_originals', return_value={}), \
                 mock.patch.object(op, 'build_plan', return_value={'selected': ['input', 'hdr'], 'files': {},
                     'components': {name: {'status': 'ready', 'dependencies': [], 'units': []} for name in ('input', 'hdr')}}) as build:
                op.prepare(payload, ['hdr'], system, store)
        self.assertEqual(build.call_args.args[2], ['input', 'hdr'])
        managed = build.call_args.args[4]['paths']
        self.assertNotIn('var/lib/foreign', managed)
        self.assertIn('var/lib/own', managed)
        self.assertIn('opt/shared', managed)

    def test_runtime_has_public_version_user_timer_and_no_os_update_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'entry.py').write_text('pass\n')
            (root / 'OXP3-Maintenance.desktop').write_text('[Desktop Entry]\n')
            with mock.patch.object(op, 'RUNTIME', root / 'not-installed'):
                files = op.runtime_files(root, {'version': '0.1.0-beta'}, {'components': {}})
            self.assertIn('usr/local/lib/oxp3-maintenance/current-release.json', files)
            self.assertTrue(files['home/deck/.config/systemd/user/oxp3-maintenance-check.timer']['user'])
            serialized = '\n'.join(files) + '\n' + '\n'.join(v['data'].decode(errors='ignore') for v in files.values())
            self.assertNotIn('atomupd', serialized)
            self.assertNotIn('rauc.service', serialized)
            self.assertNotIn('pacman -Syu', serialized)

    def test_success_keeps_service_enables_and_restores_readonly(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            def command(*args, **kwargs):
                calls.append(args)
                if args == ('steamos-readonly', 'status'):
                    return 'enabled'
                if args[:2] == ('systemctl', 'is-enabled'):
                    return 'disabled'
                return 'inactive'
            with mock.patch.object(op, 'STATE', Path(temporary)), mock.patch.object(op, 'command', side_effect=command):
                with op.live_write(None, {'slot': {'id': 'here'}}, ['new.service']):
                    command('systemctl', 'enable', 'new.service')
            self.assertIn(('steamos-readonly', 'enable'), calls)
            self.assertNotIn(('systemctl', 'disable', 'new.service'), calls)
            self.assertFalse((Path(temporary) / 'live-operation.json').exists())

    def test_failure_preserves_journal_and_does_not_suppress_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            def command(*args, **kwargs):
                return 'enabled' if args == ('steamos-readonly', 'status') else 'inactive'
            with mock.patch.object(op, 'STATE', Path(temporary)), mock.patch.object(op, 'command', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'failed midway'):
                    with op.live_write(None, {'slot': {'id': 'here'}}, []):
                        raise RuntimeError('failed midway')
            self.assertTrue((Path(temporary) / 'live-operation.json').exists())

    def test_guard_refuses_pending_writes_before_services_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'pending.json').write_text('{}')
            info = SimpleNamespace(st_uid=0, st_mode=0o40700)
            with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
                 mock.patch.object(op.probe, 'live', return_value={'compatible': True, 'slot': {'id': 'here'}}), \
                 mock.patch.object(op, 'STATE', state), mock.patch.object(Path, 'lstat', return_value=info), \
                 mock.patch.object(op, 'store_for') as store:
                with self.assertRaisesRegex(RuntimeError, 'recovery'):
                    cli.dispatch(cli.parser().parse_args(['guard']))
                store.assert_not_called()  # systemctl child cannot take the parent's lock.

    def test_service_restart_observes_coherent_durable_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            def command(*args, **kwargs):
                if args == ('steamos-readonly', 'status'):
                    return 'enabled'
                if args[:2] == ('systemctl', 'is-active'):
                    return 'active'
                if args[:2] == ('systemctl', 'is-enabled'):
                    return 'enabled'
                if args[:2] == ('systemctl', 'show'):
                    return 'loaded'
                if args[:2] == ('systemctl', 'start'):
                    self.assertEqual(json.loads((state / 'live-operation.json').read_text())['phase'], 'coherent')
                return ''
            with mock.patch.object(op, 'STATE', state), mock.patch.object(op, 'command', side_effect=command):
                with op.live_write(None, {'slot': {'id': 'here'}}, ['fan.service']):
                    pass

    def test_original_and_generation_service_states_are_durable(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            store = mock.Mock()
            store.status.return_value = {'slots': {'here': {'current': {'id': 1}}}}
            system = {'slot': {'id': 'here'}}
            old = {'fan.service': {'active': False, 'enabled': 'disabled'}}
            new = {'fan.service': {'active': True, 'enabled': 'enabled'}}
            with mock.patch.object(op, 'STATE', state), mock.patch.object(op, '_unit_state', return_value=old):
                op._service_history(store, system, ['fan.service'], remember=True)
            store.status.return_value['slots']['here']['current']['id'] = 2
            with mock.patch.object(op, 'STATE', state), mock.patch.object(op, '_unit_state', return_value=new):
                original, history = op._service_history(store, system, ['fan.service'], remember=True)
            self.assertEqual(original, old)
            self.assertEqual(history['1'], old)
            self.assertEqual(history['2'], new)

    def test_low_disk_refuses_before_any_service_mutation(self):
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(op, 'STATE', Path(temporary)), \
             mock.patch.object(op.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
             mock.patch.object(op, 'command') as command:
            with self.assertRaisesRegex(RuntimeError, 'space'):
                op.check_space({'etc/test': {'data': b'new'}})
            command.assert_not_called()

    def test_advertised_version_must_match_signed_manifest(self):
        args = SimpleNamespace(bundle=None, bundle_dir='/untrusted', expected_version='0.2.0-beta', expected_manifest=None)
        with mock.patch.object(op, 'verify_directory', return_value={'release': {'version': '0.1.0-beta'}, 'files': {}}):
            with self.assertRaisesRegex(RuntimeError, 'advertised'):
                with op.authenticated(args):
                    self.fail('must reject replay')

    def test_reviewed_manifest_cannot_be_swapped(self):
        args = SimpleNamespace(bundle=None, bundle_dir='/untrusted', expected_version=None, expected_manifest='0' * 64)
        with mock.patch.object(op, 'verify_directory', return_value={'release': {'version': '0.1.0-beta'}, 'files': {}}):
            with self.assertRaisesRegex(RuntimeError, 'changed after review'):
                with op.authenticated(args):
                    self.fail('must reject changed package')

    def test_recovery_unlocks_root_before_resuming_file_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'live-operation.json').write_text(json.dumps({'slot': 'here', 'readonly': 'enabled', 'services': {},
                'file_generation': 2,
                'after_services': {'new.service': {'active': False, 'enabled': 'enabled'}}}))
            store = mock.Mock()
            store.lock.return_value = nullcontext()
            store.status.return_value = {'slots': {'here': {'current': {'id': 2, 'selected': []}}}, 'pending': None}
            calls = []
            store.recover.side_effect = lambda **kwargs: calls.append(('recover',)) or {'recovered': True}
            def command(*args, **kwargs):
                calls.append(args)
                return 'enabled' if args == ('steamos-readonly', 'status') else ''
            packages = mock.Mock()
            packages.recover.return_value = {'phase': 'absent'}
            with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
                 mock.patch.object(op.probe, 'live', return_value={'slot': {'id': 'here'}}), \
                 mock.patch.object(op, 'store_for', return_value=store), mock.patch.object(op, 'STATE', state), \
                 mock.patch.object(op, 'command', side_effect=command), mock.patch.object(op, 'PackageStore', return_value=packages):
                op.restore(SimpleNamespace(select=[]), recovery=True)
            self.assertLess(calls.index(('steamos-readonly', 'disable')), calls.index(('recover',)))
            self.assertEqual(calls[-1], ('steamos-readonly', 'enable'))
            self.assertIn(('systemctl', 'enable', 'new.service'), calls)

    def test_recovery_service_intent_is_bound_to_the_committed_file_generation(self):
        for generation, use_after in ((1, False), (2, True), (3, False)):
            with self.subTest(generation=generation), tempfile.TemporaryDirectory() as temporary:
                state = Path(temporary)
                before = {'old.service': {'active': False, 'enabled': 'enabled'},
                          'new.service': {'active': False, 'enabled': 'disabled'}}
                after = {'old.service': {'active': False, 'enabled': 'disabled'},
                         'new.service': {'active': False, 'enabled': 'enabled'}}
                (state / 'live-operation.json').write_text(json.dumps({
                    'slot': 'here', 'readonly': 'enabled', 'phase': 'writing',
                    'file_action': 'apply', 'source_generation': 1, 'file_generation': 2,
                    'services': before, 'after_services': after}))
                store = mock.Mock()
                store.lock.return_value = nullcontext()
                store.status.return_value = {'slots': {'here': {'current': {'id': generation, 'selected': []}}}}
                packages = mock.Mock()
                packages.recover.return_value = {'phase': 'absent'}
                calls = []
                def command(*args, **kwargs):
                    calls.append(args)
                    return 'enabled' if args == ('steamos-readonly', 'status') else ''
                with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
                     mock.patch.object(op.probe, 'live', return_value={'slot': {'id': 'here'}}), \
                     mock.patch.object(op, 'store_for', return_value=store), mock.patch.object(op, 'STATE', state), \
                     mock.patch.object(op, 'PackageStore', return_value=packages), mock.patch.object(op, 'command', side_effect=command):
                    op.restore(SimpleNamespace(select=[]), recovery=True)
                wanted, unwanted = ('new.service', 'old.service') if use_after else ('old.service', 'new.service')
                self.assertIn(('systemctl', 'enable', wanted), calls)
                self.assertNotIn(('systemctl', 'enable', unwanted), calls)

    def test_guard_allows_coherent_lifecycle_without_reentering_global_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            record = state / 'live-operation.json'
            info = SimpleNamespace(st_uid=0, st_mode=0o40700)
            for phase, allowed in (('writing', False), ('coherent', True)):
                record.write_text(json.dumps({'slot': 'here', 'phase': phase}))
                with mock.patch.object(op, 'require_root'), mock.patch.object(op, 'trusted_code'), \
                     mock.patch.object(op.probe, 'live', return_value={'compatible': True, 'slot': {'id': 'here'}}), \
                     mock.patch.object(op, 'STATE', state), mock.patch.object(Path, 'lstat', return_value=info), \
                     mock.patch.object(op.adoption, '_trusted'), mock.patch.object(op, 'store_for') as store:
                    if allowed:
                        self.assertEqual(cli.dispatch(cli.parser().parse_args(['guard']))['status'], 'passed')
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'recovery'):
                            cli.dispatch(cli.parser().parse_args(['guard']))
                    store.assert_not_called()

    def test_graphical_selector_includes_optional_components_unchecked(self):
        first = {'catalog': {'repairs': [{'id': 'input', 'en': 'Input'}, {'id': 'flathub-ustc', 'en': 'Mirror'}], 'plugins': []},
                 'components': {'input': {'status': 'ready'}, 'flathub-ustc': {'status': 'ready'}},
                 'defaults': ['input']}
        calls = []
        def dialog(*args):
            calls.append(args)
            return ''
        with mock.patch.object(gui, '_backend', return_value=first), mock.patch.object(gui, '_dialog', side_effect=dialog):
            with self.assertRaises(gui.Cancelled):
                gui._apply('/signed.tar.gz', gui.EN)
        self.assertIn('flathub-ustc', calls[0])
        index = calls[0].index('flathub-ustc')
        self.assertEqual(calls[0][index + 2], 'off')

    def test_first_install_desktop_resolves_space_and_uri_paths(self):
        desktop = Path(__file__).parents[1] / 'Install-OXP3-Maintenance.desktop'
        line = next(v for v in desktop.read_text(encoding='utf-8').splitlines() if v.startswith('Exec='))
        code = line.split(' -c "', 1)[1].rsplit('" %k', 1)[0]
        with tempfile.TemporaryDirectory(prefix='oxp3 space ') as temporary:
            root = Path(temporary)
            (root / 'entry.py').write_text('import json,sys\nprint(json.dumps(sys.argv))\n')
            path = root / desktop.name
            for location in (str(path), path.as_uri()):
                result = subprocess.run([sys.executable, '-I', '-B', '-c', code, location],
                                        check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(result.stdout), [str(root / 'entry.py'), 'gui'])


if __name__ == '__main__':
    unittest.main()
