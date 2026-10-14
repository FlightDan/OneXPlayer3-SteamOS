import json
from pathlib import Path
import unittest
from compatibility import evaluate


class VersionGateChecks(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(Path(__file__).with_name('profile.json').read_text())

    def test_exact_match_is_distinct_from_installation_acceptance(self):
        target = self.profile['system']
        result = evaluate(self.profile, target, target['kernel'], self.profile['packages'])
        self.assertTrue(result['compatible']); self.assertFalse(result['installation_allowed'])

    def test_recovery_source_and_other_kernel_are_rejected(self):
        result = evaluate(self.profile, {'version': '3.8.14', 'build': '20260707.10'}, '6.16.12-valve24.4-1-neptune-616', {})
        self.assertFalse(result['compatible']); self.assertGreater(len(result['reasons']), 3)

    def test_python_or_system_upgrade_requires_a_new_build(self):
        target = self.profile['system']; packages = dict(self.profile['packages']); packages['python'] = '3.15.0-1'
        result = evaluate(self.profile, target, target['kernel'], packages)
        self.assertFalse(result['compatible']); self.assertTrue(any('python' in error for error in result['reasons']))


if __name__ == '__main__': unittest.main()
