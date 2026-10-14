"""Controller payload lifecycle tests on disposable directories, without firmware."""
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid

import manage as m
import test_refind


class GamepadDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'esp'
        self.payload = Path(__file__).parent
        self.esp = str(uuid.UUID(int=23))
        # Distinct PE fixture stands in for the official loader in filesystem tests.
        loader = bytearray(160)
        loader[:2] = b'MZ'
        struct.pack_into('<I', loader, 60, 64)
        loader[64:68] = b'PE\0\0'
        struct.pack_into('<H', loader, 68, 0x8664)
        for name in (m.FALLBACK, 'EFI/steamos/steamcl.efi'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(loader)

    def install(self, payload=None):
        return m.install(self.root, payload or self.payload, 'SteamOS', 5, self.esp)

    def test_complete_lifecycle_and_every_interruption_boundary(self):
        result = test_refind.run(self.root, self.payload, self.esp, filesystem='temporary directory')
        self.assertTrue(result['passed'])
        self.assertEqual((self.root/m.GAMEPAD_CONFIG).read_bytes(), (self.payload/'gamepad.ini').read_bytes())
        self.assertEqual((self.root/m.OWN/m.GAMEPAD_DRIVER).read_bytes(), (self.payload/m.GAMEPAD_DRIVER).read_bytes())
        config = (self.root/'EFI/BOOT/refind.conf').read_text()
        self.assertIn('scan_driver_dirs /EFI/OXP3-rEFInd/drivers_x64', config)
        self.assertNotIn('enable_touch', config)

    def test_upgrade_old_journal_then_restore_original(self):
        state = self.install()
        new_names = set(m.FILES) - set(m.THEME_FILES)
        for name in new_names:
            m.write(self.root, name, None)
        # Emulate a journal created before controller files were managed.
        for key in ('before', 'original', 'desired'):
            for name in new_names:
                del state[key][name]
        m.save(self.root, state)
        self.install()
        m.verify(self.root)
        m.uninstall(self.root)
        self.assertTrue(all(m.read(self.root, n) is None for n in new_names))

    def test_driver_scan_directive_is_recognized_by_bundled_refind(self):
        config = m.configuration('SteamOS', 5, self.esp, None).decode()
        scan_line = next(line for line in config.splitlines()
                         if 'OXP3-rEFInd/drivers_x64' in line)
        directive = scan_line.split()[0]
        # Check against the executable's actual token table, not just our template.
        binary = (self.payload / 'refind_x64.efi').read_bytes()
        tokens = set(re.findall(r'[a-z_]{5,}', binary.decode('utf-16-le', errors='ignore')))
        self.assertIn(directive, tokens)
        self.assertNotIn('\ndriver_dirs ', config)

    def test_existing_controller_config_is_preserved(self):
        target = self.root/m.GAMEPAD_CONFIG
        target.parent.mkdir(parents=True)
        target.write_bytes(b'ButtonA=KeySpace\n')
        with self.assertRaisesRegex(RuntimeError, 'not owned'):
            self.install()
        self.assertEqual(target.read_bytes(), b'ButtonA=KeySpace\n')
        self.assertIsNone(m.load(self.root))

    def test_changed_controller_config_blocks_removal(self):
        self.install()
        target = self.root/m.GAMEPAD_CONFIG
        target.write_bytes(b'ButtonA=KeySpace\n')
        with self.assertRaisesRegex(RuntimeError, 'Managed file changed'):
            m.uninstall(self.root)
        self.assertEqual(target.read_bytes(), b'ButtonA=KeySpace\n')

    def test_non_driver_payload_rejected_before_transaction(self):
        payload = Path(self.temporary.name)/'payload'
        shutil.copytree(self.payload, payload)
        # rEFInd is an EFI application, not a boot-service driver.
        shutil.copyfile(payload/'refind_x64.efi', payload/m.GAMEPAD_DRIVER)
        with self.assertRaisesRegex(ValueError, 'boot-service driver'):
            self.install(payload)
        self.assertIsNone(m.load(self.root))

    def test_configure_from_update_payload(self):
        self.install()
        command = [sys.executable, str(self.payload/'manage.py'), 'configure',
                   '--esp', str(self.root), '--default', 'SteamOS', '--timeout', '7']
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['timeout'], 7)
        self.assertEqual(m.verify(self.root)['timeout'], 7)


if __name__ == '__main__':
    unittest.main()
