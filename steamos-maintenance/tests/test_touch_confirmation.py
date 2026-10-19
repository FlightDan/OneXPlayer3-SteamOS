"""Real GTK confirmation visibility and dispatch, with no system backend."""
import unittest
from unittest import mock

from oxp3_maintenance.touch_ui import TouchWindow


class QuietWindow(TouchWindow):
    def perform(self, action, **params):
        self.recorded.append((action, params))


class NoBackend:
    mutating_actions = frozenset({'apply', 'restore', 'rollback', 'recover'})
    has_source = False
    has_candidate = False
    on_progress = None


class TouchConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            ready, _ = Gtk.init_check(None)
        except (ImportError, ValueError, RuntimeError) as error:
            raise unittest.SkipTest('Native GTK 3 display unavailable') from error
        if not ready:
            raise unittest.SkipTest('Native GTK 3 display unavailable')

    def setUp(self):
        from gi.repository import Gtk
        patch = mock.patch.object(Gtk, 'main_quit')
        patch.start()
        self.addCleanup(patch.stop)
        self.ui = QuietWindow.__new__(QuietWindow)
        self.ui.recorded = []
        self.ui.__init__(NoBackend(), language='zh')

    def tearDown(self):
        self.ui.closed = True
        self.ui.window.destroy()

    def test_confirmation_is_visible_and_cancel_restores_actions(self):
        self.ui.protect('apply', selected=['keyboard'])
        self.assertTrue(self.ui.confirmation.get_visible())
        self.assertTrue(self.ui.confirmation.get_mapped())
        self.assertTrue(all(child.get_visible() for child in self.ui.confirmation.get_children()))
        self.assertFalse(self.ui.footer.get_visible())
        self.assertFalse(self.ui.nav_buttons['overview'].get_sensitive())
        self.assertEqual(self.ui.confirm_label.get_text(), self.ui.text['confirm_apply'])
        self.assertEqual(self.ui.recorded, [])
        self.ui._cancel_confirm()
        self.assertFalse(self.ui.confirmation.get_visible())
        self.assertTrue(self.ui.footer.get_visible())
        self.assertTrue(self.ui.nav_buttons['overview'].get_sensitive())
        self.assertEqual(self.ui.recorded, [])

    def test_explicit_confirmation_dispatches_the_reviewed_action_once(self):
        self.ui.protect('restore', selected=['keyboard'])
        self.ui._confirm()
        self.ui._confirm()
        self.assertEqual(self.ui.recorded, [('restore', {'selected': ['keyboard']})])
        self.assertIsNone(self.ui.confirm_task)
        self.assertFalse(self.ui.confirmation.get_visible())

    def test_incompatible_review_filter_and_yellow_status(self):
        from gi.repository import Gtk
        ui = self.ui
        ui.route = 'repairs'
        ui.selected = {'keyboard', 'slot-switch'}
        ui.views['repairs'] = {
            'review': True, 'can_apply': False,
            'items': [{'id': 'keyboard', 'title': 'Keyboard', 'enabled': True},
                      {'id': 'slot-switch', 'title': 'KDE <slot>', 'incompatible': True,
                       'detail': 'Unsupported inactive slot'},
                      {'id': 'dependency', 'title': 'Dependency', 'incompatible': True}],
        }
        ui._render()
        def labels(widget):
            values = [widget] if isinstance(widget, Gtk.Label) else []
            for child in widget.get_children() if isinstance(widget, Gtk.Container) else []:
                values.extend(labels(child))
            return values
        statuses = [label for label in labels(ui.page) if label.get_text() == ui.text['incompatible']]
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(label.get_style_context().has_class('incompatible') for label in statuses))
        ui.incompatible_filter.set_active(True)
        shown = [label.get_text() for label in labels(ui.page)]
        self.assertNotIn('Keyboard', shown)
        self.assertIn('KDE <slot>', shown)
        self.assertIn('Dependency', shown)
        self.assertEqual(ui.selected, {'keyboard', 'slot-switch'})
        self.assertFalse(ui.views['repairs']['can_apply'])
        self.assertEqual(ui.recorded, [])
        ui.incompatible_filter.set_active(False)
        self.assertIn('Keyboard', [label.get_text() for label in labels(ui.page)])
        ui.protect('apply')
        self.assertFalse(ui.incompatible_filter.get_sensitive())
        ui._filter_incompatible(ui.incompatible_filter)
        self.assertTrue(ui.confirmation.get_visible())
        self.assertIsNotNone(ui.confirm_task)
        ui._cancel_confirm()
        self.assertTrue(ui.incompatible_filter.get_sensitive())
        ui.busy = True
        ui._sensitivity()
        self.assertFalse(ui.incompatible_filter.get_sensitive())
        ui._filter_incompatible(ui.incompatible_filter)
        self.assertEqual(ui.recorded, [])


if __name__ == '__main__':
    unittest.main()
