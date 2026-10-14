from pathlib import Path
from unittest.mock import patch
import unittest
from test_manager import Tests


class Lifecycle(Tests):
    def setUp(self):
        super().setUp()
        self.payload=self.home/'payload';self.payload.mkdir()
        for name,data in {'OptiScaler.dll':b'MZ OptiScaler 0.9', 'OptiScaler.ini':b'[FrameGen]\nFGInput=auto\n',
                          'libxess.dll':b'new fixture','fakenvapi.dll':b'MZfake'}.items():
            (self.payload/name).write_bytes(data)
        self.pp=patch.object(self.m,'opti_package',return_value=self.payload);self.pp.start()

    def tearDown(self):
        self.pp.stop();super().tearDown()

    def fresh(self):
        for n in ('dxgi.dll','OptiScaler.ini'):(self.game/n).unlink()

    def install_opti(self,actual=''):
        r=self.m.opti_install(42,'game.exe',actual,'0.9.4','github')
        self.m.opti_confirm(42,r['target']);return r['target']

    def migrate(self,actual='~/fgmod/fgmod %command%'):
        f=self.home/'fgmod';f.mkdir(exist_ok=True)
        for n in ('dxgi.dll','libxess.dll'):
            (f/('OptiScaler.dll' if n=='dxgi.dll' else n)).write_bytes((self.game/n).read_bytes())
        r=self.m.opti_migrate(42,'game.exe',actual)
        self.m.opti_confirm(42,r['target']);return r['target']

    def test_install_remove_rollback_preserves_native_library(self):
        self.fresh();launch=self.install_opti()
        self.assertTrue(self.m.inspect_game(42)['opti']['managed'])
        r=self.m.opti_uninstall(42,launch);self.m.opti_confirm(42,r['target'])
        self.assertFalse((self.game/'dxgi.dll').exists())
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'old fixture')
        self.assertTrue(self.m.inspect_game(42)['opti']['rollback'])
        back=self.m.opti_rollback(42,r['target']);self.m.opti_confirm(42,back['target'])
        self.assertTrue((self.game/'dxgi.dll').exists())

    def test_upgrade_rollback_keeps_old_version(self):
        launch=self.migrate();old=(self.game/'dxgi.dll').read_bytes()
        self.install_opti(launch)
        self.assertNotEqual((self.game/'dxgi.dll').read_bytes(),old)
        p=self.m.opti_rollback(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),old)
        self.assertEqual(self.m.opti_record(42)['version'],'0.7.9')
        self.m.opti_uninstall(42,launch)

    def test_migrate_active_xmx_disable_then_upgrade(self):
        x=self.enable();self.m.confirm_launch(42,x['launch'])
        with (self.game/'OptiScaler.ini').open('a') as f:f.write('\n[User]\nKeep=this\n')
        launch=self.migrate(x['launch'])
        self.assertEqual(launch,x['launch'])
        x=self.m.restore(42,launch);self.m.confirm_launch(42,x['old_launch'])
        self.assertEqual(x['old_launch'],self.m.opti_record(42)['launch'])
        self.assertIn('Keep=this',(self.game/'OptiScaler.ini').read_text())
        self.install_opti(x['old_launch'])

    def test_active_xmx_settings_then_disable_uninstall(self):
        self.fresh();launch=self.install_opti()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        settings=dict(sr='xess',fg='xefg',fg_input='fsrfg30',spoof='real')
        self.m.opti_settings(42,settings)
        self.assertIn('FGOutput=xefg',(self.game/'OptiScaler.ini').read_text())
        with self.assertRaisesRegex(RuntimeError,'真实显卡'):
            self.m.opti_settings(42,dict(settings,spoof='nvidia'))
        self.m.restore(42,x['launch']);self.m.confirm_launch(42,launch)
        self.m.opti_uninstall(42,launch)

    def test_foreign_dll_blocks_removal_without_partial_change(self):
        self.fresh();launch=self.install_opti()
        (self.game/'nvapi64.dll').write_bytes(b'MZ foreign')
        with self.assertRaisesRegex(RuntimeError,'其他工具'):
            self.m.opti_uninstall(42,launch)
        self.assertTrue((self.game/'dxgi.dll').exists())

    def test_mid_copy_failure_can_rollback(self):
        self.fresh();copy=self.m.runtime().atomic_copy
        def fail(src,dst,*a,**kw):
            if Path(dst)==self.game/'libxess.dll':raise OSError('simulated disk failure')
            return copy(src,dst,*a,**kw)
        with patch.object(self.m.runtime(),'atomic_copy',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'操作中断'):self.install_opti()
        r=self.m.opti_rollback(42,'');self.m.opti_confirm(42,r['target'])
        self.assertFalse((self.game/'dxgi.dll').exists())
        self.assertEqual((self.game/'libxess.dll').read_bytes(),b'old fixture')

    def test_pending_launch_blocks_other_mutation(self):
        self.fresh();self.m.opti_install(42,'game.exe','','0.9.4','github')
        with self.assertRaisesRegex(RuntimeError,'待完成'):
            self.m.opti_install(42,'game.exe','','0.9.4','github')
        with self.assertRaisesRegex(RuntimeError,'尚未确认'):self.m.opti_confirm(42,'wrong')

    def test_existing_injector_never_overwritten(self):
        (self.game/'OptiScaler.ini').unlink()
        (self.game/'dxgi.dll').write_bytes(b'MZ reshade')
        with self.assertRaisesRegex(RuntimeError,'其他注入器'):self.install_opti()

    def test_changed_ini_is_backed_up_on_upgrade_rollback(self):
        launch=self.migrate();self.install_opti(launch)
        (self.game/'OptiScaler.ini').write_text('[User]\nNew=keep\n')
        revision=Path(self.m.opti_record(42)['undo']['folder'])
        p=self.m.opti_rollback(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual(next(revision.glob('later-ini-*')).read_text(),'[User]\nNew=keep\n')

    def test_toggle_keeps_xmx_and_settings_then_uninstall(self):
        self.fresh();launch=self.install_opti()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        with (self.game/'OptiScaler.ini').open('a') as f:f.write('\n[User]\nKeep=overlay\n')
        ini=(self.game/'OptiScaler.ini').read_bytes()
        for enabled in (False,True,False):
            p=self.m.opti_toggle(42,enabled,x['launch']);self.assertEqual(p['target'],x['launch'])
            self.m.opti_confirm(42,p['target'])
            self.assertEqual((self.game/'dxgi.dll').exists(),enabled)
            self.assertEqual((self.game/'nvapi64.dll').exists(),enabled)
            self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),ini)
            self.assertEqual(self.m.state(42)['status'],'active')
            self.assertEqual(self.m.inspect_game(42)['opti']['injection_enabled'],enabled)
        self.m.restore(42,x['launch']);self.m.confirm_launch(42,launch)
        self.m.opti_uninstall(42,launch)

    def test_disabled_opti_allows_native_xmx_and_rollback(self):
        self.fresh();launch=self.install_opti()
        p=self.m.opti_toggle(42,False,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual(self.m.inspect_game(42)['automatic']['route'],'native')
        x=self.m.enable(42,'game.exe','native',launch);self.m.confirm_launch(42,x['launch'])
        self.m.restore(42,x['launch']);self.m.confirm_launch(42,launch)
        p=self.m.opti_rollback(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertTrue((self.game/'dxgi.dll').exists())
        self.assertTrue(self.m.inspect_game(42)['opti']['injection_enabled'])

    def test_toggle_restores_original_nvapi_and_rejects_foreign_changes(self):
        self.fresh();(self.game/'nvapi64.dll').write_bytes(b'MZ original')
        launch=self.install_opti()
        p=self.m.opti_toggle(42,False,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual((self.game/'nvapi64.dll').read_bytes(),b'MZ original')
        (self.game/'dxgi.dll').write_bytes(b'MZ other mod')
        with self.assertRaisesRegex(RuntimeError,'其他工具'):self.m.opti_toggle(42,True,launch)
        self.assertEqual((self.game/'nvapi64.dll').read_bytes(),b'MZ original')

    def test_live_toggle_rejected_and_mid_write_rollback(self):
        self.fresh();launch=self.install_opti()
        with patch.object(self.m.runtime(),'game_idle',side_effect=RuntimeError('Game is running')):
            with self.assertRaisesRegex(RuntimeError,'running'):self.m.opti_toggle(42,False,launch)
        self.assertTrue((self.game/'dxgi.dll').exists())

    def test_legacy_fake_nvapi_backup_is_not_injected_in_native_mode(self):
        self.fresh();(self.game/'nvapi64.dll').write_bytes(b'MZ old fakenvapi')
        launch=self.install_opti()
        p=self.m.opti_toggle(42,False,launch);self.m.opti_confirm(42,p['target'])
        self.assertFalse((self.game/'nvapi64.dll').exists())
        p=self.m.opti_toggle(42,True,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual((self.game/'nvapi64.dll').read_bytes(),b'MZfake')
        p=self.m.opti_toggle(42,False,launch);self.m.opti_confirm(42,p['target'])
        p=self.m.opti_uninstall(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertEqual((self.game/'nvapi64.dll').read_bytes(),b'MZ old fakenvapi')

    def test_toggle_partial_removal_is_recoverable(self):
        self.fresh();launch=self.install_opti()
        unlink=Path.unlink
        def fail(p,*a,**kw):
            if p==self.game/'nvapi64.dll':raise OSError('disk failure')
            return unlink(p,*a,**kw)
        with patch.object(Path,'unlink',fail):
            with self.assertRaisesRegex(RuntimeError,'操作中断'):self.m.opti_toggle(42,False,launch)
        p=self.m.opti_rollback(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertTrue((self.game/'dxgi.dll').exists())

    def test_default_fg_input_can_be_saved_and_system_tools_are_isolated(self):
        from opti import system_env
        self.fresh();self.install_opti()
        settings=self.m.inspect_game(42)['opti']['settings']
        self.m.opti_settings(42,settings)
        with (self.game/'OptiScaler.ini').open('a') as f:f.write('\n[FrameGen]\nEnabled=true\nFGOutput=XeFG\n')
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg'],'xefg')
        with patch.dict('os.environ',{'LD_LIBRARY_PATH':'/tmp/decky-bundle'},clear=True):
            self.assertNotIn('LD_LIBRARY_PATH',system_env())


if __name__=='__main__':unittest.main()
