import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from oxp3_maintenance import autoflatpaks_compat as repair


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(data, **metadata):
    return dict({'exists': True, 'data': base64.b64encode(data).decode(),
                 'mode': 0o644, 'uid': 0, 'gid': 0}, **metadata)


class SurgicalRepairTests(unittest.TestCase):
    """Small independent installed-plugin fixtures; no bundled third-party code."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        package = {'name': 'decky-autoflatpaks', 'version': '1.6.8',
                   'author': 'jurassicplayer', 'license': 'BSD-3-Clause', 'unrelated': [1, 2]}
        old_package = (json.dumps(package, indent=2) + '\n').encode()
        package.update(version='1.6.8+oxp3.1', oxp3_compatibility_patch='Defer battery polling until Steam power state is available')
        new_package = (json.dumps(package, indent=2) + '\n').encode()
        self.before = {'package.json': old_package, 'dist/index.js': b'prefix\n' + repair.ORIGINAL + b'\nsuffix\n'}
        self.after = {'package.json': new_package, 'dist/index.js': b'prefix\n' + repair.REPLACEMENT + b'\nsuffix\n'}
        self.witnesses = {'plugin.json': b'{"name":"AutoFlatpaks","author":"jurassicplayer"}',
                          'main.py': b'# unchanged installed backend\n',
                          'LICENSE': b'Copyright Jurassicplayer; BSD-3-Clause fixture\n'}
        for attribute, value in [('BASE_HASHES', self.before), ('PATCHED_HASHES', self.after), ('WITNESSES', self.witnesses)]:
            patch = mock.patch.object(repair, attribute, {name: digest(data) for name, data in value.items()})
            patch.start()
            self.addCleanup(patch.stop)
        self.live = {repair.PREFIX + '/' + name: snapshot(data) for name, data in {**self.before, **self.witnesses}.items()}

    def read(self, path, **kwargs):
        return self.live.get(path, {'exists': False})

    def plan(self):
        with mock.patch.object(repair, '_read', side_effect=lambda root, path, **kw: self.read(path, **kw)):
            return repair.build_files(self.root)

    def test_only_two_installed_files_change_and_attribution_survives(self):
        files = self.plan()
        self.assertEqual(set(files), {repair.PREFIX + '/' + name for name in self.after})
        repair.validate_transaction(files, self.read)
        for name, expected in self.after.items():
            entry = files[repair.PREFIX + '/' + name]
            self.assertEqual(entry['data'], expected)
            self.assertEqual(entry['autoflatpaks_before_sha256'], digest(self.before[name]))
            self.assertFalse(entry['user'])
            self.assertFalse(entry['mutable'])
        metadata = json.loads(files[repair.PREFIX + '/package.json']['data'])
        self.assertEqual(metadata['author'], 'jurassicplayer')
        self.assertEqual(metadata['license'], 'BSD-3-Clause')
        self.assertEqual(metadata['unrelated'], [1, 2])
        for name, expected in self.witnesses.items():
            self.assertEqual(base64.b64decode(self.live[repair.PREFIX + '/' + name]['data']), expected)

    def test_missing_plugin_is_never_installed(self):
        self.live.clear()
        with self.assertRaisesRegex(ValueError, 'already be installed'):
            self.plan()
        self.assertFalse((self.root / repair.PREFIX).exists())

    def test_unknown_frontend_and_mixed_version_are_refused(self):
        for package, frontend in [(self.before['package.json'], self.before['dist/index.js'] + b'// user edit'),
                                  (self.after['package.json'], self.before['dist/index.js'])]:
            with self.subTest(package=package[:20], frontend=frontend[-10:]):
                with self.assertRaisesRegex(ValueError, 'externally changed'):
                    repair.patched_bytes(package, frontend)

    def test_known_patched_files_are_idempotent(self):
        for name, data in self.after.items():
            self.live[repair.PREFIX + '/' + name] = snapshot(data)
        files = self.plan()
        repair.validate_transaction(files, self.read)
        self.assertEqual(repair.patched_bytes(self.after['package.json'], self.after['dist/index.js']), self.after)

    def test_identity_backend_and_license_changes_are_refused(self):
        for name in self.witnesses:
            original = self.live[repair.PREFIX + '/' + name]
            self.live[repair.PREFIX + '/' + name] = snapshot(b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'identity, backend or original license'):
                self.plan()
            self.live[repair.PREFIX + '/' + name] = original

    def test_plan_to_apply_change_is_refused(self):
        files = self.plan()
        target = repair.PREFIX + '/dist/index.js'
        self.live[target] = snapshot(b'new user customization')
        with self.assertRaisesRegex(ValueError, 'externally changed'):
            repair.validate_transaction(files, self.read)

    def test_after_validation_before_capture_change_is_refused(self):
        files = self.plan()
        repair.validate_transaction(files, self.read)
        target = repair.PREFIX + '/dist/index.js'
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            repair.validate_before(target, files[target], snapshot(b'concurrent modification'))

    def test_plan_cannot_target_new_files_or_change_other_settings(self):
        files = self.plan()
        files[repair.PREFIX + '/settings.json'] = dict(next(iter(files.values())), data=b'{}')
        with self.assertRaisesRegex(ValueError, 'exactly its two'):
            repair.validate_transaction(files, self.read)

    def test_changed_plan_bytes_or_permissions_are_refused(self):
        files = self.plan()
        target = repair.PREFIX + '/dist/index.js'
        for change in [{'data': b'bad'}, {'mode': 0o755}, {'mutable': True}, {'user': True}, {'autoflatpaks_before_sha256': '0' * 64}]:
            invalid = {**files, target: dict(files[target], **change)}
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'changed after planning'):
                repair.validate_transaction(invalid, self.read)

    def test_unsafe_installed_ownership_or_permissions_are_refused(self):
        target = repair.PREFIX + '/package.json'
        for metadata in [{'uid': 1000}, {'gid': 1000}, {'mode': 0o777}, {'mode': 0o4644}]:
            self.live[target] = snapshot(self.before['package.json'], **metadata)
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.plan()

    def test_unrelated_components_have_no_hook_effect(self):
        repair.validate_transaction({'etc/example': {'component': 'other'}}, lambda *a, **k: self.fail('read'))
        repair.validate_before('etc/example', {'component': 'other'}, {'exists': False})


class PinnedArchiveTests(unittest.TestCase):
    def test_real_archives_reproduce_reviewed_frontend_and_metadata(self):
        directory = Path(__file__).resolve().parents[2] / 'windows-installer/cache/plugins/autoflatpaks'
        source = directory / 'autoflatpaks-1.6.8.zip'
        patched = directory / 'autoflatpaks-1.6.8+oxp3.1.zip'
        if not source.is_file() or not patched.is_file():
            self.skipTest('Optional locally cached pinned upstream archives are not redistributed with maintenance')
        self.assertEqual(digest(source.read_bytes()), repair.UPSTREAM_ARCHIVE_SHA256)
        self.assertEqual(digest(patched.read_bytes()), repair.PATCHED_ARCHIVE_SHA256)
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(patched) as new:
            prefix = 'decky-autoflatpaks/'
            output = repair.patched_bytes(old.read(prefix + 'package.json'), old.read(prefix + 'dist/index.js'))
            for name, data in output.items():
                self.assertEqual(data, new.read(prefix + name))
            for name, expected in repair.WITNESSES.items():
                self.assertEqual(digest(old.read(prefix + name)), expected)
                self.assertEqual(old.read(prefix + name), new.read(prefix + name))

    def test_filesystem_reader_rejects_hardlinked_plugin_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / repair.PREFIX / 'package.json'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{}')
            os.link(target, root / 'alias')
            with self.assertRaisesRegex(ValueError, 'single regular file'):
                repair._read(root, repair.PREFIX + '/package.json')


if __name__ == '__main__':
    unittest.main()
