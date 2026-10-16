"""Hidden installed components must never remain silently selected."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from oxp3_maintenance.touch_ui import TouchWindow


class TouchSelectionTests(unittest.TestCase):
    def test_hiding_installed_removes_only_confirmed_installed_selection(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.views = {'repairs': {'items': [
            {'id': 'installed', 'installed': True},
            {'id': 'missing', 'installed': False},
            {'id': 'unknown', 'installed': None}]}}
        ui.selected = {'installed', 'missing', 'unknown'}
        ui.selections = {}
        ui._render = Mock()
        ui._filter_installed(SimpleNamespace(get_active=lambda: False))
        self.assertEqual(ui.selected, {'missing', 'unknown'})
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
