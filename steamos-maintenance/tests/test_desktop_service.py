"""Desktop controller review state and privileged command boundary regressions."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import catalog, cli, downloads, gui, probe, releases
from oxp3_maintenance.desktop_service import DesktopService


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = mock.patch.object(Path, 'home', return_value=Path(temporary.name))
        home.start()
        self.addCleanup(home.stop)
        installed = mock.patch.object(cli, 'installed_release', return_value={'version': '1.0.0', 'channel': 'stable'})
        installed.start()
        self.addCleanup(installed.stop)
        self.service = DesktopService(SimpleNamespace(bundle='/offline.tar.gz', bundle_dir=None))
        self.plan = {'release': {'version': '1.1.0'}, 'manifest_digest': 'reviewed-manifest',
                     'components': {'keyboard': {'status': 'ready', 'reason': 'Ready for transactional installation'}},
                     'selected': ['keyboard'], 'defaults': ['keyboard'], 'can_apply': True,
                     'file_count': 3, 'restart_required': True, 'retained': {'input': 'kept'},
                     'catalog': {'repairs': [{'id': 'keyboard', 'en': 'Touch keyboard'}], 'plugins': []}}
        self.applied = {'status': 'files_installed', 'restart_required': True,
                        'operation': {'changed': True, 'preserved': ['home/deck/.config/kwinrc'], 'generation': 3}}

    def test_apply_without_review_never_calls_backend(self):
        with mock.patch.object(self.service, '_backend') as backend:
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        backend.assert_not_called()

    def test_review_binds_apply_to_manifest_version_and_exact_selection(self):
        with mock.patch.object(self.service, '_backend', side_effect=[self.plan, self.applied]) as backend, \
             mock.patch.object(gui, '_after_install') as after:
            view = self.service.perform('plan', selected=['keyboard'])
            result = self.service.perform('apply')
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertTrue(view['review'])
        self.assertEqual(result['tone'], 'success')
        backend.assert_has_calls([
            mock.call('plan', ['keyboard'], tool_only=False),
            mock.call('apply', ['keyboard'], tool_only=False, expected_version='1.1.0',
                      expected_manifest='reviewed-manifest')])
        self.assertEqual(backend.call_count, 2)
        after.assert_called_once_with(self.applied)
        self.assertIsNone(self.service.review)

    def test_changing_source_prevents_apply_without_another_review(self):
        with mock.patch.object(self.service, '_backend', return_value=self.plan) as backend:
            self.service.perform('plan', selected=['keyboard'])
            self.service.source = '/another.tar.gz'
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertEqual(backend.call_count, 1)

    def test_failed_preflight_never_authorizes_apply(self):
        refused = copy.deepcopy(self.plan)
        refused['can_apply'] = False
        refused['components']['keyboard'].update(status='blocked', reason='Legacy drift')
        with mock.patch.object(self.service, '_backend', return_value=refused) as backend:
            self.assertFalse(self.service.perform('plan', selected=['keyboard'])['can_apply'])
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertEqual(backend.call_count, 1)

    def test_failed_new_review_invalidates_previous_review(self):
        with mock.patch.object(self.service, '_backend', side_effect=[self.plan, RuntimeError('New preflight failed')]) as backend:
            self.service.perform('plan', selected=['keyboard'])
            with self.assertRaisesRegex(RuntimeError, 'New preflight failed'):
                self.service.perform('plan', selected=['gyro'])
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertEqual(backend.call_count, 2)

    def test_invalid_new_selection_invalidates_previous_review(self):
        with mock.patch.object(self.service, '_backend', return_value=self.plan) as backend:
            self.service.perform('plan', selected=['keyboard'])
            with self.assertRaisesRegex(RuntimeError, 'Invalid component selection'):
                self.service.perform('plan', selected=[3])
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertEqual(backend.call_count, 1)

    def test_caller_cannot_mutate_reviewed_selection(self):
        selection = ['keyboard']
        with mock.patch.object(self.service, '_backend', side_effect=[self.plan, self.applied]) as backend, \
             mock.patch.object(gui, '_after_install'):
            self.service.perform('plan', selected=selection)
            selection.append('gyro')
            self.service.perform('apply')
        self.assertEqual(list(backend.call_args.args[1]), ['keyboard'])

    def test_import_invalidates_review_even_if_new_bundle_plan_fails(self):
        self.service.review = {'old': 'review'}
        with mock.patch.object(self.service, '_backend', side_effect=RuntimeError('Invalid signature')):
            with self.assertRaisesRegex(RuntimeError, 'Invalid signature'):
                self.service.perform('import', path='/invalid.tar.gz')
        self.assertIsNone(self.service.review)

    def test_download_has_no_privileged_backend_and_invalidates_review(self):
        self.service.candidate = {'version': '1.1.0'}
        self.service.review = {'old': 'review'}
        with mock.patch.object(downloads, 'save', return_value={'path': '/verified.tar.gz'}) as save, \
             mock.patch.object(self.service, '_backend') as backend, \
             mock.patch.object(subprocess, 'run') as run:
            view = self.service.perform('download')
        save.assert_called_once()
        backend.assert_not_called()
        run.assert_not_called()
        self.assertEqual(self.service.source, '/verified.tar.gz')
        self.assertIsNone(self.service.review)
        self.assertTrue(view['source_ready'])

    def test_discovery_authenticates_catalog_without_privileged_backend(self):
        candidate = {'version': '1.1.0', 'size': 1024}
        report = {'latest_project': {'version': '1.1.0'}, 'latest_maintenance': candidate, 'status': 'update_available'}
        value = {'signed': 'catalog'}
        described = {'components': [{'id': 'keyboard', 'en': 'Touch keyboard',
                                    'status': 'download_available', 'reason': 'Check resources'}]}
        with mock.patch.object(releases, 'check_releases', return_value=report), \
             mock.patch.object(releases, 'fetch_catalog', return_value=value) as fetch, \
             mock.patch.object(downloads, 'trusted_key', return_value=Path('/trusted.pem')), \
             mock.patch.object(catalog, 'describe', return_value=described) as describe, \
             mock.patch.object(probe, 'live', side_effect=RuntimeError('No compatible host')), \
             mock.patch.object(self.service, '_backend') as backend, \
             mock.patch.object(subprocess, 'run') as run:
            view = self.service.perform('discover')
        fetch.assert_called_once_with(candidate, Path('/trusted.pem'), progress=self.service._network_progress)
        describe.assert_called_once_with(value, None)
        backend.assert_not_called()
        run.assert_not_called()
        self.assertIs(self.service.candidate, candidate)
        self.assertIsNone(self.service.source)
        self.assertFalse(view['source_ready'])
        self.assertEqual(view['items'][0]['title'], 'Touch keyboard')

    def test_apply_refused_on_recheck_is_not_reported_as_success_or_reusable(self):
        refused = copy.deepcopy(self.plan)
        refused.update(status='preflight_refused', can_apply=False)
        refused['components']['keyboard'].update(status='blocked', reason='Changed since review')
        with mock.patch.object(self.service, '_backend', side_effect=[self.plan, refused]) as backend, \
             mock.patch.object(gui, '_after_install') as after:
            self.service.perform('plan', selected=['keyboard'])
            view = self.service.perform('apply')
            with self.assertRaisesRegex(RuntimeError, 'Review the changes again'):
                self.service.perform('apply')
        self.assertFalse(view['can_apply'])
        self.assertFalse(view['items'][0]['enabled'])
        self.assertEqual(backend.call_count, 2)
        after.assert_not_called()

    def test_failed_catalog_authentication_does_not_offer_candidate(self):
        self.service.candidate = {'version': 'old'}
        report = {'latest_project': {'version': '1.1.0'}, 'latest_maintenance': {'version': '1.1.0'}}
        with mock.patch.object(releases, 'check_releases', return_value=report), \
             mock.patch.object(releases, 'fetch_catalog', side_effect=RuntimeError('Invalid signature')), \
             mock.patch.object(self.service, '_backend') as backend:
            with self.assertRaisesRegex(RuntimeError, 'Invalid signature'):
                self.service.perform('discover')
        self.assertIsNone(self.service.candidate)
        backend.assert_not_called()

    def test_backend_uses_selected_only_and_review_bindings_with_no_write_timeout(self):
        response = SimpleNamespace(returncode=0, stdout=json.dumps(self.applied), stderr='')
        with mock.patch.object(subprocess, 'run', return_value=response) as run:
            self.service._backend('apply', ['keyboard'], expected_version='1.1.0',
                                  expected_manifest='reviewed-manifest')
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['pkexec', '/usr/bin/python3', '-I', '-B'])
        self.assertIn('--selected-only', command)
        self.assertEqual(command[command.index('--select') + 1], 'keyboard')
        self.assertEqual(command[command.index('--expected-version') + 1], '1.1.0')
        self.assertEqual(command[command.index('--expected-manifest') + 1], 'reviewed-manifest')
        self.assertIsNone(run.call_args.kwargs['timeout'])

    def test_backend_never_invokes_privileged_discovery_or_download(self):
        with mock.patch.object(subprocess, 'run') as run:
            for action in ('discover', 'download'):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    self.service._backend(action)
        run.assert_not_called()

    def test_authentication_cancellation_consumes_review_without_postinstall(self):
        response = SimpleNamespace(returncode=126, stdout='', stderr='')
        with mock.patch.object(self.service, '_backend', return_value=self.plan):
            self.service.perform('plan', selected=['keyboard'])
        with mock.patch.object(subprocess, 'run', return_value=response), \
             mock.patch.object(gui, '_after_install') as after:
            with self.assertRaisesRegex(RuntimeError, 'Authentication cancelled'):
                self.service.perform('apply')
        self.assertIsNone(self.service.review)
        after.assert_not_called()

    def test_refused_operation_log_reports_no_success(self):
        refused = copy.deepcopy(self.plan)
        refused.update(status='preflight_refused', can_apply=False)
        refused['components']['keyboard'].update(status='blocked', reason='Changed since review')
        with mock.patch.object(self.service, '_backend', return_value={'result': refused}):
            view = self.service.perform('logs')
        self.assertNotEqual(view['tone'], 'success')
        self.assertNotIn('Files and recovery records were saved', view['message'])

    def test_aborted_first_upgrade_status_identifies_retained_engine(self):
        status = {'release': {'version': '0.1.4'},
                  'system': {'os': {'VERSION_ID': '3.10'}, 'slot': {'id': 'A', 'label': 'A'}},
                  'operations': {'slots': {'A': {'current': {'selected': ['_maintenance'],
                      'legacy_selected': ['input'], 'release': {'apply_outcome': 'aborted_engine_retained'}}}},
                      'pending': None}}
        with mock.patch.object(self.service, '_backend', return_value=status):
            view = self.service.perform('status')
        self.assertIn('component upgrade was aborted', view['message'])
        self.assertIn('recovery engine was retained', view['message'])
        self.assertEqual(view['items'], [])
        self.assertIn(('Managed components', '0'), view['facts'])
        self.assertIn(('Retained legacy choices', '1'), view['facts'])

    def test_status_and_logs_return_human_views_without_private_json(self):
        status = {'release': {'version': '1.1.0'},
                  'system': {'os': {'VERSION_ID': '3.10'}, 'slot': {'id': 'A', 'label': 'A'}},
                  'operations': {'slots': {'A': {'current': {'selected': ['_maintenance', 'keyboard'],
                                                           'legacy_selected': ['input']}}}, 'pending': None},
                  'private': {'data': 'SECRET BYTES'}}
        logged = {'time': '2026-10-15', 'result': dict(self.applied, private={'snapshot': 'SECRET BYTES'})}
        with mock.patch.object(self.service, '_backend', side_effect=[status, logged]):
            status_view = self.service.perform('status')
            log_view = self.service.perform('logs')
        self.assertEqual(status_view['heading'], 'Current status')
        self.assertEqual(status_view['items'][0]['title'], 'Touch keyboard')
        self.assertEqual(log_view['heading'], 'Last operation')
        for view in (status_view, log_view):
            self.assertNotIn('SECRET BYTES', json.dumps(view))
            self.assertIsInstance(view['message'], str)
            self.assertTrue(all(isinstance(item, tuple) for item in view['facts']))


if __name__ == '__main__':
    unittest.main()
