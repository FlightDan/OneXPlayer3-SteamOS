import unittest
import os
from unittest.mock import Mock, patch
import power_control as power


class PowerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.actual = dict(pl1_watts=30, pl2_watts=52, pl1_values=[30, 30],
                           pl2_values=[52, 52], pl1_min_watts=10, pl1_max_watts=40,
                           pl2_min_watts=10, pl2_max_watts=80)
        self.dbus = Mock()
        self.dbus.UInt32.side_effect = int
        self.props, self.api = Mock(), Mock()
        self.api.GetLimits.side_effect = lambda **kwargs: self.actual
        self.connection = patch.object(power, '_connect', return_value=(self.dbus, self.props, self.api))
        self.connection.start()
        self.addCleanup(self.connection.stop)

    def test_read_never_sets_power_and_observes_external_changes(self):
        self.assertEqual(power.get_status()['pl1_watts'], 30)
        self.actual.update(pl1_watts=35, pl1_values=[35, 35])
        self.assertEqual(power.get_status()['pl1_watts'], 35)
        self.props.Set.assert_not_called()
        self.api.SetPl2.assert_not_called()

    def test_pl1_uses_native_property_and_preserves_pl2(self):
        def apply(*args, **kwargs):
            self.actual.update(pl1_watts=25, pl1_values=[25, 25])
        self.props.Set.side_effect = apply
        self.assertEqual(power.set_pl1(25)['pl2_values'], [52, 52])
        self.props.Set.assert_called_once_with(power.TDP_INTERFACE, 'TdpLimit', 25, timeout=5)
        self.api.SetPl2.assert_not_called()

    def test_pl2_uses_provider_and_never_writes_pl1(self):
        class UInt32(int):
            pass
        self.dbus.UInt32.side_effect = UInt32
        def apply(value, **kwargs):
            self.actual.update(pl2_watts=value, pl2_values=[value, value])
        self.api.SetPl2.side_effect = apply
        self.assertEqual(power.set_pl2(80)['pl1_values'], [30, 30])
        self.api.SetPl2.assert_called_once_with(80, timeout=5)
        self.assertIs(type(self.api.SetPl2.call_args.args[0]), UInt32)
        self.props.Set.assert_not_called()

    def test_rejected_or_lost_writes_are_never_reported_successful(self):
        with self.assertRaisesRegex(RuntimeError, 'did not remain applied'):
            power.set_pl1(35)
        with self.assertRaisesRegex(RuntimeError, 'did not remain applied'):
            power.set_pl2(80)
        self.api.SetPl2.side_effect = RuntimeError('PL2 below PL1')
        with self.assertRaisesRegex(RuntimeError, 'below PL1'):
            power.set_pl2(20)

    def test_invalid_types_and_ranges_fail_before_connect(self):
        with patch.object(power, '_connect') as connect:
            for setter, values in ((power.set_pl1, (True, 9, 41, 30.0, '30')),
                                   (power.set_pl2, (False, 9, 81, 52.0, '52'))):
                for value in values:
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        setter(value)
            connect.assert_not_called()

    def test_missing_domain_is_an_error(self):
        self.actual['pl2_values'] = [52]
        with self.assertRaisesRegex(RuntimeError, 'both power domains'):
            power.get_status()

    def test_frozen_bridge_uses_system_python_and_cleans_library_path(self):
        reply = Mock(returncode=0, stdout='{"pl1_watts": 30}', stderr='')
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/frozen', 'LD_LIBRARY_PATH_ORIG': '/system'}), \
                patch.object(power.subprocess, 'run', return_value=reply) as run:
            self.assertEqual(power.request('set-pl2', 52), {'pl1_watts': 30})
            args = run.call_args.args[0]
            self.assertEqual(args[:3], ['/usr/bin/python3', '-I', '-B'])
            self.assertEqual(args[-2:], ['set-pl2', '52'])
            self.assertEqual(run.call_args.kwargs['env']['LD_LIBRARY_PATH'], '/system')
            self.assertNotIn('LD_LIBRARY_PATH_ORIG', run.call_args.kwargs['env'])
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/frozen'}, clear=True), \
                patch.object(power.subprocess, 'run', return_value=reply) as run:
            power.request('status')
            self.assertNotIn('LD_LIBRARY_PATH', run.call_args.kwargs['env'])

    def test_frozen_bridge_rejects_injection_and_surfaces_system_errors(self):
        with patch.object(power.subprocess, 'run') as run:
            for operation, value in (('other', None), ('set-pl2', '52; reboot'), ('set-pl1', True), ('status', 30)):
                with self.assertRaises(ValueError):
                    power.request(operation, value)
            run.assert_not_called()
        reply = Mock(returncode=1, stdout='', stderr='PL2 below live PL1')
        with patch.object(power.subprocess, 'run', return_value=reply), \
                self.assertRaisesRegex(RuntimeError, 'below live PL1'):
            power.request('set-pl2', 20)


if __name__ == '__main__':
    unittest.main()
