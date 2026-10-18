import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from oxp3_maintenance import animation_changer_compat as repair


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
        source = b'import os\n' + repair.ORIGINAL + b'\n' + repair.APPLY + b'\n' + repair.STARTUP + b'\n'
        prior = source.replace(repair.ORIGINAL, repair.CANONICAL)
        after = source.replace(repair.ORIGINAL, repair.REPLACEMENT).replace(repair.APPLY, repair.APPLY_REPLACEMENT).replace(repair.STARTUP, repair.STARTUP_REPLACEMENT)
        self.before = {'main.py': source}
        self.prior = {'main.py': prior}
        self.after = {'main.py': after}
        self.witnesses = {'plugin.json': b'{"name":"Animation Changer","author":"Justin Marentette"}',
                          'package.json': b'{"name":"decky-animation-changer","version":"1.3.2","license":"BSD-3-Clause"}',
                          'dist/index.js': b'// unchanged installed frontend\n',
                          'LICENSE': b'Copyright Justin Marentette; BSD-3-Clause fixture\n'}
        for attribute, value in [('BASE_HASHES', self.before), ('PRIOR_HASHES', self.prior), ('PATCHED_HASHES', self.after), ('WITNESSES', self.witnesses)]:
            patch = mock.patch.object(repair, attribute, {name: digest(data) for name, data in value.items()})
            patch.start()
            self.addCleanup(patch.stop)
        self.live = {repair.PREFIX + '/' + name: snapshot(data) for name, data in {**self.before, **self.witnesses}.items()}

    def read(self, path, **kwargs):
        return self.live.get(path, {'exists': False})

    def plan(self):
        with mock.patch.object(repair, '_read', side_effect=lambda root, path, **kw: self.read(path, **kw)):
            return repair.build_files(self.root)

    def test_only_backend_change_and_attribution_survives(self):
        files = self.plan()
        self.assertEqual(set(files), {repair.PREFIX + '/' + name for name in self.after})
        repair.validate_transaction(files, self.read)
        for name, expected in self.after.items():
            entry = files[repair.PREFIX + '/' + name]
            self.assertEqual(entry['data'], expected)
            self.assertEqual(entry['animation_changer_before_sha256'], digest(self.before[name]))
            self.assertFalse(entry['user'])
            self.assertFalse(entry['mutable'])
        for name, expected in self.witnesses.items():
            self.assertEqual(base64.b64decode(self.live[repair.PREFIX + '/' + name]['data']), expected)

    def test_missing_plugin_is_never_installed(self):
        self.live.clear()
        with self.assertRaisesRegex(ValueError, 'already be installed'):
            self.plan()
        self.assertFalse((self.root / repair.PREFIX).exists())

    def test_unknown_backend_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'externally changed'):
            repair.patched_bytes(self.before['main.py'] + b'# user edit')

    def test_prior_canonical_path_patch_is_upgraded(self):
        self.live[repair.PREFIX + '/main.py'] = snapshot(self.prior['main.py'])
        files = self.plan()
        repair.validate_transaction(files, self.read)
        self.assertEqual(files[repair.PREFIX + '/main.py']['data'], self.after['main.py'])

    def test_known_patched_files_are_idempotent(self):
        for name, data in self.after.items():
            self.live[repair.PREFIX + '/' + name] = snapshot(data)
        files = self.plan()
        repair.validate_transaction(files, self.read)
        self.assertEqual(repair.patched_bytes(self.after['main.py']), self.after)

    def test_identity_backend_and_license_changes_are_refused(self):
        for name in self.witnesses:
            original = self.live[repair.PREFIX + '/' + name]
            self.live[repair.PREFIX + '/' + name] = snapshot(b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'identity, frontend or original license'):
                self.plan()
            self.live[repair.PREFIX + '/' + name] = original

    def test_plan_to_apply_change_is_refused(self):
        files = self.plan()
        target = repair.PREFIX + '/main.py'
        self.live[target] = snapshot(b'new user customization')
        with self.assertRaisesRegex(ValueError, 'externally changed'):
            repair.validate_transaction(files, self.read)

    def test_after_validation_before_capture_change_is_refused(self):
        files = self.plan()
        repair.validate_transaction(files, self.read)
        target = repair.PREFIX + '/main.py'
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            repair.validate_before(target, files[target], snapshot(b'concurrent modification'))

    def test_plan_cannot_target_new_files_or_change_other_settings(self):
        files = self.plan()
        files[repair.PREFIX + '/settings.json'] = dict(next(iter(files.values())), data=b'{}')
        with self.assertRaisesRegex(ValueError, 'exactly its one'):
            repair.validate_transaction(files, self.read)

    def test_changed_plan_bytes_or_permissions_are_refused(self):
        files = self.plan()
        target = repair.PREFIX + '/main.py'
        for change in [{'data': b'bad'}, {'mode': 0o755}, {'mutable': True}, {'user': True}, {'animation_changer_before_sha256': '0' * 64}]:
            invalid = {**files, target: dict(files[target], **change)}
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'changed after planning'):
                repair.validate_transaction(invalid, self.read)

    def test_unsafe_installed_ownership_or_permissions_are_refused(self):
        target = repair.PREFIX + '/main.py'
        for metadata in [{'uid': 1000}, {'gid': 1000}, {'mode': 0o777}, {'mode': 0o4644}]:
            self.live[target] = snapshot(self.before['main.py'], **metadata)
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.plan()

    def test_unrelated_components_have_no_hook_effect(self):
        repair.validate_transaction({'etc/example': {'component': 'other'}}, lambda *a, **k: self.fail('read'))
        repair.validate_before('etc/example', {'component': 'other'}, {'exists': False})


class PinnedArchiveTests(unittest.TestCase):
    def test_real_archive_matches_supported_states_and_installer_patch(self):
        source = Path(os.environ.get('OXP3_ANIMATION_CHANGER_ARCHIVE',
                      Path(__file__).resolve().parents[2] / 'windows-installer/cache/plugins/animation-changer/animation-changer-1.3.2.zip'))
        if not source.is_file():
            self.skipTest('Optional pinned ZIP is not redistributed with maintenance')
        self.assertEqual(digest(source.read_bytes()), repair.UPSTREAM_ARCHIVE_SHA256)
        with zipfile.ZipFile(source) as archive:
            prefix = 'SDH-AnimationChanger/'
            original = archive.read(prefix + 'main.py')
            prior = original.replace(repair.ORIGINAL, repair.CANONICAL)
            self.assertEqual({'main.py': digest(original)}, repair.BASE_HASHES)
            self.assertEqual({'main.py': digest(prior)}, repair.PRIOR_HASHES)
            output = repair.patched_bytes(original)
            self.assertEqual(output, repair.patched_bytes(prior))
            self.assertEqual(output, repair.patched_bytes(output['main.py']))
            for name, expected in repair.WITNESSES.items():
                self.assertEqual(digest(archive.read(prefix + name)), expected)
            import ast
            source_path = Path(__file__).resolve().parents[2] / 'windows-installer/components/plugin_installer.py'
            function = next(node for node in ast.parse(source_path.read_text()).body
                            if isinstance(node, ast.FunctionDef) and node.name == 'patch_animation_changer')
            namespace = {'json': json}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), 'exec'), namespace)
            files = {prefix + name: {'data': archive.read(prefix + name)} for name in ('main.py', 'package.json', 'plugin.json')}
            self.assertEqual(namespace['patch_animation_changer'](files, prefix)[prefix + 'main.py']['data'], output['main.py'])

    def test_filesystem_reader_rejects_hardlinked_plugin_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / repair.PREFIX / 'main.py'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{}')
            os.link(target, root / 'alias')
            with self.assertRaisesRegex(ValueError, 'single regular file'):
                repair._read(root, repair.PREFIX + '/main.py')


if __name__ == '__main__':
    unittest.main()
