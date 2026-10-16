"""Exercise release boundaries: no payload leaks, stale runtime, or unpinned publication."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_maintenance', Path(__file__).with_name('prepare-maintenance.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class MaintenancePreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.output = self.root / 'staged'
        for name in ('entry.py', 'OXP3-Maintenance.desktop', 'oxp3_maintenance/touch_ui.py',
                     'oxp3_maintenance/operations.py', 'cache/large-driver.bin', 'tests/test_secret.py',
                     'publisher-private.key', 'oxp3_maintenance/__pycache__/old.pyc'):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# fixture\n')

    def test_only_application_code_enters_image_payload(self):
        report = prepare.prepare(self.source, self.output)
        self.assertEqual(set(report['files']), {'entry.py', 'OXP3-Maintenance.desktop',
                                               'oxp3_maintenance/touch_ui.py', 'oxp3_maintenance/operations.py'})
        self.assertFalse(report['publisher_key'])
        prepare.prepare(self.source, self.output, check=True)
        with self.assertRaisesRegex(ValueError, 'fresh directory'):
            prepare.prepare(self.source, self.output)

    def test_publication_refuses_missing_or_invalid_trust_anchor(self):
        with self.assertRaisesRegex(ValueError, 'Public releases require'):
            prepare.prepare(self.source, self.output, require_key=True)
        (self.source / 'trusted-public-key.pem').write_bytes(b'not a key')
        with self.assertRaisesRegex(ValueError, 'Ed25519'):
            prepare.prepare(self.source, self.output, require_key=True)
        self.assertFalse(self.output.exists())

    def test_changed_code_or_extra_staged_files_require_repreparation(self):
        prepare.prepare(self.source, self.output)
        (self.output / 'app/entry.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            prepare.prepare(self.source, self.output, check=True)
        (self.output / 'app/entry.py').write_bytes(b'# fixture\n')
        (self.output / 'app/extra.bin').write_bytes(b'unexpected')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            prepare.prepare(self.source, self.output, check=True)


if __name__ == '__main__':
    unittest.main()
