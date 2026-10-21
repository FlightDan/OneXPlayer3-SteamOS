import copy
import unittest

from oxp3_maintenance import compatibility


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.system = {'os': dict(compatibility.BASE), 'kernel': compatibility.KERNEL,
                       'dmi': dict(compatibility.DEVICE)}

    def test_old_steamos_device_support_is_separate_from_patch_baseline(self):
        self.system.update(kernel='older-kernel', compatible=True)
        self.system['os'].update(VERSION_ID='3.7', BUILD_ID='old')
        self.assertTrue(compatibility.device_supported(self.system))
        self.assertFalse(compatibility.baseline_supported(self.system))
        for name in compatibility.PORTABLE:
            result = compatibility.evaluate(name, self.system)
            self.assertTrue(result['supported'])
            self.assertNotIn('kernel', result['requirements'])
        for name in compatibility.BASELINE:
            self.assertFalse(compatibility.evaluate(name, self.system)['supported'], name)

    def test_other_distribution_never_gets_portable_permission(self):
        for key, values in [('os', {'ID': 'arch'})]:
            system = copy.deepcopy(self.system)
            system[key].update(values)
            system.update(device_supported=True, baseline_supported=True)
            for name in compatibility.PORTABLE | compatibility.BASELINE:
                self.assertFalse(compatibility.evaluate(name, system)['supported'], name)

    def test_model_identity_is_not_an_adapter_requirement(self):
        for dmi in ({}, {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER X2 MINI'},
                    {'sys_vendor': 'Other', 'product_name': 'Other'}):
            system = copy.deepcopy(self.system)
            system['dmi'] = dmi
            for name in compatibility.PORTABLE | compatibility.BASELINE:
                with self.subTest(dmi=dmi, component=name):
                    result = compatibility.evaluate(name, system)
                    self.assertTrue(result['supported'])
                    self.assertNotIn('dmi', result['requirements'])

    def test_unknown_adapter_is_explicit_even_on_exact_baseline(self):
        result = compatibility.evaluate('future-driver', self.system)
        self.assertFalse(result['supported'])
        self.assertEqual(result['profile'], 'unsupported-adapter')
        self.assertIn('reviewed adapter', result['reason'])

    def test_requirements_are_serializable_independent_copies(self):
        metadata = {'packages': {'glibc': 'accepted'}}
        result = compatibility.evaluate('hdr', self.system, metadata)
        self.assertEqual(result['requirements']['packages'], {'glibc': 'accepted', 'gamescope': '3.16.30-1'})
        self.assertEqual(metadata, {'packages': {'glibc': 'accepted'}})
        result['requirements']['os']['ID'] = 'changed'
        self.assertEqual(compatibility.BASE['ID'], 'steamos')
        gyro = compatibility.evaluate('gyro', self.system)['requirements']
        self.assertNotIn('bios', gyro)
        self.assertIn('inputplumber', gyro['package_patterns'])


if __name__ == '__main__':
    unittest.main()
