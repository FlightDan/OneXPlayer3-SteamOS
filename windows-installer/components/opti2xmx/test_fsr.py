import argparse
import hashlib
import json
from pathlib import Path
import struct
from unittest.mock import patch
import zipfile

import fsr
from fsr_cm import correct_pre
from test_manager import Tests, engine


def pe_fixture():
    data = bytearray(2048)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 1)
    struct.pack_into('<H', data, 0x94, 240)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x20b)
    struct.pack_into('<II', data, optional + 120, 0x1000, 40)
    section = optional + 240
    struct.pack_into('<IIII', data, section + 8, 1024, 0x1000, 1024, 0x200)
    struct.pack_into('<IIIII', data, 0x200, 0x1060, 0, 0, 0x1080, 0x1060)
    data[0x280:0x28c] = b'Cabinet.dll\0'
    return bytes(data)


class FsrTests(Tests):
    def setUp(self):
        super().setUp()
        self.model = self.home / 'model'
        self.model.mkdir()
        files = {'amd_fidelityfx_upscaler_dx12.dll': pe_fixture(),
                 'fsr-original.dll': b'MZ original weights', 'nvngx_dlss.dll': b'MZ unused DLSS companion'}
        self.archive = self.home / 'model.zip'
        with zipfile.ZipFile(self.archive, 'w') as out:
            for name, data in files.items():out.writestr(name, data)
        self.pin = dict(schema=1, version='4.1.2-lite-xmx-0.6', sha256=fsr.digest(self.archive),
                        size_bytes=self.archive.stat().st_size, opti_version='10.0.0-pre1_20261025',
                        patched_upscaler_sha256=hashlib.sha256(fsr.patch_decompressor_import(pe_fixture())).hexdigest(),
                        files={name:dict(size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})
        self.pin_patch = patch.object(fsr, 'descriptor', return_value=self.pin)
        self.pin_patch.start()
        self.compat = {}
        for name in ('fsrxdec.dll', 'libwim-15.dll'):
            path = self.home / name
            path.write_bytes(b'MZ fixture ' + name.encode())
            self.compat[name] = path
        self.compat_patch = patch.object(self.m, '_fsr_compat', return_value=self.compat)
        self.compat_patch.start()
        self.payload = self.home / 'opti10'
        (self.payload / 'OptiScaler').mkdir(parents=True)
        (self.payload / 'OptiScaler.dll').write_bytes(b'MZ OptiScaler v10 fixture')
        (self.payload / 'OptiScaler.ini').write_text('[Upscalers]\nDx12Upscaler=xess\n[FrameGen]\nEnabled=false\n')
        (self.payload / 'OptiScaler/libxess.dll').write_bytes(b'new fixture')
        self.package_patch = patch.object(self.m, 'opti_package', return_value=self.payload)
        self.package_patch.start()

    def tearDown(self):
        self.package_patch.stop()
        self.compat_patch.stop()
        self.pin_patch.stop()
        super().tearDown()

    def prepare_fsr(self):
        self.m.fsr_import(str(self.archive))
        for name in ('OptiScaler.ini', 'dxgi.dll', 'libxess.dll'):
            (self.game / name).unlink()
        pending = self.m.fsr_prepare(42, 'game.exe', '', 'github')
        self.m.opti_confirm(42, pending['target'])
        return pending['target']

    def select_fsr(self):
        old = self.prepare_fsr()
        xmx = self.m.enable(42, 'game.exe', 'opti', old)
        self.m.confirm_launch(42, xmx['launch'])
        self.m.opti_settings(42, dict(sr='fsr_xmx', fg='native', fg_input='upscaler', spoof='real'))
        return old, xmx

    def test_import_patches_only_the_dependency_name_and_rejects_wrong_zip(self):
        self.assertFalse(self.m.fsr_status()['ready'])
        self.assertTrue(self.m.fsr_import(str(self.archive))['ready'])
        path = self.m._fsr_payload()
        changed = (path / 'amd_fidelityfx_upscaler_dx12.dll').read_bytes()
        before = pe_fixture()
        self.assertEqual(len(changed), len(before))
        self.assertEqual(changed[:0x280], before[:0x280])
        self.assertEqual(changed[0x28c:], before[0x28c:])
        self.assertEqual(changed[0x280:0x28c], b'fsrxdec.dll\0')
        current = (self.m._fsr_root() / 'current.json').read_bytes()
        altered = self.home / 'wrong.zip'
        altered.write_bytes(self.archive.read_bytes()[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.m.fsr_import(str(altered))
        self.assertEqual((self.m._fsr_root() / 'current.json').read_bytes(), current)

    def test_fresh_prepare_installs_root_sdk_and_can_enable(self):
        old, xmx = self.select_fsr()
        self.assertEqual((self.game / 'libxess.dll').read_bytes(), b'new fixture')
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['sr'], 'fsr_xmx')
        ini = self.game / 'OptiScaler.ini'
        original = next(Path(row['original']) for row in xmx['files'] if row['path'] == str(ini))
        self.assertIn('Dx12Upscaler=xess', original.read_text())
        self.assertIn('UpscalerIndex=auto', original.read_text())
        self.assertIn('fsr-compile.sh', (Path(xmx['state']) / 'xmx/game.conf').read_text())
        self.m.restore(42, xmx['launch'])
        self.m.confirm_launch(42, old)
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['sr'], 'xess')
        self.assertFalse(self.m.inspect_game(42)['opti']['settings_rollback'])

    def test_fsr_cannot_run_on_inactive_or_old_xmx_bridge(self):
        old = self.prepare_fsr()
        settings = dict(sr='fsr_xmx', fg='native', fg_input='upscaler', spoof='real')
        with self.assertRaisesRegex(RuntimeError, 'XMX'):
            self.m.opti_settings(42, settings)
        xmx = self.m.enable(42, 'game.exe', 'opti', old)
        self.m.confirm_launch(42, xmx['launch'])
        xmx.pop('fsr_bridge')
        self.m.save(xmx)
        with self.assertRaisesRegex(RuntimeError, 'XMX'):
            self.m.opti_settings(42, settings)

    def test_known_core_adopts_companions_as_originals_without_claiming_them(self):
        core=self.game/'dxgi.dll'
        self.pin['known_opti_cores']={fsr.digest(core):{'size_bytes':core.stat().st_size,'version':'0.9.4'}}
        original={p:p.read_bytes() for p in self.game.iterdir() if p.is_file()}
        pending=self.m.opti_migrate(42,'game.exe','')
        self.m.opti_confirm(42,pending['target'])
        record=self.m.opti_record(42)
        self.assertTrue(record['preserves_preexisting_installation'])
        self.assertEqual(record['version'],'0.9.4')
        (self.game/'libxess.dll').write_bytes(b'replacement must be refused')
        with self.assertRaisesRegex(RuntimeError,'其他工具'):
            self.m.opti_uninstall(42,pending['target'])
        (self.game/'libxess.dll').write_bytes(original[self.game/'libxess.dll'])
        removed=self.m.opti_uninstall(42,pending['target'])
        self.m.opti_confirm(42,removed['target'])
        for path,data in original.items():self.assertEqual(path.read_bytes(),data)

    def test_injection_toggle_keeps_safe_restore_and_undo_roundtrip(self):
        old, xmx = self.select_fsr()
        pending = self.m.opti_toggle(42, False, xmx['launch'])
        self.m.opti_confirm(42, pending['target'])
        pending = self.m.opti_toggle(42, True, xmx['launch'])
        self.m.opti_confirm(42, pending['target'])
        self.m.restore(42, xmx['launch'])
        self.m.confirm_launch(42, old)
        self.assertIn('Dx12Upscaler=xess', (self.game / 'OptiScaler.ini').read_text())

    def test_fsr_setting_undo_while_active_keeps_projection_separate(self):
        old, xmx = self.select_fsr()
        self.m.opti_settings(42, dict(sr='xess', fg='native', fg_input='upscaler', spoof='real'))
        self.m.opti_restore_settings(42)
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['sr'], 'fsr_xmx')
        self.m.restore(42, xmx['launch'])
        self.m.confirm_launch(42, old)
        self.assertIn('Dx12Upscaler=xess', (self.game / 'OptiScaler.ini').read_text())

    def test_runtime_failure_blocks_fsr_instead_of_stock_fallback(self):
        _, xmx = self.select_fsr()
        with patch.object(engine, 'compiler_check', return_value=(False, 'fixture unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'FSR XMX requires'):
                engine.launch(argparse.Namespace(state=str(Path(xmx['state']) / 'xmx'), command=['echo', 'not-run']))

    def test_pre_profile_changes_metadata_only_and_xess_passes_unchanged(self):
        code = b'compiled machine code fixture'
        data = bytearray(472 + len(code))
        data[:4] = b'CMK2'
        data[472:] = code
        struct.pack_into('<4I', data, 168, 0xffffffff, 0, 0, 11)
        struct.pack_into('<11I', data, 280, *range(11))
        path = self.home / '46fe6c9997eb76ed_b080_fixture.cmk'
        path.write_bytes(data)
        self.assertTrue(correct_pre(path))
        after = path.read_bytes()
        self.assertEqual(after[:168], data[:168])
        self.assertEqual(after[180:], data[180:])
        other = self.home / 'native-xess.cmk'
        other.write_bytes(b'unrelated compiler output')
        self.assertFalse(correct_pre(other))
        self.assertEqual(other.read_bytes(), b'unrelated compiler output')
