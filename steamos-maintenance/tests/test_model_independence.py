"""No device writes: model-independent entry with interface/version safeguards."""
import contextlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from oxp3_maintenance import bootstrap, gyro_binding, probe


class ModelIndependenceTests(unittest.TestCase):
    @contextlib.contextmanager
    def desktop(self, release='ID=steamos\n'):
        gi = types.ModuleType('gi')
        gi.require_version = lambda *args: None
        repository = types.ModuleType('gi.repository')
        repository.Gtk = types.SimpleNamespace(init_check=lambda _: (True, []))
        pwd = types.ModuleType('pwd')
        pwd.getpwuid = lambda _: types.SimpleNamespace(pw_name='deck')
        reads = []
        def read(path, *args, **kwargs):
            reads.append(path.as_posix())
            if path.as_posix() != '/etc/os-release':
                raise AssertionError('Entry must not depend on DMI: ' + str(path))
            return release
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(bootstrap.os, 'geteuid', return_value=1000, create=True))
            stack.enter_context(patch.object(bootstrap.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(bootstrap.platform, 'machine', return_value='x86_64'))
            stack.enter_context(patch.object(Path, 'is_file', return_value=True))
            stack.enter_context(patch.object(Path, 'read_text', read))
            stack.enter_context(patch.dict(sys.modules, {'pwd': pwd, 'gi': gi, 'gi.repository': repository}))
            stack.enter_context(patch.dict(bootstrap.os.environ, {'DISPLAY': ':0', 'XDG_CURRENT_DESKTOP': 'KDE', 'DESKTOP_SESSION': 'plasma'}, clear=True))
            yield reads

    def test_entry_uses_steamos_without_reading_model(self):
        with self.desktop() as reads:
            bootstrap.check_environment(False)
        self.assertEqual(reads, ['/etc/os-release'])

    def test_entry_still_rejects_other_distribution(self):
        with self.desktop('ID=arch\n'), self.assertRaisesRegex(RuntimeError, 'Use SteamOS'):
            bootstrap.check_environment(False)

    def test_entry_still_rejects_other_architecture(self):
        with self.desktop(), patch.object(bootstrap.platform, 'machine', return_value='aarch64'), self.assertRaisesRegex(RuntimeError, 'x86_64'):
            bootstrap.check_environment(False)

    def test_missing_dmi_is_diagnostic_only(self):
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertEqual(probe._dmi_value('product_name'), '')

    def test_gyro_requires_exact_interface_and_versions_without_dmi(self):
        devices = MagicMock()
        devices.iterdir.return_value = [Path('/sys/devices/' + gyro_binding.DEVICE)]
        (devices / gyro_binding.DEVICE).resolve.return_value = Path('/sys/devices/' + gyro_binding.DEVICE)
        backend = gyro_binding.SystemBackend()
        with patch.object(gyro_binding, 'DEVICES', devices), \
             patch.object(gyro_binding.os, 'uname', return_value=types.SimpleNamespace(release=gyro_binding.KERNEL), create=True), \
             patch.object(Path, 'read_text', side_effect=AssertionError('No DMI/BIOS requirement')), \
             patch.object(backend, 'command', return_value='inputplumber 0.78.0') as command:
            backend.guard(input_version=True)
            with patch.object(gyro_binding.os, 'uname', return_value=types.SimpleNamespace(release='wrong-kernel')):
                with self.assertRaises(gyro_binding.BindingError): backend.guard(input_version=True)
            command.return_value = 'inputplumber 0.79.0'
            with self.assertRaises(gyro_binding.BindingError): backend.guard(input_version=True)
            command.return_value = 'inputplumber 0.78.0'
            devices.iterdir.return_value = []
            with self.assertRaises(gyro_binding.BindingError): backend.guard(input_version=True)


if __name__ == '__main__':
    unittest.main()
