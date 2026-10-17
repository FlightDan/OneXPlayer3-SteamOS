"""Exercise read-only fan discovery without a controller/status file."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('telemetry', Path(__file__).with_name('telemetry.py'))
telemetry = importlib.util.module_from_spec(spec)
with patch('os.getuid', return_value=1000, create=True):
    spec.loader.exec_module(telemetry)

class FanTelemetryTests(unittest.TestCase):
    def test_discovery_and_sensor_failure(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            def sensor(index, name, rpm):
                p = root / ('hwmon' + str(index)); p.mkdir()
                (p / 'name').write_text(name)
                (p / 'fan1_input').write_text(rpm)
                return p
            sensor(0, 'acpi_fan', '1234')
            live = sensor(9, 'oxp_ec', '3587\n')
            original = Path
            def mapped(value):
                self.assertEqual(value, '/sys/class/hwmon')
                return original(root)
            with patch.object(telemetry, 'Path', side_effect=mapped):
                self.assertEqual(telemetry.fan_text(), '3587 RPM')
                for value, expected in [('0', '0 RPM'), ('30000', '30000 RPM'),
                                        ('-1', 'N/A'), ('30001', 'N/A'), ('nan', 'N/A')]:
                    (live / 'fan1_input').write_text(value)
                    self.assertEqual(telemetry.fan_text(), expected)
                (live / 'fan1_input').unlink()
                self.assertEqual(telemetry.fan_text(), 'N/A')
                (live / 'fan1_input').write_text('3587')
                duplicate = sensor(10, 'oxp_ec', '3587')
                self.assertEqual(telemetry.fan_text(), 'N/A')
                (duplicate / 'name').write_text('other')
                (live / 'name').write_text('other')
                self.assertEqual(telemetry.fan_text(), 'N/A')

if __name__ == '__main__':
    unittest.main()
