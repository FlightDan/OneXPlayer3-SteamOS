"""Touch health-check actions stay read-only and retry on the health route."""
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance.touch_ui import TouchWindow


class DeferredThread:
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class TouchHealthTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = []
        self.service = SimpleNamespace(
            mutating_actions={'apply', 'rollback', 'restore', 'recover'},
            perform=mock.Mock(side_effect=self.perform_service),
        )
        self.ui = TouchWindow.__new__(TouchWindow)
        ui = self.ui
        ui.service = self.service
        ui.busy = ui.mutating = ui.closed = ui.reviewing = False
        ui.route = 'overview'
        ui.views = {}
        ui.retry_task = None
        ui.text = {'working': 'Working', 'mutating': 'Changing the system', 'done': 'Done',
                   'ready': 'Ready', 'error': 'Operation did not finish'}
        ui.spinner, ui.progress, ui.retry_button = mock.Mock(), mock.Mock(), mock.Mock()
        ui._notice, ui._sensitivity, ui._render = mock.Mock(), mock.Mock(), mock.Mock()
        ui.scroll = SimpleNamespace(get_vadjustment=lambda: SimpleNamespace(set_value=mock.Mock()))
        ui.GLib = SimpleNamespace(
            idle_add=lambda callback, *args: self.callbacks.append((callback, args)),
            timeout_add=mock.Mock(),
        )
        self.thread = mock.patch('oxp3_maintenance.touch_ui.threading.Thread', DeferredThread)
        self.thread.start()
        self.addCleanup(self.thread.stop)

    @staticmethod
    def health_view():
        return {
            'heading': 'Health check',
            'message': 'Read-only inspection complete.',
            'tone': 'success',
            'facts': [('Controller', 'Connected')],
            'items': [{'id': 'controller', 'title': 'Controller', 'detail': 'Connected'}],
            'report_ready': True,
        }

    def perform_service(self, action, **params):
        if action in ('health', 'export-health'):
            return self.health_view()
        raise AssertionError('Unexpected service action: ' + action)

    def complete(self):
        callback, args = self.callbacks.pop(0)
        callback(*args)

    def test_health_check_and_export_route_without_repair_or_selection_actions(self):
        self.ui._start_health_check()

        self.service.perform.assert_called_once_with('health')
        self.assertFalse(self.ui.mutating)
        self.assertEqual(self.ui.retry_task, ('health', {}, 'health'))
        self.complete()
        self.assertEqual(self.ui.route, 'health')
        self.assertTrue(self.ui.views['health']['report_ready'])

        self.ui._export_health_report()
        self.service.perform.assert_called_with('export-health')
        self.assertFalse(self.ui.mutating)
        self.complete()
        self.assertEqual(self.ui.route, 'health')
        self.assertEqual([call.args[0] for call in self.service.perform.call_args_list],
                         ['health', 'export-health'])

    def test_health_page_renders_read_only_items_and_gates_report_export(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.toolbar, ui.footer = object(), object()
        ui.text = {'health_again': 'Run again', 'health_export': 'Export report',
                   'health_back': 'Back to repairs & plugins'}
        ui._start_health_check = mock.Mock()
        ui._export_health_report = mock.Mock()
        ui._render_items = mock.Mock()
        ui._action = mock.Mock()

        view = self.health_view()
        view['report_ready'] = False
        TouchWindow._render_health(ui, view)

        ui._render_items.assert_called_once_with(view['items'], selectable=False)
        self.assertNotIn('Export report', [call.args[1] for call in ui._action.call_args_list])
        retry = ui._action.call_args_list[0]
        self.assertIs(retry.args[2], ui._start_health_check)

        ui._action.reset_mock()
        view['report_ready'] = True
        TouchWindow._render_health(ui, view)
        export = next(call for call in ui._action.call_args_list if call.args[1] == 'Export report')
        self.assertIs(export.args[2], ui._export_health_report)
        self.assertTrue(export.kwargs['primary'])
        ui.navigate = mock.Mock()
        back = next(call for call in ui._action.call_args_list if call.args[1] == 'Back to repairs & plugins')
        back.args[2](None)
        ui.navigate.assert_called_once_with('repairs')

    def test_failed_health_check_retries_the_health_action_without_confirmation(self):
        self.service.perform.side_effect = [RuntimeError('temporary failure'), self.health_view()]
        self.ui._start_health_check()
        self.complete()

        self.assertEqual(self.ui._notice.call_args, mock.call('Operation did not finish\ntemporary failure', 'failure'))
        self.assertEqual(self.ui.retry_task, ('health', {}, 'health'))
        self.assertFalse(self.ui.mutating)
        self.ui._retry()
        self.assertEqual([call.args[0] for call in self.service.perform.call_args_list], ['health', 'health'])
        self.assertFalse(self.ui.mutating)
        self.complete()
        self.assertEqual(self.ui.route, 'health')
        self.assertIsNone(self.ui.retry_task)


if __name__ == '__main__':
    unittest.main()
