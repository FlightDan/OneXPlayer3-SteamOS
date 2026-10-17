"""Runtime provisioner fixtures: no network, installed drivers, games or root work."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

from manager import Manager
from main import Plugin
import runtime_setup as setup


def fixture_archive(extra=None):
    library = b'MZ' + struct.pack('<4I', 0xfeef04bd, 0x10000, 2 << 16, (2 << 16) + 68)
    files = {name: b'fixture' for name in setup.REQUIRED}
    files.update({'sdk/libxess.dll': library, 'runtime/igc/neo/bin/ocloc-25.18.1': b'fixture',
                  'runtime/igc/igc/local/lib/libigc.so.2': b'fixture',
                  'runtime/igc/igc/local/lib/libigdfcl.so.2': b'fixture'})
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
        if extra:
            archive.addfile(extra, io.BytesIO(b'x' * extra.size) if extra.isreg() else None)
    return output.getvalue()


class Response(io.BytesIO):
    def geturl(self):
        return 'https://release-assets.githubusercontent.com/fixture'


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        def atomic(path, text):
            temporary = path.with_suffix('.tmp'); temporary.write_text(text); temporary.replace(path)
        def no_links(path):
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise RuntimeError('Symlink path')
        self.engine = types.SimpleNamespace(ordinary_user=lambda: None, no_symlink_parents=no_links,
                    owned_directory=lambda p: None, atomic_text=atomic,
                    driver_check=lambda *a: (True, 'fixture'), compiler_check=lambda *a: (True, 'fixture'))
        self.manager = Manager(self.home, self.engine)
        self.payload = fixture_archive()
        self.descriptor = dict(schema=1, version='fixture', size_bytes=len(self.payload),
            sha256=hashlib.sha256(self.payload).hexdigest(), published=True,
            url='https://github.com/FlightDan/Opti2XMX/releases/download/runtime-fixture/runtime.tar.gz')
        for target, value in [('runtime_setup.source_descriptor', lambda: self.descriptor),
                              ('runtime_setup.host_issue', lambda: ''),
                              ('runtime_setup.runtime_lock', lambda p: contextlib.nullcontext()),
                              ('runtime_setup.urllib.request.urlopen', lambda *a, **kw: Response(self.payload))]:
            item = patch(target, side_effect=value); item.start(); self.addCleanup(item.stop)
        if not hasattr(os, 'getuid'):
            item = patch('runtime_setup.os.getuid', return_value=0, create=True); item.start(); self.addCleanup(item.stop)
        if os.name != 'posix':
            item = patch.object(self.manager, '_runtime_private_directories'); item.start(); self.addCleanup(item.stop)

    def assert_clean(self, config=None):
        path = self.manager.root / 'runtime.json'
        self.assertEqual(path.read_bytes() if path.exists() else None, config)
        parent = self.manager.root / 'runtimes'
        self.assertEqual(list(parent.iterdir()) if parent.exists() else [], [])
        self.assertFalse(self.manager.progress.snapshot()['running'])

    def test_missing_runtime_and_unpublished_source_no_write_or_download(self):
        self.descriptor['published'] = False
        with patch('runtime_setup.urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
            self.assertFalse(self.manager.dependencies()[2])
            status = self.manager.runtime_status()
            self.assertFalse(status['ready']); self.assertFalse(status['available'])
            self.assertGreater(status['size_bytes'], 0)
            with self.assertRaisesRegex(RuntimeError, '尚未发布'):
                self.manager.runtime_install()
        self.assertFalse(self.manager.root.exists())

    def test_success_atomically_selects_user_runtime_no_optiscaler(self):
        status = self.manager.runtime_install()
        self.assertTrue(status['ready'])
        config = json.loads((self.manager.root / 'runtime.json').read_text())
        self.assertEqual(config['sha256'], self.descriptor['sha256'])
        self.assertEqual(config['version'], 'fixture')
        self.assertTrue(Path(config['package']).is_relative_to(self.manager.root / 'runtimes'))
        self.assertTrue(Path(config['sr']).is_file())
        self.assertFalse((self.manager.root / 'opti').exists())
        progress = self.manager.progress.snapshot()
        self.assertEqual(progress['kind'], 'runtime_install'); self.assertEqual(progress['phase'], 'completed')
        self.assertEqual(progress['downloaded_bytes'], len(self.payload))

    def test_hash_failure_preserves_config_then_retry_succeeds(self):
        self.manager.root.mkdir(parents=True)
        config = self.manager.root / 'runtime.json'; config.write_bytes(b'{"existing":"keep"}')
        self.descriptor['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'integrity'):
            self.manager.runtime_install()
        self.assert_clean(config.read_bytes())
        self.descriptor['sha256'] = hashlib.sha256(self.payload).hexdigest()
        self.assertTrue(self.manager.runtime_install()['ready'])

    def test_truncated_and_oversized_downloads(self):
        for size in (len(self.payload) - 1, len(self.payload) + 1):
            self.descriptor['size_bytes'] = size
            with self.assertRaisesRegex(RuntimeError, 'pinned size|integrity'):
                self.manager.runtime_install()
            self.assert_clean()

    def test_host_failure_and_preflight_failure_preserve_existing_config(self):
        with patch('runtime_setup.host_issue', return_value='Missing host dependency: vulkaninfo'):
            with self.assertRaisesRegex(RuntimeError, 'vulkaninfo'):
                self.manager.runtime_install()
        self.assertFalse(self.manager.root.exists())
        self.manager.root.mkdir(parents=True)
        config = self.manager.root / 'runtime.json'; config.write_bytes(b'old config')
        self.engine.compiler_check = lambda p: (False, 'ocloc dependency missing')
        with self.assertRaisesRegex(RuntimeError, 'ocloc dependency missing'):
            self.manager.runtime_install()
        self.assert_clean(b'old config')

    def test_atomic_config_failure_removes_only_new_runtime(self):
        self.manager.root.mkdir(parents=True)
        config = self.manager.root / 'runtime.json'; config.write_bytes(b'old config')
        self.engine.atomic_text = lambda *args: (_ for _ in ()).throw(OSError('Fixture pointer failure'))
        with self.assertRaisesRegex(OSError, 'pointer failure'):
            self.manager.runtime_install()
        self.assert_clean(b'old config')

    def test_external_config_change_is_not_overwritten(self):
        def changed(package):
            (self.manager.root / 'runtime.json').write_bytes(b'external change')
            return True, ''
        self.engine.compiler_check = changed
        with self.assertRaisesRegex(RuntimeError, 'changed during download'):
            self.manager.runtime_install()
        self.assert_clean(b'external change')

    @unittest.skipUnless(os.name == 'posix', 'Linux permission bits')
    def test_writable_runtime_ancestor_rejected_before_download(self):
        self.manager.root.mkdir(parents=True)
        self.manager.root.parent.chmod(0o777)
        try:
            with patch('runtime_setup.urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
                with self.assertRaisesRegex(RuntimeError, 'group or world writable'):
                    self.manager.runtime_install()
            self.assert_clean()
        finally:
            self.manager.root.parent.chmod(0o700)

    def test_archive_traversal_links_devices_and_bomb_rejected(self):
        extras = []
        for name in ('../escape', '/absolute', 'runtime/../../escape', 'runtime/evil\\path', 'sdk/C:evil'):
            info = tarfile.TarInfo(name); info.size = 1; extras.append(info)
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            info = tarfile.TarInfo('runtime/evil'); info.type = kind; info.linkname = '../escape'; extras.append(info)
        for info in extras:
            self.payload = fixture_archive(info)
            self.descriptor.update(size_bytes=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                self.manager.runtime_install()
            self.assert_clean()
        self.payload = fixture_archive()
        self.descriptor.update(size_bytes=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())
        with patch('runtime_setup.MAX_EXPANDED', 1):
            with self.assertRaisesRegex(RuntimeError, 'extraction limits'):
                self.manager.runtime_install()
        self.assert_clean()

    def test_malformed_runtime_config_is_missing_not_inventory_crash(self):
        self.manager.root.mkdir(parents=True)
        (self.manager.root / 'runtime.json').write_text('{invalid')
        self.assertFalse(self.manager.dependencies()[2])
        self.assertFalse(self.manager.runtime_status()['ready'])

    @unittest.skipUnless(os.name == 'posix', 'Linux fcntl lock')
    def test_cross_process_lock_rejects_second_installer(self):
        # Exercise the real lock function retained before setUp patches it.
        with REAL_LOCK(self.home / 'lock'):
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                with REAL_LOCK(self.home / 'lock'):
                    self.fail('second lock acquired')


REAL_LOCK = setup.runtime_lock


class RuntimeRPC(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_operation_uses_existing_mutation_guard(self):
        import asyncio
        manager = Manager('/tmp/opti-fixture', types.SimpleNamespace())
        plugin = Plugin(); started = asyncio.Event(); release = asyncio.Event()
        async def delayed(fn, *args):
            started.set(); await release.wait(); return {'ready': True}
        with patch('main.Manager', return_value=manager), patch('main.asyncio.to_thread', side_effect=delayed):
            job = asyncio.create_task(plugin.runtime_install()); await started.wait()
            self.assertFalse((await plugin.runtime_install())['ok'])
            self.assertFalse((await plugin.opti_install(42, 'game.exe', '', '0.9.4', 'github'))['ok'])
            self.assertFalse((await plugin.operation_progress())['data']['running'])
            release.set(); self.assertTrue((await job)['ok'])


class DescriptorTests(unittest.TestCase):
    def test_source_is_bundled_pinned_to_release(self):
        source = setup.source_descriptor()
        self.assertEqual(source['size_bytes'], 195558423)
        self.assertEqual(source['sha256'], 'aa384e5704286e2d765ed9770e6599ad8e46e2d15821c1f9e51682f3521aa50b')
        self.assertTrue(source['published'])
        self.assertEqual(source['url'], 'https://github.com/FlightDan/Opti2XMX/releases/download/v0.2.3/opti2xmx-xmx-runtime-20261005-' + source['sha256'][:16] + '.tar.gz')

    def test_published_descriptor_rejects_unsigned_remote_metadata_and_mirrors(self):
        source = setup.source_descriptor(); source['published'] = True
        for url in ('http://github.com/FlightDan/Opti2XMX/releases/download/v1/runtime.tar.gz',
                    'https://example.com/runtime.tar.gz', 'https://github.com/other/project/releases/download/v1/runtime.tar.gz',
                    'https://github.com/FlightDan/Opti2XMX/releases/latest/download/runtime.tar.gz'):
            with patch('runtime_setup.Path.read_text', return_value=json.dumps(dict(source, url=url))):
                with self.assertRaisesRegex(RuntimeError, 'immutable'):
                    setup.source_descriptor()
        url = 'https://github.com/FlightDan/Opti2XMX/releases/download/runtime-20261005/runtime.tar.gz'
        with patch('runtime_setup.Path.read_text', return_value=json.dumps(dict(source, url=url))):
            self.assertTrue(setup.source_descriptor()['published'])


if __name__ == '__main__':
    unittest.main()
