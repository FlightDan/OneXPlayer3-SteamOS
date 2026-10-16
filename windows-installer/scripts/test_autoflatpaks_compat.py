"""Rebuild pinned AutoFlatpaks and test its real bundle without Steam or a device."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parent
INSTALLER = SCRIPT_DIR.parent
spec = importlib.util.spec_from_file_location('patch_autoflatpaks', SCRIPT_DIR / 'patch-autoflatpaks.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SOURCE = Path(os.environ.get('OXP3_AUTOFLATPAKS_ARCHIVE',
                            INSTALLER / 'cache/plugins/autoflatpaks/autoflatpaks-1.6.8.zip'))


class AutoFlatpaksPatchTests(unittest.TestCase):
    def test_unexpected_polling_block_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'polling block'):
            builder.patch_text('window.SystemPowerStore.batteryState;')

    def test_unrecognized_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'changed.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(builder.PREFIX + 'package.json',
                                 '{"name":"decky-autoflatpaks","version":"1.6.9"}')
            with self.assertRaisesRegex(RuntimeError, 'version'):
                builder.build(path, Path(directory) / 'patched.zip')

    @unittest.skipUnless(SOURCE.is_file(), 'pinned upstream archive is not cached')
    def test_pinned_archive_preserves_unmodified_files_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = [Path(directory) / name for name in ['first.zip', 'second.zip']]
            builder.build(SOURCE, first)
            builder.build(SOURCE, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(SOURCE) as upstream, zipfile.ZipFile(first) as patched:
                for name in upstream.namelist():
                    if name in [builder.PREFIX + 'dist/index.js', builder.PREFIX + 'package.json']:
                        continue
                    self.assertEqual(upstream.read(name), patched.read(name), name)
                metadata = json.loads(patched.read(builder.PREFIX + 'package.json'))
                self.assertEqual(metadata['version'], builder.VERSION)
                bundle = patched.read(builder.PREFIX + 'dist/index.js').decode()
                self.assertEqual(bundle.count(builder.MARKER), 1)
                self.assertEqual(bundle, builder.patch_text(upstream.read(builder.PREFIX + 'dist/index.js').decode()))
                self.assertIn('BSD-3-Clause', metadata['license'])
                self.assertIn(builder.PREFIX + 'oxp3-compat/dist-index.js.patch', patched.namelist())

    @unittest.skipUnless(SOURCE.is_file(), 'pinned upstream archive is not cached')
    def test_actual_bundle(self):
        node = os.environ.get('NODE') or shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for the actual bundle fixture')
        with tempfile.TemporaryDirectory() as directory:
            archive = builder.build(SOURCE, Path(directory) / 'patched.zip')
            with zipfile.ZipFile(archive) as patched:
                bundle = Path(directory) / 'index.js'
                bundle.write_bytes(patched.read(builder.PREFIX + 'dist/index.js'))
            subprocess.run([node, str(SCRIPT_DIR / 'test-autoflatpaks-compat.mjs'), str(bundle)],
                           check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
