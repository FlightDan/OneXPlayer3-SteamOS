"""Temporary cache and RPC concurrency checks; never access real games."""
import asyncio
import io
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from download_progress import OperationProgress, LIMIT
from manager import Manager
from main import Plugin


class StateChecks(unittest.TestCase):
    def test_unknown_invalid_and_underreported_lengths(self):
        progress = OperationProgress(); identity = progress.begin(42, 'opti_install')
        for total in (None, 0, -1, LIMIT+1, '12', True, 1):
            progress.update(identity, 'downloading', 2, total)
            self.assertIsNone(progress.snapshot()['total_bytes'])
        with self.assertRaises(ValueError): progress.update(identity, 'downloading', -1)
        with self.assertRaises(ValueError): progress.update(identity, 'downloading', LIMIT+1)

    def test_identity_snapshot_isolation_and_failure_release(self):
        progress = OperationProgress(); first = progress.begin(42, 'opti_install')
        with self.assertRaises(RuntimeError): progress.begin(43, 'opti_install')
        value = progress.snapshot(); value['running'] = False
        self.assertTrue(progress.snapshot()['running'])
        progress.finish(first, error='Failed https://user:token@example.com/file')
        self.assertNotIn('token', progress.snapshot()['error'])
        second = progress.begin(43, 'opti_install')
        self.assertFalse(progress.update(first, 'downloading', 100, 100))
        self.assertFalse(progress.finish(first))
        self.assertEqual(progress.snapshot()['operation_id'], second)
        progress.finish(second, phase='awaiting-launch')
        self.assertFalse(progress.snapshot()['running'])

    def test_concurrent_snapshot_consistency(self):
        progress = OperationProgress(); identity = progress.begin(42, 'opti_install')
        def writer():
            for count in range(1000): progress.update(identity, 'downloading', count, 1000)
        thread = threading.Thread(target=writer); thread.start()
        while thread.is_alive():
            value = progress.snapshot()
            self.assertEqual(value['appid'], 42)
            self.assertLessEqual(value['downloaded_bytes'], value['total_bytes'] or 1000)
        thread.join()


class CacheChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.manager = Manager(self.directory.name, types.SimpleNamespace(no_symlink_parents=lambda path: None))

    def response(self, total):
        data = b'7z\xbc\xaf\x27\x1c' + b'x' * (2*1024*1024)
        response = io.BytesIO(data); response.headers = {} if total is None else {'Content-Length': total}
        return response, data

    def unpack(self, arguments, **kwargs):
        data = b'[FrameGen]\n' if arguments[-1].endswith('.ini') else b'MZfixture'
        return types.SimpleNamespace(returncode=0, stdout=data)

    def test_chunks_known_length_extraction_and_cache_hit_without_io(self):
        response, data = self.response(str(2*1024*1024+6)); events = []
        update = self.manager.progress.update
        def observe(*args, **kwargs):
            result = update(*args, **kwargs); events.append(self.manager.progress.snapshot()); return result
        with patch.object(self.manager.progress, 'update', side_effect=observe), patch('opti.urllib.request.urlopen', return_value=response), patch('opti.subprocess.run', side_effect=self.unpack):
            payload = self.manager.opti_package('0.9.4', 'github')
        chunks = [event for event in events if event['phase']=='downloading']
        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual(chunks[-1]['downloaded_bytes'], len(data))
        self.assertEqual(chunks[-1]['total_bytes'], len(data))
        self.assertTrue(any(event['phase']=='extracting' for event in events))
        with patch('opti.urllib.request.urlopen', side_effect=AssertionError('Cache contacted network')), patch('opti.subprocess.run', side_effect=AssertionError('Cache extracted again')):
            self.assertEqual(self.manager.opti_package('0.9.4', 'github'), payload)
        self.assertEqual(self.manager.progress.snapshot()['downloaded_bytes'], len(data))

    def test_unknown_length_does_not_publish_total(self):
        response, _ = self.response(None)
        with patch('opti.urllib.request.urlopen', return_value=response), patch('opti.subprocess.run', side_effect=self.unpack):
            self.manager.opti_package('0.9.4', 'github')
        self.assertIsNone(self.manager.progress.snapshot()['total_bytes'])

    def test_network_failure_releases_running_and_keeps_cache_clean(self):
        with patch('opti.urllib.request.urlopen', side_effect=OSError('network unavailable')):
            with self.assertRaises(OSError): self.manager.opti_package('0.9.4', 'github')
        self.assertFalse(self.manager.progress.snapshot()['running'])
        self.assertEqual(self.manager.progress.snapshot()['phase'], 'failed')
        self.assertFalse(list(Path(self.directory.name).rglob('*.part')))

    def test_install_releases_pending_and_failure_is_retryable(self):
        with patch.object(self.manager, '_opti_install', return_value={'target':'fixture'}):
            self.manager.opti_install(42, 'fixture.exe', '', '0.9.4', 'github')
        self.assertEqual(self.manager.progress.snapshot()['phase'], 'awaiting-launch')
        self.assertFalse(self.manager.progress.snapshot()['running'])
        with patch.object(self.manager, '_opti_install', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError): self.manager.opti_install(42, 'fixture.exe', '', '0.9.4', 'github')
        self.assertEqual(self.manager.progress.snapshot()['phase'], 'failed')


class RpcChecks(unittest.IsolatedAsyncioTestCase):
    async def test_mutation_rejected_before_worker_progress_begins(self):
        manager = Manager('/tmp/nonexistent-opti-progress-fixture', types.SimpleNamespace())
        plugin = Plugin(); submitted = asyncio.Event(); release = asyncio.Event()
        async def delayed(function, *args):
            submitted.set(); await release.wait(); return function(*args)
        with patch('main.Manager', return_value=manager), patch('main.asyncio.to_thread', side_effect=delayed), patch.object(manager, '_opti_install', return_value={'target':'fixture'}), patch.object(manager, 'enable', side_effect=AssertionError('Queued mutation')):
            job = asyncio.create_task(plugin.opti_install(42, 'fixture.exe', '', '0.9.4', 'github'))
            await submitted.wait()
            self.assertFalse(manager.progress.snapshot()['running'])
            self.assertFalse((await plugin.enable(42, 'fixture.exe', 'native', ''))['ok'])
            self.assertFalse((await plugin.opti_install(42, 'fixture.exe', '', '0.9.4', 'github'))['ok'])
            self.assertFalse((await plugin.operation_progress())['data']['running'])
            release.set(); self.assertTrue((await job)['ok'])

    async def test_progress_bypasses_held_lock_duplicate_rejected_and_initialization_once(self):
        manager = Manager('/tmp/nonexistent-opti-progress-fixture', types.SimpleNamespace())
        started = threading.Event(); release = threading.Event()
        def install(*args):
            started.set(); release.wait(3); return {'target':'fixture'}
        plugin = Plugin()
        with patch('main.Manager', return_value=manager) as factory, patch.object(manager, '_opti_install', side_effect=install), patch.object(manager, 'enable', side_effect=AssertionError('Queued mutation')):
            job = asyncio.create_task(plugin.opti_install(42, 'fixture.exe', '', '0.9.4', 'github'))
            try:
                await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
                value = await asyncio.wait_for(plugin.operation_progress(), .2)
                self.assertTrue(value['data']['running'])
                self.assertEqual(value['data']['appid'], 42)
                self.assertFalse((await plugin.opti_install(42, 'fixture.exe', '', '0.9.4', 'github'))['ok'])
                self.assertFalse((await plugin.enable(42, 'fixture.exe', 'native', ''))['ok'])
                existing = plugin.manager; lock = plugin.lock
                await plugin._main()
                self.assertIs(plugin.manager, existing); self.assertIs(plugin.lock, lock)
                self.assertEqual(factory.call_count, 1)
            finally: release.set()
            self.assertTrue((await job)['ok'])
            self.assertFalse((await plugin.operation_progress())['data']['running'])


if __name__ == '__main__': unittest.main()
