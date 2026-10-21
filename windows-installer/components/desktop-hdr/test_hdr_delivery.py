"""Delivery invariants across installer, maintenance and KDE bootstrap."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class DeliveryTests(unittest.TestCase):
    def test_canonical_device_helpers_are_byte_synchronized(self):
        source = (ROOT / 'windows-installer/components/desktop-hdr/x2mini_device.py').read_bytes()
        for name in ('windows-installer/components/x2mini_hdr_device.py',
                     'steamos-maintenance/oxp3_maintenance/x2mini_hdr_device.py'):
            self.assertEqual((ROOT / name).read_bytes(), source, name)

    def test_launch_bootstrap_matches_runtime_source(self):
        self.assertEqual((ROOT / 'research/desktop-hdr/launch-stable.sh').read_bytes(),
                         (ROOT / 'windows-installer/components/desktop-hdr/launch.sh').read_bytes())

    def test_installed_canonical_runtime_includes_restore_helper(self):
        tree = ast.parse((ROOT / 'windows-installer/components/integration.py').read_text(encoding='utf8'))
        lists = [node for node in ast.walk(tree) if isinstance(node, (ast.Tuple, ast.List))]
        self.assertTrue(any('integration.py' in values and 'x2mini_hdr_device.py' in values
                            for node in lists
                            for values in [[item.value for item in node.elts
                                            if isinstance(item, ast.Constant)]]))


if __name__ == '__main__':
    unittest.main()
