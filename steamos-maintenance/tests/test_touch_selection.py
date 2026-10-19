"""Hidden installed components must never remain silently selected."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from oxp3_maintenance.touch_ui import TouchWindow


class TouchSelectionTests(unittest.TestCase):
    def test_review_filter_does_not_change_selection_or_plan(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.selected = {'keyboard', 'slot-switch'}
        ui.selections = {'repairs': set(ui.selected)}
        ui.views = {'repairs': {'review': True, 'can_apply': False}}
        ui._render = Mock()
        ui.scroll = SimpleNamespace(get_vadjustment=lambda: SimpleNamespace(set_value=Mock()))
        items = [dict(id='keyboard', enabled=True),
                 dict(id='slot-switch', incompatible=True),
                 dict(id='dependency', incompatible=True),
                 dict(id='unknown', enabled=False)]
        ui._filter_incompatible(SimpleNamespace(get_active=lambda: True))
        self.assertEqual([item['id'] for item in ui._review_items(items)], ['slot-switch', 'dependency'])
        self.assertEqual(ui.selected, {'keyboard', 'slot-switch'})
        self.assertEqual(ui.selections['repairs'], ui.selected)
        self.assertFalse(ui.views['repairs']['can_apply'])
        ui._filter_incompatible(SimpleNamespace(get_active=lambda: False))
        self.assertEqual(ui._review_items(items), items)

    def test_restored_selection_excludes_disabled_and_incompatible_items(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.selected = {'ready', 'disabled', 'stale', 'blocked'}
        ui.selections = {}
        ui._restrict_selection({'items': [dict(id='ready', enabled=True),
                                       dict(id='disabled', enabled=False),
                                       dict(id='blocked', enabled=True, incompatible=True)]})
        self.assertEqual(ui.selected, {'ready'})
        self.assertEqual(ui.selections['repairs'], {'ready'})

    def test_hiding_installed_removes_only_confirmed_installed_selection(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.views = {'repairs': {'items': [
            {'id': 'installed', 'installed': True},
            {'id': 'update', 'installed': True, 'update_available': True},
            {'id': 'missing', 'installed': False},
            {'id': 'unknown', 'installed': None}]}}
        ui.selected = {'installed', 'update', 'missing', 'unknown'}
        ui.selections = {}
        ui._render = Mock()
        ui._filter_installed(SimpleNamespace(get_active=lambda: False))
        self.assertEqual(ui.selected, {'update', 'missing', 'unknown'})
        self.assertEqual(ui.selections['repairs'], ui.selected)
        ui._render.assert_called_once()

    def test_showing_installed_does_not_add_them_to_selection(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.selected = {'new-repair'}
        ui._render = Mock()
        ui._filter_installed(SimpleNamespace(get_active=lambda: True))
        self.assertTrue(ui.show_installed)
        self.assertEqual(ui.selected, {'new-repair'})


if __name__ == '__main__':
    unittest.main()
