import json
from pathlib import Path
import unittest
from compatibility import evaluate


class ControlGateChecks(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(Path(__file__).with_name('profile.json').read_text())
        target = self.profile['target']
        self.system = {'version': target['system_version'], 'build': target['system_build'], 'kernel': target['kernel']}
        self.hardware = {'vendor': target['vendor'], 'product': target['product']}
        self.packages = {'steamos-manager': target['manager'], 'mangoapp': target['mangoapp']}
        self.features = {'core_groups': [2,8,4], 'intel_pstate': 'active', 'fan_driver_validated': True, 'battery_standard_controls_validated': True}

    def check(self, component): return evaluate(self.profile, component, self.system, self.hardware, self.packages, self.features)

    def test_matching_target_is_distinct_from_installation_acceptance(self):
        for component in self.profile['components']:
            self.assertTrue(self.check(component)['compatible'])
            self.assertFalse(self.check(component)['installation_allowed'])

    def test_recovery_source_and_other_model_are_rejected(self):
        self.system['version'] = '3.8.14'; self.hardware['product'] = 'Other device'
        for component in self.profile['components']: self.assertFalse(self.check(component)['compatible'])

    def test_unknown_driver_or_core_topology_is_rejected(self):
        self.features['fan_driver_validated'] = False
        self.assertFalse(self.check('oxp3-fan')['compatible'])
        self.features['core_groups'] = [4,8,2]
        self.assertFalse(self.check('oxp3-cpu')['compatible'])

    def test_manager_upgrade_requires_a_new_patch_baseline(self):
        self.packages['steamos-manager'] = '26.5.0-1'
        self.assertFalse(self.check('manager')['compatible'])
        self.assertFalse(self.check('native-tdp')['compatible'])

    def test_charging_needs_shared_driver_standard_controls_and_manager(self):
        self.features['battery_standard_controls_validated'] = False
        self.assertFalse(self.check('charging')['compatible'])
        self.features['battery_standard_controls_validated'] = True
        self.features['fan_driver_validated'] = False
        self.assertFalse(self.check('charging')['compatible'])
        self.features['fan_driver_validated'] = True
        self.packages['steamos-manager'] = 'future-version'
        self.assertFalse(self.check('charging')['compatible'])


if __name__ == '__main__': unittest.main()
