"""Read-only diagnostics on incomplete, customized and damaged installations."""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

from oxp3_maintenance import cli, health, inventory
from oxp3_maintenance.desktop_service import DesktopService


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.protection = mock.patch.object(inventory, '_protected', return_value=True)
        self.protection.start()
        self.addCleanup(self.protection.stop)
        self.system = {'slot': {'id': 'partuuid-test', 'label': 'A'},
                       'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3', 'serial': 'PRIVATE-SERIAL'},
                       'kernel': '6.16', 'os': {'ID': 'steamos', 'VERSION_ID': '3.10'},
                       'packages': {'inputplumber': '0.78.0', 'secret-package': 'private'}}
        self.services = {'inputplumber.service': {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running'},
                         'oxp3-gyro.service': {'LoadState': 'not-found', 'ActiveState': 'inactive'}}
        self.write('proc/bus/input/devices', b'I: Bus=0003 Vendor=045e Product=028e Version=0110\nN: Name="Microsoft X-Box 360 pad"\nP: Phys=PRIVATE-PHYS\nU: Uniq=PRIVATE-UNIQ\nS: Sysfs=/devices/pci0000/input/input0\nH: Handlers=event0 js0\nB: KEY=10000 0 0 0 0\n')

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path

    def managed(self, contents=b'expected', *, mutable=False, component='input', relative='etc/inputplumber/example.yaml'):
        path = self.write(relative, contents)
        info = path.stat()
        self.entry = {'component': component, 'mutable': mutable, 'user': False,
                      'snapshot': {'exists': True, 'data': base64.b64encode(contents).decode(),
                                   'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}}
        self.index = {'format': 1, 'slots': {'partuuid-test': {'current': {'selected': [component],
                      'paths': {relative: self.entry}}}}}
        self.write(health.STATE + '/lock', b'')
        self.save_index()
        return path

    def save_index(self):
        self.write(health.STATE + '/index.json', self.index)

    def collect(self, **kwargs):
        return health.collect(root=self.root, system_probe=lambda: self.system, query_services=lambda: self.services, **kwargs)

    def finding(self, report, name):
        return next(item for item in report['checks'] if item['id'] == name)

    def test_wifi_results_are_integrated_and_rendered_with_controller_results(self):
        check = dict(id='wifi.networkmanager', status='info', title=health.words('Wi-Fi 连接', 'Wi-Fi connection'),
                     message=health.words('已连接；尚未验证互联网。', 'Connected; Internet not verified.'),
                     advice=health.words('查看网络设置。', 'Review network settings.'), evidence={'adapters': []})
        query = mock.Mock(return_value=[check])
        report = self.collect(query_wifi=query)
        query.assert_called_once_with(root=self.root)
        self.assertEqual(self.finding(report, 'wifi.networkmanager'), check)
        self.assertIn('input.devices', [item['id'] for item in report['checks']])
        with mock.patch.object(Path, 'home', return_value=self.root / 'home/deck'):
            service = DesktopService(SimpleNamespace(bundle=None, bundle_dir=None), language='zh')
        service.health_report = report
        view = service._health_view()
        self.assertTrue(any(item['id'] == 'wifi.networkmanager' and '已连接' in item['detail'] for item in view['items']))

    def test_wifi_failure_keeps_partial_controller_report(self):
        report = self.collect(query_wifi=mock.Mock(side_effect=RuntimeError('PRIVATE NETWORK DATA')))
        self.assertEqual(self.finding(report, 'wifi.status')['status'], 'unknown')
        self.assertEqual(self.finding(report, 'input.devices')['evidence']['gamepads'], 1)
        self.assertNotIn('PRIVATE NETWORK DATA', json.dumps(report))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_empty_state_does_not_create_lock_or_state_directory(self):
        before = self.snapshot()
        report = self.collect()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / health.STATE).exists())
        self.assertEqual(self.finding(report, 'input.devices')['evidence']['gamepads'], 1)
        self.assertEqual(self.finding(report, 'service.oxp3-gyro.service')['status'], 'info')

    def test_managed_check_is_read_only_and_never_exports_private_bytes(self):
        self.managed(b'PRIVATE FILE CONTENT')
        before = self.snapshot()
        report = self.collect()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.finding(report, 'files.input')['status'], 'ok')
        serialized = json.dumps(report)
        for secret in ('PRIVATE FILE CONTENT', base64.b64encode(b'PRIVATE FILE CONTENT').decode(),
                       'PRIVATE-PHYS', 'PRIVATE-UNIQ', 'PRIVATE-SERIAL', 'secret-package', 'partuuid-test'):
            self.assertNotIn(secret, serialized)

    def test_changed_immutable_file_has_expected_actual_hash_and_path(self):
        path = self.managed()
        path.write_bytes(b'changed')
        check = self.finding(self.collect(), 'files.input')
        self.assertEqual(check['status'], 'warning')
        difference = check['evidence']['details'][0]
        self.assertEqual(difference['path'], 'etc/inputplumber/example.yaml')
        self.assertIn('expected', difference['differences']['sha256'])
        self.assertIn('actual', difference['differences']['sha256'])

    def test_custom_config_is_information_but_missing_config_warns(self):
        path = self.managed(mutable=True)
        path.write_bytes(b'custom')
        self.assertEqual(self.finding(self.collect(), 'files.input')['status'], 'info')
        path.unlink()
        self.assertEqual(self.finding(self.collect(), 'files.input')['status'], 'warning')

    def test_metadata_difference_is_not_hidden_as_customization(self):
        self.managed(mutable=True)
        self.entry['snapshot']['uid'] += 10
        self.save_index()
        self.assertEqual(self.finding(self.collect(), 'files.input')['status'], 'warning')

    def test_no_joystick_is_warning_not_crash(self):
        self.write('proc/bus/input/devices', b'')
        report = self.collect()
        self.assertEqual(self.finding(report, 'input.devices')['status'], 'warning')
        self.assertIn('input.manual_test', [c['id'] for c in report['checks']])

    def test_gamepad_bitmap_without_js_handler(self):
        # BTN_GAMEPAD=0x130 falls in the fifth 64-bit word (offset 48).
        devices = health.input_devices('N: Name="Pad"\nH: Handlers=event7\nB: KEY=1000000000000 0 0 0 0\n')
        self.assertTrue(devices[0]['gamepad_capability'])

    def test_failed_system_probe_does_not_suppress_input_results(self):
        report = health.collect(root=self.root, system_probe=mock.Mock(side_effect=RuntimeError('PRIVATE ERROR')),
                                query_services=lambda: self.services)
        self.assertEqual(self.finding(report, 'system.identity')['status'], 'unknown')
        self.assertEqual(self.finding(report, 'input.devices')['evidence']['gamepads'], 1)
        self.assertNotIn('PRIVATE ERROR', json.dumps(report))

    def test_service_timeout_yields_partial_report(self):
        report = health.collect(root=self.root, system_probe=lambda: self.system,
                                query_services=mock.Mock(side_effect=subprocess.TimeoutExpired('systemctl', 12)))
        self.assertEqual(self.finding(report, 'input.services')['status'], 'unknown')
        self.assertIn('input.devices', [c['id'] for c in report['checks']])

    def test_pending_transaction_is_visible_without_recovery(self):
        self.managed()
        self.write(health.STATE + '/pending.json', {'private': 'ORIGINAL_BYTES'})
        before = self.snapshot()
        report = self.collect()
        self.assertEqual(self.finding(report, 'maintenance.operation')['status'], 'warning')
        self.assertEqual(before, self.snapshot())
        self.assertNotIn('ORIGINAL_BYTES', json.dumps(report))

    def test_first_interrupted_install_without_index_does_not_fall_back_to_legacy(self):
        for marker in ('pending.json', 'live-operation.json'):
            with self.subTest(marker=marker):
                path = self.write(health.STATE + '/' + marker, {})
                with mock.patch.object(inventory, 'inspect') as inspect:
                    report = self.collect()
                inspect.assert_not_called()
                self.assertEqual(self.finding(report, 'maintenance.operation')['status'], 'warning')
                self.assertIn('input.devices', [c['id'] for c in report['checks']])
                path.unlink()

    def test_missing_lock_with_existing_index_cannot_revive_legacy_state(self):
        self.managed()
        (self.root / health.STATE / 'lock').unlink()
        report = self.collect()
        self.assertEqual(self.finding(report, 'maintenance.state')['status'], 'unknown')
        self.assertNotIn('files.input', [c['id'] for c in report['checks']])

    def test_corrupt_state_is_unknown_and_input_checks_continue(self):
        self.managed()
        self.write(health.STATE + '/index.json', b'{broken')
        report = self.collect()
        self.assertEqual(self.finding(report, 'maintenance.state')['status'], 'unknown')
        self.assertIn('input.devices', [c['id'] for c in report['checks']])

    def test_structurally_invalid_state_does_not_abort_device_checks(self):
        self.managed()
        pristine = copy.deepcopy(self.index)
        for bad in ('slot', 'generation', 'entry', 'adopted'):
            with self.subTest(bad=bad):
                self.index = copy.deepcopy(pristine)
                slot = self.index['slots']['partuuid-test']
                if bad == 'slot':
                    self.index['slots']['partuuid-test'] = []
                elif bad == 'generation':
                    slot['current'] = []
                elif bad == 'entry':
                    slot['current']['paths']['etc/inputplumber/example.yaml'] = []
                else:
                    slot['current']['legacy_adopted'] = [{}]
                self.save_index()
                report = self.collect()
                self.assertEqual(self.finding(report, 'maintenance.state')['status'], 'unknown')
                self.assertIn('input.devices', [c['id'] for c in report['checks']])

    def test_unsafe_record_path_does_not_get_read(self):
        self.managed()
        current = self.index['slots']['partuuid-test']['current']
        current['paths'] = {'etc/shadow': self.entry}
        self.save_index()
        report = self.collect()
        self.assertEqual(self.finding(report, 'maintenance.state')['status'], 'unknown')
        self.assertNotIn('etc/shadow', json.dumps(report))

    def test_size_limit_is_unknown_and_does_not_modify_file(self):
        self.managed(b'large file')
        with mock.patch.object(health, 'MAX_TOTAL', 1):
            report = self.collect()
        self.assertEqual(self.finding(report, 'files.input')['status'], 'unknown')

    def test_legacy_baseline_compares_bytes_and_marks_custom_input_config(self):
        relative = 'etc/inputplumber/devices.d/50-onexplayer_3.yaml'
        self.write(relative, b'custom yaml')
        self.write('home/.oxp3-installer/integration/A/request.json', {'repairs': ['input'], 'plugins': [], 'set_deck_password': 'PRIVATE PASSWORD'})
        self.write('home/.oxp3-installer/integration/A/input/state.json', {
            'phase': 'installed', 'allowed': [relative], 'original': {relative: {'exists': False}},
            'applied': {relative: base64.b64encode(b'original yaml').decode()}})
        report = self.collect()
        self.assertEqual(self.finding(report, 'files.input')['status'], 'info')
        self.assertNotIn('PRIVATE PASSWORD', json.dumps(report))

    def test_export_contains_only_sanitized_report_and_does_not_overwrite(self):
        report = self.collect()
        folder = Path(self.temp.name) / 'reports'
        first = health.export_report(report, folder)
        second = health.export_report(report, folder, 'en')
        self.assertNotEqual(first, second)
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), {'report.json', 'report.txt'})
            self.assertEqual(json.loads(archive.read('report.json')), report)
            self.assertNotIn(b'PRIVATE', archive.read('report.txt'))

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink safety')
    def test_symlink_target_is_unknown_without_reading_destination(self):
        path = self.managed()
        path.unlink()
        target = self.write('etc/private', b'PRIVATE VALUE')
        path.symlink_to(target)
        report = self.collect()
        self.assertEqual(self.finding(report, 'files.input')['status'], 'unknown')
        self.assertNotIn('PRIVATE VALUE', json.dumps(report))

    @unittest.skipUnless(os.name == 'posix', 'POSIX nonblocking shared lock')
    def test_busy_transaction_is_unknown_without_waiting(self):
        import fcntl
        self.managed()
        with (self.root / health.STATE / 'lock').open('rb') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            report = self.collect()
        self.assertEqual(self.finding(report, 'maintenance.state')['status'], 'unknown')


class HealthDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch.object(Path, 'home', return_value=Path(self.temp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.service = DesktopService(SimpleNamespace(bundle=None, bundle_dir=None))
        self.report = {'schema': 1, 'kind': 'oxp3-health-report', 'created_at': '2026-10-18T00:00:00Z',
                       'summary': {'warning': 1, 'unknown': 0, 'info': 0, 'ok': 0},
                       'checks': [dict(id='test', status='warning', title=health.words('测试', 'Test'),
                                       message=health.words('差异', 'Mismatch'), advice=health.words('检查', 'Review'), evidence={})]}

    def test_check_and_export_never_apply_or_need_a_bundle(self):
        with mock.patch.object(self.service, '_backend', return_value=self.report) as backend:
            view = self.service.perform('health')
            saved = self.service.perform('export-health')
        backend.assert_called_once_with('health')
        self.assertTrue(view['report_ready'])
        self.assertTrue(Path(saved['facts'][-1][1]).is_file())
        self.assertIsNone(self.service.review)

    def test_failed_rerun_invalidates_export(self):
        self.service.health_report = self.report
        with mock.patch.object(self.service, '_backend', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                self.service.perform('health')
        with self.assertRaisesRegex(RuntimeError, 'Run a health check'):
            self.service.perform('export-health')

    def test_cli_health_does_not_require_strict_probe_before_collector(self):
        with mock.patch.object(health, 'collect', return_value=self.report) as collect:
            result = cli.dispatch(cli.parser().parse_args(['health', '--json']))
        collect.assert_called_once_with()
        self.assertEqual(result, self.report)

    def test_network_route_persists_and_direct_is_applied_to_requests(self):
        with mock.patch('oxp3_maintenance.desktop_service.subprocess.run', return_value=SimpleNamespace(returncode=0)):
            self.service.perform('settings', enabled=False, channel='stable', github_network='direct')
        saved = json.loads(self.service.settings.read_text())
        self.assertEqual(saved['github_network'], 'direct')
        self.assertEqual(self.service.perform('preferences')['github_network'], 'direct')
        self.assertEqual(self.service._network_kwargs()['opener'].__self__.mode, 'direct')

    def test_invalid_proxy_setting_does_not_write_settings(self):
        with self.assertRaisesRegex(RuntimeError, 'Invalid GitHub network'):
            self.service.perform('settings', enabled=True, channel='stable', github_network='https://evil.invalid')
        self.assertFalse(self.service.settings.exists())

    def test_saved_auto_policy_is_not_overridden_by_environment(self):
        with mock.patch.dict(os.environ, {'OXP3_GITHUB_NETWORK': 'direct'}):
            self.assertEqual(self.service._network_kwargs()['opener'].__self__.mode, 'auto')


if __name__ == '__main__':
    unittest.main()
