"""Explicit legacy receipt export: real old formats, no repair or key mutation."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import adoption_export as export, auth_session, cli, operations, probe
from oxp3_maintenance.transactions import Store

SOURCE = Path(__file__).resolve().parents[1]
POSIX_ROOT = os.name == 'posix' and os.geteuid() == 0
INSTALLER_SOURCE = os.environ.get('BOILER_INSTALLER_SOURCE')


class AdoptionExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/root' if POSIX_ROOT else None)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.key = (SOURCE/'trusted-public-key.pem').read_bytes()

    def fixture(self, maintenance):
        def write(name, data, mode=0o600):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        def snapshot(data, mode=0o644):
            return {'exists': True, 'data': base64.b64encode(data).decode(), 'mode': mode, 'uid': 0, 'gid': 0}
        self.write = write
        write('usr/local/lib/oxp3-maintenance/current-release.json', json.dumps({'version': '1.0.6', 'maintenance_runtime': '1.0.6+maintenance.9'}).encode(), 0o644)
        write('usr/local/lib/oxp3-maintenance/releases/1.0.6+maintenance.9/trusted-public-key.pem', self.key, 0o644)
        write('etc/passwd', b'root:x:0:0:root:/root:/bin/sh\ndeck:x:1000:1000:deck:/home/deck:/bin/sh\n', 0o644)
        targets = {'etc/model.conf': ('input', b'old configuration\n', b'applied configuration\n'),
                   'usr/local/lib/model-runtime/data.bin': ('_maintenance', b'old runtime\n', b'applied runtime\n')}
        originals, paths = {}, {}
        for name, (component, before, after) in targets.items():
            write(name, after, 0o644)
            originals['A:'+name] = snapshot(before)
            paths[name] = {'component': component, 'snapshot': snapshot(after)}
        if maintenance:
            write('home/.oxp3-maintenance/index.json', json.dumps({'format': 1, 'originals': originals,
                  'slots': {'A': {'current': {'id': 7, 'release': {'version': '1.0.6+maintenance.9'}, 'paths': paths}}}}).encode())
        else:
            write('home/.oxp3-installer/integration/A/result.json', json.dumps({'schema': 1, 'slot': 'A',
                  'release': {'version': '1.0.6'}, 'components': {'input': {'status': 'files_installed'}}}).encode())
            for name, (component, before, after) in targets.items():
                group = 'runtime' if component == '_maintenance' else component
                write('home/.oxp3-installer/integration/A/'+group+'/state.json', json.dumps({'phase': 'installed', 'allowed': [name],
                      'original': {name: snapshot(before)}, 'applied': {name: snapshot(after)['data']}, 'metadata': {name: {}}}).encode())
        (self.root/'home/.oxp3-maintenance').mkdir(parents=True, exist_ok=True)
        (self.root/'home/.oxp3-maintenance').chmod(0o700)
        return targets

    def reader(self, root, name, **kwargs):
        path = root/name
        if path.is_symlink():
            raise RuntimeError('Test fixture link is forbidden')
        return {'exists': True, 'data': base64.b64encode(path.read_bytes()).decode(),
                'mode': 0o600 if name.endswith('.json') else 0o644, 'uid': 0, 'gid': 0}

    def reader_context(self):
        # Windows cannot exercise POSIX descriptor traversal or ownership.
        # Linux/root deliberately uses the real protected reader instead.
        return mock.patch.object(export, '_protected_snapshot', side_effect=self.reader) if not POSIX_ROOT else mock.patch.dict(os.environ, {})

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_both_actual_formats_export_originals_and_leave_legacy_bytes_unchanged(self):
        for maintenance in (True, False):
            with self.subTest(maintenance=maintenance):
                # Separate directories avoid making one format mask the other.
                with tempfile.TemporaryDirectory(dir='/root' if POSIX_ROOT else None) as fresh:
                    self.root = Path(fresh)
                    targets = self.fixture(maintenance)
                    before = self.files()
                    store = Store(self.root, self.root/'home/.oxp3-maintenance', enforce_owner=POSIX_ROOT)
                    with store.lock(), self.reader_context():
                        receipt = export._collect_export(self.root, 'A', self.key)
                    self.assertEqual({item['id'] for item in receipt['components']}, {'oxp3:input', 'oxp3:maintenance-runtime' if maintenance else 'oxp3:runtime'})
                    operations_by_path = {op['target']: op for item in receipt['components'] for op in item['operations']}
                    for name, (_, original, current) in targets.items():
                        self.assertEqual(base64.b64decode(operations_by_path[name]['before']['data']), original)
                        self.assertEqual(base64.b64decode(operations_by_path[name]['after']['data']), current)
                    self.assertFalse(receipt['migration_complete'])
                    self.assertTrue(receipt['preserve_legacy'])
                    after = self.files()
                    after.pop('home/.oxp3-maintenance/lock', None)
                    self.assertEqual(after, before)

    def test_refuses_wrong_key_live_edits_pending_and_unknown_formats(self):
        for change in ('key', 'live', 'pending', 'lifecycle', 'format'):
            with self.subTest(change=change), tempfile.TemporaryDirectory(dir='/root' if POSIX_ROOT else None) as fresh:
                self.root = Path(fresh)
                self.fixture(True)
                expected_key = b'unrelated key' if change == 'key' else self.key
                if change == 'live': self.write('etc/model.conf', b'changed by user\n', 0o644)
                if change == 'pending': self.write('home/.oxp3-maintenance/pending.json', b'{}')
                if change == 'lifecycle': self.write('home/.oxp3-maintenance/live-operation.json', b'{"slot":"A","phase":"applying"}')
                if change == 'format': self.write('home/.oxp3-maintenance/index.json', b'{"format":2}')
                before = self.files()
                with self.reader_context(), self.assertRaises(RuntimeError):
                    export._collect_export(self.root, 'A', expected_key)
                self.assertEqual(self.files(), before)

    def test_rechecks_evidence_and_live_bytes_before_publication(self):
        self.fixture(True)
        real = export._protected_snapshot if POSIX_ROOT else self.reader
        counts = {}
        def change(root, name, **kwargs):
            counts[name] = counts.get(name, 0)+1
            if name == 'etc/model.conf' and counts[name] == 2:
                self.write(name, b'concurrent edit\n', 0o644)
            return real(root, name, **kwargs)
        with mock.patch.object(export, '_protected_snapshot', side_effect=change), self.assertRaisesRegex(RuntimeError, 'changed during'):
            export._collect_export(self.root, 'A', self.key)

    def test_cli_is_explicit_and_not_exposed_to_window_session(self):
        arguments = cli.parser().parse_args(['export-adoption', '--output', '/root/adoption.json'])
        with mock.patch.object(export, 'export_live', return_value={'status': 'test'}) as action:
            self.assertEqual(cli.dispatch(arguments), {'status': 'test'})
        action.assert_called_once_with('/root/adoption.json')
        self.assertNotIn('export-adoption', auth_session.ACTIONS)
        with mock.patch.object(operations, 'require_root', side_effect=RuntimeError('root required')):
            with self.assertRaisesRegex(RuntimeError, 'root required'): export.export_live('/root/adoption.json')

    def test_live_dispatch_takes_old_lock_and_returns_only_summary(self):
        self.fixture(True)
        store = Store(self.root, self.root/'home/.oxp3-maintenance', enforce_owner=POSIX_ROOT)
        system = {'compatible': True, 'device_supported': True, 'slot': {'id': 'A'}, 'uid': 1000, 'gid': 1000}
        collect = export._collect_export
        captured = {}
        def translated(root, slot, key):
            self.assertEqual(store._depth, 1)
            self.assertEqual(root, Path('/'))
            return collect(self.root, slot, key)
        def write(path, data):
            self.assertEqual(store._depth, 1)
            captured['receipt'] = json.loads(data)
            captured['raw'] = data
        with mock.patch.object(operations, 'require_root'), mock.patch.object(operations, 'trusted_code'), \
             mock.patch.object(operations, 'store_for', return_value=store), mock.patch.object(probe, 'live', return_value=system), \
             mock.patch.object(export, '_collect_export', side_effect=translated), mock.patch.object(export, '_write_receipt', side_effect=write), self.reader_context():
            summary = cli.dispatch(cli.parser().parse_args(['export-adoption', '--output', '/root/adoption.json']))
        self.assertEqual(summary['sha256'], hashlib.sha256(captured['raw']).hexdigest())
        self.assertNotIn('data', json.dumps(summary))
        self.assertNotIn('applied configuration', json.dumps(summary))
        self.assertFalse(summary['migration_complete'])
        self.assertEqual(store._depth, 0)

    @unittest.skipUnless(INSTALLER_SOURCE, 'Set BOILER_INSTALLER_SOURCE for the separate new-runtime integration')
    def test_export_adopt_verify_restore_both_formats_without_legacy_mutation(self):
        # Explicit opt-in keeps the legacy repository independently testable.
        # The model/runtime source is never fetched or imported implicitly.
        import sys
        with mock.patch.object(sys, 'path', [str(Path(INSTALLER_SOURCE).resolve()), *sys.path]):
            from maintenance import Engine
        for maintenance in (True, False):
            with self.subTest(maintenance=maintenance), tempfile.TemporaryDirectory(dir='/root' if POSIX_ROOT else None) as fresh:
                self.root = Path(fresh)
                targets = self.fixture(maintenance)
                before = self.files()
                store = Store(self.root, self.root/'home/.oxp3-maintenance', enforce_owner=POSIX_ROOT)
                receipt_path = self.root/'receipt.json'
                with store.lock(), self.reader_context():
                    receipt = export._collect_export(self.root, 'A', self.key)
                    data = json.dumps(receipt).encode()
                    if POSIX_ROOT:
                        export._write_receipt(receipt_path, data)
                    else:
                        # Windows exercises the real Engine using a fixture
                        # receipt; POSIX tests use the protected publisher.
                        receipt_path.write_bytes(data)
                    engine = Engine(self.root)
                    result = engine.adopt(receipt_path)
                self.assertTrue(result['migration_complete'])
                for item in receipt['components']:
                    self.assertTrue(engine.verify(item['id'])['ok'])
                for name in before:
                    self.assertEqual((self.root/name).read_bytes(), before[name])
                for transaction in reversed(result['transactions']):
                    engine.restore(transaction)
                for name, (_, original, _) in targets.items():
                    self.assertEqual((self.root/name).read_bytes(), original)
                for name in before:
                    if name not in targets:
                        self.assertEqual((self.root/name).read_bytes(), before[name])

    @unittest.skipUnless(POSIX_ROOT, 'Real private ownership and descriptor checks require Linux root')
    def test_private_create_only_publication_preserves_existing_files(self):
        destination = self.root/'receipt.json'
        export._write_receipt(destination, b'private original snapshots\n')
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(destination.stat().st_nlink, 1)
        with self.assertRaises(FileExistsError): export._write_receipt(destination, b'replacement')
        self.assertEqual(destination.read_bytes(), b'private original snapshots\n')
        self.assertEqual(list(self.root.glob('.adoption-export-*')), [])
        linked = self.root/'link.json'
        linked.symlink_to(destination)
        with self.assertRaises(FileExistsError): export._write_receipt(linked, b'replacement')
        public = self.root/'public'
        public.mkdir(mode=0o755)
        with self.assertRaisesRegex(RuntimeError, 'private'): export._write_receipt(public/'receipt.json', b'secret')

    @unittest.skipUnless(POSIX_ROOT, 'Real protected source checks require Linux root')
    def test_real_export_rejects_source_links_and_public_metadata(self):
        self.fixture(True)
        index = self.root/'home/.oxp3-maintenance/index.json'
        index.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'not protected'): export._collect_export(self.root, 'A', self.key)
        index.chmod(0o600)
        target = self.root/'etc/model.conf'
        renamed = target.with_suffix('.saved')
        target.rename(renamed)
        target.symlink_to(renamed)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'): export._collect_export(self.root, 'A', self.key)


if __name__ == '__main__':
    unittest.main()
