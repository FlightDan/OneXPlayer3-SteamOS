"""Real payload file lifecycle tests on isolated directories, no hardware activation."""
import base64
import configparser
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from integration import stage,restore,validate,config_file,zip_files,LogicalFiles,apply_files,package_version
import update_hold

# Supported original-image profile, not a substitute for update_hold.files().
# All staging tests execute the real mandatory preflight, apply and journal.
OFFICIAL_CLIENT=(b'# vendor configuration retained\n[Server]\n'
    b'ImagesUrl = https://steamdeck-images.steamos.cloud/\n'
    b'MetaUrl = https://steamdeck-atomupd.steamos.cloud/meta\n'
    b'Variants = steamdeck\nBranches = stable;rc;beta;bc;preview;pc;main\n'
    b'BranchesDev = main;staging\n')
OFFICIAL_ATOM_UNIT=(b'[Unit]\nDescription=Atomic Update Daemon\n[Service]\n'
    b'Type=dbus\nBusName=com.steampowered.Atomupd1\n'
    b'ExecStartPre=-/usr/bin/true\nExecStart=/usr/lib/atomupd-daemon\n')
OFFICIAL_MANIFEST={'product':'steamos','release':'holo','variant':'steamdeck','arch':'amd64',
    'version':'3.10.0','buildid':'20260924.1000','branch':'main','default_update_branch':'main',
    'introduces_checkpoint':0,'requires_checkpoint':0,'shadow_checkpoint':False,
    'estimated_size':100,'skip':False}

def supported_update_fixture(root):
    files={update_hold.VENDOR_CLIENT:OFFICIAL_CLIENT,
        update_hold.VENDOR_MANIFEST:json.dumps(OFFICIAL_MANIFEST).encode(),
        'usr/lib/os-release':b'NAME="SteamOS"\nID=steamos\nID_LIKE=arch\nVERSION_CODENAME=holo\n',
        'usr/lib/systemd/system/atomupd.service':OFFICIAL_ATOM_UNIT,
        'usr/lib/systemd/system/rauc.service':b'[Service]\nExecStart=/usr/bin/rauc service\n',
        update_hold.STOCK_RAUC:update_hold.STOCK_RAUC_DATA,
        'etc/steamos-atomupd/preferences.conf':b'[Preferences]\nBranch=beta\n'}
    for relative,data in files.items():
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data); path.chmod(0o644)
    for relative,target in ((update_hold.STANDARD_CLIENT,'/usr/lib/steamos-atomupd/client.conf'),
                            (update_hold.STANDARD_MANIFEST,'/usr/lib/steamos-atomupd/manifest.json')):
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.symlink_to(target)

def tree_snapshot(root):
    output={}
    for path in [root,*root.rglob('*')]:
        info=path.lstat()
        data=('link',os.readlink(path)) if path.is_symlink() else ('file',path.read_bytes()) if path.is_file() else ('directory',)
        output[path.relative_to(root).as_posix()]=(data,info.st_mode,info.st_uid,info.st_gid)
    return output


def copy_maintenance_fixture(payload):
    source=Path(__file__).resolve().parent.parent
    source=(source/'maintenance') if (source/'maintenance').is_dir() else source/'cache/maintenance'
    shutil.copytree(source,Path(payload)/'maintenance')

PAYLOAD=Path('/mnt/payload')
CATALOG=json.loads((PAYLOAD/'components/options.json').read_text())

class IntegrationChecks(unittest.TestCase):
    def legacy_payload(self, plugin_ids, repairs=()):
        """Private catalog for retained compatibility paths, never product options."""
        pinned={'protondb':'protondb-1.3.4.zip','hltb':'hltb-2.0.12.zip',
                'tabmaster':'tabmaster-2.15.1+oxp3.1.zip',
                'autoflatpaks':'autoflatpaks-1.6.8+oxp3.1.zip'}
        for name in plugin_ids:
            directory=PAYLOAD/'plugins'/name
            archives=([directory/pinned[name]] if name in pinned else list(directory.glob('*.zip')))
            if not any(path.is_file() for path in archives):
                self.skipTest('Legacy compatibility archive intentionally absent from public payload: '+name)
        temporary=tempfile.TemporaryDirectory(prefix='oxp3-legacy-plugin-payload-')
        self.addCleanup(temporary.cleanup)
        payload=Path(temporary.name)
        # The production trust check rejects linked components/integration trees.
        shutil.copytree(PAYLOAD/'components',payload/'components')
        copy_maintenance_fixture(payload)
        (payload/'integration').mkdir()
        (payload/'plugins').symlink_to(PAYLOAD/'plugins',target_is_directory=True)
        catalog=json.loads((payload/'components/options.json').read_text())
        existing={item['id'] for item in catalog['plugins']}
        catalog['plugins'].extend({'id':name,'default':False,'dependencies':['decky']}
                                 for name in plugin_ids if name not in existing)
        (payload/'components/options.json').write_text(json.dumps(catalog))
        manifest=json.loads((PAYLOAD/'integration/manifest.json').read_text())
        selected={name:manifest[name] for name in repairs}
        for metadata in selected.values():
            for entry in metadata.get('files',[]):
                source=Path(entry['source'])
                target=payload/'integration'/source
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(PAYLOAD/'integration'/source,target)
        (payload/'integration/manifest.json').write_text(json.dumps(selected))
        return payload

    def test_serial_console_policy_repeat_and_restore_both_slots(self):
        from serial_console import DROPIN, DATA
        self.options.update(repairs=[],plugins=[],kde_language='system')
        original=self.root/'etc/systemd/system/getty@tty1.service.d/keep.conf'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'[Service]\nTTYVTDisallocate=no\n')
        for slot in ('A','B'):
            with self.subTest(slot=slot):
                result=stage(self.root,PAYLOAD,self.options,slot)
                self.assertEqual(stage(self.root,PAYLOAD,self.options,slot),result)
                report=result['components']['serial-console-policy']
                self.assertEqual(report['activation'],'next-boot')
                self.assertEqual((self.root/DROPIN).read_bytes(),DATA)
                self.assertEqual((self.root/DROPIN).stat().st_uid,0)
                runtime=self.root/'usr/local/lib/oxp3-integration'
                self.assertEqual((runtime/'serial_console.py').read_bytes(),(PAYLOAD/'components/serial_console.py').read_bytes())
                restored=subprocess.run([sys.executable,'-I','-B',str(runtime/'integration.py'),'restore',
                    '--root',str(self.root),'--slot',slot,'--component','serial-console-policy'],
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(restored.returncode,0,restored.stderr)
                self.assertEqual(json.loads(restored.stdout),[])
                self.assertFalse((self.root/DROPIN).exists())
        self.assertEqual(original.read_bytes(),b'[Service]\nTTYVTDisallocate=no\n')

    def test_serial_console_policy_preserves_later_admin_edit(self):
        from serial_console import DROPIN
        self.options.update(repairs=[],plugins=[],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        changed=b'[Unit]\nConditionKernelCommandLine=custom-serial\n'
        (self.root/DROPIN).write_bytes(changed)
        errors=restore(self.root,'A','serial-console-policy')
        self.assertTrue(errors)
        self.assertEqual((self.root/DROPIN).read_bytes(),changed)

    def test_autoflatpaks_pinned_patch_stages_and_restores(self):
        # 0.1.4 intentionally omits third-party plugins from its default catalog.
        # Exercise the retained compatibility deployment with an explicit private
        # catalog, without reintroducing that option into the product UI.
        payload=self.legacy_payload(['autoflatpaks'])
        self.options.update(repairs=[],plugins=['decky','autoflatpaks'],kde_language='system')
        result=stage(self.root,payload,self.options,'A')
        self.assertEqual(result['components']['autoflatpaks']['status'],'files_installed')
        directory=self.root/'var/lib/oxp3-installer/decky/runtime/plugins/decky-autoflatpaks'
        package=json.loads((directory/'package.json').read_text())
        self.assertEqual(package['version'],'1.6.8+oxp3.1')
        self.assertEqual(package['oxp3_compatibility_patch'],'Defer battery polling until Steam power state is available')
        self.assertIn('window.SystemPowerStore?.batteryState',(directory/'dist/index.js').read_text())
        self.assertNotIn('window.SystemPowerStore.batteryState',(directory/'dist/index.js').read_text())
        self.assertEqual((directory/'dist/index.js').stat().st_uid,0)
        self.assertEqual(stage(self.root,payload,self.options,'A'),result)
        self.assertEqual(restore(self.root,'A','autoflatpaks'),[])
        self.assertFalse((directory/'dist/index.js').exists())

    def test_maintenance_tool_repeat_launch_and_restore(self):
        self.options.update(repairs=[],plugins=[],kde_language='system')
        for slot in ('A','A'):
            result=stage(self.root,PAYLOAD,self.options,slot)
            report=result['components']['maintenance-tool']
            self.assertEqual(report['status'],'files_installed')
            runtime=self.root/'usr/local/lib/oxp3-maintenance'
            release=json.loads((runtime/'current-release.json').read_text())
            self.assertEqual(release['version'],result['release']['version'])
            generation=runtime/'releases'/release['maintenance_runtime']
            self.assertIn('/usr/local/lib/oxp3-maintenance/releases/'+release['maintenance_runtime']+'/entry.py',
                          (runtime/'entry.py').read_text())
            launch=subprocess.run([sys.executable,'-I','-B',str(generation/'entry.py'),'--help'],capture_output=True,text=True)
            self.assertEqual(launch.returncode,0,launch.stderr)
            self.assertIn('gui',launch.stdout)
            desktop=self.root/'home/deck/Desktop/OXP3-Maintenance.desktop'
            menu=self.root/'home/deck/.local/share/applications/OXP3-Maintenance.desktop'
            self.assertEqual(desktop.read_bytes(),menu.read_bytes())
            self.assertIn('Exec=/usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py gui',desktop.read_text())
            self.assertEqual(desktop.stat().st_uid,1000)
            self.assertEqual(desktop.stat().st_mode&0o777,0o755)
            for relative in report['files']:
                if relative.startswith('usr/'):
                    path=self.root/relative
                    self.assertEqual(path.stat().st_uid,0)
                    self.assertFalse(path.stat().st_mode&0o022)
            self.assertEqual(json.loads((runtime/'activation.json').read_text())['components'],{})
            self.assertFalse((self.root/'home/.oxp3-maintenance').exists())
            self.assertFalse((self.root/'etc/systemd/system/multi-user.target.wants/oxp3-maintenance-activate.service').exists())
            self.assertFalse((self.root/'home/deck/.config/systemd/user/timers.target.wants/oxp3-maintenance-check.timer').exists())
            self.assertNotIn('oxp3-maintenance-activate.service',result['services'])
        self.assertEqual(restore(self.root,'A','maintenance-tool'),[])
        self.assertFalse((self.root/'home/deck/Desktop/OXP3-Maintenance.desktop').exists())
        self.assertFalse((self.root/'usr/local/lib/oxp3-maintenance/entry.py').exists())

    def test_maintenance_missing_payload_refuses_before_image_writes(self):
        from unittest.mock import patch
        before=tree_snapshot(self.root)
        with patch('maintenance_tool.files',side_effect=FileNotFoundError('Maintenance application missing')):
            with self.assertRaises(FileNotFoundError):
                stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(tree_snapshot(self.root),before)

    def test_maintenance_manifest_tampering_is_refused(self):
        from maintenance_tool import files
        with tempfile.TemporaryDirectory() as temporary:
            payload=Path(temporary)
            shutil.copytree(PAYLOAD/'maintenance',payload/'maintenance')
            app=payload/'maintenance/app'
            (app/'entry.py').write_bytes(b'raise SystemExit("tampered")\n')
            with self.assertRaisesRegex(RuntimeError,'differs'):
                files(self.root,payload,{'version':'0.1.4'})

    def assert_hold(self,root,result,slot='A'):
        report=result['components']['system-update-hold']
        self.assertEqual(report['status'],'files_installed')
        self.assertEqual(report['activation'],'next-boot')
        self.assertEqual(report['os_image_updates'],'held')
        self.assertEqual(report['steam_client_updates'],'unchanged')
        self.assertEqual(report['steam_game_updates'],'unchanged')
        expected=update_hold.files(root)
        self.assertEqual(set(report['files']),set(expected))
        self.assertEqual(len(expected),18)
        for relative,item in expected.items(): self.assertEqual((root/relative).read_bytes(),item['data'])
        self.assertTrue((root/'home/.oxp3-installer/integration'/slot/'system-update-hold/state.json').is_file())
    def test_shared_storage_preflight_failure_skips_both_slots_and_keeps_repair(self):
        import contextlib,io
        from unittest.mock import patch
        from integration import verify_shared_storage_skip
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system',storage_mounts=[{
            'partuuid':'11111111-2222-3333-4444-555555555555','filesystem':'exfat','mount_name':'share-d1-p1'}])
        original=b'# fixture fstab must remain unchanged\n'
        (self.root/'etc/fstab').write_bytes(original)
        output=io.StringIO()
        with patch('integration.shared_storage_files',side_effect=RuntimeError('Unsafe shared storage path: /mnt/integration-root/mnt')):
            with contextlib.redirect_stdout(output):
                for slot in ('A','B'):
                    result=stage(self.root,PAYLOAD,self.options,slot)
                    state=self.root/'home/.oxp3-installer/integration'/slot
                    report=result['components']['shared-storage']
                    self.assertEqual(report['status'],'not_installed')
                    self.assertTrue(report['safe_to_skip'])
                    self.assertIn('Unsafe shared storage path',report['reason'])
                    self.assertEqual(result['components']['keyboard']['status'],'files_installed')
                    self.assertEqual(json.loads((state/'result.json').read_text()),result)
                    verify_shared_storage_skip(state,report)
                    self.assertFalse((state/'shared-storage').exists())
        self.assertEqual((self.root/'etc/fstab').read_bytes(),original)
        rows=[json.loads(line.removeprefix('OXP_COMPONENT_RESULT=')) for line in output.getvalue().splitlines() if line.startswith('OXP_COMPONENT_RESULT=')]
        self.assertEqual({row['slot'] for row in rows if row['id']=='shared-storage' and row['status']=='not_installed'},{'A','B'})

    def test_shared_storage_preflight_device_errors_remain_fatal(self):
        import errno
        from unittest.mock import patch
        from integration import stage_shared_storage
        state=self.root/'home/.oxp3-installer/integration/A'
        for code in (errno.EIO,errno.ENOSPC,errno.EROFS,errno.ENODEV,errno.EUCLEAN,errno.ENXIO,errno.EBADMSG,errno.ETIMEDOUT):
            with self.subTest(errno=code),patch('integration.shared_storage_files',side_effect=OSError(code,'Device failure')):
                with self.assertRaises(OSError): stage_shared_storage(self.root,state,[],(1000,1000))

    def test_shared_storage_unmanaged_fstab_conflict_is_readonly_skip(self):
        from integration import verify_shared_storage_skip
        self.options.update(repairs=[],plugins=[],kde_language='system',storage_mounts=[{
            'partuuid':'11111111-2222-3333-4444-555555555555','filesystem':'exfat','mount_name':'share-d1-p1'}])
        fstab=self.root/'etc/fstab'
        original=b'PARTUUID=11111111-2222-3333-4444-555555555555 /media/existing exfat defaults 0 0\n'
        fstab.write_bytes(original)
        result=stage(self.root,PAYLOAD,self.options,'A')
        report=result['components']['shared-storage']
        self.assertIn('unmanaged fstab mount',report['reason'])
        verify_shared_storage_skip(self.root/'home/.oxp3-installer/integration/A',report)
        self.assertEqual(fstab.read_bytes(),original)

    def test_shared_storage_existing_transaction_cannot_be_skipped(self):
        from unittest.mock import patch
        from integration import stage_shared_storage,verify_shared_storage_skip
        state=self.root/'home/.oxp3-installer/integration/A'
        report={'status':'not_installed','safe_to_skip':True,'reason':'Unavailable'}
        for directory in (state/'shared-storage',state.parent/'shared/shared-storage'):
            directory.mkdir(parents=True)
            # Even an empty transaction directory can precede an interrupted
            # journal commit, so its absence is required for a safe skip.
            with patch('integration.shared_storage_files',side_effect=RuntimeError('Preflight conflict')):
                with self.assertRaisesRegex(RuntimeError,'Preflight conflict'):
                    stage_shared_storage(self.root,state,[],(1000,1000))
            with self.assertRaisesRegex(RuntimeError,'transaction evidence'):
                verify_shared_storage_skip(state,report)
            directory.rmdir()
        verify_shared_storage_skip(state,report)
        for changed in ({'safe_to_skip':False},{'reason':'  '},{'reason':True},{'files':['etc/fstab']},{'mounts':[{}]}):
            with self.assertRaises(RuntimeError): verify_shared_storage_skip(state,dict(report,**changed))

    def test_shared_storage_partial_write_failure_remains_fatal(self):
        from unittest.mock import patch
        self.options.update(repairs=[],plugins=[],kde_language='system',storage_mounts=[{
            'partuuid':'11111111-2222-3333-4444-555555555555','filesystem':'exfat','mount_name':'share-d1-p1'}])
        apply=apply_files
        def interrupted(root,state,name,files,owner):
            if name=='shared-storage':
                apply(root,state,name,files,owner)
                raise RuntimeError('Interrupted after shared storage write')
            return apply(root,state,name,files,owner)
        with patch('integration.apply_files',interrupted):
            with self.assertRaisesRegex(RuntimeError,'Interrupted after shared storage write'):
                stage(self.root,PAYLOAD,self.options,'A')
        state=self.root/'home/.oxp3-installer/integration/A'
        self.assertTrue((state/'shared-storage/state.json').exists())
        self.assertFalse((state/'result.json').exists())

    def test_decky_order_retries_saved_intent_after_interrupted_journal_commit(self):
        from integration import seed_decky_order
        from decky_order import SETTINGS
        self.options.update(repairs=['oxp3-cpu'],plugins=['decky'],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        state=self.root/'home/.oxp3-installer/integration/A'
        record=state/'decky-order/state.json'
        value=json.loads(record.read_text()); value['phase']='installing'
        record.write_text(json.dumps(value))
        # Simulate interruption after the file rename, before installed was saved.
        original=(self.root/SETTINGS).read_bytes()
        self.assertEqual(seed_decky_order(self.root,state,(1000,1000)),[SETTINGS])
        self.assertEqual((self.root/SETTINGS).read_bytes(),original)
        self.assertEqual(json.loads(record.read_text())['phase'],'installed')

    def test_decky_order_is_per_slot_with_shared_home(self):
        from decky_order import SETTINGS
        payload=self.legacy_payload(['steamgriddb'], repairs=['oxp3-cpu'])
        self.options.update(repairs=['oxp3-cpu'],plugins=['decky','steamgriddb'],kde_language='system')
        temporary=tempfile.TemporaryDirectory(prefix='oxp3-decky-order-B-')
        self.addCleanup(temporary.cleanup); other=Path(temporary.name)
        shutil.copytree(self.root,other,symlinks=True,dirs_exist_ok=True,ignore=shutil.ignore_patterns('home'))
        (self.root/'home').mkdir()
        (other/'home').mkdir()
        subprocess.run(['mount','--bind',str(self.root/'home'),str(other/'home')],check=True)
        self.addCleanup(lambda: subprocess.run(['umount',str(other/'home')],check=True))
        stage(self.root,payload,self.options,'A')
        (self.root/SETTINGS).write_text('{"pluginOrder":["SteamGridDB","OXP3 CPU"]}')
        stage(other,payload,self.options,'B')
        self.assertEqual(json.loads((other/SETTINGS).read_text())['pluginOrder'],['OXP3 CPU','SteamGridDB'])
        self.assertEqual(json.loads((self.root/SETTINGS).read_text())['pluginOrder'],['SteamGridDB','OXP3 CPU'])
        self.assertEqual(restore(other,'B','oxp3-cpu'),[])
        self.assertEqual(restore(other,'B','steamgriddb'),[])
        self.assertEqual(restore(other,'B','decky'),[])
        self.assertFalse((other/SETTINGS).exists())
        self.assertEqual(json.loads((self.root/SETTINGS).read_text())['pluginOrder'],['SteamGridDB','OXP3 CPU'])

    def test_decky_default_order_is_once_only_and_restore_preserves_manual_changes(self):
        from decky_order import SETTINGS
        payload=self.legacy_payload(['steamgriddb'], repairs=['oxp3-cpu'])
        self.options.update(repairs=['oxp3-cpu'],plugins=['decky','steamgriddb'],kde_language='system')
        first=stage(self.root,payload,self.options,'A')
        path=self.root/SETTINGS
        self.assertEqual(json.loads(path.read_text())['pluginOrder'],['OXP3 CPU','SteamGridDB'])
        self.assertIn(SETTINGS,first['components']['decky']['files'])
        self.assertEqual(stage(self.root,payload,self.options,'A'),first)
        path.write_text('{"pluginOrder":["SteamGridDB","OXP3 CPU"],"sortPlugins":false}')
        manual=path.read_bytes()
        stage(self.root,payload,self.options,'A')
        self.assertEqual(path.read_bytes(),manual)
        self.assertEqual(restore(self.root,'A','oxp3-cpu'),[])
        self.assertEqual(restore(self.root,'A','steamgriddb'),[])
        self.assertTrue(restore(self.root,'A','decky'))
        self.assertEqual(path.read_bytes(),manual)

    def test_decky_default_order_restore_removes_only_seeded_settings(self):
        from decky_order import SETTINGS
        self.options.update(repairs=['oxp3-cpu'],plugins=['decky'],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(restore(self.root,'A','oxp3-cpu'),[])
        self.assertEqual(restore(self.root,'A','decky'),[])
        self.assertFalse((self.root/SETTINGS).exists())

    def test_css_theme_directory_is_writable_without_chowning_code(self):
        from runtime_access import require_access
        payload=self.legacy_payload(['css-loader','protondb','hltb','tabmaster'])
        self.options.update(repairs=[],plugins=['decky','css-loader','protondb','hltb','tabmaster'],kde_language='system')
        parent=self.root/'home/deck/homebrew'
        parent.mkdir(parents=True); parent.chmod(0o755)
        sentinel=parent/'root-owned-sentinel'; sentinel.write_text('preserve')
        original=(sentinel.stat().st_uid,sentinel.stat().st_gid)
        old_mask=os.umask(0o077)
        try:
            first=stage(self.root,payload,self.options,'A')
            self.assertEqual(stage(self.root,payload,self.options,'A'),first)
            stage(self.root,payload,self.options,'B')
        finally: os.umask(old_mask)
        themes=parent/'themes'
        self.assertEqual((themes.stat().st_uid,themes.stat().st_gid),(1000,1000))
        self.assertEqual(parent.stat().st_uid,0)
        self.assertEqual((sentinel.stat().st_uid,sentinel.stat().st_gid),original)
        self.root.chmod(0o755)
        require_access(self.root,{'home/deck/homebrew/themes':os.R_OK|os.W_OK|os.X_OK})
        for folder,version in [('protondb-decky','1.3.4'),('hltb-for-deck','2.0.12')]:
            package=self.root/'var/lib/oxp3-installer/decky/runtime/plugins'/folder/'package.json'
            self.assertEqual(json.loads(package.read_text())['version'],version)
            self.assertEqual(package.stat().st_uid,0)
        tabmaster=self.root/'var/lib/oxp3-installer/decky/runtime/plugins/TabMaster'
        package=json.loads((tabmaster/'package.json').read_text())
        self.assertEqual(package['version'],'2.15.1+oxp3.1')
        self.assertEqual(package['oxp3_compatibility_patch'],'Allow absent Steam achievement cache during initialization')
        runtime=(tabmaster/'dist/index.js').read_text()
        self.assertIn('m_achievementProgress?.mapCache?.size ?? 0',runtime)
        self.assertIn('m_achievementProgress?.mapCache?.get(appOverview.appid)',runtime)
        (themes/'user-theme.css').write_text('preserve')
        self.assertEqual(restore(self.root,'A','css-loader'),[])
        self.assertEqual((themes/'user-theme.css').read_text(),'preserve')

    def test_slot_switch_shared_lifecycle(self):
        from runtime_access import require_access
        self.options.update(repairs=['slot-switch'],plugins=[],kde_language='system')
        other_directory=tempfile.TemporaryDirectory(prefix='oxp3-slot-B-')
        self.addCleanup(other_directory.cleanup)
        other=Path(other_directory.name)
        shutil.copytree(self.root,other,symlinks=True,dirs_exist_ok=True,ignore=shutil.ignore_patterns('home'))
        first=stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(first['components']['slot-switch']['status'],'files_installed')
        self.assertEqual(stage(self.root,PAYLOAD,self.options,'A'),first)
        (other/'home').mkdir()
        subprocess.run(['mount','--bind',str(self.root/'home'),str(other/'home')],check=True)
        self.addCleanup(lambda: subprocess.run(['umount',str(other/'home')],check=True))
        stage(other,PAYLOAD,self.options,'B')
        code=self.root/'home/.oxp3-slot-switch/boot.py'
        launcher=self.root/'home/deck/Desktop/oxp3-slot-switch.desktop'
        self.assertEqual(code.stat().st_uid,0)
        self.assertEqual(code.stat().st_mode & 0o777,0o644)
        self.assertEqual(launcher.stat().st_uid,1000)
        self.assertIn('Name=SteamOS 槽位切换 / 系统回退',launcher.read_text())
        self.root.chmod(0o755)
        require_access(self.root,{'home/.oxp3-slot-switch/desktop.py':os.R_OK,
                                 'home/.oxp3-slot-switch/oxp3-switch-slot':os.R_OK|os.X_OK,
                                 'home/deck/Desktop/oxp3-slot-switch.desktop':os.R_OK|os.X_OK})
        self.assertEqual(restore(self.root,'A','slot-switch'),[])
        self.assertFalse(code.exists()); self.assertFalse(launcher.exists())
        stage(self.root,PAYLOAD,self.options,'A')
        code.write_text('# user modification\n')
        self.assertTrue(restore(self.root,'A','slot-switch'))
        self.assertTrue(launcher.exists())
    def test_decky_startup_paths_and_deck_read_access(self):
        from runtime_access import require_access
        payload=self.legacy_payload(['steamgriddb'], repairs=['oxp3-cpu'])
        self.options.update(repairs=['oxp3-cpu'],plugins=['decky','steamgriddb'],kde_language='system')
        old_mask=os.umask(0o077)
        try:
            first=stage(self.root,payload,self.options,'A')
            self.assertEqual(stage(self.root,payload,self.options,'A'),first)
            stage(self.root,payload,self.options,'B')
        finally: os.umask(old_mask)
        privileged=self.root/'var/lib/oxp3-installer/decky/runtime'
        unit=(self.root/'etc/systemd/system/plugin_loader.service').read_text()
        self.assertIn('Environment=PRIVILEGED_PATH=/var/lib/oxp3-installer/decky/runtime',unit)
        self.assertIn('Environment=CHOWN_PLUGIN_PATH=0',unit)
        paths={}
        for folder in ('OXP3-CPU','decky-steamgriddb'):
            plugin=privileged/'plugins'/folder
            for file in (plugin/'plugin.json',plugin/'dist/index.js'):
                self.assertEqual(file.stat().st_uid,0)
                self.assertEqual(file.stat().st_mode & 0o022,0)
                paths[file.relative_to(self.root).as_posix()]=os.R_OK
        marker=self.root/'home/deck/.local/share/Steam/.cef-enable-remote-debugging'
        self.assertEqual(marker.stat().st_uid,1000)
        paths[marker.relative_to(self.root).as_posix()]=os.R_OK
        paths['home/deck/.local/share/Steam']=os.R_OK|os.W_OK|os.X_OK
        self.root.chmod(0o755)
        self.assertEqual(require_access(self.root,paths),len(paths))
        self.assertFalse((self.root/'home/deck/homebrew/plugins').exists())
        self.assertEqual(restore(self.root,'A','oxp3-cpu'),[])
        self.assertEqual(restore(self.root,'A','steamgriddb'),[])
        self.assertEqual(restore(self.root,'A','decky'),[])
        self.assertFalse(marker.exists())

    def test_desktop_return_launcher_repeat_and_existing_marker(self):
        from runtime_access import require_access
        self.options.update(repairs=[],plugins=['decky'],kde_language='system')
        marker=self.root/'home/deck/.local/share/Steam/.cef-enable-remote-debugging'
        marker.parent.mkdir(parents=True)
        marker.write_text('existing marker retained')
        os.chown(marker,1000,1000)
        stage(self.root,PAYLOAD,self.options,'A')
        stage(self.root,PAYLOAD,self.options,'B')
        launcher=self.root/'home/deck/Desktop/Return.desktop'
        self.assertIn('Exec=/usr/bin/steamos-session-select gamescope',launcher.read_text())
        self.assertIn('Name=\u8fd4\u56de\u6e38\u620f\u6a21\u5f0f',launcher.read_text(encoding='utf-8'))
        self.assertEqual(launcher.stat().st_uid,1000)
        self.root.chmod(0o755)
        require_access(self.root,{'home/deck/Desktop/Return.desktop':os.R_OK|os.X_OK})
        self.assertEqual(restore(self.root,'A','decky'),[])
        self.assertEqual(marker.read_text(),'existing marker retained')

    def test_runtime_bundle_directories_ignore_restrictive_umask(self):
        for name,prefix in (('desktop-hdr','opt/oxp3-desktop-gamma22/6.7.3-1.6'),
                            ('opti2xmx','opt/oxp3-opti2xmx/20261005')):
            relative=prefix+'/runtime/lib/library.so'
            old_mask=os.umask(0o077)
            try:
                apply_files(self.root,self.root/'state',name,
                            {relative:{'data':b'runtime fixture','mode':0o644}},(1000,1000))
            finally:
                os.umask(old_mask)
            library=self.root/relative
            self.assertEqual(library.stat().st_mode & 0o777,0o644)
            for directory in (library.parent,library.parent.parent,self.root/prefix,(self.root/prefix).parent):
                self.assertEqual(directory.stat().st_mode & 0o777,0o755,str(directory))
            self.assertEqual(((self.root/prefix).parent/'.installer-state').stat().st_mode & 0o777,0o700)

    def test_directory_modes_do_not_inherit_secret_umask(self):
        from hdr.installer import ensure_directory
        old_mask=os.umask(0o077)
        try:
            public=self.root/'etc/dbus-1/session.d'
            private=self.root/'private-state'
            owned=self.root/'home/deck/.local/lib'
            ensure_directory(public,0o755)
            ensure_directory(private,0o700)
            ensure_directory(owned,0o755,(1000,1000))
        finally:
            os.umask(old_mask)
        for directory in (public,public.parent,owned,owned.parent,owned.parent.parent):
            self.assertEqual(directory.stat().st_mode & 0o777,0o755,str(directory))
        self.assertEqual((owned.stat().st_uid,owned.stat().st_gid),(1000,1000))
        self.assertEqual(private.stat().st_mode & 0o777,0o700)
        # Existing private paths and foreign symlinks must remain untouched.
        ensure_directory(private,0o755)
        self.assertEqual(private.stat().st_mode & 0o777,0o700)
        link=self.root/'private-link'; link.symlink_to(private,target_is_directory=True)
        with self.assertRaises(OSError): ensure_directory(link,0o755)

    def test_resource_io_failure_is_fatal(self):
        from unittest.mock import patch
        import errno
        self.options.update(repairs=[],plugins=['decky'],kde_language='system')
        read_bytes=Path.read_bytes
        def broken(path):
            if path==PAYLOAD/'plugins/decky/PluginLoader': raise OSError(errno.EIO,'Injected device I/O failure')
            return read_bytes(path)
        with patch.object(Path,'read_bytes',broken):
            with self.assertRaisesRegex(OSError,'device I/O failure'):
                stage(self.root,PAYLOAD,self.options,'A')

    def test_invalid_plugin_archive_is_skipped(self):
        from unittest.mock import patch
        import zipfile
        payload=self.legacy_payload(['steamgriddb'])
        self.options.update(repairs=['keyboard'],plugins=['decky','steamgriddb'],kde_language='system')
        with patch('integration.zip_files',side_effect=zipfile.BadZipFile('File is not a zip file')):
            result=stage(self.root,payload,self.options,'A')
        self.assertEqual(result['components']['decky']['status'],'files_installed')
        self.assertTrue(result['components']['steamgriddb']['safe_to_skip'])
        self.assertEqual(result['components']['keyboard']['status'],'files_installed')

    def test_missing_decky_skips_dependents_and_keeps_independent_repair(self):
        from unittest.mock import patch
        self.options.update(repairs=['keyboard'],plugins=['decky','windows-reboot'],kde_language='system')
        read_bytes=Path.read_bytes
        def missing(path):
            if path==PAYLOAD/'plugins/decky/PluginLoader': raise FileNotFoundError('Plugin download unavailable')
            return read_bytes(path)
        with patch.object(Path,'read_bytes',missing):
            for slot in ('A','B'):
                result=stage(self.root,PAYLOAD,self.options,slot)
                for name in ('decky','windows-reboot'):
                    self.assertEqual(result['components'][name]['status'],'not_installed')
                    self.assertTrue(result['components'][name]['safe_to_skip'])
                self.assertIn('Dependency not installed',result['components']['windows-reboot']['reason'])
                self.assertEqual(result['components']['keyboard']['status'],'files_installed')
                self.assertNotIn('plugin_loader.service',result['services'])
        self.assertFalse((self.root/'etc/systemd/system/plugin_loader.service').exists())

    def test_component_write_failure_is_fatal(self):
        from unittest.mock import patch
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        apply=apply_files
        def broken(root,state,name,files,owner):
            if name=='keyboard': raise OSError('Injected interrupted write')
            return apply(root,state,name,files,owner)
        with patch('integration.apply_files',broken):
            with self.assertRaisesRegex(OSError,'interrupted write'):
                stage(self.root,PAYLOAD,self.options,'A')
        self.assertFalse((self.root/'home/.oxp3-installer/integration/A/result.json').exists())

    def test_flathub_fresh_repository_repeat_and_restore_both_slots(self):
        self.options.update(repairs=['flathub-ustc'],plugins=[],kde_language='system')
        definition=self.root/'etc/flatpak/remotes.d/flathub.flatpakrepo'
        for slot in ('A','B'):
            first=stage(self.root,PAYLOAD,self.options,slot)
            self.assertEqual(first['components']['flathub-ustc']['status'],'files_installed')
            parser=configparser.ConfigParser(interpolation=None); parser.read(definition)
            self.assertEqual(parser['Flatpak Repo']['Url'],'https://mirrors.ustc.edu.cn/flathub')
            self.assertGreater(len(base64.b64decode(parser['Flatpak Repo']['GPGKey'],validate=True)),1024)
            self.assertFalse((self.root/'var/lib/flatpak/repo/config').exists())
            self.assertEqual(stage(self.root,PAYLOAD,self.options,slot),first)
            self.assertEqual(restore(self.root,slot,'flathub-ustc'),[])
            self.assertFalse(definition.exists())

    def test_flathub_existing_repo_preserves_keys_other_remotes_and_restores(self):
        self.options.update(repairs=['flathub-ustc'],plugins=[],kde_language='system')
        config=self.root/'var/lib/flatpak/repo/config'; config.parent.mkdir(parents=True)
        definition=self.root/'etc/flatpak/remotes.d/flathub.flatpakrepo'
        definition.parent.mkdir(parents=True); definition.write_text('old declaration\n')
        for remote in (False,True):
            original='[core]\nrepo_version=1\n[remote "other"]\nurl=https://example.org/\n'
            if remote: original+='[remote "flathub"]\nurl=https://dl.flathub.org/repo/\ngpg-verify=true\nxa.title=Custom Flathub\n'
            config.write_text(original)
            result=stage(self.root,PAYLOAD,self.options,'A')
            self.assertEqual(result['components']['flathub-ustc']['status'],'files_installed')
            if remote:
                self.assertIn('gpg-verify=true',config.read_text())
                self.assertIn('xa.title=Custom Flathub',config.read_text())
                self.assertIn('url=https://mirrors.ustc.edu.cn/flathub',config.read_text())
                self.assertIn('[remote "other"]\nurl=https://example.org/',config.read_text())
            else: self.assertEqual(config.read_text(),original)
            self.assertEqual(restore(self.root,'A','flathub-ustc'),[])
            self.assertEqual(config.read_text(),original)
            self.assertEqual(definition.read_text(),'old declaration\n')

    def test_gm7_boot_entries_repeat_and_restore(self):
        self.options.update(repairs=['gm7-resume','xe-dsb'],plugins=[],kde_language='system')
        grub=self.root/'efi/EFI/steamos/grub.cfg'; grub.parent.mkdir(parents=True)
        original='set quiet="quiet splash"\n steamenv_boot /boot/vmlinuz-neptune root=PARTUUID=abc $quiet\n linux /boot/vmlinuz-neptune root=PARTUUID=abc single\n'
        grub.write_text(original)
        disk={'model':'Predator SSD GM7 1TB','bus':'NVMe'}
        first=stage(self.root,PAYLOAD,self.options,'A',target_disk=disk)
        self.assertTrue(first['components']['gm7-resume']['applicable'])
        self.assertEqual(grub.read_text().count('nvme.noacpi=1'),2)
        self.assertEqual(stage(self.root,PAYLOAD,self.options,'A',target_disk=disk),first)
        self.assertEqual(grub.read_text().count('nvme.noacpi=1'),2)
        self.assertEqual(restore(self.root,'A','gm7-resume'),[])
        self.assertEqual(grub.read_text(),original)
        self.assertIn('enable_dsb=0',(self.root/'etc/modprobe.d/xe-oxp3.conf').read_text())
        self.assertEqual(restore(self.root,'A','xe-dsb'),[])
        self.assertFalse((self.root/'etc/modprobe.d/xe-oxp3.conf').exists())

    def test_gm7_does_not_tune_other_disks_or_override_conflicts(self):
        from boot_repairs import gm7_files
        for disk in (None,{'model':'Samsung SSD','bus':'NVMe'},{'model':'Predator GM7','bus':'USB'}):
            self.assertEqual(gm7_files(self.root,disk),{})
        grub=self.root/'efi/EFI/steamos/grub.cfg'; grub.parent.mkdir(parents=True)
        original='steamenv_boot /boot/vmlinuz-neptune nvme.noacpi=0\n'; grub.write_text(original)
        with self.assertRaisesRegex(RuntimeError,'Conflicting'):
            gm7_files(self.root,{'model':'Predator SSD GM7 1TB','bus':'NVMe'})
        self.assertEqual(grub.read_text(),original)

    def test_be201_missing_firmware_repeat_restore_preserves_stock(self):
        self.options.update(repairs=['wifi'],plugins=[],kde_language='system')
        stock=self.root/'usr/lib/firmware/intel/ibt-00a0-0291-usb.sfi.zst'
        stock.parent.mkdir(parents=True); stock.write_bytes(b'stock-compressed-firmware')
        first=stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(first['components']['wifi']['status'],'files_installed')
        self.assertEqual(stage(self.root,PAYLOAD,self.options,'A'),first)
        self.assertFalse(stock.with_suffix('').exists())
        self.assertTrue((stock.parent/'ibt-00a0-0291-iml.sfi').is_file())
        self.assertEqual(restore(self.root,'A','wifi'),[])
        self.assertEqual(stock.read_bytes(),b'stock-compressed-firmware')
        self.assertFalse((stock.parent/'ibt-00a0-0291-iml.sfi').exists())

    def test_fresh_home_allows_deck_to_create_steam(self):
        self._check_home_ownership(False)
    def test_root_owned_home_parents_are_repaired_without_recursive_chown(self):
        self._check_home_ownership(True)
    def _check_home_ownership(self, existing):
        home=self.root/'home/deck'
        directories=('.local','.local/bin','.local/share','.config',
                     '.config/gamescope','.config/gamescope/scripts','.cache')
        if existing:
            for name in directories: (home/name).mkdir(parents=True,exist_ok=True)
            sentinel=home/'.local/share/root-managed-sentinel'
            sentinel.write_text('preserve root-owned file')
        self.options.update(repairs=['keyboard','gamescope-env'],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        self.assertTrue(all(x['status']=='files_installed' for x in result['components'].values()))
        # Check unconditional ancestors and the selected gamescope-env parent.
        # Optional application directories may be created by deck on first use.
        prepared=[home,*[home/name for name in directories],home/'.config/systemd/user']
        if (home/'.local/share/applications').exists(): prepared.append(home/'.local/share/applications')
        for path in prepared:
            self.assertTrue(path.is_dir(),str(path))
            info=path.stat()
            self.assertEqual((info.st_uid,info.st_gid),(1000,1000),str(path))
        if existing:
            self.assertEqual(sentinel.stat().st_uid,0)
            self.assertEqual(sentinel.read_text(),'preserve root-owned file')
        self.root.chmod(0o755)
        # Exercise real Unix permissions as the target UID, not as root.
        code='''import os,sys
from pathlib import Path
os.setgroups([])
os.setgid(1000)
os.setuid(1000)
assert os.getresuid()==(1000,1000,1000)
assert os.getresgid()==(1000,1000,1000)
assert os.getgroups()==[]
home=Path(sys.argv[1])
for relative in ('.local/share/Steam/config/deck-write-check',
                 '.local/share/applications/deck-write-check.desktop',
                 '.cache/steam-write-check'):
    path=home/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(sys.argv[2])
    assert path.read_text()==sys.argv[2]
'''
        created=('.local/share/Steam','.local/share/Steam/config',
                 '.local/share/Steam/config/deck-write-check',
                 '.local/share/applications','.local/share/applications/deck-write-check.desktop',
                 '.cache/steam-write-check')
        subprocess.run(['python3','-c',code,str(home),'first-write'],check=True)
        for name in created:
            info=(home/name).stat()
            self.assertEqual((info.st_uid,info.st_gid),(1000,1000),name)
        stage(self.root,PAYLOAD,self.options,'B')
        for name in created:
            path=home/name; info=path.stat()
            self.assertEqual((info.st_uid,info.st_gid),(1000,1000),name)
            if path.is_file(): self.assertEqual(path.read_text(),'first-write',name)
        # Repeated A/B preparation must leave deck able to update its own files.
        subprocess.run(['python3','-c',code,str(home),'second-write'],check=True)
        for name in created:
            path=home/name
            if path.is_file(): self.assertEqual(path.read_text(),'second-write',name)
        if existing:
            self.assertEqual(sentinel.stat().st_uid,0)
            self.assertEqual(sentinel.read_text(),'preserve root-owned file')
    def test_user_directory_rejects_symlinks_and_foreign_owners(self):
        from hdr.installer import ensure_user_directory
        home=self.root/'home/deck'; home.mkdir(parents=True); os.chown(home,1000,1000)
        outside=self.root/'outside'; outside.mkdir()
        (home/'.local').symlink_to(outside,target_is_directory=True)
        with self.assertRaises((OSError,RuntimeError)):
            ensure_user_directory(home/'.local/share',0o755,(1000,1000),home)
        self.assertEqual(outside.stat().st_uid,0)
        self.assertFalse((outside/'share').exists())
        (home/'.local').unlink(); (home/'.local').mkdir(); os.chown(home/'.local',1001,1001)
        with self.assertRaisesRegex(RuntimeError,'another account'):
            ensure_user_directory(home/'.local/share',0o755,(1000,1000),home)
        self.assertEqual((home/'.local').stat().st_uid,1001)
        with self.assertRaisesRegex(RuntimeError,'inside'):
            ensure_user_directory(outside,0o755,(1000,1000),home)
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='oxp3-options-'); self.root=Path(self.directory.name)
        (self.root/'etc').mkdir(); (self.root/'etc/passwd').write_text('deck:x:1000:1000::/home/deck:/bin/bash\n')
        (self.root/'etc/os-release').write_text('ID=steamos\nVERSION_ID=3.10\nBUILD_ID=20260924.1000\n')
        (self.root/'usr/share/applications').mkdir(parents=True)
        (self.root/'usr/share/applications/org.kde.plasma.keyboard.desktop').write_text('[Desktop Entry]\n')
        (self.root/'usr/bin').mkdir(parents=True,exist_ok=True)
        units=self.root/'usr/lib/systemd/system'; units.mkdir(parents=True,exist_ok=True)
        supported_update_fixture(self.root)
        for tool in ('python3','efibootmgr','systemctl','pkexec','kdialog','steamos-bootconf','busctl'):
            (self.root/'usr/bin'/tool).write_bytes(b'fixture tool')
        p=self.root/'etc/inputplumber/capability_maps.d/onexplayer_type3.yaml'; p.parent.mkdir(parents=True)
        p.write_text('  - name: Keyboard key (Ctrl+Meta+O)\n    target_event:\n      gamepad:\n        button: Keyboard\n  - name: Orange Button\n')
        packages={'gamescope':'3.16.30-1'}
        manifest=json.loads((PAYLOAD/'integration/manifest.json').read_text())
        for item in manifest.values(): packages.update(item.get('packages',{}))
        for name,version in packages.items():
            d=self.root/'var/lib/pacman/local'/(name+'-'+version); d.mkdir(parents=True)
            (d/'desc').write_text('%NAME%\n'+name+'\n\n%VERSION%\n'+version+'\n')
        self.options={'schema':1,'repairs':[x['id'] for x in CATALOG['repairs'] if x['default']], 'plugins':[x['id'] for x in CATALOG['plugins'] if x['default']], 'installer_language':'zh-CN','kde_language':'zh_CN'}
    def tearDown(self): self.directory.cleanup()
    def test_image_database_takes_precedence_over_var(self):
        d=self.root/'usr/lib/holo/pacmandb/local/gamescope-3.16.30-1'; d.mkdir(parents=True)
        (d/'desc').write_text('%NAME%\ngamescope\n\n%VERSION%\n3.16.30-1\n')
        stale=self.root/'var/lib/pacman/local/gamescope-3.16.30-1/desc'
        stale.write_text('%NAME%\ngamescope\n\n%VERSION%\nstale\n')
        self.assertEqual(package_version(self.root,'gamescope'),'3.16.30-1')
        (d/'desc').unlink()
        self.assertIsNone(package_version(self.root,'gamescope'))
    def test_stock_mapping_creates_restorable_override(self):
        override=self.root/'etc/inputplumber/capability_maps.d/oxp3-installer.yaml'
        stock=self.root/'usr/share/inputplumber/capability_maps/oxp3-installer.yaml'
        self.options.update(repairs=['input','multifunction'],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(result['components']['multifunction']['status'],'files_installed')
        self.assertIn('RightPaddle2',override.read_text()); self.assertNotIn('RightPaddle2',stock.read_text())
        self.assertIn('LeftPaddle2',stock.read_text())
        self.assertEqual(restore(self.root,'A','multifunction'),[]); self.assertFalse(override.exists())
    def test_all_default_payloads(self):
        # A prepared image has the mounted slot EFI boot file required by the
        # newly default-selected split-lock repair. Other fixtures intentionally
        # retain missing-EFI behavior for independent component skip checks.
        grub=self.root/'efi/EFI/steamos/grub.cfg'
        grub.parent.mkdir(parents=True)
        grub.write_text('steamenv_boot linux /boot/vmlinuz-linux-neptune-72 root=PARTUUID=fixture quiet\n')
        result=stage(self.root,PAYLOAD,self.options,'A')
        refused={k:v for k,v in result['components'].items() if v['status']!='files_installed'}
        self.assertEqual(refused,{})
        self.assertIn('LANGUAGE=zh_CN',(self.root/'home/deck/.config/plasma-localerc').read_text())
        self.assertIn('RightPaddle2',(self.root/'etc/inputplumber/capability_maps.d/oxp3-installer.yaml').read_text())
        self.assertEqual(json.loads((self.root/'var/lib/oxp3-fan/config.json').read_text()),{'mode':'auto'})
        self.assertFalse(json.loads((self.root/'var/lib/oxp3-cpu/config.json').read_text())['enabled'])
        self.assertEqual((self.root/'usr/bin/steamos-manager').read_bytes(),(PAYLOAD/'integration/manager/steamos-manager').read_bytes())
        self.assertTrue((self.root/'opt/oxp3-desktop-gamma22/6.7.3-1.6/bin/kwin_wayland').is_file())
        opti=self.root/'var/lib/oxp3-installer/decky/runtime/plugins/opti2xmx'
        self.assertEqual(json.loads((opti/'package.json').read_text())['version'],'0.2.4')
        self.assertTrue((opti/'opti.py').is_file())
        for relative in ('main.py','opti.py','plugin.json','dist/index.js'):
            info=(opti/relative).stat()
            self.assertEqual(info.st_uid,0)
            self.assertEqual(info.st_mode&0o022,0)
        self.assertEqual(json.loads((opti/'plugin.json').read_text())['flags'],[])
        self.assertTrue((self.root/'opt/oxp3-opti2xmx/20261005/runtime/igc/neo/bin').is_dir())
        self.assertTrue(os.access(self.root/'opt/oxp3-opti2xmx/20261005/runtime/tools/cm-compile.sh',os.X_OK))
        self.assertFalse((self.root/'home/deck/.local/share/opti2xmx/games').exists())
        # Repeat preserves originals and does not reset control configuration.
        second=stage(self.root,PAYLOAD,self.options,'A'); self.assertEqual(result,second)
        record=self.root/'home/deck/.local/share/opti2xmx/opti/42/current.json'
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'status':'active','injection_enabled':False}))
        with self.assertRaisesRegex(RuntimeError,'Uninstall managed Opti'):
            restore(self.root,'A','opti2xmx')
        self.assertTrue((opti/'main.py').exists())
        record.write_text(json.dumps({'status':'removed','pending':None}))
        self.assertEqual(restore(self.root,'A','opti2xmx'),[])
        self.assertFalse((opti/'main.py').exists())
        self.assertFalse((self.root/'opt/oxp3-opti2xmx/20261005').exists())
        self.assertEqual(restore(self.root,'A','keyboard'),[])
        self.assertFalse((self.root/'home/deck/.config/kwinrc').exists())
        # Restore then install creates a new original epoch.
        data=config_file(self.root,'home/deck/.config/kwinrc','Wayland',{'InputMethod':'/usr/share/applications/org.kde.plasma.keyboard.desktop','VirtualKeyboardMode':'1'})
        apply_files(self.root,self.root/'home/.oxp3-installer/integration/A','keyboard',{'home/deck/.config/kwinrc':{'data':data,'user':True}},(1000,1000))
        self.assertTrue((self.root/'home/deck/.config/kwinrc').exists())
    def test_gyro_lifecycle_preserves_button_mapping(self):
        self.options.update(repairs=['input','multifunction','gyro'],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        self.assertTrue(all(x['status']=='files_installed' for x in result['components'].values()))
        profile=self.root/'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml'
        self.assertIn('gyro_bias: [0, 0, 0]',profile.read_text())
        self.assertIn('gyro_auto_calibrate: false',profile.read_text())
        self.assertIn('y: [-1, 0, 0]',profile.read_text())
        self.assertEqual(stage(self.root,PAYLOAD,self.options,'A'),result)
        with self.assertRaises(RuntimeError): restore(self.root,'A','input')
        self.assertEqual(restore(self.root,'A','gyro'),[])
        self.assertFalse(profile.exists())
        self.assertFalse((self.root/'etc/systemd/system/inputplumber.service.d/oxp3-gyro-v1.conf').exists())
        self.assertTrue((self.root/'etc/inputplumber/devices.d/50-onexplayer_3.yaml').exists())
        self.assertIn('RightPaddle2',(self.root/'etc/inputplumber/capability_maps.d/oxp3-installer.yaml').read_text())
    def test_gyro_live_restore_restarts_input_after_failure(self):
        from unittest.mock import patch
        import integration_runtime as runtime
        commands=[]
        def fake_run(*args):
            commands.append(args)
            return 'enabled' if args==('steamos-readonly','status') else ''
        with patch.object(runtime,'run',side_effect=fake_run), patch.object(runtime.subprocess,'run') as active, patch.object(runtime,'restore',side_effect=RuntimeError('conflict')):
            active.return_value.returncode=0
            with self.assertRaises(RuntimeError): runtime.restore_live('gyro','A')
        self.assertLess(commands.index(('systemctl','stop','inputplumber.service')),commands.index(('systemctl','stop','oxp3-gyro.service')))
        self.assertEqual(commands[-2:],[('systemctl','daemon-reload'),('systemctl','start','inputplumber.service')])
        self.assertIn(('steamos-readonly','enable'),commands)
    def test_gyro_manual_calibration_blocks_partial_restore(self):
        self.options.update(repairs=['input','gyro'],plugins=[],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        profile=self.root/'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml'
        profile.write_text(profile.read_text().replace('gyro_bias: [0, 0, 0]','gyro_bias: [0.1, 0.2, 0.3]'))
        with self.assertRaises(RuntimeError): restore(self.root,'A','gyro')
        self.assertTrue((self.root/'var/lib/oxp3-gyro-v1/launch.sh').is_file())
        self.assertTrue((self.root/'etc/systemd/system/inputplumber.service.d/oxp3-gyro-v1.conf').is_file())
    def test_disabled_items_do_not_install(self):
        self.options.update(repairs=[],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(set(result['components']),{'system-update-hold','serial-console-policy','maintenance-tool'})
        self.assert_hold(self.root,result)
        self.assertFalse((self.root/'usr/lib/firmware/iwlwifi-sc-a0-fm-c0-c106.ucode').exists())
        self.assertFalse((self.root/'home/deck/.config/plasma-localerc').exists())
        self.assertFalse((self.root/'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml').exists())
        self.assertFalse((self.root/'opt/oxp3-opti2xmx').exists())
    def test_incompatible_source_refuses_repairs(self):
        (self.root/'etc/os-release').write_text('ID=steamos\nVERSION_ID=3.8.14\nBUILD_ID=20260707.10\n')
        self.options.update(repairs=['hdr','wifi','input','desktop-hdr'],plugins=[])
        before=tree_snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError,'Unsupported image'):
            stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual(tree_snapshot(self.root),before)
        self.assertFalse((self.root/'opt/oxp3-desktop-gamma22').exists())
        self.assertFalse((self.root/'usr/lib/firmware/iwlwifi-sc-a0-fm-c0-c106.ucode').exists())
    def test_dependency_and_unknown_language_rejected_before_write(self):
        for changed in (dict(self.options,plugins=[]),dict(self.options,kde_language='../../etc'),dict(self.options,repairs=['not-real'])):
            with self.assertRaises(ValueError): stage(self.root,PAYLOAD,changed,'A')
        self.assertFalse((self.root/'home').exists())
    def test_user_changes_block_restore(self):
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        config=self.root/'home/deck/.config/kwinrc'; config.write_text('Manual user edit\n')
        self.assertTrue(restore(self.root,'A','keyboard'))
        self.assertEqual(config.read_text(),'Manual user edit\n')
    def test_changed_request_is_preserved(self):
        self.options.update(repairs=[],plugins=[],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        with self.assertRaises(RuntimeError): stage(self.root,PAYLOAD,dict(self.options,kde_language='en_US'),'A')
    def test_kde_preserves_unrelated_settings(self):
        p=self.root/'home/deck/.config/plasma-localerc'; p.parent.mkdir(parents=True)
        p.write_text('[Formats]\nLANG=de_DE.UTF-8\n[Translations]\nLANGUAGE=de\n[Other]\nkeep=yes\n')
        data=config_file(self.root,'home/deck/.config/plasma-localerc','Translations',{'LANGUAGE':'zh_CN'}).decode()
        self.assertIn('LANG=de_DE.UTF-8',data); self.assertIn('keep=yes',data); self.assertIn('LANGUAGE=zh_CN',data)
    def test_desktop_language_presets_stage_and_restore(self):
        p=self.root/'home/deck/.config/plasma-localerc'; p.parent.mkdir(parents=True)
        original='[Formats]\nLANG=de_DE.UTF-8\n[Translations]\nLANGUAGE=en_US\n[Other]\nkeep=yes\n'
        p.write_text(original)
        for installer_language,desktop_language in (('zh-CN','zh_CN'),('en-US','en_US')):
            with self.subTest(language=installer_language), tempfile.TemporaryDirectory(prefix='oxp3-language-') as directory:
                root=Path(directory); shutil.copytree(self.root,root,symlinks=True,dirs_exist_ok=True)
                config=root/'home/deck/.config/plasma-localerc'
                os.chown(config,1000,1000)
                options=dict(self.options,repairs=[],plugins=[],installer_language=installer_language,kde_language=desktop_language)
                result=stage(root,PAYLOAD,options,'A')
                parser=configparser.ConfigParser(interpolation=None); parser.read(config)
                self.assertEqual(parser['Translations']['LANGUAGE'],desktop_language)
                self.assertEqual(parser['Formats']['LANG'],'de_DE.UTF-8')
                self.assertEqual(parser['Other']['keep'],'yes')
                self.assertEqual(config.stat().st_uid,1000)
                self.assertEqual(result['components']['kde-language']['activation'],'next-login')
                self.assertEqual(stage(root,PAYLOAD,options,'A'),result)
                self.assertEqual(restore(root,'A','kde-language'),[])
                self.assertEqual(config.read_text(),original)
        result=stage(self.root,PAYLOAD,dict(self.options,repairs=[],plugins=[],kde_language='system'),'B')
        self.assertNotIn('kde-language',result['components'])
        self.assertEqual(p.read_text(),original)
    def test_gamescope_environment_isolation_has_independent_restore(self):
        self.options.update(repairs=['gamescope-env'],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        p=self.root/'home/deck/.config/systemd/user/gamescope-session.service.d/90-oxp3-desktop-env-isolation.conf'
        data=p.read_text()
        self.assertIn('unset-environment WAYLAND_DISPLAY WAYLAND_SOCKET',data)
        self.assertIn('UnsetEnvironment=WAYLAND_DISPLAY WAYLAND_SOCKET',data)
        self.assertNotIn('WAYLAND_DISPLAY=',data)
        self.assertEqual(result['components']['gamescope-env']['status'],'files_installed')
        self.assertFalse((self.root/'opt/oxp3-desktop-gamma22').exists())
        self.assertEqual(restore(self.root,'A','gamescope-env'),[])
        self.assertFalse(p.exists())
    def test_live_guard_refuses_this_virtual_machine(self):
        from integration_runtime import device_guard
        with self.assertRaises(RuntimeError): device_guard()
    def test_cross_slot_home_original_and_recovery(self):
        self.options.update(repairs=['keyboard','gamescope-env'],plugins=[],kde_language='system')
        stage(self.root,PAYLOAD,self.options,'A')
        other=Path(self.directory.name)/'slot-B'; (other/'etc').mkdir(parents=True)
        for name in ('passwd','os-release'): (other/'etc'/name).write_bytes((self.root/'etc'/name).read_bytes())
        (other/'usr/share/applications').mkdir(parents=True)
        (other/'usr/share/applications/org.kde.plasma.keyboard.desktop').write_text('[Desktop Entry]\n')
        units=other/'usr/lib/systemd/system'; units.mkdir(parents=True)
        supported_update_fixture(other)
        (other/'home').mkdir(); subprocess.run(['mount','--bind',str(self.root/'home'),str(other/'home')],check=True)
        try:
            stage(other,PAYLOAD,self.options,'B')
            self.assertEqual((other/'usr/local/lib/oxp3-integration/slot').read_text().strip(),'B')
            for target in (self.root,other):
                runtime=target/'usr/local/lib/oxp3-maintenance'
                current=json.loads((runtime/'current-release.json').read_text())
                self.assertTrue((runtime/'releases'/current['maintenance_runtime']/'oxp3_maintenance/touch_ui.py').is_file())
                self.assertTrue((target/'home/deck/Desktop/OXP3-Maintenance.desktop').is_file())
            # Reprepare A after B using separate roots and the real shared home.
            stage(self.root,PAYLOAD,self.options,'A')
            self.assertEqual(restore(other,'B','keyboard'),[])
            self.assertFalse((self.root/'home/deck/.config/kwinrc').exists())
        finally: subprocess.run(['umount',str(other/'home')],check=True)

    def test_new_install_selections_preserve_system_updaters(self):
        # Keep the official updater units unmasked while the required hold is
        # applied through its own real journal for every selection.
        original_updaters={relative:(self.root/relative).read_bytes() for relative in
            ('usr/lib/systemd/system/atomupd.service','usr/lib/systemd/system/rauc.service',
             update_hold.VENDOR_CLIENT,update_hold.VENDOR_MANIFEST,update_hold.STOCK_RAUC,
             'etc/steamos-atomupd/preferences.conf')}
        original_fstab=b'# existing mounts belong to the image\n'
        (self.root/'etc/fstab').write_bytes(original_fstab)
        shadow=b'root:*:20000:0:99999:7:::\ndeck:!:20000:0:99999:7:::\n'
        (self.root/'etc/shadow').write_bytes(shadow); (self.root/'etc/shadow').chmod(0o600)
        (self.root/'usr/lib/systemd/system/sshd.service').write_text('[Service]\nExecStart=/usr/bin/sshd -D\n')
        cases=(('repair',{'repairs':['keyboard']},'keyboard'),
               ('language',{'kde_language':'zh_CN'},'kde-language'),
               ('access',{'set_deck_password':True,'enable_ssh':True},'deck-access'),
               ('disabled',{},None),
               ('skipped',{'repairs':['keyboard','gamescope-env']},'keyboard'))
        for name,choices,component in cases:
            with self.subTest(selection=name):
                root=self.root/name
                shutil.copytree(self.root/'etc',root/'etc',symlinks=True)
                shutil.copytree(self.root/'usr',root/'usr',symlinks=True)
                if name=='skipped':
                    (root/'usr/share/applications/org.kde.plasma.keyboard.desktop').unlink()
                options=dict(self.options,repairs=[],plugins=[],kde_language='system')
                options.update(choices)
                password_hash='$6$fixture$'+'a'*86 if name=='access' else None
                result=stage(root,PAYLOAD,options,'A',deck_password_hash=password_hash)
                self.assert_hold(root,result)
                for relative,data in original_updaters.items(): self.assertEqual((root/relative).read_bytes(),data)
                state=root/'home/.oxp3-installer/integration/A'
                self.assertEqual(json.loads((state/'result.json').read_text()),result)
                self.assertNotIn('system-update-policy',result['components'])
                self.assertFalse((state/'system-update-policy').exists())
                self.assertFalse((root/'var/lib/oxp3-installer/system-update-policy.json').exists())
                for unit in ('atomupd.service','rauc.service'):
                    self.assertFalse(os.path.lexists(root/'etc/systemd/system'/unit))
                self.assertEqual((root/'etc/fstab').read_bytes(),original_fstab)
                if component:
                    self.assertEqual(result['components'][component]['status'],
                                     'not_installed' if name=='skipped' else 'files_installed')
                else: self.assertEqual(set(result['components']),{'system-update-hold','serial-console-policy','maintenance-tool'})
                if name=='repair':
                    self.assertIn('InputMethod=/usr/share/applications/org.kde.plasma.keyboard.desktop',
                                  (root/'home/deck/.config/kwinrc').read_text())
                elif name=='language':
                    self.assertIn('LANGUAGE=zh_CN',(root/'home/deck/.config/plasma-localerc').read_text())
                elif name=='access':
                    self.assertIn('deck:'+password_hash+':',(root/'etc/shadow').read_text())
                    self.assertTrue((root/'etc/systemd/system/multi-user.target.wants/sshd.service').is_symlink())
                elif name=='skipped':
                    self.assertTrue(result['components']['keyboard']['safe_to_skip'])
                    self.assertFalse((root/'home/deck/.config/kwinrc').exists())
                    self.assertEqual(result['components']['gamescope-env']['status'],'files_installed')
                    self.assertIn('UnsetEnvironment=WAYLAND_DISPLAY WAYLAND_SOCKET',
                                  (root/'home/deck/.config/systemd/user/gamescope-session.service.d/90-oxp3-desktop-env-isolation.conf').read_text())

    def test_existing_administrator_update_configuration_is_preserved(self):
        # Each administrator conflict must fail independently, with no home,
        # journal, configuration or component writes preceding the refusal.
        units=self.root/'etc/systemd/system'; units.mkdir(parents=True)
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        for service in ('atomupd.service','rauc.service'):
            for mask in (True,False):
                with self.subTest(service=service,mask=mask):
                    path=units/service
                    if mask: path.symlink_to('/dev/null')
                    else: path.write_bytes(b'[Service]\nExecStart=/usr/local/bin/administrator-updater\n')
                    before=tree_snapshot(self.root)
                    with self.assertRaisesRegex(RuntimeError,'Untrusted|Conflicting updater unit'):
                        stage(self.root,PAYLOAD,self.options,'A')
                    self.assertEqual(tree_snapshot(self.root),before)
                    self.assertFalse((self.root/'home').exists())
                    path.unlink()

    def test_missing_vendor_update_units_refuse_before_new_writes(self):
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        for service in ('atomupd.service','rauc.service'):
            with self.subTest(service=service):
                path=self.root/'usr/lib/systemd/system'/service
                original=path.read_bytes(); path.unlink()
                before=tree_snapshot(self.root)
                with self.assertRaisesRegex(RuntimeError,'Required official file is missing'):
                    stage(self.root,PAYLOAD,self.options,'A')
                self.assertEqual(tree_snapshot(self.root),before)
                self.assertFalse((self.root/'home').exists())
                path.write_bytes(original)

    def test_mandatory_update_hold_real_journals_restore_both_slots(self):
        options=dict(self.options,repairs=[],plugins=[],kde_language='system')
        with tempfile.TemporaryDirectory(prefix='oxp3-hold-B-') as directory:
            other=Path(directory)
            shutil.copytree(self.root,other,symlinks=True,dirs_exist_ok=True)
            for root,slot in ((self.root,'A'),(other,'B')):
                with self.subTest(slot=slot):
                    original=tree_snapshot(root)
                    result=stage(root,PAYLOAD,options,slot)
                    self.assert_hold(root,result,slot)
                    self.assertEqual(stage(root,PAYLOAD,options,slot),result)
                    runtime=root/'usr/local/lib/oxp3-integration'
                    self.assertEqual((runtime/'update_hold.py').read_bytes(),(PAYLOAD/'components/update_hold.py').read_bytes())
                    restored=subprocess.run([sys.executable,'-I','-B',str(runtime/'integration.py'),'restore',
                        '--root',str(root),'--slot',slot,'--component','system-update-hold'],
                        text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
                    self.assertEqual(restored.returncode,0,restored.stderr)
                    self.assertEqual(json.loads(restored.stdout),[])
                    for relative in result['components']['system-update-hold']['files']:
                        self.assertFalse((root/relative).exists(),relative)
                    state=root/'home/.oxp3-installer/integration'/slot
                    self.assertEqual(json.loads((state/'result.json').read_text())['components']['system-update-hold']['status'],'restored')
                    for relative,record in original.items():
                        data=record[0]; path=root/relative
                        if data[0]=='file': self.assertEqual(path.read_bytes(),data[1],relative)
                        elif data[0]=='link': self.assertEqual(os.readlink(path),data[1],relative)

    def test_legacy_update_policy_journal_remains_restorable(self):
        from system_update_policy import files,verify
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        result=stage(self.root,PAYLOAD,self.options,'A')
        state=self.root/'home/.oxp3-installer/integration/A'
        # Reconstruct an installation produced by the former mandatory policy.
        policy=files(self.root)
        apply_files(self.root,state,'system-update-policy',policy,(1000,1000))
        result['components']['system-update-policy']={'status':'files_installed','files':list(policy)}
        (state/'result.json').write_text(json.dumps(result))
        self.assertTrue(verify(self.root)['paused'])
        before=(state/'result.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'original SteamOS image'):
            stage(self.root,PAYLOAD,self.options,'A')
        self.assertEqual((state/'result.json').read_bytes(),before)
        self.assertTrue(verify(self.root)['paused'])
        self.assertEqual(restore(self.root,'A','system-update-policy'),[])
        for unit in ('atomupd.service','rauc.service'):
            self.assertFalse(os.path.lexists(self.root/'etc/systemd/system'/unit))
        self.assertFalse((self.root/'var/lib/oxp3-installer/system-update-policy.json').exists())
        self.assertTrue((self.root/'home/deck/.config/kwinrc').is_file())
        self.assertEqual(json.loads((state/'result.json').read_text())['components']['system-update-policy']['status'],'restored')
        self.assertNotIn('system-update-policy',stage(self.root,PAYLOAD,self.options,'A')['components'])
        for unit in ('atomupd.service','rauc.service'):
            self.assertFalse(os.path.lexists(self.root/'etc/systemd/system'/unit))

    def test_legacy_policy_marker_or_incomplete_journal_refuses_before_new_writes(self):
        self.options.update(repairs=['keyboard'],plugins=[],kde_language='system')
        traces=('var/lib/oxp3-installer/system-update-policy.json',
                'home/.oxp3-installer/integration/B/system-update-policy/state.json')
        for index,relative in enumerate(traces):
            with self.subTest(trace=relative):
                root=self.root/('legacy-'+str(index))
                shutil.copytree(self.root/'etc',root/'etc',symlinks=True)
                trace=root/relative; trace.parent.mkdir(parents=True); trace.write_bytes(b'legacy evidence')
                with self.assertRaisesRegex(RuntimeError,'original SteamOS image'):
                    stage(root,PAYLOAD,self.options,'A')
                self.assertEqual(trace.read_bytes(),b'legacy evidence')
                self.assertFalse((root/'home/deck').exists())
                self.assertFalse((root/'home/.oxp3-installer/integration/A/request.json').exists())

if __name__=='__main__': unittest.main()
