"""Package recovery fixtures; no system package manager is invoked."""
import json
from contextlib import ExitStack, nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

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
        self.transaction_output = None
        self.transaction_error = None

    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args == ('pacman', '-Q'):
            if self.query_error:
                raise RuntimeError('package database is unavailable')
            return '\n'.join(name + ' ' + version for name, version in sorted(self.installed.items()))
        if args[:2] == ('pacman', '-Qp'):
            name, version = self.sources[args[2]]
            return name + ' ' + version
        if args[:3] == ('pacman', '-U', '--print'):
            if self.transaction_error:
                raise self.transaction_error
            if self.transaction_output is not None:
                return self.transaction_output
            return '\n'.join('\t'.join((*self.sources[path], path)) for path in args[6:])
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
        return [call for call in self.fake.calls if call[:3] in
                (('pacman', '-U', '--noconfirm'), ('pacman', '-R', '--noconfirm'))]

    def printed_transaction(self):
        return '\n'.join('\t'.join((*self.fake.sources[str(path)], str(path))) for path in self.paths)

    def test_implicit_repository_dependencies_are_refused_before_journal_or_install(self):
        for extra in ('lxc\t6.0-1\thttps://mirror/lxc.pkg.tar.zst',
                      'unrelated-user-package\t10.0-1\thttps://mirror/unrelated.pkg.tar.zst'):
            with self.subTest(extra=extra):
                self.fake.transaction_output = self.printed_transaction() + '\n' + extra
                with self.assertRaisesRegex(PackageError, 'exceeds the exact staged package set'):
                    self.store.prepare(self.paths)
                self.assertFalse(self.store.path.exists())
                self.assertEqual(self.mutating_calls(), [])
                self.assertEqual(self.fake.installed, {'unrelated-user-package': '9.0-1'})

    def test_transaction_requires_complete_unique_archive_identities(self):
        good = self.printed_transaction()
        for malformed in ('', good + '\n' + good.splitlines()[0],
                          'loading packages...', good.replace('\t1.0-1\t', '\t2.0-1\t', 1),
                          good.replace(str(self.paths[0]), 'https://mirror/same-name.pkg.tar.zst', 1),
                          good.replace('\t', ' ', 1)):
            with self.subTest(output=malformed):
                self.fake.transaction_output = malformed
                with self.assertRaises(PackageError):
                    self.store.prepare(self.paths)
                self.assertFalse(self.store.path.exists())
                self.assertEqual(self.mutating_calls(), [])

    def test_print_preflight_failure_preserves_signing_error_without_install(self):
        # Project bundle authentication does not disable pacman's independent
        # signing checks, and a print failure must remain actionable.
        self.fake.transaction_error = PackageError('required key missing; keyring is not initialized')
        with self.assertRaisesRegex(PackageError, 'required key missing'):
            self.store.prepare(self.paths)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.mutating_calls(), [])

    def test_exact_preinstalled_five_require_no_transaction_or_signature_override(self):
        self.fake.installed.update({name: '1.0-1' for name in NAMES})
        self.fake.transaction_error = AssertionError('No pending archive transaction')
        self.assertEqual(self.store.prepare(self.paths)['phase'], 'prepared')
        self.assertEqual(self.store.install()['phase'], 'installed')
        self.assertEqual(self.mutating_calls(), [])

    def test_transaction_is_rechecked_immediately_before_install(self):
        self.store.prepare(self.paths)
        self.fake.transaction_output = self.printed_transaction() + '\nlxc\t6.0-1\thttps://mirror/lxc.pkg.tar.zst'
        with self.assertRaisesRegex(PackageError, 'exceeds the exact staged package set'):
            self.store.install()
        self.assertEqual(self.read_journal()['phase'], 'prepared')
        self.assertEqual(self.mutating_calls(), [])

    def test_recovery_completion_refuses_implicit_dependencies_and_keeps_intent(self):
        self.store.prepare(self.paths)
        journal = self.read_journal()
        journal['phase'] = 'installing'
        self.store.path.write_bytes(json.dumps(journal).encode())
        self.fake.transaction_output = self.printed_transaction() + '\nlxc\t6.0-1\thttps://mirror/lxc.pkg.tar.zst'
        with self.assertRaisesRegex(PackageError, 'Unregistered package files may remain.*lxc'):
            self.store.recover()
        self.assertEqual(self.read_journal()['phase'], 'rollback_failed')
        self.assertEqual(self.read_journal()['rollback_stage'], 'complete-install')
        self.assertEqual(self.mutating_calls(), [])

    def test_install_and_completion_errors_remain_visible_and_durable(self):
        self.store.prepare(self.paths)
        original = self.fake.__call__
        failures = iter(('initial pacman signing failure: required key missing',
                         'recovery pacman signing failure: missing public key'))
        def command(*args, check=True):
            if args[:3] == ('pacman', '-U', '--noconfirm'):
                raise PackageError(next(failures))
            return original(*args, check=check)
        self.store.command = command
        with self.assertRaises(PackageError) as caught:
            self.store.install()
        message = str(caught.exception)
        self.assertIn('initial pacman signing failure', message)
        self.assertIn('recovery pacman signing failure', message)
        self.assertIn('registration verification failed', message)
        saved = self.read_journal()
        self.assertIn('initial pacman signing failure', saved['install_error'])
        self.assertIn('recovery pacman signing failure', saved['recovery_install_error'])
        self.assertIn('missing or changed', saved['recovery_verification_error'])
        self.assertEqual(saved['phase'], 'rollback_failed')

    def test_apply_dependency_refusal_precedes_managed_files_and_service_mutation(self):
        from oxp3_maintenance import cli, operations as op
        directory = self.base / 'verified'
        directory.mkdir()
        relative = ['usr/local/lib/oxp3-waydroid/packages/' + path.name for path in self.paths]
        plan = {'selected': ['waydroid'], 'components': {'waydroid': {
            'status': 'ready', 'units': ['waydroid-container.service'],
            'package_install_required': True, 'package_files': relative}},
            'files': {name: {'data': path.read_bytes()} for name, path in zip(relative, self.paths)}}
        system = {'slot': {'id': 'A'}, 'shared_os_compatible': True}
        store = mock.Mock()
        store.lock.return_value = nullcontext()
        original = self.fake.__call__
        def command(*args, check=True):
            if args[:2] == ('pacman', '-Qp') and args[2] not in self.fake.sources:
                name = Path(args[2]).read_bytes().decode().split(': ', 1)[1]
                self.fake.sources[args[2]] = (name, '1.0-1')
            output = original(*args, check=check)
            if args[:3] == ('pacman', '-U', '--print'):
                return output + '\nlxc\t6.0-1\thttps://mirror/lxc.pkg.tar.zst'
            return output
        with ExitStack() as stack:
            for name, replacement in {
                'STATE': self.base / 'apply-state', 'RUNTIME': self.base / 'not-installed',
                'require_root': mock.Mock(), 'trusted_code': mock.Mock(),
                'device_supported': mock.Mock(return_value=True),
                'store_for': mock.Mock(return_value=store),
                'authenticated': mock.Mock(return_value=nullcontext((directory, {'release': {'version': '0.2.0'}}))),
                'prepare': mock.Mock(return_value=(plan, {})), 'runtime_files': mock.Mock(return_value={}),
                'check_space': mock.Mock(), 'current_selection': mock.Mock(return_value=[]),
                '_service_history': mock.Mock(), 'command': command,
                'PackageStore': lambda state, slot, command: PackageStore(state, slot, command, enforce_owner=False),
            }.items():
                stack.enter_context(mock.patch.object(op, name, replacement))
            stack.enter_context(mock.patch.object(op.probe, 'live', return_value=system))
            stack.enter_context(mock.patch.object(cli, 'installed_release', return_value={'version': '0.1.0'}))
            live = stack.enter_context(mock.patch.object(op, 'live_write'))
            with self.assertRaisesRegex(PackageError, 'exceeds the exact staged package set.*lxc'):
                op.apply(cli.parser().parse_args(['apply', '--select', 'waydroid']))
            live.assert_not_called()
        store.apply.assert_not_called()
        self.assertEqual(self.mutating_calls(), [])
        self.assertFalse(any(call[0] in ('systemctl', 'steamos-readonly', 'depmod') for call in self.fake.calls))
        self.assertFalse((self.base / 'apply-state/packages-A.json').exists())

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
            if args[:3] == ('pacman', '-U', '--noconfirm'):
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
