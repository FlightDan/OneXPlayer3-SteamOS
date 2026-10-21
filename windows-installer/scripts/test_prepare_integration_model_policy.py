"""A stale model-locked driver must stop preparation before any payload writes."""
from pathlib import Path
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


class ModelPolicyPreparationTests(unittest.TestCase):
    def test_old_module_is_refused_before_creating_output(self):
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            staged = workspace / 'windows-installer/scripts'
            staged.mkdir(parents=True)
            for name in ('prepare-integration.py', 'opti_payload.py', 'desktop_hdr_policy.py'):
                shutil.copyfile(scripts / name, staged / name)
            components = workspace / 'windows-installer/components'
            components.mkdir()
            shutil.copyfile(scripts.parent / 'components/opti2xmx-release.json',
                            components / 'opti2xmx-release.json')
            module = components / 'gyro/oxp3_bmi260.ko'
            module.parent.mkdir(parents=True)
            module.write_bytes(b'old-model-locked-fixture')
            output = workspace / 'candidate'
            result = subprocess.run([sys.executable, '-B', str(staged / 'prepare-integration.py'),
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('old model-locked module cannot be packaged', result.stderr)
            self.assertFalse(output.exists())

    def test_old_desktop_hdr_runtime_is_refused_before_any_output_writes(self):
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            staged = workspace / 'windows-installer/scripts'
            staged.mkdir(parents=True)
            for name in ('prepare-integration.py', 'opti_payload.py', 'desktop_hdr_policy.py'):
                shutil.copyfile(scripts / name, staged / name)
            components = workspace / 'windows-installer/components'
            components.mkdir(parents=True)
            shutil.copyfile(scripts.parent / 'components/opti2xmx-release.json',
                            components / 'opti2xmx-release.json')
            module = components / 'gyro/oxp3_bmi260.ko'
            module.parent.mkdir(parents=True)
            module.write_bytes(b'oxp3_model_policy=hardware-interface-v2\x00')
            output = workspace / 'candidate'
            archive_path = output / 'desktop-hdr/accepted-runtime.tar'
            archive_path.parent.mkdir(parents=True)
            with tarfile.open(archive_path, 'w') as archive:
                for name, data in (
                    ('bin/oxp3-mapped-hdr-control', b'OXP3_GAMMA22_POLICY_EDID_ONLY_V2 ONE-NETBOOK'),
                    ('lib/libkwin.so.6.7.3', b'OXP3_GAMMA22_POLICY_EDID_ONLY_V2 /sys/class/dmi/id/product_name'),
                ):
                    info = tarfile.TarInfo(name)
                    info.mode = 0o755 if name.startswith('bin/') else 0o644
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            archive_digest = __import__('hashlib').sha256(archive_path.read_bytes()).hexdigest()
            result = subprocess.run([sys.executable, '-B', str(staged / 'prepare-integration.py'),
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('still contains an OP3 model hard gate', result.stderr)
            self.assertEqual(__import__('hashlib').sha256(archive_path.read_bytes()).hexdigest(), archive_digest)
            self.assertEqual(sorted(path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file()),
                             ['desktop-hdr/accepted-runtime.tar'])


if __name__ == '__main__':
    unittest.main()
