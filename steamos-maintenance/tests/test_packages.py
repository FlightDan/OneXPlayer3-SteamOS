"""Package recovery fixtures; no system package manager is invoked."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oxp3_maintenance.packages import PackageStore, PackageError, NAMES


class Pacman:
    def __init__(self):
        self.installed = {'unrelated-user-package': '9.0-1'}
        self.sources = {}
        self.calls = []
        self.fail_install = None
        self.fail_remove = False
        self.fail_depmod = False
        self.before_install = None
        self.query_error = False

    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args == ('pacman', '-Q'):
            if self.query_error:
                raise RuntimeError('package database is unavailable')
            return '\n'.join(name + ' ' + version for name, version in sorted(self.installed.items()))
        if args[:2] == ('pacman', '-Qp'):
            name, version = self.sources[args[2]]
            return name + ' ' + version
        if args[:3] == ('pacman', '-U', '--noconfirm'):
            if self.before_install:
                self.before_install()
            for index, path in enumerate(args[3:]):
                name, version = self.sources[path]
                self.installed[name] = version
                if self.fail_install and index == 1:
                    failure = self.fail_install
                    self.fail_install = None
                    raise failure
            return ''
        if args[:3] == ('pacman', '-R', '--noconfirm'):
            if self.fail_remove:
                raise RuntimeError('a user package still depends on Waydroid')
            for name in args[3:]:
                self.installed.pop(name)
            return ''
        if args == ('depmod', '-a'):
            if self.fail_depmod:
                self.fail_depmod = False
                raise RuntimeError('depmod failed')
            return ''
        raise AssertionError('Unexpected command: ' + repr(args))


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.fake = Pacman()
        self.paths = []
        for name in sorted(NAMES):
            path = self.base / (name + '-1.0-1.pkg.tar.zst')
            path.write_bytes(('signed fixture: ' + name).encode())
            self.paths.append(path)
            self.fake.sources[str(path)] = (name, '1.0-1')
        self.store = PackageStore(self.base / 'state', 'A', self.fake, enforce_owner=False)

    def read_journal(self):
        return json.loads(self.store.path.read_bytes())

    def mutating_calls(self):
        return [call for call in self.fake.calls if call[:2] in (('pacman', '-U'), ('pacman', '-R'))]

    def test_prepare_records_original_ownership_and_durable_install_intent(self):
        self.fake.installed['libgbinder'] = '1.0-1'
        prepared = self.store.prepare(self.paths)
        self.assertEqual(prepared['phase'], 'prepared')
        self.assertEqual(self.mutating_calls(), [])
        originals = {x['name']: x['original_installed'] for x in prepared['packages']}
        self.assertTrue(originals['libgbinder'])
        self.assertFalse(originals['waydroid'])
        self.fake.before_install = lambda: self.assertEqual(self.read_journal()['phase'], 'installing')
        installed = self.store.install()
        self.assertEqual(installed['phase'], 'installed')
        install = self.mutating_calls()[0]
        self.assertEqual(len(install[3:]), 4)  # Do not reinstall the user's exact package.
        self.assertEqual(self.fake.installed['unrelated-user-package'], '9.0-1')

    def test_preexisting_different_version_refuses_upgrade_without_journal(self):
        self.fake.installed['waydroid'] = 'older-1'
        with self.assertRaisesRegex(PackageError, 'upgrades are refused'):
            self.store.prepare(self.paths)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.mutating_calls(), [])
        self.assertEqual(self.fake.installed['waydroid'], 'older-1')

    def test_exact_five_known_names_and_regular_files_are_required(self):
        with self.assertRaisesRegex(PackageError, 'Exactly five'):
            self.store.prepare(self.paths[:-1])
        self.fake.sources[str(self.paths[0])] = ('glibc', '1.0-1')
        with self.assertRaisesRegex(PackageError, 'Unexpected Waydroid'):
            self.store.prepare(self.paths)
        self.assertEqual(self.mutating_calls(), [])

    def test_duplicate_package_identity_is_rejected(self):
        self.fake.sources[str(self.paths[0])] = self.fake.sources[str(self.paths[1])]
        with self.assertRaisesRegex(PackageError, 'exact five'):
            self.store.prepare(self.paths)
        self.assertFalse(self.store.path.exists())

    def test_package_database_error_is_never_treated_as_absence(self):
        self.fake.query_error = True
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.store.prepare(self.paths)
        self.assertEqual(self.mutating_calls(), [])
        self.assertFalse(self.store.path.exists())

    def test_source_bytes_changed_after_prepare_refuse_install(self):
        self.store.prepare(self.paths)
        self.paths[0].write_bytes(b'replaced after verification')
        with self.assertRaisesRegex(PackageError, 'Staged package changed'):
            self.store.install()
        self.assertEqual(self.mutating_calls(), [])

    def test_host_package_changed_after_prepare_refuse_install(self):
        self.store.prepare(self.paths)
        self.fake.installed['waydroid'] = '1.0-1'
        with self.assertRaisesRegex(PackageError, 'changed after preparation'):
            self.store.install()
        self.assertEqual(self.mutating_calls(), [])
        # Preparation has no install intent, so rollback preserves that external install.
        self.store.rollback()
        self.assertEqual(self.fake.installed['waydroid'], '1.0-1')

    def test_partial_pacman_failure_rolls_back_only_new_packages(self):
        self.fake.installed['libgbinder'] = '1.0-1'
        original = dict(self.fake.installed)
        self.store.prepare(self.paths)
        self.fake.fail_install = RuntimeError('pacman process failed midway')
        with self.assertRaisesRegex(PackageError, 'were rolled back'):
            self.store.install()
        self.assertEqual(self.fake.installed, original)
        self.assertEqual(self.read_journal()['phase'], 'restored')
        self.assertNotIn('libgbinder', self.mutating_calls()[-1][3:])

    def test_crash_after_partial_install_is_recovered_from_persisted_intent(self):
        self.store.prepare(self.paths)
        self.fake.fail_install = KeyboardInterrupt('simulated process death')
        with self.assertRaises(KeyboardInterrupt):
            self.store.install()
        self.assertEqual(self.read_journal()['phase'], 'installing')
        fresh = PackageStore(self.base / 'state', 'A', self.fake, enforce_owner=False)
        self.assertEqual(fresh.recover()['phase'], 'restored')
        self.assertEqual(self.fake.installed, {'unrelated-user-package': '9.0-1'})

    def test_unregistered_partial_package_files_require_exact_completion(self):
        self.store.prepare(self.paths)
        journal = self.read_journal()
        journal['phase'] = 'installing'
        self.store.path.write_bytes(json.dumps(journal).encode())
        # Simulate a killed pacman that unpacked a file but did not register
        # its package. A database-only rollback must not claim clean success.
        partial = self.base / 'unregistered-package-file'
        partial.write_bytes(b'partially unpacked file')
        original = self.fake.__call__
        def command(*args, check=True):
            if args[:2] == ('pacman', '-U'):
                raise RuntimeError('partial unregistered file causes filesystem conflict')
            return original(*args, check=check)
        self.store.command = command
        with self.assertRaisesRegex(PackageError, 'Unregistered package files may remain'):
            self.store.recover()
        self.assertEqual(self.read_journal()['phase'], 'rollback_failed')
        self.assertEqual(self.read_journal()['rollback_stage'], 'complete-install')
        self.assertTrue(partial.exists())
        self.assertFalse(any(call[:2] == ('pacman', '-R') for call in self.fake.calls))

    def test_unavailable_recovery_archive_never_claims_clean_rollback(self):
        self.store.prepare(self.paths)
        journal = self.read_journal()
        journal['phase'] = 'installing'
        self.store.path.write_bytes(json.dumps(journal).encode())
        self.paths[0].unlink()
        with self.assertRaisesRegex(PackageError, 'Unregistered package files may remain'):
            self.store.recover()
        self.assertEqual(self.read_journal()['phase'], 'rollback_failed')

    def test_depmod_failure_also_rolls_back_added_packages(self):
        self.store.prepare(self.paths)
        self.fake.fail_depmod = True
        with self.assertRaisesRegex(PackageError, 'were rolled back'):
            self.store.install()
        self.assertEqual(self.fake.installed, {'unrelated-user-package': '9.0-1'})

    def test_repeat_install_verifies_journal_and_preserves_first_original(self):
        self.store.prepare(self.paths)
        self.store.install()
        changes = len(self.mutating_calls())
        repeated = self.store.prepare(self.paths)
        self.assertTrue(all(not x['original_installed'] for x in repeated['packages']))
        self.store.install()
        self.assertEqual(len(self.mutating_calls()), changes)
        self.fake.installed.pop('waydroid')
        with self.assertRaisesRegex(PackageError, 'missing or changed'):
            self.store.recover()

    def test_changed_package_blocks_restore_without_removing_any_package(self):
        self.store.prepare(self.paths)
        self.store.install()
        self.fake.installed['waydroid'] = '2.0-1'
        before = dict(self.fake.installed)
        with self.assertRaisesRegex(PackageError, 'preserving'):
            self.store.restore()
        self.assertEqual(self.fake.installed, before)
        self.assertEqual(self.read_journal()['phase'], 'rollback_conflict')
        self.assertFalse(any(call[:2] == ('pacman', '-R') for call in self.fake.calls))
        self.fake.installed['waydroid'] = '1.0-1'
        self.assertEqual(self.store.recover()['phase'], 'restored')

    def test_restore_preserves_preexisting_packages_and_android_data(self):
        self.fake.installed['libgbinder'] = '1.0-1'
        android = self.base / 'android-data'
        android.mkdir()
        (android / 'keep').write_bytes(b'user applications and data')
        self.store.prepare(self.paths)
        self.store.install()
        self.assertEqual(self.store.restore()['phase'], 'restored')
        self.assertEqual(self.fake.installed, {'unrelated-user-package': '9.0-1', 'libgbinder': '1.0-1'})
        self.assertEqual((android / 'keep').read_bytes(), b'user applications and data')
        self.assertEqual(self.store.restore()['phase'], 'restored')

    def test_package_removal_failure_is_durable_and_retryable(self):
        self.store.prepare(self.paths)
        self.store.install()
        self.fake.fail_remove = True
        with self.assertRaisesRegex(PackageError, 'rollback is incomplete'):
            self.store.restore()
        self.assertEqual(self.read_journal()['phase'], 'rollback_failed')
        self.fake.fail_remove = False
        self.assertEqual(self.store.recover()['phase'], 'restored')

    def test_new_package_generation_requires_restore_first(self):
        self.store.prepare(self.paths)
        self.store.install()
        for path in self.paths:
            name, _ = self.fake.sources[str(path)]
            self.fake.sources[str(path)] = (name, '2.0-1')
        with self.assertRaisesRegex(PackageError, 'upgrades are refused'):
            self.store.prepare(self.paths)
        self.assertEqual(self.read_journal()['phase'], 'installed')

    def test_corrupt_or_wrong_slot_journal_is_refused(self):
        self.store.prepare(self.paths)
        value = self.read_journal()
        value['slot'] = 'B'
        self.store.path.write_bytes(json.dumps(value).encode())
        with self.assertRaisesRegex(PackageError, 'schema or slot'):
            self.store.recover()
        self.assertEqual(self.mutating_calls(), [])

    def test_actual_partuuid_slot_is_a_safe_journal_key(self):
        slot = 'partuuid-12345678-abcd-1234-abcd-1234567890ab'
        store = PackageStore(self.base / 'other-state', slot, self.fake, enforce_owner=False)
        self.assertEqual(store.prepare(self.paths)['slot'], slot)
        self.assertEqual(store.install()['phase'], 'installed')
        self.assertEqual(store.restore()['phase'], 'restored')
        self.assertEqual(store.path.name, 'packages-' + slot + '.json')
        for bad in ('../A', '', 'a/b', 'a\\b', '.', '..', 'x' * 81):
            with self.assertRaises(PackageError):
                PackageStore(self.base / 'state', bad, self.fake, enforce_owner=False)

    def test_linked_journal_and_source_are_refused(self):
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.base / 'linked-state').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks unavailable for the test account')
        linked = PackageStore(self.base / 'linked-state', 'A', self.fake, enforce_owner=False)
        with self.assertRaisesRegex(PackageError, 'Unsafe package journal ancestor'):
            linked.prepare(self.paths)
        original = self.paths[0]
        link = self.base / 'linked-source.pkg.tar.zst'
        link.symlink_to(original)
        with self.assertRaisesRegex(PackageError, 'regular staged package'):
            self.store.prepare([link] + self.paths[1:])


if __name__ == '__main__':
    unittest.main()
