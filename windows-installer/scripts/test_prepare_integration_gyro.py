"""Exercise the real targeted gyro payload generator against an isolated fixture."""
import importlib.util
import json
from pathlib import Path
from importlib.machinery import SourceFileLoader
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
PREPARE_SCRIPT = REPOSITORY / 'windows-installer/scripts/prepare-integration.py'
GYRO_SOURCES = REPOSITORY / 'windows-installer/components/gyro'
HELPER_SOURCE = REPOSITORY / 'steamos-maintenance/oxp3_maintenance/gyro_binding.py'


def _load_binding_test_backend():
    path = REPOSITORY / 'steamos-maintenance/tests/test_gyro_binding.py'
    spec = importlib.util.spec_from_file_location('gyro_binding_test_backend', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Backend


class PrepareIntegrationGyroTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / 'workspace'
        self.installer = self.workspace / 'windows-installer'
        self.script_dir = self.installer / 'scripts'
        self.store = self.installer / 'cache/integration'
        self.script_dir.mkdir(parents=True)
        (self.store / 'gyro').mkdir(parents=True)

        for name in ('prepare-integration.py', 'desktop_hdr_policy.py', 'opti_payload.py'):
            shutil.copyfile(REPOSITORY / 'windows-installer/scripts' / name, self.script_dir / name)
        components = self.installer / 'components'
        (components / 'gyro').mkdir(parents=True)
        (components / 'opti2xmx-release.json').write_text(json.dumps({
            'plugin_version': '0.1.4', 'plugin_sha256': '0' * 64, 'files_sha256': '0' * 64,
            'runtime': {'sha256': '0' * 64, 'size_bytes': 1,
                        'url': 'https://example.invalid/runtime.tar.gz'},
        }), encoding='utf-8')

        # Use real checked-in gyro sources; native and external build inputs stay fixture-only.
        for name in ('load.sh', 'unload.sh', 'launch.sh', 'oxp3-gyro.service', 'inputplumber.conf',
                     'oxp3_bmi260.c', 'bmi270.h', 'onexplayer3-bmi260.patch', 'Makefile'):
            shutil.copyfile(GYRO_SOURCES / name, components / 'gyro' / name)
        (components / 'gyro/oxp3_bmi260.ko').write_bytes(
            b'isolated BMI260 module fixture\0oxp3_model_policy=hardware-interface-v2\0')
        (components / 'input-profile.yaml').write_text(
            '  - group: imu\n    iio:\n      name: "{i2c-BMI0160:00,bmi260,bmi160}"\n', encoding='utf-8')
        (self.installer / 'docs').mkdir()
        shutil.copyfile(REPOSITORY / 'windows-installer/docs/GYRO_INTEGRATION.md',
                        self.installer / 'docs/GYRO_INTEGRATION.md')
        (self.installer / 'cache/gyro').mkdir(parents=True)
        (self.installer / 'cache/gyro/inputplumber').write_bytes(b'isolated InputPlumber fixture')

        # The script copies only these safe, self-contained provenance inputs.
        patch = self.workspace / 'onexplayer3-steamos-setup/gyro/inputplumber-0.78.0-oxp3-gyro.patch'
        patch.parent.mkdir(parents=True)
        patch.write_text('safe InputPlumber patch fixture\n', encoding='utf-8')
        license_file = self.workspace / 'research/input/LICENSE'
        license_file.parent.mkdir(parents=True)
        license_file.write_text('safe license fixture\n', encoding='utf-8')
        helper = self.workspace / 'steamos-maintenance/oxp3_maintenance/gyro_binding.py'
        helper.parent.mkdir(parents=True)
        shutil.copyfile(HELPER_SOURCE, helper)

        self.write_manifest()

    def write_manifest(self):
        self.store.mkdir(parents=True, exist_ok=True)
        manifest = {
            'input': {'files': [{'source': 'input/000.bin',
                                 'target': 'etc/inputplumber/devices.d/50-onexplayer_3.yaml'}],
                      'units': [], 'packages': {}, 'missing': []},
            'gyro': {'files': [{'source': 'gyro/000.bin',
                                'target': 'var/lib/oxp3-gyro-v1/old.py'}],
                     'units': [], 'packages': {}, 'missing': []},
        }
        (self.store / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (self.store / 'input').mkdir(exist_ok=True)
        (self.store / 'input/000.bin').write_bytes(b'preserve input integration bytes')
        (self.store / 'gyro/000.bin').write_bytes(b'old gyro integration bytes')

    def run_script(self, *arguments):
        return subprocess.run([sys.executable, str(self.script_dir / 'prepare-integration.py'),
                               *arguments], cwd=self.workspace, capture_output=True,
                              text=True, timeout=30)

    def snapshot_store(self):
        return {path.relative_to(self.store).as_posix(): path.read_bytes()
                for path in self.store.rglob('*') if path.is_file()}

    def emitted(self, target):
        return self.store / self.entry(target)['source']

    def entry(self, target):
        manifest = json.loads((self.store / 'manifest.json').read_text(encoding='utf-8'))
        records = [item for item in manifest['gyro']['files'] if item['target'] == target]
        self.assertEqual(len(records), 1, target)
        return records[0]

    def test_gyro_only_uses_the_shared_binding_helper_and_restores_stock_driver(self):
        before = json.loads((self.store / 'manifest.json').read_text(encoding='utf-8'))
        result = self.run_script('--gyro-only', '--output', str(self.store))
        self.assertEqual(result.returncode, 0, result.stderr)

        after = json.loads((self.store / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(after['input'], before['input'])
        self.assertEqual(after['input']['files'], before['input']['files'])
        self.assertEqual((self.store / 'input/000.bin').read_bytes(), b'preserve input integration bytes')
        self.assertEqual(self.emitted('var/lib/oxp3-gyro-v1/binding.py').read_bytes(),
                         (self.workspace / 'steamos-maintenance/oxp3_maintenance/gyro_binding.py').read_bytes())
        self.assertEqual(self.emitted('var/lib/oxp3-gyro-v1/load.sh').read_bytes(),
                         b'#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py start\n')
        self.assertEqual(self.emitted('var/lib/oxp3-gyro-v1/unload.sh').read_bytes(),
                         b'#!/bin/sh\nexec /usr/bin/python3 -I -B /var/lib/oxp3-gyro-v1/binding.py stop\n')
        self.assertEqual(self.entry('var/lib/oxp3-gyro-v1/inputplumber')['mode'], 0o755)

        unit = self.emitted('etc/systemd/system/oxp3-gyro.service').read_bytes()
        self.assertIn(b'TimeoutStartSec=40', unit)
        self.assertIn(b'TimeoutStopSec=20', unit)

        helper_path = self.emitted('var/lib/oxp3-gyro-v1/binding.py')
        loader = SourceFileLoader('prepared_gyro_binding', str(helper_path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        prepared = importlib.util.module_from_spec(spec)
        loader.exec_module(prepared)
        backend = _load_binding_test_backend()()
        manager = prepared.BindingManager(backend)
        self.assertEqual(manager.start()['driver'], prepared.CUSTOM)
        self.assertEqual(backend.current, prepared.CUSTOM)
        self.assertEqual(manager.stop()['driver'], prepared.STOCK)
        self.assertEqual(backend.current, prepared.STOCK)

    def test_missing_required_inputs_or_helper_leave_manifest_and_payload_untouched(self):
        cases = (
            ('upstream patch', self.workspace / 'onexplayer3-steamos-setup/gyro/inputplumber-0.78.0-oxp3-gyro.patch'),
            ('InputPlumber license', self.workspace / 'research/input/LICENSE'),
            ('canonical helper', self.workspace / 'steamos-maintenance/oxp3_maintenance/gyro_binding.py'),
        )
        for label, path in cases:
            with self.subTest(missing=label):
                before = self.snapshot_store()
                path.unlink()
                try:
                    result = self.run_script('--gyro-only', '--output', str(self.store))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.snapshot_store(), before)
                finally:
                    if label == 'canonical helper':
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(HELPER_SOURCE, path)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text('safe fixture restored\n', encoding='utf-8')

    def test_option_modes_are_mutually_exclusive_without_writes(self):
        before = self.snapshot_store()
        result = self.run_script('--gyro-only', '--opti-only', '--output', str(self.store))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.snapshot_store(), before)

    def test_old_model_locked_module_is_rejected_without_writes(self):
        module = self.installer / 'components/gyro/oxp3_bmi260.ko'
        module.write_bytes(b'old model-locked module fixture')
        before = self.snapshot_store()
        result = self.run_script('--gyro-only', '--output', str(self.store))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('old model-locked module cannot be packaged', result.stderr)
        self.assertEqual(self.snapshot_store(), before)


if __name__ == '__main__':
    unittest.main()
