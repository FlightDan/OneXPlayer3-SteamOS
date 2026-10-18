"""Wi-Fi diagnostics remain bounded, read-only and free of network identities."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import wifi_health as wifi


class WifiHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sys/class/net').mkdir(parents=True)
        (self.root / 'sys/class/rfkill').mkdir(parents=True)
        self.commands = []
        self.nm = 'GENERAL.STATE:100 (connected)\nGENERAL.REASON:0 (No reason given)\nIP4.ADDRESS[1]:192.0.2.123/24\nIP6.ADDRESS[1]:2001:db8::42/64\n'
        self.current = self.log('iwlwifi 0000:00:14.3: Microcode SW error detected. error=-110')
        self.previous = ''
        self.reasons = {}

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def adapter(self, name='wlan0', *, driver=True):
        path = self.root / 'sys/class/net' / name
        (path / 'wireless').mkdir(parents=True)
        if driver:
            (path / 'device/driver').mkdir(parents=True)
        return path

    def radio(self, soft='0', hard='0', kind='wlan', index=0):
        for key, value in (('type', kind), ('soft', soft), ('hard', hard)):
            self.write(f'sys/class/rfkill/rfkill{index}/{key}', value)

    @staticmethod
    def log(message, **fields):
        return json.dumps({'MESSAGE': message, '_TRANSPORT': 'kernel',
                           '__REALTIME_TIMESTAMP': '1792281600000000', **fields}) + '\n'

    def query(self, argv):
        self.commands.append(argv)
        key = 'nm' if argv[0].endswith('nmcli') else 'previous' if '--boot=-1' in argv else 'current'
        return {'stdout': getattr(self, key), 'reason': self.reasons.get(key)}

    def collect(self):
        return {check['id']: check for check in wifi.collect(root=self.root, query=self.query)}

    def test_visible_connected_interface_is_not_claimed_to_have_internet(self):
        self.adapter()
        self.radio()
        report = self.collect()
        self.assertEqual(report['wifi.devices']['evidence']['count'], 1)
        self.assertEqual(report['wifi.driver']['status'], 'ok')
        self.assertEqual(report['wifi.rfkill']['status'], 'ok')
        self.assertEqual(report['wifi.networkmanager']['status'], 'info')
        state = report['wifi.networkmanager']['evidence']['interfaces'][0]
        self.assertEqual(state['state'], 'activated')
        self.assertTrue(state['has_ipv4'])
        self.assertTrue(state['has_ipv6'])
        self.assertIn('已连接', report['wifi.networkmanager']['message']['zh'])
        self.assertIn('未测试外网', report['wifi.networkmanager']['message']['zh'])

    def test_driver_missing_warns_independently_of_disconnected_state(self):
        self.adapter(driver=False)
        self.nm = 'GENERAL.STATE:30 (disconnected)\nGENERAL.REASON:39 (user requested)\n'
        report = self.collect()
        self.assertEqual(report['wifi.driver']['status'], 'warning')
        self.assertEqual(report['wifi.networkmanager']['status'], 'info')
        self.assertEqual(report['wifi.networkmanager']['evidence']['interfaces'][0]['reason'], 'user_disconnected')
        self.assertIn('未连接', report['wifi.networkmanager']['message']['zh'])

    def test_missing_interfaces_and_rfkill_do_not_become_passes(self):
        report = self.collect()
        self.assertEqual(report['wifi.devices']['status'], 'unknown')
        self.assertEqual(report['wifi.rfkill']['status'], 'unknown')
        self.assertEqual(report['wifi.networkmanager']['status'], 'unknown')
        self.assertFalse(any(cmd[0].endswith('nmcli') for cmd in self.commands))

    def test_both_soft_and_hard_blocks_and_non_wlan_are_distinguished(self):
        self.adapter()
        self.radio(soft='1')
        self.radio(hard='1', index=1)
        self.radio(soft='1', kind='bluetooth', index=2)
        check = self.collect()['wifi.rfkill']
        self.assertEqual(check['status'], 'warning')
        self.assertEqual(check['evidence']['radios'], [
            {'soft_blocked': True, 'hard_blocked': False},
            {'soft_blocked': False, 'hard_blocked': True}])

    def test_nm_reason_codes_match_upstream_enum_and_unknown_is_other(self):
        for code, expected in ((7, 'secrets_unavailable'), (11, 'supplicant_timeout'),
                               (15, 'dhcp_start_failed'), (17, 'dhcp_failed'),
                               (22, 'autoip_failed'), (39, 'user_disconnected'),
                               (53, 'ssid_not_found'), (67, 'other'), (999, 'other')):
            with self.subTest(code=code):
                parsed = wifi._nm(f'GENERAL.STATE:120 (failed)\nGENERAL.REASON:{code} (untrusted description)\n')
                self.assertEqual(parsed['reason_code'], code)
                self.assertEqual(parsed['reason'], expected)
        self.adapter()
        self.nm = 'GENERAL.STATE:120 (failed)\nGENERAL.REASON:7 (no secrets)\n'
        self.assertEqual(self.collect()['wifi.networkmanager']['status'], 'warning')

    def test_no_secret_or_raw_log_or_interface_identity_is_exported(self):
        self.adapter('PRIVATE-NAME')
        self.radio()
        secret = 'PRIVATE-SSID PRIVATE-USER PRIVATE-SERIAL aa:bb:cc:dd:ee:ff 198.51.100.8 2001:db8::89 PRIVATE-PASSWORD'
        self.nm += 'GENERAL.CONNECTION:' + secret + '\n'
        self.current += self.log('iwlwifi firmware error ' + secret)
        self.current += self.log('wifi supplicant authentication failed ' + secret,
                                 _TRANSPORT='syslog', _SYSTEMD_UNIT='NetworkManager.service')
        serialized = json.dumps(self.collect(), ensure_ascii=False)
        for value in ('PRIVATE-NAME', *secret.split(), '192.0.2.123', '2001:db8::42', '0000:00:14.3', 'untrusted description'):
            self.assertNotIn(value, serialized)
        self.assertIn('驱动固件或微码错误', serialized)
        self.assertIn('1792281600000000', self.current)
        self.assertNotIn('1792281600000000', serialized)

    def test_recent_and_previous_boot_categories_times_codes_are_safe(self):
        self.previous = self.log('iwlwifi Direct firmware load failed: error=-2')
        checks = self.collect()
        current = checks['wifi.logs.current']
        previous = checks['wifi.logs.previous']
        self.assertEqual(current['status'], 'warning')
        self.assertEqual(current['evidence']['events'][0]['category'], 'driver_firmware_error')
        self.assertEqual(current['evidence']['events'][0]['code'], -110)
        self.assertIn('time_utc', current['evidence']['events'][0])
        self.assertEqual(previous['evidence']['events'][0]['category'], 'firmware_load_failed')
        self.assertIn('错误码 -110', current['message']['zh'])

    def test_firmware_load_microcode_timeout_and_nm_errors(self):
        examples = [('iwlwifi Failed to load firmware file', 'firmware_load_failed'),
                    ('iwlwifi firmware: failed to load file', 'firmware_load_failed'),
                    ('iwlwifi Microcode SW error detected', 'driver_firmware_error'),
                    ('iwlwifi command timed out', 'driver_timeout'),
                    ('iwlwifi Timeout waiting for firmware', 'driver_timeout')]
        for message, category in examples:
            with self.subTest(message=message):
                self.assertEqual(wifi._event(json.loads(self.log(message)))['category'], category)
        event = wifi._event(json.loads(self.log('wifi supplicant authentication failed',
            _SYSTEMD_UNIT='NetworkManager.service', _TRANSPORT='syslog')))
        self.assertEqual(event['category'], 'authentication_failed')
        self.assertIsNone(wifi._event(json.loads(self.log('unrelated disk error'))))
        self.assertIsNone(wifi._event(json.loads(self.log('iwlwifi firmware version successfully loaded'))))

    def test_no_recognized_error_is_info_and_no_previous_journal_is_unknown(self):
        self.current = self.log('unrelated disk error')
        report = self.collect()
        self.assertEqual(report['wifi.logs.current']['status'], 'info')
        self.assertEqual(report['wifi.logs.previous']['status'], 'unknown')
        self.assertIn('不证明', report['wifi.logs.current']['message']['zh'])

    def test_missing_tools_timeout_and_partial_logs_preserve_other_results(self):
        self.adapter()
        self.radio()
        self.reasons = {'nm': 'tool_unavailable', 'current': 'query_failed_or_partial_access', 'previous': 'timeout'}
        report = self.collect()
        self.assertEqual(report['wifi.devices']['status'], 'info')
        self.assertEqual(report['wifi.driver']['status'], 'ok')
        for key in ('wifi.networkmanager', 'wifi.logs.current', 'wifi.logs.previous'):
            self.assertEqual(report[key]['status'], 'unknown')
        self.assertEqual(len(report['wifi.logs.current']['evidence']['events']), 1)
        self.assertIn('部分错误', report['wifi.logs.current']['message']['zh'])

    def test_nm_exception_does_not_suppress_logs_or_sysfs(self):
        self.adapter()
        def query(argv):
            if argv[0].endswith('nmcli'):
                raise subprocess.TimeoutExpired(argv, 5)
            return self.query(argv)
        report = {c['id']: c for c in wifi.collect(root=self.root, query=query)}
        self.assertEqual(report['wifi.networkmanager']['status'], 'unknown')
        self.assertEqual(report['wifi.logs.current']['status'], 'warning')

    def test_invalid_nm_or_journal_output_is_unknown(self):
        self.adapter()
        self.nm = 'GENERAL.STATE:100 (connected)\n'
        self.current += 'BROKEN SECRET LOG\n'
        report = self.collect()
        self.assertEqual(report['wifi.networkmanager']['status'], 'unknown')
        self.assertEqual(report['wifi.logs.current']['status'], 'unknown')
        self.assertNotIn('BROKEN SECRET LOG', json.dumps(report))

    def test_recent_errors_keep_latest_forty_and_latest_three_in_message(self):
        self.current = ''.join(self.log('iwlwifi driver error=' + str(index)) for index in range(61))
        check = self.collect()['wifi.logs.current']
        events = check['evidence']['events']
        self.assertEqual(len(events), 40)
        self.assertEqual(events[0]['code'], 21)
        self.assertEqual(events[-1]['code'], 60)
        self.assertTrue(check['evidence']['events_truncated'])
        self.assertIn('错误码 60', check['message']['zh'])
        self.assertNotIn('错误码 21', check['message']['zh'])

    def test_unreadable_message_shapes_are_incomplete_not_no_errors(self):
        for record in ({}, {'MESSAGE': None}, {'MESSAGE': ['private raw bytes']},
                       {'MESSAGE': 'x' * 32769}, []):
            with self.subTest(record_type=type(record).__name__):
                self.current = json.dumps(record) + '\n'
                check = self.collect()['wifi.logs.current']
                self.assertEqual(check['status'], 'unknown')
                self.assertEqual(check['evidence']['reason'], 'invalid_or_truncated_output')
        self.current = self.log('normal readable unrelated text')
        self.assertEqual(self.collect()['wifi.logs.current']['status'], 'info')

    def test_only_fixed_read_commands_and_validated_interface_argument(self):
        self.adapter()
        self.collect()
        self.assertEqual(len(self.commands), 3)
        nm = self.commands[0]
        self.assertEqual(nm[-3:], ['device', 'show', 'wlan0'])
        self.assertNotIn('wifi', nm)
        self.assertNotIn('connect', nm)
        for command in self.commands[1:]:
            self.assertIn('--lines=200', command)
            self.assertIn('--priority=warning', command)
        if os.name != 'nt':
            self.adapter('--malicious')
            self.commands.clear()
            self.assertEqual(self.collect()['wifi.devices']['status'], 'unknown')
            self.assertFalse(any(c[0].endswith('nmcli') for c in self.commands))

    def test_offline_root_never_queries_live_host_and_writes_nothing(self):
        self.adapter()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with mock.patch.object(wifi, '_query', side_effect=AssertionError('host query')):
            checks = wifi.collect(root=self.root)
        self.assertEqual(next(c for c in checks if c['id'] == 'wifi.networkmanager')['status'], 'unknown')
        after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    @unittest.skipUnless(os.name == 'posix', 'Linux sysfs symlink fixture')
    def test_sysfs_links_inside_sys_are_allowed_and_outside_rejected(self):
        target = self.root / 'sys/devices/pci/wlan0'
        (target / 'wireless').mkdir(parents=True)
        drivers = self.root / 'sys/bus/pci/drivers/iwlwifi'
        drivers.mkdir(parents=True)
        (target / 'device').mkdir()
        (target / 'device/driver').symlink_to(drivers, target_is_directory=True)
        (self.root / 'sys/class/net/wlan0').symlink_to(target, target_is_directory=True)
        report = self.collect()
        self.assertEqual(report['wifi.driver']['evidence']['interfaces'][0]['driver'], 'iwlwifi')
        (self.root / 'sys/class/net/wlan0').unlink()
        outside = self.root / 'private'
        (outside / 'wireless').mkdir(parents=True)
        (self.root / 'sys/class/net/wlan0').symlink_to(outside, target_is_directory=True)
        self.commands.clear()
        self.assertEqual(self.collect()['wifi.devices']['status'], 'unknown')
        self.assertFalse(any(c[0].endswith('nmcli') for c in self.commands))

    @unittest.skipUnless(os.name == 'posix', 'Linux sysfs anchor symlink fixture')
    def test_redirected_sys_anchor_cannot_authorize_outside_root_reads(self):
        outside_temp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temp.cleanup)
        outside = Path(outside_temp.name)
        (outside / 'class/net/wlan0/wireless').mkdir(parents=True)
        (outside / 'class/net/wlan0/device/driver').mkdir(parents=True)
        (outside / 'class/rfkill').mkdir(parents=True)
        sys_root = self.root / 'sys'
        (sys_root / 'class/net').rmdir()
        (sys_root / 'class/rfkill').rmdir()
        (sys_root / 'class').rmdir()
        sys_root.rmdir()
        sys_root.symlink_to(outside, target_is_directory=True)
        report = self.collect()
        self.assertEqual(report['wifi.devices']['status'], 'unknown')
        self.assertEqual(report['wifi.rfkill']['status'], 'unknown')
        self.assertFalse(any(c[0].endswith('nmcli') for c in self.commands))

    def test_query_runner_caps_output_timeout_and_stderr_without_exporting_it(self):
        response = wifi._query([sys.executable, '-c', "print('x' * 200000)"])
        self.assertEqual(response['reason'], 'output_limit')
        self.assertLessEqual(len(response['stdout']), wifi.MAX_OUTPUT)
        response = wifi._query([sys.executable, '-c', "import sys; sys.stderr.write('PRIVATE STDERR')"])
        self.assertEqual(response['reason'], 'query_failed_or_partial_access')
        self.assertNotIn('PRIVATE STDERR', str(response))
        response = wifi._query([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.05)
        self.assertEqual(response['reason'], 'timeout')
        with mock.patch.object(wifi.subprocess, 'Popen', side_effect=FileNotFoundError):
            self.assertEqual(wifi._query(['/usr/bin/nmcli'])['reason'], 'tool_unavailable')

    def test_total_command_budget_stops_further_processes(self):
        with mock.patch.object(wifi.time, 'monotonic', side_effect=[10, 15]), mock.patch.object(wifi, '_query', return_value={'stdout': '', 'reason': None}) as run:
            query = wifi._limited_query(12)
            query(['/usr/bin/nmcli'])
            second = query(['/usr/bin/journalctl'])
        self.assertEqual(run.call_args.kwargs['timeout'], 2)
        self.assertEqual(second['reason'], 'query_budget_exhausted')
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
