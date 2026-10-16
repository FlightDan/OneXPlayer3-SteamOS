"""Regressions for retaining legacy repairs while updating the maintenance tool."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import cli, gui, operations as op


def system_facts():
    return {'slot': {'id': 'here', 'label': 'A'}, 'uid': 1000, 'gid': 1000,
            'os': dict(op.probe.BASE), 'kernel': op.probe.KERNEL,
            'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}}


class EngineFlowTests(unittest.TestCase):
    def test_background_pending_revision_notifies_once(self):
        from oxp3_maintenance import releases, compatibility
        report = {'status': 'maintenance_package_pending', 'candidates': [],
                  'latest_project': {'version': '0.1.4+maintenance.10', 'display_version': '0.1.4'}}
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(Path, 'home', return_value=Path(temporary)), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '0.1.4+maintenance.9'}), \
             mock.patch.object(releases, 'check_releases', return_value=report), \
             mock.patch.object(op.probe, 'live', return_value=system_facts()), \
             mock.patch.object(compatibility, 'device_supported', return_value=True), \
             mock.patch.object(cli.subprocess, 'run') as run:
            cli.check_updates(background=True)
            cli.check_updates(background=True)
            run.assert_called_once()
            self.assertEqual((Path(temporary) / '.local/state/oxp3-maintenance/notified-version').read_text(),
                             '0.1.4+maintenance.10')

    def test_online_revision_uses_update_with_exact_selected_version(self):
        from oxp3_maintenance import downloads
        candidate = {'version': '0.1.4+maintenance.10', 'display_version': '0.1.4', 'size': 1024}
        report = {'status': 'update_available', 'candidates': [candidate], 'latest_maintenance': candidate}
        with mock.patch.object(cli, 'check_updates', return_value=report), \
             mock.patch.object(cli, 'installed_release', return_value={'version': '0.1.4+maintenance.9'}), \
             mock.patch.object(downloads, 'save', return_value={'path': '/test/bundle'}), \
             mock.patch.object(gui, '_progress', return_value=nullcontext()), \
             mock.patch.object(gui, '_dialog'), mock.patch.object(gui, '_apply') as apply:
            gui._online(gui.EN, 'update')
            apply.assert_called_once_with('/test/bundle', gui.EN, updating=True,
                                          expected_version=candidate['version'], tool_only=False)

    def test_tool_only_apply_preserves_unreadable_legacy_selection(self):
        """Exercise the real apply/prepare path, including the second legacy read."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            app = directory / 'app'
            app.mkdir()
            (app / 'entry.py').write_text('pass\n')
            (app / 'OXP3-Maintenance.desktop').write_text('[Desktop Entry]\n')
            store = mock.Mock()
            store.managed.return_value = {'paths': {}, 'components': {}}
            store.status.return_value = {'slots': {}}
            store.lock.return_value = nullcontext()
            store.apply.return_value = {'generation': 1, 'changed': True}
            packages = mock.Mock()
            packages._read.return_value = None
            live = {'services': {'oxp3-maintenance-activate.service': {
                'active': False, 'enabled': 'disabled'}}}
            release = {'version': '0.2.0', 'channel': 'stable'}
            args = cli.parser().parse_args(['apply', '--tool-only'])
            with mock.patch.object(op, 'require_root'), \
                 mock.patch.object(op.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(op, 'trusted_code'), \
                 mock.patch.object(op.probe, 'live', return_value=system_facts()), \
                 mock.patch.object(op, 'store_for', return_value=store), \
                 mock.patch.object(op, 'authenticated', return_value=nullcontext((directory, {'release': release}))), \
                 mock.patch.object(cli, 'installed_release', return_value={'version': '0.1.0'}), \
                 mock.patch.object(op, 'current_selection', side_effect=RuntimeError('Untrusted legacy selection')) as selection, \
                 mock.patch.object(op, 'PackageStore', return_value=packages), \
                 mock.patch.object(op.probe, 'verify_shared') as exact_shared, \
                 mock.patch.object(op.probe, 'verify_shared_os', return_value=True), \
                 mock.patch.object(op, 'RUNTIME', directory / 'not-installed'), \
                 mock.patch.object(op, 'check_space'), \
                 mock.patch.object(op, '_service_history'), \
                 mock.patch.object(op, 'live_write', return_value=nullcontext(live)), \
                 mock.patch.object(op, '_file_intent'), \
                 mock.patch.object(op, '_save_private'), \
                 mock.patch.object(op, 'command') as command:
                result = op.apply(args)
            self.assertEqual(result['status'], 'files_installed')
            self.assertIn('_legacy_selection', result['retained'])
            self.assertGreaterEqual(selection.call_count, 2)
            self.assertEqual(store.apply.call_args.args[2], ['_maintenance'])
            self.assertTrue(all(item['component'] == '_maintenance'
                                for item in store.apply.call_args.args[0].values()))
            exact_shared.assert_not_called()
            self.assertNotIn(mock.call('systemctl', 'disable', 'oxp3-selected-components.service'), command.call_args_list)

    def test_tool_only_does_not_verify_changed_managed_host_packages(self):
        packages = mock.Mock()
        packages._read.return_value = {'phase': 'installed', 'packages': [
            {'name': 'waydroid', 'version': 'old-version', 'original_installed': False}]}
        packages._verify_installed.side_effect = RuntimeError('Managed host package is missing or changed')
        store = mock.Mock()
        store.managed.return_value = {'paths': {}, 'components': {}}
        store.status.return_value = {'slots': {}}
        with mock.patch.object(op, 'PackageStore', return_value=packages), \
             mock.patch.object(op, 'current_selection', return_value=['waydroid']), \
             mock.patch.object(op.probe, 'verify_shared') as exact_shared, \
             mock.patch.object(op.probe, 'verify_shared_os', return_value=True), \
             mock.patch.object(op, 'build_plan') as build:
            plan, originals = op.prepare(Path('/unused-payload'), [], system_facts(), store, tool_only=True)
        self.assertIn('waydroid', plan['retained'])
        self.assertEqual(plan['files'], {})
        self.assertEqual(originals, {})
        packages._verify_installed.assert_not_called()
        packages.install.assert_not_called()
        exact_shared.assert_not_called()
        build.assert_not_called()

    def test_graphical_tool_only_install_activates_user_update_timer(self):
        plan = {'release': {'version': '0.2.0'}, 'manifest_digest': 'reviewed-digest'}
        result = {'status': 'files_installed'}
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(Path, 'home', return_value=Path(temporary)), \
             mock.patch.object(gui, '_backend', side_effect=[plan, result]) as backend, \
             mock.patch.object(gui, '_dialog'), mock.patch.object(gui, '_show'), \
             mock.patch.object(gui.subprocess, 'run') as run:
            gui._apply('/download/bundle.tar.gz', gui.EN, updating=True,
                       expected_version='0.2.0', tool_only=True)
        backend.assert_has_calls([
            mock.call('plan', '/download/bundle.tar.gz', tool_only=True, expected_version='0.2.0'),
            mock.call('update', '/download/bundle.tar.gz', tool_only=True,
                      expected_version='0.2.0', expected_manifest='reviewed-digest')])
        run.assert_has_calls([
            mock.call(['systemctl', '--user', 'daemon-reload'], check=False),
            mock.call(['systemctl', '--user', 'enable', '--now', 'oxp3-maintenance-check.timer'], check=False)])

    def test_plain_cli_plan_retains_existing_separate_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'payload/components').mkdir(parents=True)
            (directory / 'payload/integration').mkdir()
            (directory / 'payload/components/options.json').write_text(json.dumps({
                'schema': 1, 'repairs': [{'id': 'slot-switch', 'default': True, 'dependencies': []}],
                'plugins': []}))
            (directory / 'payload/integration/manifest.json').write_text('{}')
            store = mock.Mock()
            store.lock.return_value = nullcontext()
            store.managed.return_value = {'paths': {}, 'components': {}}
            packages = mock.Mock()
            packages._read.return_value = None
            manifest = {'release': {'version': '0.2.0'}, '_review_digest': 'reviewed-digest'}
            with mock.patch.object(op, 'require_root'), \
                 mock.patch.object(op.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(op.probe, 'live', return_value=system_facts()), \
                 mock.patch.object(op, 'store_for', return_value=store), \
                 mock.patch.object(op, 'authenticated', return_value=nullcontext((directory, manifest))), \
                 mock.patch.object(op, 'current_selection', return_value=['slot-switch']), \
                 mock.patch.object(op, 'PackageStore', return_value=packages), \
                 mock.patch.object(op.probe, 'verify_shared', return_value=True), \
                 mock.patch.object(op.probe, 'verify_shared_os', return_value=True), \
                 mock.patch.object(cli, 'installed_component_states', return_value={}), \
                 mock.patch.object(op.adoption, 'import_originals') as adoption:
                result = cli.dispatch(cli.parser().parse_args(['plan']))
            self.assertTrue(result['can_apply'])
            self.assertEqual(result['selected'], [])
            self.assertEqual(result['components'], {})
            self.assertIn('slot-switch', result['retained'])
            self.assertEqual(result['manifest_digest'], 'reviewed-digest')
            adoption.assert_not_called()
            store.apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
