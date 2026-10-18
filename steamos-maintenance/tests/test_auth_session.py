"""Window authorization protocol and privileged execution boundary."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from oxp3_maintenance import auth_session as auth, cli, operations


def request(action, params=None, sequence=1):
    return dict(protocol=1, sequence=sequence, action=action, params=params or {})


def wire(values):
    return b''.join(json.dumps(value).encode() + b'\n' for value in values)


class ProtocolTests(unittest.TestCase):
    def test_command_is_fixed_and_selects_explicit_components(self):
        params = {'bundle': '/home/deck/Downloads/package.tar.gz', 'selected': ['input'],
                  'expected_version': '1.0.7', 'expected_manifest': 'a' * 64}
        action, checked = auth.validate_request(request('apply', params), 1)
        command = auth.command(action, checked)
        self.assertEqual(command[:6], ['/usr/bin/python3', '-I', '-B', str(auth.ENTRY), 'apply', '--json'])
        self.assertIn('--selected-only', command)
        self.assertEqual(command[command.index('--select') + 1], 'input')

    def test_rejects_actions_parameters_types_paths_and_unreviewed_apply(self):
        cases = [request('bootstrap'), request('download'), request('session-service'), request('gui'),
                 request('status', {'command': 'sh'}), request('restore'), request('status', {'selected': []}),
                 request('plan', {'bundle': '/valid', 'selected': ['--help']}),
                 request('plan', {'bundle': '/valid', 'selected': ['input', 'input']}),
                 request('plan', {'bundle': '/valid', 'tool_only': 1}),
                 request('plan', {'bundle': '../evil'}), request('plan', {'bundle': '/a/../evil'}),
                 request('plan', {'bundle': '/valid', 'bundle_dir': '/valid'}),
                 request('apply', {'bundle': '/valid'}), request('status', sequence=True)]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                auth.validate_request(value, 1)
        with self.assertRaises(ValueError):
            auth.validate_request(request('status', sequence=2), 1)

    def test_message_limits_duplicate_keys_partial_messages_and_numbers(self):
        for raw in (b'{"x":1,"x":2}\n', b'{}', b'{"x":NaN}\n', b'x' * 11 + b'\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                auth._line(io.BytesIO(raw), 10)
        self.assertIsNone(auth._line(io.BytesIO(), 10))

    def test_eof_exits_and_only_fixed_backend_is_invoked(self):
        output = io.BytesIO()
        with mock.patch.object(auth, 'run_backend', return_value={'status': 'ok'}) as run:
            auth._serve(io.BytesIO(wire([request('status')])), output)
        run.assert_called_once_with('status', {})
        values = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(values[0], {'protocol': 1, 'status': 'authorized'})
        self.assertEqual(values[1]['sequence'], 1)

    def test_apply_uses_exact_single_consumption_review(self):
        params = {'bundle': '/signed.tar.gz', 'selected': ['input']}
        applied = dict(params, expected_version='1.0.7', expected_manifest='a' * 64)
        values = [request('plan', params), request('apply', applied, 2), request('apply', applied, 3)]
        planned = {'can_apply': True, 'release': {'version': '1.0.7'}, 'manifest_digest': 'a' * 64}
        output = io.BytesIO()
        with mock.patch.object(auth, 'run_backend', side_effect=[planned, {'status': 'done'}]) as run:
            auth._serve(io.BytesIO(wire(values)), output)
        self.assertEqual(run.call_count, 2)
        self.assertIn('Review the changes again', json.loads(output.getvalue().splitlines()[-1])['error'])

    def test_changed_review_cannot_invoke_apply(self):
        plan = {'bundle': '/signed', 'selected': ['input']}
        apply = dict(plan, selected=['gyro'], expected_version='1.0.7', expected_manifest='a' * 64)
        result = {'can_apply': True, 'release': {'version': '1.0.7'}, 'manifest_digest': 'a' * 64}
        with mock.patch.object(auth, 'run_backend', return_value=result) as run:
            auth._serve(io.BytesIO(wire([request('plan', plan), request('apply', apply, 2)])), io.BytesIO())
        self.assertEqual(run.call_count, 1)

    def test_invalid_sequence_stops_without_dispatching(self):
        with mock.patch.object(auth, 'run_backend') as run, self.assertRaises(ValueError):
            auth._serve(io.BytesIO(wire([request('status', sequence=2)])), io.BytesIO())
        run.assert_not_called()

    def test_cli_service_rejects_all_extra_arguments(self):
        with mock.patch.object(auth, 'serve', return_value=None) as serve:
            self.assertIsNone(cli.dispatch(cli.parser().parse_args(['session-service'])))
            serve.assert_called_once()
            for extra in (['--json'], ['--bundle', '/tmp/x'], ['--select', 'input']):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    cli.dispatch(cli.parser().parse_args(['session-service', *extra]))


class ClientTests(unittest.TestCase):
    def process(self, responses):
        return SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(wire(responses)),
                               poll=lambda: None, wait=lambda: 0)

    def test_authorize_once_and_reuse_pipe_for_all_actions(self):
        process = self.process([{'protocol': 1, 'status': 'authorized'},
                                {'protocol': 1, 'sequence': 1, 'result': {'status': 'one'}},
                                {'protocol': 1, 'sequence': 2, 'result': {'status': 'two'}}])
        client = auth.Client()
        with mock.patch.object(auth, 'supported', return_value=True), \
             mock.patch.object(subprocess, 'Popen', return_value=process) as popen:
            client.authorize()
            self.assertEqual(client.request('status', {})['status'], 'one')
            self.assertEqual(client.request('logs', {})['status'], 'two')
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.args[0], ['/usr/bin/pkexec', '/usr/bin/python3', '-I', '-B', str(auth.ENTRY), 'session-service'])
        client.close()
        self.assertTrue(process.stdin.closed)
        with self.assertRaises(RuntimeError):
            client.authorize()

    def test_cancelled_authorization_can_retry_without_replaying_actions(self):
        failed, ready = self.process([]), self.process([{'protocol': 1, 'status': 'authorized'}])
        client = auth.Client()
        with mock.patch.object(auth, 'supported', return_value=True), \
             mock.patch.object(subprocess, 'Popen', side_effect=[failed, ready]) as popen:
            with self.assertRaisesRegex(RuntimeError, 'Authentication cancelled'):
                client.authorize()
            client.authorize()
        self.assertEqual(popen.call_count, 2)
        client.close()

    def test_close_never_waits_for_request_lock_or_kills_process(self):
        client = auth.Client()
        process = self.process([])
        process.terminate, process.kill = mock.Mock(), mock.Mock()
        client.process = process
        with client.lock:
            client.close()
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_invalid_request_does_not_start_authorization(self):
        with mock.patch.object(subprocess, 'Popen') as popen, self.assertRaises(ValueError):
            auth.Client().request('shell', {})
        popen.assert_not_called()

    def test_missing_old_helper_never_executes_download_directory(self):
        with mock.patch.object(auth, 'supported', return_value=False), \
             mock.patch.object(subprocess, 'Popen') as popen, self.assertRaises(auth.SessionUnavailable):
            auth.Client().authorize()
        popen.assert_not_called()


class BackendTests(unittest.TestCase):
    def test_dual_output_is_drained_bounded_and_writes_finish_even_on_overflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'finished'
            script = ('import sys; from pathlib import Path; '
                      'sys.stdout.buffer.write(b"x" * 200000); '
                      'sys.stderr.buffer.write(b"y" * 200000); '
                      'Path(sys.argv[1]).write_text("finished")')
            with mock.patch.object(auth, 'trusted_entry'), mock.patch.object(auth, 'MAX_RESPONSE', 1024), \
                 mock.patch.object(auth, 'command', return_value=[sys.executable, '-c', script, str(marker)]), \
                 self.assertRaisesRegex(RuntimeError, 'output exceeded'):
                auth.run_backend('apply', {})
            self.assertEqual(marker.read_text(), 'finished')


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'real root-owned POSIX fixture')
class InstalledTrustTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        # Fixtures live in the OS temporary parent; emulate the protected
        # /usr hierarchy for that ancestor without changing real permissions.
        original_lstat = Path.lstat
        ancestor = self.base.parent
        def protected_parent(path):
            info = original_lstat(path)
            if path == ancestor:
                fields = list(info)
                fields[0] &= ~0o022
                return os.stat_result(fields)
            return info
        metadata = mock.patch.object(Path, 'lstat', protected_parent)
        metadata.start()
        self.addCleanup(metadata.stop)
        self.entry = self.base / 'entry.py'
        patch = mock.patch.object(auth, 'ENTRY', self.entry)
        patch.start()
        self.addCleanup(patch.stop)
        self.generation = self.base / 'releases/1.0.7-generation'
        package = self.generation / 'oxp3_maintenance'
        package.mkdir(parents=True)
        for path in (self.generation / 'entry.py', package / '__init__.py', package / 'auth_session.py'):
            path.write_text('# protected\n')
            path.chmod(0o644)
        self.entry.write_text('#!/usr/bin/python3\nimport runpy\nrunpy.run_path('
                              + repr(str(self.generation / 'entry.py')) + ', run_name="__main__")\n')
        self.entry.chmod(0o755)

    def test_generation_wrapper_is_authority_even_if_release_metadata_is_mid_transaction(self):
        (self.base / 'current-release.json').write_text('{"maintenance_runtime":"new-not-written"}')
        self.assertEqual(auth._trusted_runtime(), self.generation)
        self.assertTrue(auth.supported())

    def test_actual_runtime_files_generation_is_accepted(self):
        app = self.base / 'source-app'
        package = app / 'oxp3_maintenance'
        package.mkdir(parents=True)
        for name in ('entry.py', 'OXP3-Maintenance.desktop', 'oxp3_maintenance/__init__.py',
                     'oxp3_maintenance/auth_session.py'):
            (app / name).write_text('# signed application\n')
        files = operations.runtime_files(app, {'version': '1.0.7'}, {'components': {}},
                                         installed_runtime=self.base / 'not-installed')
        root = self.base / 'fresh'
        prefix = 'usr/local/lib/oxp3-maintenance/'
        entry = root / prefix / 'entry.py'
        for relative, record in files.items():
            if not relative.startswith(prefix):
                continue
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = record['data']
            if relative == prefix + 'entry.py':
                data = data.replace(b'/usr/local/lib/oxp3-maintenance', str(entry.parent).encode())
            path.write_bytes(data)
            path.chmod(record['mode'])
        with mock.patch.object(auth, 'ENTRY', entry):
            self.assertTrue(auth.supported())
            runtime = auth._trusted_runtime()
        self.assertEqual(runtime.parent, entry.parent / 'releases')
        self.assertTrue(runtime.name.startswith('1.0.7-'))

    def test_arbitrary_wrapper_and_unprotected_import_surfaces_are_rejected(self):
        for path in (self.generation / 'json.py', self.generation / 'oxp3_maintenance/injected.py'):
            path.write_text('# writable\n')
            path.chmod(0o666)
            with self.assertRaises(auth.SessionUnavailable):
                auth.trusted_entry()
            path.unlink()
        self.entry.write_text('import runpy\nrunpy.run_path("/tmp/evil.py")\n')
        with self.assertRaises(auth.SessionUnavailable):
            auth.trusted_entry()

    def test_service_rejects_named_files_and_noninstalled_module(self):
        with mock.patch.object(auth, '__file__', str(self.generation / 'oxp3_maintenance/auth_session.py')):
            with (self.base / 'input').open('w+b') as incoming, (self.base / 'output').open('w+b') as outgoing:
                with self.assertRaisesRegex(RuntimeError, 'anonymous pipes'):
                    auth.serve(incoming, outgoing)


if __name__ == '__main__':
    unittest.main()
