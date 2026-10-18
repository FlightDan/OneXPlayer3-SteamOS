"""Overview cache freshness through the real worker/completion dispatch."""
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance.touch_ui import TouchWindow


class DeferredThread:
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class TouchOverviewRefreshTests(unittest.TestCase):
    def setUp(self):
        self.version = '0.1.4+maintenance.1'
        self.callbacks = []
        self.service = SimpleNamespace(
            mutating_actions={'apply', 'rollback', 'restore', 'recover'},
            preferences={'enabled': True},
            has_source=False, perform=mock.Mock(side_effect=self.perform_service))
        self.ui = ui = TouchWindow.__new__(TouchWindow)
        ui.service = self.service
        ui.busy = ui.mutating = ui.closed = ui.reviewing = False
        ui.route = 'repairs'
        ui.views = {'overview': self.overview(), 'repairs': {'heading': 'Selection'}}
        ui.selections, ui.selected = {}, set()
        ui.retry_task = None
        ui.text = {name: name for name in ('working', 'mutating', 'done', 'ready', 'error')}
        for name in ('spinner', 'progress', 'retry_button', '_notice', '_sensitivity', '_render', '_cancel_confirm'):
            setattr(ui, name, mock.Mock())
        ui.scroll = SimpleNamespace(get_vadjustment=lambda: mock.Mock())
        ui.GLib = SimpleNamespace(idle_add=lambda callback, *args: self.callbacks.append((callback, args)),
                                 timeout_add=mock.Mock())
        self.thread = mock.patch('oxp3_maintenance.touch_ui.threading.Thread', DeferredThread)
        self.thread.start()
        self.addCleanup(self.thread.stop)

    def overview(self):
        return {'heading': 'Overview', 'facts': [('Installed project', self.version)]}

    def perform_service(self, action, **params):
        if action == 'overview':
            return self.overview()
        if action in self.service.mutating_actions:
            self.version = '0.1.4+maintenance.2'
            return {'heading': 'Completed', 'tone': 'success'}
        return {'heading': action}

    def complete(self):
        callback, args = self.callbacks.pop(0)
        callback(*args)

    def test_successful_apply_invalidates_old_overview_then_navigation_reads_new_release(self):
        old = self.ui.views['overview']
        self.ui.perform('apply')
        # A worker result never touches GTK state before its idle callback.
        self.assertIs(self.ui.views['overview'], old)
        self.assertTrue(self.ui.busy)
        self.ui._render.assert_not_called()
        self.complete()
        self.assertNotIn('overview', self.ui.views)
        self.ui.navigate('overview')
        self.assertTrue(self.ui.busy)
        self.assertEqual(self.service.perform.call_args_list, [mock.call('apply'), mock.call('overview')])
        self.assertNotIn('overview', self.ui.views)
        self.complete()
        self.assertFalse(self.ui.busy)
        self.assertEqual(self.ui.views['overview']['facts'][0][1], '0.1.4+maintenance.2')

    def test_all_successful_mutating_actions_invalidate_overview(self):
        for action in ('rollback', 'restore', 'recover'):
            with self.subTest(action=action):
                self.ui.views['overview'] = self.overview()
                self.ui.perform(action)
                self.complete()
                self.assertNotIn('overview', self.ui.views)

    def test_nonmutating_result_keeps_other_cached_views(self):
        old = self.ui.views['overview']
        self.ui.perform('logs')
        self.complete()
        self.assertIs(self.ui.views['overview'], old)
        self.assertEqual(self.service.perform.call_args_list, [mock.call('logs')])

    def test_failed_apply_does_not_claim_new_release_and_navigation_reads_authoritative_overview(self):
        old = self.ui.views['overview']
        self.service.perform.side_effect = RuntimeError('Authentication cancelled')
        self.ui.perform('apply')
        self.complete()
        self.assertIs(self.ui.views['overview'], old)
        self.assertEqual(self.version, '0.1.4+maintenance.1')
        self.ui._notice.assert_called_with('error\nAuthentication cancelled', 'failure')
        self.service.perform.side_effect = self.perform_service
        self.ui.navigate('overview')
        self.complete()
        self.assertEqual(self.ui.views['overview']['facts'][0][1], '0.1.4+maintenance.1')

    def test_overview_navigation_refreshes_even_when_cached_and_busy_guard_prevents_overlap(self):
        self.ui.busy = True
        self.ui.navigate('overview')
        self.assertEqual(self.ui.route, 'repairs')
        self.service.perform.assert_not_called()
        self.ui.busy = False
        self.ui.navigate('overview')
        self.assertTrue(self.ui.busy)
        self.ui.navigate('overview')
        self.service.perform.assert_called_once_with('overview')
        self.complete()
        self.assertFalse(self.ui.busy)

    def test_launch_checks_once_and_opens_results(self):
        self.ui.views.pop('repairs')
        self.ui.startup_pending = True
        self.ui.perform('overview', route='overview')
        self.complete()
        self.service.perform.assert_called_with('discover')
        self.assertFalse(self.ui.startup_pending)
        self.complete()
        self.assertEqual(self.ui.route, 'repairs')
        self.ui.navigate('overview')
        self.complete()
        self.assertEqual([c.args[0] for c in self.service.perform.call_args_list],
                         ['overview', 'discover', 'overview'])

    def test_launch_respects_disabled_checks(self):
        self.ui.views.pop('repairs')
        self.service.preferences['enabled'] = False
        self.ui.startup_pending = True
        self.ui.perform('overview', route='overview')
        self.complete()
        self.service.perform.assert_called_once_with('overview')
        self.assertEqual(self.ui.route, 'overview')
        self.assertFalse(self.ui.startup_pending)

    def test_launch_imports_explicit_bundle_even_with_checks_disabled(self):
        self.ui.views.pop('repairs')
        self.service.preferences['enabled'] = False
        self.service.has_source = True
        self.service.source = '/offline/catalog.json'
        self.ui.initial_imported = False
        self.ui.startup_pending = True
        self.ui.perform('overview', route='overview')
        self.complete()
        self.service.perform.assert_called_with('import', path='/offline/catalog.json')
        self.complete()
        self.assertEqual(self.ui.route, 'repairs')

    def test_failed_automatic_check_is_retryable_and_never_applies(self):
        self.ui.views.pop('repairs')
        self.ui.startup_pending = True
        self.service.perform.side_effect = [self.overview(), RuntimeError('offline'), {'items': []}]
        self.ui.perform('overview', route='overview')
        self.complete()
        self.complete()
        self.assertEqual(self.ui.retry_task, ('discover', {}, None))
        self.ui._retry()
        self.complete()
        self.assertEqual([c.args[0] for c in self.service.perform.call_args_list],
                         ['overview', 'discover', 'discover'])

    def test_first_catalog_checks_unknown_installations_once(self):
        self.ui.installation_check_pending = True
        self.service.perform.side_effect = [
            {'items': [{'id': 'keyboard', 'installed': None, 'enabled': True, 'selected': False}]},
            {'items': [{'id': 'keyboard', 'installed': True, 'enabled': True, 'selected': False}]},
            {'items': []}]
        self.ui.perform('discover')
        self.complete()
        self.service.perform.assert_called_with('check-installed')
        self.assertFalse(self.ui.mutating)
        self.complete()
        self.assertEqual(self.ui.selected, set())
        self.assertTrue(self.ui.views['repairs']['items'][0]['installed'])
        self.ui.perform('discover')
        self.complete()
        self.assertEqual([c.args[0] for c in self.service.perform.call_args_list],
                         ['discover', 'check-installed', 'discover'])

    def test_cancelled_automatic_installation_check_keeps_unknown_unselected(self):
        self.ui.installation_check_pending = True
        self.service.perform.side_effect = [
            {'items': [{'id': 'keyboard', 'installed': None, 'enabled': True, 'selected': False}]},
            RuntimeError('Authentication cancelled')]
        self.ui.perform('discover')
        self.complete()
        self.complete()
        self.assertEqual(self.ui.retry_task, ('check-installed', {}, 'repairs'))
        self.assertEqual(self.ui.selected, set())
        self.assertIsNone(self.ui.views['repairs']['items'][0]['installed'])


if __name__ == '__main__':
    unittest.main()
