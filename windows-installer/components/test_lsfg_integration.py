"""LSFG-VK manifest policy and optional Decky file lifecycle checks."""
import json
import os
from pathlib import Path
import unittest

from integration import (LSFG_PLUGIN_NAME, LSFG_PLUGIN_VERSION, LSFG_RUNTIME_ARCHIVE,
                         PLUGIN_ROOT, validate_lsfg_files)


class LSFGManifestChecks(unittest.TestCase):
    def files(self):
        prefix=PLUGIN_ROOT+'/'+LSFG_PLUGIN_NAME+'/'
        return {
            prefix+'plugin.json': {'data':json.dumps({'name':LSFG_PLUGIN_NAME}).encode(), 'user':False},
            prefix+'package.json': {'data':json.dumps({'name':'decky-lsfg-vk','version':LSFG_PLUGIN_VERSION}).encode(), 'user':False},
            prefix+'main.py': {'data':b'# upstream backend\n', 'user':False},
            prefix+'dist/index.js': {'data':b'// upstream frontend\n', 'user':False},
            prefix+LSFG_RUNTIME_ARCHIVE: {'data':b'pinned offline archive fixture', 'user':False},
        }

    def test_accepts_only_the_pinned_plugin_tree_and_runtime_archive(self):
        files=self.files()
        self.assertIs(validate_lsfg_files(files),files)

    def test_rejects_targets_outside_managed_plugin_tree(self):
        files=self.files(); files['home/deck/.config/lsfg-vk/config.json']={'data':b'{}','user':True}
        with self.assertRaisesRegex(RuntimeError,'inside its Decky plugin directory'):
            validate_lsfg_files(files)

    def test_rejects_path_traversal_and_user_owned_plugin_files(self):
        files=self.files(); prefix=PLUGIN_ROOT+'/'+LSFG_PLUGIN_NAME+'/'
        files[prefix+'../../home/deck/config.json']={'data':b'{}','user':False}
        with self.assertRaisesRegex(RuntimeError,'inside its Decky plugin directory'):
            validate_lsfg_files(files)
        files=self.files(); files[prefix+'main.py']['user']=True
        with self.assertRaisesRegex(RuntimeError,'root-owned'):
            validate_lsfg_files(files)

    def test_rejects_wrong_identity_version_mode_or_missing_runtime(self):
        files=self.files(); prefix=PLUGIN_ROOT+'/'+LSFG_PLUGIN_NAME+'/'
        files[prefix+'package.json']['data']=json.dumps({'name':'decky-lsfg-vk','version':'0.12.8'}).encode()
        with self.assertRaisesRegex(RuntimeError,'identity or version'):
            validate_lsfg_files(files)
        files=self.files(); files[prefix+'main.py']['mode']=0o666
        with self.assertRaisesRegex(RuntimeError,'file mode'):
            validate_lsfg_files(files)
        files=self.files(); files.pop(prefix+LSFG_RUNTIME_ARCHIVE)
        with self.assertRaisesRegex(RuntimeError,'Missing LSFG-VK runtime file'):
            validate_lsfg_files(files)


class LSFGIntegrationChecks(unittest.TestCase):
    def test_optional_plugin_lifecycle_uses_manifest_and_preserves_user_settings(self):
        # The complete guest payload is built by prepare-integration.py. A local
        # source checkout without that prepared payload still runs the pure guard tests.
        payload=Path('/mnt/payload')
        manifest_path=payload/'integration/manifest.json'
        if not manifest_path.is_file(): self.skipTest('Prepared integration payload is unavailable')
        from test_integration import IntegrationChecks, PAYLOAD
        self.assertEqual(PAYLOAD,payload)
        manifest=json.loads(manifest_path.read_text())
        metadata=manifest.get('lsfg-vk')
        if not metadata or not metadata.get('files'): self.skipTest('Prepared LSFG-VK component manifest is unavailable')

        fixture=IntegrationChecks('test_all_default_payloads')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        catalog=json.loads((PAYLOAD/'components/options.json').read_text())
        item=next(x for x in catalog['plugins'] if x['id']=='lsfg-vk')
        self.assertFalse(item['default'])
        self.assertEqual(item['dependencies'],['decky'])
        fixture.options.update(repairs=[],plugins=['decky','lsfg-vk'],kde_language='system')

        from integration import restore, stage
        first=stage(fixture.root,PAYLOAD,fixture.options,'A')
        component=first['components']['lsfg-vk']
        self.assertEqual(component['status'],'files_installed')
        self.assertEqual(component['activation'],'decky-session-pending')
        self.assertEqual(component['runtime_install'],'user-initiated-from-decky')
        self.assertEqual(component['automatic_game_configuration'],'unchanged')
        self.assertIn('Install LSFG in Decky',component['next_step_en'])
        self.assertIn('Decky 中点击 Install LSFG',component['next_step_zh'])
        prefix='var/lib/oxp3-installer/decky/runtime/plugins/Decky LSFG-VK/'
        targets={entry['target'] for entry in metadata['files']}
        self.assertEqual(set(component['files']),targets)
        self.assertTrue(targets)
        self.assertTrue(all(path.startswith(prefix) for path in targets))
        for entry in metadata['files']:
            target=fixture.root/entry['target']
            expected=(PAYLOAD/'integration'/entry['source']).read_bytes()
            self.assertEqual(target.read_bytes(),expected)
            info=target.stat()
            self.assertEqual((info.st_uid,info.st_gid),(0,0))
            self.assertFalse(info.st_mode&0o022)

        settings=fixture.root/'home/deck/.config/lsfg-vk/user-settings.json'
        settings.parent.mkdir(parents=True,exist_ok=True)
        os.chown(settings.parent,1000,1000)
        settings.write_bytes(b'{"game_options":[] }\n')
        os.chown(settings,1000,1000)
        repeated=stage(fixture.root,PAYLOAD,fixture.options,'A')
        self.assertEqual(first,repeated)
        self.assertEqual(settings.read_bytes(),b'{"game_options":[] }\n')
        with self.assertRaisesRegex(RuntimeError,'Restore dependent components first'):
            restore(fixture.root,'A','decky')
        self.assertEqual(restore(fixture.root,'A','lsfg-vk'),[])
        self.assertTrue(all(not (fixture.root/path).exists() for path in targets))
        self.assertEqual(settings.read_bytes(),b'{"game_options":[] }\n')
        self.assertEqual(restore(fixture.root,'A','decky'),[])


if __name__=='__main__':
    unittest.main()
