"""Touch settings preserve and submit the selected GitHub download route."""
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance.touch_ui import TEXT, TouchWindow, _github_network_choices


class TouchNetworkTests(unittest.TestCase):
    def test_preferences_build_choices_and_select_saved_route(self):
        options = [
            {'id': 'auto', 'name': 'Automatic'},
            {'id': 'direct', 'name': 'Direct'},
            {'id': 'gh-proxy.com', 'name': 'Proxy A'},
        ]
        choices, selected = _github_network_choices(
            {'github_network': 'gh-proxy.com', 'network_options': options}, TEXT['en'])

        self.assertEqual(choices, [('auto', 'Automatic'), ('direct', 'Direct'), ('gh-proxy.com', 'Proxy A')])
        self.assertEqual(selected, 'gh-proxy.com')

    def test_missing_or_invalid_options_use_bilingual_fixed_routes_and_auto_default(self):
        expected_ids = ['auto', 'direct', 'gh-proxy.com', 'ghfast.top', 'ghproxy.net']
        for language in ('zh', 'en'):
            with self.subTest(language=language):
                choices, selected = _github_network_choices({}, TEXT[language])
                self.assertEqual([option_id for option_id, _ in choices], expected_ids)
                self.assertEqual(selected, 'auto')
                self.assertEqual(choices[0][1], TEXT[language]['network_auto'])
                self.assertEqual(choices[1][1], TEXT[language]['network_direct'])
                self.assertIn('public files' if language == 'en' else '公开文件', TEXT[language]['network_hint'])

        choices, selected = _github_network_choices(
            {'github_network': 'unknown', 'network_options': [{'id': None, 'name': 'Invalid'}]}, TEXT['en'])
        self.assertEqual([option_id for option_id, _ in choices], expected_ids)
        self.assertEqual(selected, 'auto')

        choices, selected = _github_network_choices(
            {'network_options': [{'id': 'direct', 'name': 'Direct'}]}, TEXT['en'])
        self.assertEqual(choices[0], ('auto', TEXT['en']['network_auto']))
        self.assertEqual(selected, 'auto')

    def test_save_submits_network_with_existing_settings(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.perform = mock.Mock()
        ui.daily = SimpleNamespace(get_active=lambda: False)
        ui.beta = SimpleNamespace(get_active=lambda: True)
        ui.github_network = SimpleNamespace(get_active_id=lambda: 'ghfast.top')

        TouchWindow._save_settings(ui)

        ui.perform.assert_called_once_with('settings', enabled=False, channel='beta', github_network='ghfast.top')

    def test_completed_settings_view_keeps_saved_network_value(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.closed = False
        ui.busy = ui.mutating = False
        ui.service = SimpleNamespace(mutating_actions=set())
        ui.retry_task = ('settings', {
            'enabled': False, 'channel': 'beta', 'github_network': 'ghproxy.net',
        }, 'settings')
        ui.spinner, ui.progress = mock.Mock(), mock.Mock()
        ui.views = {}
        ui._render, ui._notice = mock.Mock(), mock.Mock()
        ui.scroll = SimpleNamespace(get_vadjustment=lambda: SimpleNamespace(set_value=mock.Mock()))
        ui.text = {'done': 'Done', 'ready': 'Ready'}

        TouchWindow._completed(ui, 'settings', 'settings', {
            'enabled': True, 'channel': 'stable', 'github_network': 'auto', 'network_options': [],
        }, None)

        self.assertEqual(ui.views['settings']['enabled'], False)
        self.assertEqual(ui.views['settings']['channel'], 'beta')
        self.assertEqual(ui.views['settings']['github_network'], 'ghproxy.net')
        self.assertEqual(ui.views['settings']['network_options'], [])

    def test_network_control_is_disabled_while_settings_are_busy(self):
        ui = TouchWindow.__new__(TouchWindow)
        ui.route, ui.busy, ui.confirm_task = 'settings', True, None
        ui.nav_buttons, ui.actions, ui.checks = {}, [], {}
        ui.daily, ui.stable, ui.beta, ui.github_network = (mock.Mock() for _ in range(4))
        ui.retry_button = mock.Mock()

        TouchWindow._sensitivity(ui)

        for widget in (ui.daily, ui.stable, ui.beta, ui.github_network):
            widget.set_sensitive.assert_called_once_with(False)


if __name__ == '__main__':
    unittest.main()
