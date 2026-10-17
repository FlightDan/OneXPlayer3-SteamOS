"""Data-only compatibility checks; downloaded plugin code is never executed."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from oxp3_maintenance.components import (
    _patch_animation_changer, _zip_files, build_plan, KERNEL, VERSION, PLUGIN_ROOT,
)


PREFIX = PLUGIN_ROOT + '/SDH-AnimationChanger/'
ORIGINAL = b"OVERRIDE_PATH = os.path.expanduser('~/.steam/root/config/uioverrides/movies')"
REPLACEMENT = b"OVERRIDE_PATH = os.path.expanduser('~/.local/share/Steam/config/uioverrides/movies')"
BACKEND = b'import os\n' + ORIGINAL + b'\nraise AssertionError("downloaded code executed")\n'


def payload():
    return {
        PREFIX + 'plugin.json': {'data': b'{"name":"Animation Changer"}'},
        PREFIX + 'package.json': {'data': b'{"name":"decky-animation-changer","version":"1.3.2"}'},
        PREFIX + 'main.py': {'data': BACKEND, 'mode': 0o644, 'user': False},
        PREFIX + 'LICENSE': {'data': b'Upstream license fixture'},
    }


def archive(path, files):
    with zipfile.ZipFile(path, 'w') as package:
        for name, entry in files.items():
            package.writestr('SDH-AnimationChanger/' + name[len(PREFIX):], entry['data'])
        package.writestr('SDH-AnimationChanger/dist/index.js', b'frontend')


class AnimationCompatibilityTests(unittest.TestCase):
    def test_only_assignment_bytes_change_with_metadata_preserved(self):
        files = payload()
        before = copy.deepcopy(files)
        changed = _patch_animation_changer(files, PREFIX)
        self.assertEqual(files, before)
        self.assertEqual(changed[PREFIX + 'main.py'], dict(before[PREFIX + 'main.py'],
                         data=BACKEND.replace(ORIGINAL, REPLACEMENT)))
        self.assertIsNot(changed, files)
        for name in files:
            if not name.endswith('/main.py'):
                self.assertEqual(changed[name], before[name])

    def test_unsupported_identity_version_or_source_fail_before_mutation(self):
        variants = [
            ('plugin.json', b'{"name":"Other Plugin"}'),
            ('plugin.json', b'[]'),
            ('package.json', b'null'),
            ('package.json', b'{"name":"other","version":"1.3.2"}'),
            ('package.json', b'{"name":"decky-animation-changer","version":"1.3.3"}'),
            ('main.py', BACKEND.replace(b'OVERRIDE_PATH =', b'OVERRIDE_PATH=')),
            ('main.py', BACKEND + BACKEND),
            ('main.py', BACKEND.replace(ORIGINAL, REPLACEMENT)),
        ]
        for relative, raw in variants:
            with self.subTest(relative=relative, raw=raw[:50]):
                files = payload()
                files[PREFIX + relative]['data'] = raw
                before = copy.deepcopy(files)
                with self.assertRaisesRegex(ValueError, 'Unsupported Animation Changer'):
                    _patch_animation_changer(files, PREFIX)
                self.assertEqual(files, before)

    def test_missing_backend_is_refused(self):
        files = payload()
        del files[PREFIX + 'main.py']
        with self.assertRaisesRegex(ValueError, 'Missing Animation Changer'):
            _patch_animation_changer(files, PREFIX)

    def test_archive_adapter_patches_in_memory_and_never_executes_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plugin.zip'
            archive(path, payload())
            before = path.read_bytes()
            with patch('subprocess.run', side_effect=AssertionError('Unexpected execution')):
                files = _zip_files(path, 'animation-changer', '1.3.2')
            self.assertEqual(files[PREFIX + 'main.py']['data'], BACKEND.replace(ORIGINAL, REPLACEMENT))
            self.assertEqual(path.read_bytes(), before)

    def test_real_pinned_archive_gets_exact_data_patch_without_cache_mutation(self):
        path = Path('C:/steamosmod/windows-installer/cache/plugins/animation-changer/animation-changer-1.3.2.zip')
        if not path.is_file():
            self.skipTest('Pinned installer cache unavailable')
        before = hashlib.sha256(path.read_bytes()).digest()
        with zipfile.ZipFile(path) as package:
            entry = next(name for name in package.namelist() if name.endswith('/main.py'))
            original = package.read(entry)
            expected_path = PLUGIN_ROOT + '/' + entry
        files = _zip_files(path, 'animation-changer', '1.3.2')
        self.assertEqual(files[expected_path]['data'], original.replace(ORIGINAL, REPLACEMENT, 1))
        self.assertNotIn(ORIGINAL, files[expected_path]['data'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_slot_switch_manifest_cannot_turn_separate_operation_into_generic_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, root = base / 'payload', base / 'root'
            (source / 'components').mkdir(parents=True)
            (source / 'integration').mkdir()
            root.mkdir()
            (source / 'components/options.json').write_text(json.dumps({'schema': 1,
                'repairs': [{'id': 'slot-switch', 'dependencies': []}], 'plugins': []}))
            (source / 'integration/manifest.json').write_text(json.dumps({'slot-switch': {
                'files': [{'source': 'unexpected.bin', 'target': 'etc/unsafe-copy'}]}}))
            (source / 'integration/unexpected.bin').write_bytes(b'unsafe')
            probe = {'os': dict(VERSION), 'kernel': KERNEL, 'uid': 1000, 'gid': 1000,
                     'dmi': {'sys_vendor': 'ONE-NETBOOK', 'product_name': 'ONEXPLAYER 3'}}
            result = build_plan(source, root, ['slot-switch'], probe)
            component = result['components']['slot-switch']
            self.assertEqual(component['status'], 'blocked')
            self.assertTrue(component['separate_operation'])
            self.assertIn('separate recovery operation', component['reason'])
            self.assertEqual(result['files'], {})
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
