"""Guard targeted Opti generation from replacing a missing/full manifest."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('prepare-integration.py')


class OptiOnlyManifestTests(unittest.TestCase):
    def run_targeted(self, output):
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--opti-only', '--output', str(output)],
            capture_output=True, text=True, check=False,
        )

    def test_missing_manifest_does_not_create_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'missing-cache'
            result = self.run_targeted(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('existing integration manifest', result.stderr)
            self.assertFalse(output.exists())

    def test_missing_manifest_in_existing_directory_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'empty-cache'
            output.mkdir()
            result = self.run_targeted(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('existing integration manifest', result.stderr)
            self.assertEqual(list(output.iterdir()), [])

    def test_incomplete_manifest_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'partial-cache'
            output.mkdir()
            manifest = output / 'manifest.json'
            manifest.write_text('{}\n', encoding='utf-8')
            result = self.run_targeted(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('complete existing integration manifest', result.stderr)
            self.assertEqual(manifest.read_text(encoding='utf-8'), '{}\n')
            self.assertEqual(sorted(path.name for path in output.iterdir()), ['manifest.json'])


if __name__ == '__main__':
    unittest.main()
