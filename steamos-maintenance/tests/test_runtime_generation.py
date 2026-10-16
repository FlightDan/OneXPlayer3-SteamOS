import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import operations as op


class RuntimeGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.app, self.runtime = self.base / 'app', self.base / 'runtime'
        self.app.mkdir()
        self.runtime.mkdir()
        self.release = {'version': '0.2.0-beta.1', 'channel': 'beta', 'display_version': 'Project beta'}
        self.plan = {'components': {}}
        self.write(self.app, 'entry.py', b'print("new engine")\n')
        self.write(self.app, 'oxp3_maintenance/cli.py', b'# current CLI\n')
        self.write(self.app, 'OXP3-Maintenance.desktop', b'[Desktop Entry]\n')

    def write(self, root, relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def files(self):
        # Fixtures cannot represent Unix ownership on Windows. Production calls
        # retain _trusted checks for all existing runtime files and directories.
        with mock.patch.object(op, 'RUNTIME', self.runtime), mock.patch.object(op.adoption, '_trusted'):
            return op.runtime_files(self.app, self.release, self.plan)

    def metadata(self, files):
        return json.loads(files['usr/local/lib/oxp3-maintenance/current-release.json']['data'])

    def install_runtime_fixture(self, files):
        marker = 'usr/local/lib/oxp3-maintenance/'
        for relative, entry in files.items():
            if relative.startswith(marker):
                self.write(self.runtime, relative[len(marker):], entry['data'])

    def test_same_content_has_deterministic_runtime_name_and_keeps_public_version(self):
        before = copy.deepcopy(self.release)
        first, second = self.files(), self.files()
        metadata = self.metadata(first)
        self.assertEqual(first, second)
        self.assertEqual(metadata['version'], self.release['version'])
        self.assertEqual(metadata['channel'], 'beta')
        self.assertRegex(metadata['maintenance_runtime'], r'^0\.2\.0-beta\.1-[a-f0-9]{64}$')
        self.assertEqual(self.release, before)
        self.install_runtime_fixture(first)
        self.assertEqual(self.files(), first)

    def test_same_project_version_changed_code_preserves_old_generation(self):
        first = self.files()
        old = self.metadata(first)['maintenance_runtime']
        self.install_runtime_fixture(first)
        self.write(self.app, 'entry.py', b'print("repackaged same version")\n')
        second = self.files()
        new = self.metadata(second)['maintenance_runtime']
        self.assertNotEqual(old, new)
        prefix = 'usr/local/lib/oxp3-maintenance/releases/'
        self.assertEqual(second[prefix + old + '/entry.py']['data'], b'print("new engine")\n')
        self.assertEqual(second[prefix + new + '/entry.py']['data'], b'print("repackaged same version")\n')
        wrapper = second['usr/local/lib/oxp3-maintenance/entry.py']['data'].decode()
        self.assertIn('/' + prefix + new + '/entry.py', wrapper)
        self.assertNotIn('/' + prefix + old + '/entry.py', wrapper)

    def test_legacy_version_directory_is_retained_without_host_absolute_path_assumptions(self):
        self.write(self.runtime, 'current-release.json', json.dumps({'version': '0.1.3'}).encode())
        self.write(self.runtime, 'releases/0.1.3/entry.py', b'legacy engine')
        files = self.files()
        self.assertEqual(files['usr/local/lib/oxp3-maintenance/releases/0.1.3/entry.py']['data'], b'legacy engine')

    def test_offline_generation_reads_only_explicit_image_runtime(self):
        self.write(self.runtime, 'current-release.json', json.dumps({'version': '0.1.3'}).encode())
        self.write(self.runtime, 'releases/0.1.3/entry.py', b'image prior engine')
        with mock.patch.object(op, 'RUNTIME', self.base / 'must-not-read-host'), mock.patch.object(op.adoption, '_trusted'):
            files = op.runtime_files(self.app, self.release, self.plan, installed_runtime=self.runtime)
        self.assertEqual(files['usr/local/lib/oxp3-maintenance/releases/0.1.3/entry.py']['data'], b'image prior engine')

    def test_actual_runtime_name_selects_previous_directory(self):
        prior = '0.1.3-' + 'a' * 64
        self.write(self.runtime, 'current-release.json', json.dumps({'version': '0.1.3', 'maintenance_runtime': prior}).encode())
        self.write(self.runtime, 'releases/' + prior + '/entry.py', b'actual prior engine')
        files = self.files()
        self.assertIn('usr/local/lib/oxp3-maintenance/releases/' + prior + '/entry.py', files)

    def test_runtime_generation_hash_includes_paths_and_file_membership(self):
        first = self.metadata(self.files())['maintenance_runtime']
        (self.app / 'oxp3_maintenance/cli.py').rename(self.app / 'oxp3_maintenance/renamed.py')
        renamed = self.metadata(self.files())['maintenance_runtime']
        self.assertNotEqual(first, renamed)
        self.write(self.app, 'extra.py', b'')
        self.assertNotEqual(renamed, self.metadata(self.files())['maintenance_runtime'])

    def test_unsafe_existing_runtime_names_and_project_versions_are_rejected(self):
        for prior in ('../outside', '/absolute', '.', '..', 'x\\escape', 'x:drive'):
            self.write(self.runtime, 'current-release.json', json.dumps({'version': '0.1.3', 'maintenance_runtime': prior}).encode())
            with self.subTest(prior=prior), self.assertRaises(RuntimeError):
                self.files()
        (self.runtime / 'current-release.json').unlink()
        for version in ('..', '.', '../escape', '/outside'):
            self.release['version'] = version
            with self.subTest(version=version), self.assertRaises(RuntimeError):
                self.files()

    def test_generation_name_never_silently_overwrites_different_existing_bytes(self):
        first = self.files()
        current = self.metadata(first)['maintenance_runtime']
        self.install_runtime_fixture(first)
        self.write(self.runtime, 'releases/' + current + '/entry.py', b'modified installed engine')
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.files()

    def test_hardlinked_application_source_is_rejected(self):
        try:
            os.link(self.app / 'entry.py', self.app / 'linked.py')
        except OSError:
            self.skipTest('hardlinks unavailable')
        with self.assertRaisesRegex(RuntimeError, 'Unsafe maintenance runtime source file'):
            self.files()


if __name__ == '__main__':
    unittest.main()
