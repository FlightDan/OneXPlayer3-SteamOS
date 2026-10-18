from pathlib import Path
from unittest.mock import patch
import copy
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

    def test_opti_install_works_without_xmx_runtime(self):
        self.fresh()
        with patch.object(self.m, 'dependencies', return_value=(self.package, self.sr, False)):
            info = self.m.inspect_game(42)
            self.assertFalse(info['runtime_ready'])
            self.assertEqual(info['automatic']['reason'], 'XMX 运行组件未就绪。')
            with self.assertRaisesRegex(RuntimeError, '运行组件'):
                self.m.enable(42, 'game.exe', 'native', '')
            self.install_opti()
            self.assertTrue(self.m.inspect_game(42)['opti']['managed'])

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
        with self.assertRaisesRegex(RuntimeError,'注入文件'):self.install_opti()

    def test_partial_install_restores_exact_leftovers_and_keeps_legacy_backup(self):
        (self.game/'dxgi.dll').unlink()
        before={n:(self.game/n).read_bytes() for n in ('OptiScaler.ini','libxess.dll')}
        (self.game/'libxess.dll.b').write_bytes(b'legacy backup')
        status=self.m.inspect_game(42)['opti']
        self.assertTrue(status['incomplete'])
        self.assertFalse(status['injection_enabled'])
        launch=self.install_opti()
        self.assertFalse(self.m.inspect_game(42)['opti']['incomplete'])
        self.assertEqual(self.m.inspect_game(42)['automatic']['reason'],'')
        pending=self.m.opti_uninstall(42,launch);self.m.opti_confirm(42,pending['target'])
        self.assertFalse((self.game/'dxgi.dll').exists())
        self.assertEqual({n:(self.game/n).read_bytes() for n in before},before)
        self.assertEqual((self.game/'libxess.dll.b').read_bytes(),b'legacy backup')

    def test_partial_install_copy_failure_rolls_back(self):
        (self.game/'dxgi.dll').unlink()
        before={n:(self.game/n).read_bytes() for n in ('OptiScaler.ini','libxess.dll')}
        original=self.m.runtime().atomic_copy
        def fail(src,dst,*args,**kwargs):
            if Path(dst)==self.game/'libxess.dll':raise OSError('disk failure')
            return original(src,dst,*args,**kwargs)
        with patch.object(self.m.runtime(),'atomic_copy',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'操作中断'):self.install_opti()
        pending=self.m.opti_rollback(42,'');self.m.opti_confirm(42,pending['target'])
        self.assertFalse((self.game/'dxgi.dll').exists())
        self.assertEqual({n:(self.game/n).read_bytes() for n in before},before)

    def test_partial_install_rechecks_proxy_after_download(self):
        (self.game/'dxgi.dll').unlink()
        before=(self.game/'OptiScaler.ini').read_bytes()
        def download(*args,**kwargs):
            (self.game/'dxgi.dll').write_bytes(b'MZ foreign')
            return self.payload
        with patch.object(self.m,'opti_package',side_effect=download):
            with self.assertRaisesRegex(RuntimeError,'注入文件'):self.install_opti()
        self.assertFalse(self.m.opti_path(42).exists())
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),b'MZ foreign')
        self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),before)

    def test_removed_record_does_not_authorize_overwriting_proxy(self):
        self.fresh();launch=self.install_opti()
        pending=self.m.opti_uninstall(42,launch);self.m.opti_confirm(42,pending['target'])
        (self.game/'dxgi.dll').write_bytes(b'MZ foreign')
        with self.assertRaisesRegex(RuntimeError,'注入文件'):self.install_opti(pending['target'])
        self.assertEqual((self.game/'dxgi.dll').read_bytes(),b'MZ foreign')

    def test_multi_executable_remembers_managed_selection(self):
        self.fresh();(self.game/'other.exe').write_bytes(b'MZ fixture')
        self.assertEqual(self.m.inspect_game(42)['automatic']['executable'],'')
        self.install_opti()
        self.assertEqual(self.m.inspect_game(42)['automatic']['executable'],'game.exe')

    def test_partial_install_rejects_foreign_nvapi(self):
        (self.game/'dxgi.dll').unlink()
        (self.game/'nvapi64.dll').write_bytes(b'MZ foreign')
        with self.assertRaisesRegex(RuntimeError,'注入文件'):self.install_opti()
        self.assertFalse(self.m.opti_path(42).exists())
        self.assertEqual((self.game/'nvapi64.dll').read_bytes(),b'MZ foreign')

    def test_partial_reinstall_after_disabled_uninstall(self):
        (self.game/'dxgi.dll').unlink()
        launch=self.install_opti()
        pending=self.m.opti_toggle(42,False,launch);self.m.opti_confirm(42,pending['target'])
        pending=self.m.opti_uninstall(42,launch);self.m.opti_confirm(42,pending['target'])
        self.install_opti(pending['target'])
        self.assertTrue(self.m.inspect_game(42)['opti']['injection_enabled'])

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

    def fg_settings(self, multiplier=None):
        result=dict(sr='xess',fg='xefg',fg_input='upscaler',spoof='real')
        if multiplier is not None:result['fg_multiplier']=multiplier
        return result

    def test_multiplier_requests_are_written_read_and_old_rpc_defaults_to_two(self):
        self.fresh();self.install_opti()
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg_multiplier'],'native')
        for multiplier,interpolations in [('2','1'),('3','2'),('4','3'),('native','auto')]:
            self.m.opti_settings(42,self.fg_settings(multiplier))
            self.assertIn('InterpolationCount='+interpolations,(self.game/'OptiScaler.ini').read_text())
            self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg_multiplier'],multiplier)
            self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg'],'native' if multiplier=='native' else 'xefg')
        self.m.opti_settings(42,self.fg_settings())
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg_multiplier'],'2')
        ini=self.game/'OptiScaler.ini';before=ini.read_bytes()
        for value in ['1','5','auto',4,None]:
            with self.assertRaises(ValueError):self.m.opti_settings(42,self.fg_settings(value) if value is not None else dict(self.fg_settings(),fg_multiplier=None))
            self.assertEqual(ini.read_bytes(),before)
        ini.write_text('[XeFG]\nInterpolationCount=auto\n')
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg_multiplier'],'native')

    def test_settings_undo_is_independent_and_latest_only(self):
        self.fresh();self.install_opti()
        install_undo=copy.deepcopy(self.m.opti_record(42)['undo'])
        self.m.opti_settings(42,self.fg_settings('3'))
        prior=(self.game/'OptiScaler.ini').read_bytes()
        self.m.opti_settings(42,self.fg_settings('4'))
        self.assertTrue(self.m.inspect_game(42)['opti']['settings_rollback'])
        self.m.opti_restore_settings(42)
        self.assertEqual((self.game/'OptiScaler.ini').read_bytes(),prior)
        self.assertEqual(self.m.opti_record(42)['undo'],install_undo)
        self.assertFalse(self.m.inspect_game(42)['opti']['settings_rollback'])
        with self.assertRaisesRegex(RuntimeError,'没有可恢复'):self.m.opti_restore_settings(42)

    def test_active_xmx_settings_undo_restores_each_mirror_and_original_preferences(self):
        self.fresh();launch=self.install_opti()
        self.m.opti_settings(42,dict(sr='fsr31',fg='native',fg_input='upscaler',spoof='nvidia'))
        ini=self.game/'OptiScaler.ini';preferences=ini.read_bytes()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        _,_,_,targets=self.m._settings_context(42)
        originals={path:path.read_bytes() for path in targets}
        self.assertGreater(len(set(originals.values())),1)
        self.m.opti_settings(42,self.fg_settings('4'))
        r,info,_,targets=self.m._settings_context(42)
        self.assertEqual(len(targets),4)
        self.assertTrue(all(p.read_bytes()==ini.read_bytes() for p in targets))
        self.m.opti_restore_settings(42)
        self.assertEqual({p:p.read_bytes() for p in targets},originals)
        self.m.restore(42,x['launch']);self.m.confirm_launch(42,launch)
        self.assertEqual(ini.read_bytes(),preferences)

    def test_settings_first_write_failure_preserves_four_distinct_originals(self):
        self.fresh();launch=self.install_opti()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        ini=self.game/'OptiScaler.ini'
        _,_,_,targets=self.m._settings_context(42)
        for n,path in enumerate(targets):path.write_bytes(path.read_bytes()+f'\n; distinct mirror {n}\n'.encode())
        originals={path:path.read_bytes() for path in targets}
        self.assertEqual(len(set(originals.values())),4)
        atomic=self.m.runtime().atomic_copy
        def fail_before_first_write(src,dst):
            if Path(dst)==ini:raise OSError('failure before first write')
            return atomic(src,dst)
        with patch.object(self.m.runtime(),'atomic_copy',side_effect=fail_before_first_write):
            with self.assertRaisesRegex(RuntimeError,'设置保存未完成'):self.m.opti_settings(42,self.fg_settings('4'))
        self.assertEqual({path:path.read_bytes() for path in targets},originals)
        self.m.opti_restore_settings(42)
        self.assertEqual({path:path.read_bytes() for path in targets},originals)

    def test_saved_settings_undo_accepts_current_target_subset_after_xmx_off(self):
        self.fresh();launch=self.install_opti()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        self.m.opti_settings(42,self.fg_settings('4'))
        journal=copy.deepcopy(self.m.opti_record(42)['settings_undo'])
        originals={f['path']:Path(f['observed']).read_bytes() for f in journal['files']}
        self.m.restore(42,x['launch']);self.m.confirm_launch(42,launch)
        _,_,_,targets=self.m._settings_context(42)
        self.assertEqual(len(targets),2)
        inactive={Path(name):Path(name).read_bytes() for name in originals if name not in set(map(str,targets))}
        self.m.opti_restore_settings(42)
        self.assertTrue(all(path.read_bytes()==originals[str(path)] for path in targets))
        self.assertEqual({path:path.read_bytes() for path in inactive},inactive)
        self.assertEqual(set(f['path'] for f in self.m.opti_record(42)['settings_undo']['files']),set(map(str,targets)))

    def test_saved_settings_undo_refuses_new_mirror_targets_without_writing(self):
        self.fresh();launch=self.install_opti();self.m.opti_settings(42,self.fg_settings('4'))
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        _,_,_,targets=self.m._settings_context(42)
        before={path:path.read_bytes() for path in targets}
        with self.assertRaisesRegex(RuntimeError,'恢复目标已变化'):self.m.opti_restore_settings(42)
        self.assertEqual({path:path.read_bytes() for path in targets},before)

    def test_settings_undo_refuses_external_changes_live_games_and_symlinks(self):
        self.fresh();self.install_opti();self.m.opti_settings(42,self.fg_settings('4'))
        ini=self.game/'OptiScaler.ini';saved=ini.read_bytes()
        with patch.object(self.m.runtime(),'game_idle',side_effect=RuntimeError('Game is running')):
            with self.assertRaisesRegex(RuntimeError,'running'):self.m.opti_restore_settings(42)
            with self.assertRaisesRegex(RuntimeError,'running'):self.m.opti_settings(42,self.fg_settings())
        ini.write_bytes(saved+b'\n[External]\nKeep=external edit\n')
        with self.assertRaisesRegex(RuntimeError,'外部修改'):self.m.opti_restore_settings(42)
        self.assertTrue(ini.read_bytes().endswith(b'Keep=external edit\n'))
        ini.unlink();external=self.home/'external.ini';external.write_bytes(saved);ini.symlink_to(external)
        with self.assertRaisesRegex(RuntimeError,'普通文件'):self.m.opti_restore_settings(42)
        with self.assertRaisesRegex(RuntimeError,'普通文件'):self.m.opti_settings(42,self.fg_settings())
        self.assertEqual(external.read_bytes(),saved)

    def test_pending_lifecycle_and_xmx_operations_block_settings(self):
        self.fresh();p=self.m.opti_install(42,'game.exe','','0.9.4','github')
        with self.assertRaisesRegex(RuntimeError,'待完成'):self.m.opti_settings(42,self.fg_settings())
        with self.assertRaisesRegex(RuntimeError,'待完成'):self.m.opti_restore_settings(42)
        self.m.opti_confirm(42,p['target'])
        x=self.m.enable(42,'game.exe','opti',p['target'])
        with self.assertRaisesRegex(RuntimeError,'XMX 操作待完成'):self.m.opti_settings(42,self.fg_settings())

    def test_each_partial_settings_write_has_retryable_recovery_and_blocks_other_changes(self):
        self.fresh();launch=self.install_opti()
        x=self.m.enable(42,'game.exe','opti',launch);self.m.confirm_launch(42,x['launch'])
        _,_,_,targets=self.m._settings_context(42)
        originals={path:path.read_bytes() for path in targets}
        atomic=self.m.runtime().atomic_copy
        for target in targets:
            with self.subTest(target=str(target)):
                def fail(src,dst):
                    if Path(dst)==target:raise OSError('injected synchronization failure')
                    return atomic(src,dst)
                with patch.object(self.m.runtime(),'atomic_copy',side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError,'设置保存未完成'):self.m.opti_settings(42,self.fg_settings('4'))
                self.assertTrue(self.m.inspect_game(42)['opti']['settings_recovery'])
                for operation in [lambda:self.m.opti_settings(42,self.fg_settings()),
                                  lambda:self.m.opti_toggle(42,False,x['launch']),
                                  lambda:self.m.restore(42,x['launch']),
                                  lambda:self.m.opti_rollback(42,x['launch'])]:
                    with self.assertRaisesRegex(RuntimeError,'恢复上次设置'):operation()
                self.m.opti_restore_settings(42)
                self.assertEqual({path:path.read_bytes() for path in targets},originals)
                self.assertFalse(self.m.inspect_game(42)['opti']['settings_recovery'])

    def test_partial_settings_restore_and_final_journal_write_can_retry(self):
        self.fresh();self.install_opti()
        ini=self.game/'OptiScaler.ini';original=ini.read_bytes()
        self.m.opti_settings(42,self.fg_settings('4'))
        _,_,_,targets=self.m._settings_context(42)
        atomic=self.m.runtime().atomic_copy
        def fail(src,dst):
            if Path(dst)==targets[-1]:raise OSError('restore sync failure')
            return atomic(src,dst)
        with patch.object(self.m.runtime(),'atomic_copy',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'设置恢复未完成'):self.m.opti_restore_settings(42)
        self.assertEqual(ini.read_bytes(),original)
        self.assertTrue(self.m.inspect_game(42)['opti']['settings_recovery'])
        self.m.opti_restore_settings(42)
        journal=self.m.opti_record(42)['settings_undo']
        self.assertTrue(all(Path(f['path']).read_bytes()==Path(f['observed']).read_bytes() for f in journal['files']))
        save=self.m.opti_save
        def fail_complete(appid,record):
            if (record.get('settings_undo') or {}).get('status')=='saved':raise OSError('journal disk failure')
            return save(appid,record)
        with patch.object(self.m,'opti_save',side_effect=fail_complete):
            with self.assertRaisesRegex(RuntimeError,'设置保存未完成'):self.m.opti_settings(42,self.fg_settings('3'))
        self.assertTrue(self.m.inspect_game(42)['opti']['settings_recovery'])
        self.m.opti_restore_settings(42)
        self.assertEqual(ini.read_bytes(),original)
        self.m.opti_settings(42,self.fg_settings('4'))
        def fail_restore_complete(appid,record):
            if (record.get('settings_undo') or {}).get('status')=='restored':raise OSError('restore journal disk failure')
            return save(appid,record)
        with patch.object(self.m,'opti_save',side_effect=fail_restore_complete):
            with self.assertRaisesRegex(RuntimeError,'设置恢复未完成'):self.m.opti_restore_settings(42)
        self.assertTrue(self.m.inspect_game(42)['opti']['settings_recovery'])
        self.m.opti_restore_settings(42)
        self.assertEqual(ini.read_bytes(),original)

    def test_settings_undo_rejects_snapshot_symlink_and_journal_path_escape(self):
        self.fresh();self.install_opti();self.m.opti_settings(42,self.fg_settings('4'))
        r=self.m.opti_record(42);journal=copy.deepcopy(r['settings_undo'])
        ini=self.game/'OptiScaler.ini';before=ini.read_bytes()
        outside=self.home/'outside.ini';outside.write_bytes(b'preserve external file')
        r['settings_undo']['before']=str(outside);self.m.opti_save(42,r)
        with self.assertRaisesRegex(RuntimeError,'备份路径'):self.m.opti_restore_settings(42)
        self.assertEqual(ini.read_bytes(),before)
        r['settings_undo']=journal;self.m.opti_save(42,r)
        snapshot=Path(journal['before']);snapshot.unlink();snapshot.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError,'普通文件'):self.m.opti_restore_settings(42)
        self.assertEqual(ini.read_bytes(),before)
        self.assertEqual(outside.read_bytes(),b'preserve external file')

    def test_version_change_resets_multiplier_and_cannot_resurrect_settings_undo(self):
        self.fresh();launch=self.install_opti();self.m.opti_settings(42,self.fg_settings('4'))
        self.install_opti(launch)
        self.assertEqual(self.m.inspect_game(42)['opti']['settings']['fg_multiplier'],'native')
        self.assertFalse(self.m.inspect_game(42)['opti']['settings_rollback'])
        p=self.m.opti_rollback(42,launch);self.m.opti_confirm(42,p['target'])
        self.assertFalse(self.m.inspect_game(42)['opti']['settings_rollback'])


if __name__=='__main__':unittest.main()
