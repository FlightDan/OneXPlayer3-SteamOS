"""Linux fixture tests. No real Steam/game paths or driver execution."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import manager

spec = importlib.util.spec_from_file_location('engine', Path(__file__).with_name('per_game.py'))
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.steam = self.home / '.local/share/Steam'
        self.game = self.steam / 'steamapps/common/Test Game'
        self.game.mkdir(parents=True)
        self.prefix = self.steam / 'steamapps/compatdata/42/pfx'
        (self.prefix / 'drive_c/windows/system32').mkdir(parents=True)
        (self.steam / 'steamapps/appmanifest_42.acf').write_text('"AppState" { "appid" "42" "name" "Test Game" "installdir" "Test Game" }')
        (self.game / 'game.exe').write_bytes(b'MZfixture')
        (self.game / 'dxgi.dll').write_bytes(b'MZ OptiScaler fixture')
        (self.game / 'libxess.dll').write_bytes(b'old fixture')
        (self.game / 'OptiScaler.ini').write_text('[Upscalers]\nDx12Upscaler=fsr31\n[Spoofing]\nDxgi=true\n')
        self.m = manager.Manager(self.home, engine)
        self.package = self.home / 'package'
        for name in ('igdext64.dll','lib/libvulkan_intel.so','tools/cm-compile.sh','tools/cmk_pack.py',
                     'igc/neo/bin/ocloc','igc/igc/local/lib/libigc.so'):
            p = self.package / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('fixture')
            p.chmod(0o700)
        self.sr = self.home / 'libxess.dll'; self.sr.write_bytes(b'new fixture')
        self.patches = [patch.object(self.m, 'dependencies', return_value=(self.package, self.sr, True)),
                        patch.object(manager, 'pe_version', side_effect=lambda p: (2,0,2,68) if p.read_bytes()==b'new fixture' else (2,0,2,53)),
                        patch.object(engine, 'stock_icds', return_value=[])]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def enable(self):
        return self.m.enable(42, 'game.exe', 'opti', '~/fgmod/fgmod %command%')

    def test_vdf_empty_comments_escaped(self):
        self.assertEqual(manager.vdf('"root" { // comment\n "empty" "" "quote" "a\\\"b" }'), {'root': {'empty': '', 'quote': 'a"b'}})

    def test_inventory_external_library_and_selection(self):
        self.assertEqual(self.m.inventory()[0]['appid'],42)
        self.assertIn('game.exe', self.m.inspect_game(42)['executables'])
        with self.assertRaises(ValueError): self.m.game(True)
        with self.assertRaises(RuntimeError): self.m.game(43)

    def test_enable_roundtrip_and_no_foreign_changes(self):
        original = (self.game / 'OptiScaler.ini').read_bytes()
        r = self.enable()
        self.assertEqual(r['status'], 'pending_launch')
        self.assertEqual((self.game / 'libxess.dll').read_bytes(), b'new fixture')
        ini = (self.game / 'OptiScaler.ini').read_text()
        self.assertIn('Dx12Upscaler=xess', ini); self.assertIn('Dxgi=false', ini)
        cfg = (Path(r['state'])/'xmx/game.conf').read_text()
        self.assertIn('INTC_ALT_DRIVER_EXTENSIONS_PATH=',cfg)
        self.assertEqual(cfg.count('INTC_ALT_DRIVER_EXTENSIONS_PATH='),1)
        self.assertEqual(Path(r['shim_path']),engine.recorded_dll_path(engine.load(Path(r['state'])/'xmx')))
        self.assertEqual(Path(r['shim_path']),self.prefix/'drive_c/opti2xmx-driver/igdext64.dll')
        import subprocess
        result=subprocess.check_output(['bash','-c',cfg+'\nprintf "%s" "$DXVK_CONFIG"'],
                                       env=dict(os.environ,DXVK_CONFIG='dxgi.maxFrameRate = 60'),text=True)
        self.assertEqual(result,'dxgi.maxFrameRate = 60;dxgi.customVendorId = 8086;dxgi.customDeviceId = -1;dxgi.customDeviceDesc = ""')
        self.assertEqual(self.m.confirm_launch(42,r['launch'])['status'],'active')
        restored = self.m.restore(42,r['launch'])
        self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),original)
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'old fixture')
        self.assertFalse(engine.prefix_dll_path(self.prefix).exists())
        self.assertEqual(self.m.confirm_launch(42,restored['old_launch'])['status'],'restored')
        self.assertEqual(self.enable()['status'],'pending_launch')

    def test_live_game_rejected_before_backup(self):
        with patch.object(engine,'game_idle',side_effect=RuntimeError('live game')):
            with self.assertRaisesRegex(RuntimeError,'live game'): self.enable()
        self.assertFalse(self.m.pointer(42).exists())

    def test_unknown_launch_chain_preserved(self):
        with self.assertRaisesRegex(RuntimeError,'自定义启动项'):
            self.m.enable(42,'game.exe','opti','strange-wrapper %command%')
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'old fixture')

    def test_external_setup_preserved(self):
        (self.prefix/engine.OWNER_REL).write_text('/other/state')
        self.assertTrue(self.m.inspect_game(42)['external_managed'])
        with self.assertRaisesRegex(RuntimeError,'外部 XMX'): self.enable()

    def test_conflicting_restore_is_all_or_nothing(self):
        r=self.enable()
        (self.game/'OptiScaler.ini').write_text('user changes')
        with self.assertRaisesRegex(RuntimeError,'文件已被'):self.m.restore(42,r['launch'])
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'new fixture')
        self.assertTrue(engine.prefix_dll_path(self.prefix).exists())

    def test_external_launch_change_blocks_restore(self):
        self.enable()
        with self.assertRaisesRegex(RuntimeError,'启动项已被'):self.m.restore(42,'different %command%')
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'new fixture')

    def test_interrupted_option_write_recoverable(self):
        r=self.enable()
        with self.assertRaisesRegex(RuntimeError,'读回不一致'):self.m.confirm_launch(42,'bad')
        restored=self.m.restore(42,r['old_launch'])
        self.assertEqual(restored['status'],'pending_restore_launch')
        # Repeated restore after UI disconnection is idempotent.
        self.assertEqual(self.m.restore(42,r['old_launch'])['status'],'pending_restore_launch')

    def test_partial_file_failure_recoverable(self):
        real=engine.atomic_copy
        def failing(src,dst):
            if Path(dst)==self.game/'OptiScaler.ini': raise OSError('injected write failure')
            return real(src,dst)
        with patch.object(engine,'atomic_copy',side_effect=failing):
            with self.assertRaisesRegex(RuntimeError,'接入未完成'): self.enable()
        r=self.m.state(42);self.assertEqual(r['status'],'recovery_required')
        self.m.restore(42,r['old_launch'])
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'old fixture')

    def test_symlink_and_unlisted_exe_rejected(self):
        with self.assertRaises(ValueError):self.m.enable(42,'../other.exe','opti','')
        (self.game/'libxess.dll').unlink()
        (self.game/'libxess.dll').symlink_to(self.sr)
        with self.assertRaisesRegex(RuntimeError,'没有找到'):self.enable()

    def test_unknown_dxgi_preserved(self):
        (self.game/'dxgi.dll').write_bytes(b'other mod')
        with self.assertRaisesRegex(RuntimeError,'未识别'):self.enable()
        self.assertFalse(self.m.pointer(42).exists())

    def test_native_route_does_not_touch_opti_ini(self):
        original=(self.game/'OptiScaler.ini').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'已有 OptiScaler'):
            self.m.enable(42,'game.exe','native','')
        self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),original)

    def test_native_route_without_opti(self):
        (self.game/'OptiScaler.ini').unlink()
        (self.game/'dxgi.dll').unlink()
        r=self.m.enable(42,'game.exe','native','')
        self.assertNotIn('dxgi=n,b',(Path(r['state'])/'launch.sh').read_text())
        self.m.restore(42,r['old_launch'])

    def test_imported_core_restore_uses_original_location(self):
        r=self.enable()
        # Mimic a metadata import retaining an existing core outside the new state.
        oldcore=Path(r['state'])/'xmx'
        imported=self.home/'existing-core'
        oldcore.rename(imported)
        manifest=engine.load.__wrapped__(imported) if hasattr(engine.load,'__wrapped__') else json.loads((imported/'manifest.json').read_text())
        manifest['state']=str(imported)
        # Core config and snapshots remain intact at their original physical paths
        # in real imports. This fixture only checks delegation, not relocation.
        r['core_state']=str(imported);r['imported']=True;self.m.save(r)
        with patch.object(engine,'load',return_value=manifest), patch.object(engine,'restore') as restore:
            self.m.restore(42,r['old_launch'])
            self.assertEqual(restore.call_args.args[0].state,str(imported))

    def test_duplicate_ini_key_rejected(self):
        with self.assertRaises(RuntimeError): manager.ini_set('[A]\nx=1\nx=2\n','A','x','3')

    def test_demo_auto_selects_native_and_skips_helpers(self):
        (self.game/'OptiScaler.ini').unlink()
        (self.game/'game.exe').rename(self.game/'riftbreaker_win_release.exe')
        (self.game/'CrashReporter.exe').write_text('helper')
        (self.game/'Launcher.exe').write_text('helper')
        plan=self.m.inspect_game(42)['automatic']
        self.assertEqual(plan['executable'],'riftbreaker_win_release.exe')
        self.assertEqual(plan['route'],'native')
        self.assertEqual(plan['reason'],'')

    def test_auto_does_not_guess_between_game_variants(self):
        (self.game/'alternate.exe').write_text('alternate game')
        plan=self.m.inspect_game(42)['automatic']
        self.assertEqual(plan['executable'],'')
        self.assertEqual(len(plan['candidates']),2)
        self.assertIn('多个',plan['reason'])

    def test_auto_uses_managed_executable(self):
        self.enable()
        (self.game/'alternate.exe').write_text('alternate')
        plan=self.m.inspect_game(42)['automatic']
        self.assertEqual(plan['executable'],'game.exe')
        self.assertEqual(plan['route'],'opti')

    def test_runtime_tools_not_in_game_menu(self):
        (self.steam/'steamapps/appmanifest_99.acf').write_text('"AppState" {"appid" "99" "name" "Proton 11.0" "installdir" "Test Game"}')
        self.assertEqual([g['appid'] for g in self.m.inventory()],[42])


if __name__=='__main__': unittest.main(verbosity=2)
