"""Serial policy boundaries and normal current-slot transaction recovery."""
import ast
import configparser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oxp3_maintenance import serial_console


class SerialConsolePolicyTests(unittest.TestCase):
    def test_only_ttys0_login_is_gated_and_explicit_opt_in_remains(self):
        with patch('subprocess.run', side_effect=AssertionError('planner ran a command')):
            files = serial_console.files()
        self.assertEqual(set(files), {
            'etc/systemd/system/serial-getty@ttyS0.service.d/90-oxp3-console.conf'})
        entry = next(iter(files.values()))
        policy = configparser.ConfigParser(interpolation=None)
        policy.read_string(entry['data'].decode())
        self.assertEqual(policy.sections(), ['Unit'])
        self.assertEqual(dict(policy['Unit']), {
            'conditionkernelcommandline': 'oxp3.serial-console=1'})
        self.assertEqual((entry['mode'], entry['user'], entry['mutable']), (0o644, False, False))

    def test_matches_maintained_offline_installer_policy_without_executing_it(self):
        source = Path(__file__).resolve().parents[2] / 'windows-installer/components/serial_console.py'
        if not source.is_file():
            self.skipTest('Offline installer source is not present in this test export')
        values = {}
        for node in ast.parse(source.read_text(encoding='utf-8-sig')).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('DROPIN', 'DATA'):
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(values, {'DROPIN': serial_console.DROPIN, 'DATA': serial_console.DATA})

    def test_identical_hotfix_is_accepted_without_mutating_input(self):
        existing = bytes(serial_console.DATA)
        self.assertEqual(serial_console.files(existing), serial_console.files())
        self.assertEqual(existing, serial_console.DATA)

    def test_custom_policy_is_preserved_for_review(self):
        for existing in (b'', b'[Unit]\nConditionKernelCommandLine=diagnostic=1\n',
                         serial_console.DATA + b'# administrator note\n'):
            with self.subTest(existing=existing), self.assertRaisesRegex(ValueError, 'preserve it for review'):
                serial_console.files(existing)
        for existing in ('text', {}, False):
            with self.subTest(existing=existing), self.assertRaisesRegex(ValueError, 'Invalid existing'):
                serial_console.files(existing)


@unittest.skipUnless(os.name == 'posix', 'Real file transaction requires Unix locks and metadata')
class SerialConsoleTransactionTests(unittest.TestCase):
    def test_current_slot_only_apply_and_restore_preserves_other_gettys_and_cmdline(self):
        from oxp3_maintenance.transactions import Store
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            current, other = base / 'current-root', base / 'other-root'
            current.mkdir()
            other.mkdir()
            unchanged = {
                'proc/cmdline': b'console=ttyS0,115200 console=tty1 quiet\n',
                'etc/default/grub': b'GRUB_CMDLINE_LINUX="console=ttyS0,115200"\n',
                'etc/systemd/system/getty@tty1.service.d/local.conf': b'[Service]\nTTYVTDisallocate=no\n',
            }
            for root in (current, other):
                for relative, data in unchanged.items():
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            store = Store(current, base / 'state', uid=os.getuid(), gid=os.getgid(), enforce_owner=False)
            planned = {name: dict(entry, component='serial-console-policy')
                       for name, entry in serial_console.files().items()}
            with patch('subprocess.run', side_effect=AssertionError('transaction ran a command')):
                store.apply(planned, {'version': '0.1.4'}, ['serial-console-policy'], 'current-slot')
                self.assertEqual((current / serial_console.DROPIN).read_bytes(), serial_console.DATA)
                self.assertFalse((other / serial_console.DROPIN).exists())
                store.restore('current-slot', ['serial-console-policy'])
            self.assertFalse((current / serial_console.DROPIN).exists())
            self.assertIsNone(store.status()['pending'])
            for root in (current, other):
                for relative, data in unchanged.items():
                    self.assertEqual((root / relative).read_bytes(), data)

    def test_identical_preexisting_hotfix_remains_after_restore(self):
        from oxp3_maintenance.transactions import Store
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'root'
            target = root / serial_console.DROPIN
            target.parent.mkdir(parents=True)
            target.write_bytes(serial_console.DATA)
            store = Store(root, base / 'state', uid=os.getuid(), gid=os.getgid(), enforce_owner=False)
            planned = {name: dict(entry, component='serial-console-policy')
                       for name, entry in serial_console.files(target.read_bytes()).items()}
            store.apply(planned, {'version': '0.1.4'}, ['serial-console-policy'], 'slot')
            store.restore('slot', ['serial-console-policy'])
            self.assertEqual(target.read_bytes(), serial_console.DATA)


if __name__ == '__main__':
    unittest.main()
