"""Isolated tests for retryable gyro binding cleanup before live restore."""
import base64
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import types
import unittest
from unittest.mock import patch


COMPONENTS = Path(__file__).resolve().parent
ROOT = COMPONENTS.parents[1]
HELPER = ROOT / 'steamos-maintenance/oxp3_maintenance/gyro_binding.py'
GYRO = COMPONENTS / 'gyro'
STATE_PATH = '/home/.oxp3-installer/integration/A/gyro/state.json'
REQUIRED = (
    'var/lib/oxp3-gyro-v1/binding.py',
    'var/lib/oxp3-gyro-v1/load.sh',
    'var/lib/oxp3-gyro-v1/unload.sh',
    'etc/systemd/system/oxp3-gyro.service',
)


def _load_runtime():
    if str(COMPONENTS) not in sys.path:
        sys.path.insert(0, str(COMPONENTS))
    missing_fcntl = 'fcntl' not in sys.modules
    if missing_fcntl:
        try:
            __import__('fcntl')
        except ImportError:
            fake = types.ModuleType('fcntl')
            fake.LOCK_EX = 2
            fake.LOCK_NB = 4
            fake.flock = lambda *args: None
            sys.modules['fcntl'] = fake
        else:
            missing_fcntl = False
    spec = importlib.util.spec_from_file_location(
        'isolated_gyro_integration_runtime', COMPONENTS / 'integration_runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(runtime)
    finally:
        if missing_fcntl:
            sys.modules.pop('fcntl', None)
    return runtime


class TrustedPath:
    """A tiny POSIX path fixture with controllable root-owned directory stats."""

    def __init__(self, value, directory_overrides=None):
        self.value = PurePosixPath(str(value))
        self.directory_overrides = directory_overrides or {}

    def __truediv__(self, value):
        return TrustedPath(self.value / str(value), self.directory_overrides)

    def __str__(self):
        return self.value.as_posix()

    @property
    def parents(self):
        return tuple(TrustedPath(path, self.directory_overrides) for path in self.value.parents)

    def lstat(self):
        override = self.directory_overrides.get(str(self), {})
        mode = stat.S_IFDIR | override.get('mode', 0o755)
        return types.SimpleNamespace(st_mode=mode, st_uid=override.get('uid', 0))


class GyroRestoreRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = _load_runtime()
        cls.integration = sys.modules['integration']

    def exact_files(self):
        helper = HELPER.read_bytes()
        load = (GYRO / 'load.sh').read_bytes()
        unload = (GYRO / 'unload.sh').read_bytes()
        unit = (GYRO / 'oxp3-gyro.service').read_bytes()
        # prepare-integration.py adds this first-boot guard when it emits a unit.
        guard = (b'ExecCondition=/usr/bin/python3 -I -B '
                 b'/usr/local/lib/oxp3-integration/integration_runtime.py guard\n')
        unit = unit.replace(b'[Service]\n', b'[Service]\n' + guard, 1)
        return dict(zip(REQUIRED, (helper, load, unload, unit)))

    def generated_journal(self, files):
        """Serialize the same relative-path repair record as LogicalFiles.save."""
        root = PurePosixPath('/')
        logical = self.integration.LogicalFiles.__new__(self.integration.LogicalFiles)
        logical.root = root
        logical.state = root / 'fake/state.json'
        logical.files = {
            relative: {'user': False, 'mode': 0o755 if relative.endswith('.sh') else 0o644}
            for relative in files
        }
        absolute = {str(root / relative): base64.b64encode(data).decode()
                    for relative, data in files.items()}
        value = {
            'phase': 'installed',
            'allowed': list(absolute),
            'original': {path: {'exists': False} for path in absolute},
            'applied': absolute,
            'accepted': {},
        }
        captured = {}

        def capture(_path, data, *_args):
            captured['data'] = data

        with patch.object(self.integration, 'Path', PurePosixPath), \
             patch.object(self.integration, 'atomic_write', side_effect=capture):
            logical.save(value)
        return json.loads(captured['data'])

    @staticmethod
    def snapshot_for(journal, files, *, state_uid=0, state_mode=0o600,
                     file_overrides=None):
        encoded = base64.b64encode(json.dumps(journal).encode()).decode()
        snapshots = {STATE_PATH: {'exists': True, 'data': encoded,
                                  'uid': state_uid, 'mode': state_mode}}
        file_overrides = file_overrides or {}
        for relative, data in files.items():
            metadata = file_overrides.get(relative, {})
            snapshots['/' + relative] = {
                'exists': True, 'data': base64.b64encode(data).decode(),
                'uid': metadata.get('uid', 0), 'mode': metadata.get(
                    'mode', 0o755 if relative.endswith('.sh') else 0o644),
            }

        def read(path, *_args, **_kwargs):
            return snapshots.get(str(path), {'exists': False})
        return read

    def call_binding_cleanup(self, journal, files, *, state_uid=0, state_mode=0o600,
                             file_overrides=None, directory_overrides=None):
        reader = self.snapshot_for(journal, files, state_uid=state_uid,
                                   state_mode=state_mode, file_overrides=file_overrides)
        run = patch.object(self.runtime, 'run')
        with patch.object(self.runtime, 'Path',
                          side_effect=lambda value: TrustedPath(value, directory_overrides)), \
             patch.object(self.runtime, 'snapshot', side_effect=reader), run as command:
            self.runtime.stop_gyro_binding('A')
        return command

    def test_failed_or_inactive_gyro_unit_cleans_binding_before_restore(self):
        events = []

        def run(*args):
            events.append(('run', args))
            if args == ('steamos-readonly', 'status'):
                return 'enabled'
            # Model systemd's stop of an already failed unit as an idempotent no-op.
            return ''

        def cleanup(slot):
            events.append(('cleanup', slot))

        def restore(*args):
            events.append(('restore', args))
            return []

        with patch.object(self.runtime, 'run', side_effect=run), \
             patch.object(self.runtime.subprocess, 'run') as active, \
             patch.object(self.runtime, 'stop_gyro_binding', side_effect=cleanup), \
             patch.object(self.runtime, 'restore', side_effect=restore):
            active.return_value.returncode = 0
            self.assertEqual(self.runtime.restore_live('gyro', 'A'), [])

        cleanup_at = events.index(('cleanup', 'A'))
        restore_at = next(index for index, event in enumerate(events) if event[0] == 'restore')
        self.assertLess(events.index(('run', ('systemctl', 'stop', 'inputplumber.service'))), cleanup_at)
        self.assertLess(cleanup_at, events.index(('run', ('systemctl', 'stop', 'oxp3-gyro.service'))))
        self.assertLess(cleanup_at, restore_at)
        self.assertEqual(events[-2:], [
            ('run', ('systemctl', 'daemon-reload')),
            ('run', ('systemctl', 'start', 'inputplumber.service')),
        ])

    def test_cleanup_failure_blocks_restore_and_restarts_previously_active_inputplumber(self):
        commands = []

        def run(*args):
            commands.append(args)
            return ''

        with patch.object(self.runtime, 'run', side_effect=run), \
             patch.object(self.runtime.subprocess, 'run') as active, \
             patch.object(self.runtime, 'stop_gyro_binding', side_effect=RuntimeError('pending journal')), \
             patch.object(self.runtime, 'restore') as restore:
            active.return_value.returncode = 0
            with self.assertRaisesRegex(RuntimeError, 'pending journal'):
                self.runtime.restore_live('gyro', 'A')

        restore.assert_not_called()
        self.assertNotIn(('systemctl', 'stop', 'oxp3-gyro.service'), commands)
        self.assertEqual(commands[-2:], [
            ('systemctl', 'daemon-reload'), ('systemctl', 'start', 'inputplumber.service')])

    def test_legacy_journal_without_binding_helper_is_not_executed(self):
        files = self.exact_files()
        files.pop('var/lib/oxp3-gyro-v1/binding.py')
        journal = self.generated_journal(files)
        command = self.call_binding_cleanup(journal, files)
        command.assert_not_called()

    def test_drift_untrusted_journal_or_unknown_stop_wrapper_refuses_execution(self):
        exact = self.exact_files()

        cases = [
            ('untrusted journal owner', self.generated_journal(exact), exact,
             {'state_uid': 1000}),
            ('untrusted journal mode', self.generated_journal(exact), exact,
             {'state_mode': 0o644}),
            ('drifted helper', self.generated_journal(exact),
             {**exact, REQUIRED[0]: b'changed helper'}, {}),
            ('untrusted helper owner', self.generated_journal(exact), exact,
             {'file_overrides': {REQUIRED[0]: {'uid': 1000}}}),
            ('untrusted parent directory', self.generated_journal(exact), exact,
             {'directory_overrides': {'/var/lib': {'mode': 0o777}}}),
        ]
        unknown_stop = dict(exact, **{REQUIRED[2]: b'#!/bin/sh\necho unknown stop\n'})
        cases.append(('unknown stop wrapper', self.generated_journal(unknown_stop), unknown_stop, {}))

        for label, journal, current, options in cases:
            with self.subTest(case=label):
                values = {'state_uid': 0, 'state_mode': 0o600,
                          'file_overrides': None, 'directory_overrides': None}
                values.update(options)
                reader = self.snapshot_for(journal, current, state_uid=values['state_uid'],
                                           state_mode=values['state_mode'],
                                           file_overrides=values['file_overrides'])
                with patch.object(self.runtime, 'Path', side_effect=lambda value: TrustedPath(
                        value, values['directory_overrides'])), \
                     patch.object(self.runtime, 'snapshot', side_effect=reader), \
                     patch.object(self.runtime, 'run') as command:
                    with self.assertRaises(RuntimeError):
                        self.runtime.stop_gyro_binding('A')
                command.assert_not_called()

    def test_exact_generated_journal_and_installed_files_allow_explicit_helper_stop(self):
        files = self.exact_files()
        journal = self.generated_journal(files)
        for relative, data in files.items():
            self.assertEqual(journal['applied'][relative], base64.b64encode(data).decode())
            self.assertEqual(journal['metadata'][relative]['user'], False)

        command = self.call_binding_cleanup(journal, files)
        command.assert_called_once_with(
            '/usr/bin/python3', '-I', '-B', '/var/lib/oxp3-gyro-v1/binding.py', 'stop')


if __name__ == '__main__':
    unittest.main()
