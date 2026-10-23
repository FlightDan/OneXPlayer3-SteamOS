"""Localized advisory copy must not invent an installation refusal."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import cli, compatibility
from oxp3_maintenance.desktop_service import DesktopService


class StatusReasonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = mock.patch.object(Path, 'home', return_value=Path(temporary.name))
        home.start()
        self.addCleanup(home.stop)
        self.service = DesktopService(SimpleNamespace(bundle=None, bundle_dir=None))
        self.service.zh = True

    def test_supported_current_and_legacy_reasons_have_positive_chinese_copy(self):
        for reason in ('Supported exact OXP3 SteamOS baseline',
                       'Supported exact SteamOS baseline',
                       'Supported SteamOS adapter; required resources are checked during planning'):
            with self.subTest(reason=reason):
                detail = self.service._reason(reason)
                self.assertNotIn('暂不可安装', detail)
                self.assertNotIn('Supported', detail)
                self.assertIn('检查更改', detail)
                self.assertIn('预检', detail)

    def test_untranslated_explanations_are_neutral_and_preserve_the_detail(self):
        for reason in ('Run in SteamOS to check installation compatibility',
                       'A new resource check is pending', 'Custom conflict detected'):
            with self.subTest(reason=reason):
                self.assertEqual(self.service._reason(reason), '详细说明：' + reason)
        self.assertEqual(self.service._reason(''), '')
        self.service.zh = False
        self.assertEqual(self.service._reason('Supported exact SteamOS baseline'),
                         'Supported exact SteamOS baseline')

    def test_installed_supported_rows_stay_selectable_and_blocked_plans_stay_blocked(self):
        names = ('opti2xmx', 'gamescope-env')
        value = {'schema': 2, 'release': {'version': '1.0.6'}, 'bundle': {},
                 'packages': {}, 'component_packages': {name: [] for name in names},
                 'distribution_manifest_digest': 'fixture', 'components': [
                     {'id': name, 'kind': 'repairs', 'delivery': 'maintenance',
                      'available': True, 'dependencies': [], 'revision': 'fixture'} for name in names]}
        system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                  'slot': {'id': 'here'}}
        states = dict.fromkeys(names, True)
        with mock.patch.object(cli, 'installed_release', return_value={'version': '1.0.6'}):
            rows = self.service._distribution_view(value, system=system, installation=states)['items']
            for row in rows:
                self.assertTrue(row['enabled'])
                self.assertTrue(row['installed'])
                self.assertTrue(row['needs_preflight'])
                self.assertFalse(row['incompatible'])
                self.assertFalse(row['selected'])
                self.assertIn('系统版本检查通过', row['detail'])
            plan = {'installed_states': states, 'components': {
                name: {'status': 'blocked', 'reason': 'Custom conflict detected',
                       'compatibility': {'supported': True}} for name in names}}
            for row in self.service._distribution_view(value, system=system, plan=plan)['items']:
                self.assertFalse(row['enabled'])
                self.assertFalse(row['selected'])
                self.assertTrue(row['incompatible'])
                self.assertIn('Custom conflict detected', row['detail'])


if __name__ == '__main__':
    unittest.main()
