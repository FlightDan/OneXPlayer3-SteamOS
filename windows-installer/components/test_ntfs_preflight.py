"""Tests for the early-boot NTFS generator and bounded preflight controller.

No physical block device, mount, or fstab is accessed. Controller lifecycle
tests use a private root-owned fixture and mock every device-facing command.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'partition-mount'
UUID = 'AAAA-1111-BBBB-2222'
OPTIONS = ('rw,exec,nosuid,nodev,nofail,x-systemd.automount,'
           'x-systemd.device-timeout=5s,x-systemd.mount-timeout=15s,'
           'uid=1000,gid=1000,fmask=0022,dmask=0022,windows_names')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load('oxp3_ntfs_generator_test', SOURCE / 'ntfs-generator.py')
mounts = load('oxp3_ntfs_mounts_test', SOURCE / 'mounts.py')

# preflight imports fcntl at module load. Supply a harmless import-only shim on
# Windows so its portable state() function can still be tested there.
if os.name == 'nt' and 'fcntl' not in sys.modules:
    _fcntl = types.ModuleType('fcntl')
    _fcntl.LOCK_EX = 2
    _fcntl.LOCK_NB = 4
    _fcntl.flock = lambda *args: None
    with patch.dict(sys.modules, {'fcntl': _fcntl}):
        preflight = load('oxp3_ntfs_preflight_test', SOURCE / 'preflight.py')
else:
    preflight = load('oxp3_ntfs_preflight_test', SOURCE / 'preflight.py')


def fstab_row(uuid=UUID, filesystem='ntfs3', options=OPTIONS):
    return (f'UUID={uuid} /var/mnt/oxp3-volumes/{uuid} '
            f'{filesystem} {options} 0 0\n')


def managed_block(*rows):
    return (generator.BEGIN + ''.join(rows) + generator.END).encode('utf-8')


def checker_result(status, *, returncode=0, schema=1):
    return types.SimpleNamespace(returncode=returncode,
        stdout=json.dumps({'schema': schema, 'status': status}), stderr='')


class GeneratorTests(unittest.TestCase):
    def test_existing_v1_canonical_ntfs_row_gets_preflight_dependency(self):
        raw = managed_block(fstab_row())
        self.assertEqual(generator.managed_ntfs(raw), {UUID: {'uid': 1000, 'gid': 1000}})
        unit = generator.service_unit(UUID)
        self.assertEqual(unit, r'oxp3-ntfs-preflight@AAAA\x2d1111\x2dBBBB\x2d2222.service')
        mount = generator.mount_unit(UUID)
        self.assertEqual(mount, r'var-mnt-oxp3\x2dvolumes-AAAA\x2d1111\x2dBBBB\x2d2222.mount')
        self.assertEqual(generator.dropin(UUID),
            (f'[Unit]\nRequires={unit}\nAfter={unit}\n').encode('utf-8'))

    def test_non_ntfs_managed_entry_is_not_returned_or_generated(self):
        raw = managed_block(fstab_row('EXT4-0001', 'ext4', 'rw,relatime'))
        self.assertEqual(generator.managed_ntfs(raw), {})
        with tempfile.TemporaryDirectory(prefix='oxp3-ntfs-generator-') as temporary:
            output = Path(temporary) / 'generator-output'
            output.mkdir()
            nofollow = getattr(os, 'O_NOFOLLOW', 0)
            with patch.object(generator.os, 'O_NOFOLLOW', nofollow, create=True):
                self.assertEqual(generator.generate(output, raw), {})
            self.assertEqual(list(output.iterdir()), [])

    def test_edited_rows_and_duplicate_uuids_are_rejected_before_output(self):
        canonical = fstab_row()
        corruptions = (
            managed_block(canonical.replace('fmask=0022', 'fmask=0000')),
            managed_block(canonical.replace('/var/mnt/oxp3-volumes/', '/mnt/')),
            managed_block(canonical, canonical),
            managed_block(fstab_row('../bad')),
            managed_block(canonical).replace(generator.BEGIN.encode(),
                                               b'# BEGIN OXP3 PARTITION MOUNTS edited\n'),
            (managed_block(canonical) + generator.END.encode()),
        )
        for raw in corruptions:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory(prefix='oxp3-ntfs-invalid-') as temporary:
                output = Path(temporary) / 'generator-output'
                output.mkdir()
                nofollow = getattr(os, 'O_NOFOLLOW', 0)
                with patch.object(generator.os, 'O_NOFOLLOW', nofollow, create=True):
                    with self.assertRaises(ValueError):
                        generator.generate(output, raw)
                self.assertEqual(list(output.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'Systemd generator path layout is POSIX-specific')
    def test_generate_writes_dropin_but_never_rewrites_fstab(self):
        raw = b'# preserved\n' + managed_block(fstab_row()) + b'# after\n'
        with tempfile.TemporaryDirectory(prefix='oxp3-ntfs-generator-') as temporary:
            root = Path(temporary)
            fstab = root / 'fstab'
            fstab.write_bytes(raw)
            output = root / 'generator-output'
            output.mkdir()
            result = generator.generate(output, fstab.read_bytes())
            self.assertEqual(result, {UUID: {'uid': 1000, 'gid': 1000}})
            directory = output / (generator.mount_unit(UUID) + '.d')
            self.assertEqual((directory / '50-oxp3-ntfs-preflight.conf').read_bytes(),
                             generator.dropin(UUID))
            self.assertEqual(fstab.read_bytes(), raw)


class StateTests(unittest.TestCase):
    def test_clean_and_dirty_states_are_only_read_from_native_checker(self):
        for status in ('clean', 'dirty'):
            with self.subTest(status=status), patch.object(preflight, 'run',
                    return_value=checker_result(status)) as run:
                self.assertEqual(preflight.state(Path('/fixture/ntfs_status'), Path('/dev/fake')), status)
                self.assertEqual(run.call_args.args[0], [str(Path('/fixture/ntfs_status')), str(Path('/dev/fake'))])
                self.assertEqual(run.call_count, 1)

    def test_hibernated_and_unknown_checker_results_fail_closed(self):
        bad_results = (
            checker_result('hibernated'),
            checker_result('unknown'),
            types.SimpleNamespace(returncode=1, stdout='{}', stderr='read failed'),
            types.SimpleNamespace(returncode=0, stdout='not json', stderr=''),
            types.SimpleNamespace(returncode=0,
                stdout=json.dumps({'schema': 2, 'status': 'dirty'}), stderr=''),
        )
        for result in bad_results:
            with self.subTest(result=result), patch.object(preflight, 'run',
                    return_value=result) as run:
                with self.assertRaises(RuntimeError):
                    preflight.state(Path('/fixture/ntfs_status'), Path('/dev/fake'))
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][0], str(Path('/fixture/ntfs_status')))


class MountHookTests(unittest.TestCase):
    def test_first_use_inactive_unit_is_not_reset_and_failed_unit_is_reset(self):
        unit = generator.service_unit(UUID)
        with patch.object(mounts, 'command', return_value='inactive\n') as command:
            mounts.reset_failed_unit(unit)
            self.assertEqual(command.call_count, 1)
        with patch.object(mounts, 'command', side_effect=['failed\n', '']) as command:
            mounts.reset_failed_unit(unit)
            self.assertEqual(command.call_args.args, ('/usr/bin/systemctl', 'reset-failed', unit))

    def test_generated_hook_requires_exact_single_dropin_and_content(self):
        unit = generator.mount_unit(UUID)
        dropin_path = ('/run/systemd/generator/' + unit +
                       '.d/50-oxp3-ntfs-preflight.conf')
        expected = generator.dropin(UUID)
        displayed = json.dumps(dropin_path)  # systemctl quotes/escapes path arrays.
        with patch.object(mounts, 'read_trusted', return_value=expected) as read:
            mounts.verify_generated_hook(UUID, unit, displayed)
        read.assert_called_once_with(Path(dropin_path))

        with self.subTest(case='changed content'), \
                patch.object(mounts, 'read_trusted', return_value=b'[Unit]\n'):
            with self.assertRaisesRegex(RuntimeError, 'dependency is missing or changed'):
                mounts.verify_generated_hook(UUID, unit, displayed)

        for reported in ('', displayed + ' /run/systemd/generator/extra.conf'):
            with self.subTest(reported=reported), patch.object(mounts, 'read_trusted') as read:
                with self.assertRaisesRegex(RuntimeError, 'dependency is missing or changed'):
                    mounts.verify_generated_hook(UUID, unit, reported)
                read.assert_not_called()
        with patch.object(mounts, 'read_trusted') as read:
            with self.assertRaisesRegex(RuntimeError, 'Invalid NTFS preflight dependency paths'):
                mounts.verify_generated_hook(UUID, unit, '"unterminated')
            read.assert_not_called()

        with self.subTest(case='missing file'), \
                patch.object(mounts, 'read_trusted', side_effect=FileNotFoundError(dropin_path)):
            with self.assertRaises(FileNotFoundError):
                mounts.verify_generated_hook(UUID, unit, displayed)

    def test_preflight_issue_uses_this_service_window_and_classifies_hibernation(self):
        started = '1793210000.123456'
        lines = (
            'not json',
            json.dumps({'schema': 2, 'status': 'blocked', 'error': 'hibernated from other schema'}),
            json.dumps({'schema': 1, 'status': 'blocked', 'error': 'another check failed'}),
            json.dumps({'schema': 1, 'status': 'blocked',
                        'error': 'NTFS is hibernated; resume Windows and fully shut it down'}),
        )
        fallback = {'code': 'ntfs_unclean', 'details': 'kernel reported dirty volume'}
        with patch.object(mounts, 'command', return_value='\n'.join(lines)) as command:
            result = mounts.preflight_issue(UUID, started, fallback)
        self.assertEqual(result, {'code': 'ntfs_hibernated',
            'details': 'NTFS is hibernated; resume Windows and fully shut it down'})
        self.assertEqual(command.call_args.args, ('/usr/bin/journalctl',
            '--unit=' + mounts.preflight_unit(UUID), '--since=@' + started,
            '--no-pager', '--output=cat', '--lines=30'))

    def test_preflight_issue_preserves_kernel_fallback_without_service_json(self):
        fallback = {'code': 'ntfs_inconsistent', 'details': '$MFTMirr mismatch'}
        with patch.object(mounts, 'command', return_value='ordinary journal text\n{}'):
            self.assertEqual(mounts.preflight_issue(UUID, '100.5', fallback), fallback)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'Requires an isolated root Linux fixture')
class ControllerTests(unittest.TestCase):
    """Use genuine path/hash/fstab validation while mocking block-device IO."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='oxp3-ntfs-preflight-', dir='/root')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home' / '.oxp3-partition-mount'
        self.tools = self.home / 'tools'
        self.tools.mkdir(parents=True)
        self.fstab = self.root / 'etc' / 'fstab'
        self.fstab.parent.mkdir()
        self.fstab.write_bytes(managed_block(fstab_row()))
        self.fstab.chmod(0o644)
        self.generator_path = self.root / 'etc' / 'systemd' / 'system-generators' / 'oxp3-ntfs-preflight'
        self.generator_path.parent.mkdir(parents=True)
        self.generator_path.write_bytes((SOURCE / 'ntfs-generator.py').read_bytes())
        self.generator_path.chmod(0o644)
        (self.home / 'preflight.py').write_text('# isolated controller fixture\n', encoding='utf-8')
        self.checker = self.tools / 'ntfs_status'
        self.repair = self.tools / 'ntfsfix'
        self.checker.write_bytes(b'checker fixture')
        self.repair.write_bytes(b'repair fixture')
        for path in (self.checker, self.repair):
            path.chmod(0o755)
        manifest = {'schema': 1, 'architecture': 'x86_64', 'static': True, 'files': {}}
        for name, path in (('ntfs_status', self.checker), ('ntfsfix', self.repair)):
            data = path.read_bytes()
            manifest['files'][name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        manifest_path = self.tools / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        manifest_path.chmod(0o644)
        self.locks = self.root / 'run' / 'lock'
        self.locks.mkdir(parents=True)
        for name, value in (('HOME', self.home), ('GENERATOR', self.generator_path),
                            ('FSTAB', self.fstab), ('LOCKS', self.locks)):
            manager = patch.object(preflight, name, value)
            manager.start()
            self.addCleanup(manager.stop)
        self.device = Path('/dev/fixture-ntfs')
        self.number = os.makedev(8, 4)

    def execute(self, statuses, *, repair_returncodes=None):
        """Run preflight with deterministic checker and ntfsfix subprocess results."""
        statuses = iter(statuses)
        repair_returncodes = iter(repair_returncodes or ())
        calls = []

        def run(args, timeout=15):
            args = list(args)
            calls.append(args)
            if args[0] == str(self.checker):
                return checker_result(next(statuses))
            if args[0] == str(self.repair):
                code = next(repair_returncodes, 0)
                return types.SimpleNamespace(returncode=code, stdout='', stderr='repair failed' if code else '')
            self.fail('Unexpected preflight subprocess: ' + repr(args))

        return calls, patch.object(preflight, 'run', side_effect=run)

    def test_clean_volume_does_not_run_ntfsfix(self):
        calls, runner = self.execute(['clean'])
        with runner, patch.object(preflight, 'identity', return_value=(self.device, self.number)) as identity, \
                patch.object(preflight, 'unmounted') as unmounted:
            result = preflight.preflight(UUID)
        self.assertEqual(result, {'schema': 1, 'uuid': UUID, 'status': 'clean', 'repaired': False})
        self.assertEqual(calls, [[str(self.checker), str(self.device)]])
        identity.assert_called_once_with(UUID)
        unmounted.assert_called_once_with(self.number)

    def test_dirty_volume_clears_once_then_read_verifies_and_observes_clean(self):
        calls, runner = self.execute(['dirty', 'clean'])
        with runner, patch.object(preflight, 'identity', return_value=(self.device, self.number)) as identity, \
                patch.object(preflight, 'unmounted') as unmounted:
            result = preflight.preflight(UUID)
        clear = [str(self.repair), '--clear-dirty', str(self.device)]
        no_action = [str(self.repair), '--no-action', str(self.device)]
        self.assertEqual(calls, [[str(self.checker), str(self.device)], clear, no_action,
                                 [str(self.checker), str(self.device)]])
        self.assertEqual(calls.count(clear), 1)
        self.assertEqual(result, {'schema': 1, 'uuid': UUID, 'status': 'clean', 'repaired': True})
        self.assertEqual(identity.call_count, 3)
        self.assertGreaterEqual(unmounted.call_count, 3)

    def test_hibernated_and_unknown_states_never_write(self):
        cases = (['hibernated'], ['unknown'])
        for statuses in cases:
            with self.subTest(statuses=statuses):
                calls, runner = self.execute(statuses)
                with runner, patch.object(preflight, 'identity', return_value=(self.device, self.number)), \
                        patch.object(preflight, 'unmounted'):
                    with self.assertRaises(RuntimeError):
                        preflight.preflight(UUID)
                self.assertFalse(any(args[0] == str(self.repair) for args in calls))

    def test_already_mounted_volume_never_checks_or_repairs(self):
        calls, runner = self.execute(['dirty'])
        with runner, patch.object(preflight, 'identity', return_value=(self.device, self.number)), \
                patch.object(preflight, 'unmounted', side_effect=RuntimeError('already mounted')):
            with self.assertRaisesRegex(RuntimeError, 'already mounted'):
                preflight.preflight(UUID)
        self.assertEqual(calls, [])

    def test_dependency_and_initial_identity_failures_never_write(self):
        calls, runner = self.execute(['dirty'])
        with runner, patch.object(preflight, 'runtime', side_effect=RuntimeError('missing tool')) as runtime, \
                patch.object(preflight, 'identity') as identity:
            with self.assertRaisesRegex(RuntimeError, 'missing tool'):
                preflight.preflight(UUID)
        runtime.assert_called_once_with()
        identity.assert_not_called()
        self.assertEqual(calls, [])

        calls, runner = self.execute(['dirty'])
        with runner, patch.object(preflight, 'identity', side_effect=RuntimeError('identity changed')), \
                patch.object(preflight, 'unmounted'):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                preflight.preflight(UUID)
        self.assertEqual(calls, [])

    def test_changed_identity_on_prewrite_recheck_never_repairs(self):
        calls, runner = self.execute(['dirty'])
        identities = [(self.device, self.number), (self.device, self.number + 1)]
        with runner, patch.object(preflight, 'identity', side_effect=identities), \
                patch.object(preflight, 'unmounted'):
            with self.assertRaisesRegex(RuntimeError, 'block device changed'):
                preflight.preflight(UUID)
        self.assertEqual(calls, [[str(self.checker), str(self.device)]])
        self.assertFalse(any(args[0] == str(self.repair) for args in calls))

    def test_unselected_uuid_never_loads_tools_or_writes(self):
        other = 'CCCC-3333-DDDD-4444'
        calls, runner = self.execute(['dirty'])
        with runner, patch.object(preflight, 'runtime') as runtime, patch.object(preflight, 'identity') as identity:
            with self.assertRaisesRegex(RuntimeError, 'not selected'):
                preflight.preflight(other)
        runtime.assert_not_called()
        identity.assert_not_called()
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
