import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import stat
import shutil
import subprocess
from types import SimpleNamespace
import unittest
import zipfile
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

builder = module('model_builder', ROOT/'scripts/build.py')
adapter = module('model_adapter', ROOT/'adapter.py')

class ModelPackageTests(unittest.TestCase):
    def fixture(self, base):
            base.mkdir()
            (base/'payload').mkdir()
            (base/'payload/data').write_bytes(b'configuration\n')
            entry = {'path': 'payload/data', 'sha256': hashlib.sha256(b'configuration\n').hexdigest(), 'size': 14}
            manifest = {'schema_version': 1, 'kind': 'DevicePackage', 'id': 'device:fixture', 'version': '0.1.0',
                        'source': {'kind': 'local', 'path': 'fixture'}, 'compatibility': {},
                        'trust': {'status': 'unsigned-development'}, 'components': [], 'files': [entry]}
            (base/'manifest.json').write_text(json.dumps(manifest))
            return manifest

    def test_archive_whitelist_has_no_generic_installer_or_research(self):
            lock = json.loads((ROOT/'upstream-lock.json').read_text())
            for name in ('research/dynamic-policy.py', '.release-private/key.pem', 'app/SteamOSInstaller.exe',
                         'runtime/qemu.exe', 'guest/build.sh', 'AGENTS.md', 'device-records.txt'):
                self.assertIsNone(builder.selected_path(name, lock))
            self.assertEqual(builder.selected_path('cache/integration/manifest.json', lock), 'payload/legacy/integration/manifest.json')

    def test_bad_public_asset_rejected_before_output(self):
            with tempfile.TemporaryDirectory() as work:
                source = Path(work)/'input.zip'
                source.write_bytes(b'not the locked public package')
                with self.assertRaises(ValueError):
                    builder.build(source, Path(work)/'out', {})
                self.assertFalse((Path(work)/'out').exists())

    def test_public_archive_uses_authenticated_handle_if_path_is_replaced(self):
            with tempfile.TemporaryDirectory() as work:
                source, replacement = Path(work)/'input.zip', Path(work)/'replacement.zip'
                for path, data in ((source, b'locked public bytes'), (replacement, b'untrusted replacement')):
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr('payload.txt', data)
                expected = {'size':source.stat().st_size, 'sha256':builder.digest(source)}
                original_digest = builder.stream_digest
                calls = []
                def checked_then_replace(stream):
                    value = original_digest(stream)
                    if not calls:
                        try:
                            os.replace(replacement, source)
                        except PermissionError:
                            # Windows's held share-read handle denies replacement.
                            pass
                    calls.append(value)
                    return value
                with mock.patch.object(builder, 'stream_digest', side_effect=checked_then_replace):
                    with builder.public_input(source, expected) as stream, zipfile.ZipFile(stream) as archive:
                        self.assertEqual(archive.read('payload.txt'), b'locked public bytes')
                self.assertEqual(calls, [expected['sha256'], expected['sha256']])

    def test_public_archive_snapshots_input_or_denies_concurrent_writes(self):
            with tempfile.TemporaryDirectory() as work:
                source = Path(work)/'input.zip'
                source.write_bytes(b'locked bytes')
                expected = {'size':source.stat().st_size, 'sha256':builder.digest(source)}
                if os.name == 'nt':
                    with builder.public_input(source, expected):
                        with self.assertRaises(PermissionError):
                            source.write_bytes(b'edited bytes')
                else:
                    with builder.public_input(source, expected) as authenticated:
                        source.write_bytes(b'edited bytes')
                        self.assertEqual(authenticated.read(), b'locked bytes')
                        source.write_bytes(b'locked bytes')

    def test_release_source_binds_exact_public_commit_and_rejects_dirty_or_unlisted_files(self):
            with tempfile.TemporaryDirectory() as work:
                repository = Path(work)/'public'
                model = repository/'boiler-device'
                model.mkdir(parents=True)
                for name in builder.SOURCE_FILES:
                    destination = model/name
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(ROOT/name,destination)
                def git(*args):
                    return subprocess.check_output(['git','-C',str(repository),*args],stderr=subprocess.PIPE).decode().strip()
                git('init','-q')
                git('config','core.autocrlf','false')
                git('config','user.name','Model source fixture')
                git('config','user.email','model-fixture@example.invalid')
                git('remote','add','origin','https://github.com/FlightDan/OneXPlayer3-SteamOS.git')
                git('add','boiler-device')
                git('commit','-qm','Disposable public model fixture')
                commit = git('rev-parse','HEAD')
                frozen = builder.committed_model(model,commit)
                self.assertEqual(set(frozen),set(builder.SOURCE_FILES))
                self.assertEqual(frozen['adapter.py'],(ROOT/'adapter.py').read_bytes())
                with self.assertRaisesRegex(ValueError,'HEAD'):
                    builder.committed_model(model,'f'*40)
                (model/'adapter.py').write_bytes(b'dirty uncommitted source')
                with self.assertRaisesRegex(ValueError,'clean'):
                    builder.committed_model(model,commit)
                (model/'adapter.py').write_bytes(frozen['adapter.py'])
                (model/'unreviewed.txt').write_text('not approved for export')
                git('add','boiler-device/unreviewed.txt')
                git('commit','-qm','Disposable unlisted fixture')
                with self.assertRaisesRegex(ValueError,'whitelist'):
                    builder.committed_model(model,git('rev-parse','HEAD'))

    def test_explicit_namespaced_choices_and_policy_acknowledgement(self):
            catalog = {'languages': ['en-US'], 'kde_languages': ['system'], 'repairs': [{'id': 'input', 'dependencies': []}], 'plugins': []}
            choice = {'schema_version': 1, 'slot': 'guest', 'repairs': ['oxp3:input'], 'plugins': [],
                      'installer_language': 'en-US', 'kde_language': 'system', 'acknowledge_legacy_update_hold': True}
            self.assertEqual(adapter.selection(choice, catalog)['repairs'], ['input'])
            for patch in ({'repairs': ['input']}, {'acknowledge_legacy_update_hold': False}, {'repairs': ['oxp3:unknown']}, {'schema_version': True}):
                with self.assertRaises(ValueError):
                    adapter.selection(dict(choice, **patch), catalog)

    def adoption_fixture(self, root, *, maintenance=True):
            def write(name, data):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            def snapshot(data, mode=0o644):
                import base64
                return {'exists': True, 'data': base64.b64encode(data).decode(), 'mode': mode, 'uid': 0, 'gid': 0}
            write('usr/local/lib/oxp3-maintenance/current-release.json', json.dumps({'version': '1.0.6', 'maintenance_runtime': '1.0.6-test'}).encode())
            write('usr/local/lib/oxp3-maintenance/releases/1.0.6-test/trusted-public-key.pem', b'pinned public key')
            write('etc/passwd', b'root:x:0:0:root:/root:/bin/sh\ndeck:x:1000:1000:deck:/home/deck:/bin/sh\n')
            write('etc/model.conf', b'installed\n')
            before, after = snapshot(b'original\n'), snapshot(b'installed\n')
            if maintenance:
                write('home/.oxp3-maintenance/index.json', json.dumps({'format': 1, 'originals': {'A:etc/model.conf': before},
                      'slots': {'A': {'current': {'id': 3, 'release': {'version': '1.0.6'}, 'paths': {'etc/model.conf': {'component': 'input', 'snapshot': after}}}}}}).encode())
            else:
                write('home/.oxp3-installer/integration/A/result.json', json.dumps({'schema': 1, 'slot': 'A', 'release': {'version': '1.0.6'},
                      'components': {'input': {'status': 'files_installed'}}}).encode())
                write('home/.oxp3-installer/integration/A/input/state.json', json.dumps({'phase': 'installed', 'allowed': ['etc/model.conf'],
                      'original': {'etc/model.conf': before}, 'applied': {'etc/model.conf': after['data']}, 'metadata': {'etc/model.conf': {}}}).encode())
            def reader(name, **kwargs):
                return snapshot((root/name).read_bytes(), 0o600 if name.endswith(('index.json', 'state.json', 'result.json')) else 0o644)
            return reader

    def test_adoption_translates_originals_without_mutating_legacy(self):
            for maintenance in (True, False):
                with self.subTest(maintenance=maintenance), tempfile.TemporaryDirectory() as work:
                    root = Path(work)
                    reader = self.adoption_fixture(root, maintenance=maintenance)
                    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}
                    value = adapter.collect_adoption(root, 'A', b'pinned public key', reader=reader)
                    self.assertTrue(value['translation_complete'])
                    self.assertEqual(value['components'][0]['id'], 'oxp3:input')
                    op = value['components'][0]['operations'][0]
                    self.assertEqual(op['before']['sha256'], hashlib.sha256(b'original\n').hexdigest())
                    self.assertEqual(op['after']['sha256'], hashlib.sha256(b'installed\n').hexdigest())
                    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}
                    self.assertEqual(before, after)

    def test_adoption_refuses_key_replacement_edits_and_pending_state(self):
            for alteration in ('key', 'edited', 'pending'):
                with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as work:
                    root = Path(work)
                    reader = self.adoption_fixture(root)
                    expected_key = b'wrong key' if alteration == 'key' else b'pinned public key'
                    if alteration == 'edited':
                        (root/'etc/model.conf').write_bytes(b'user edit')
                    if alteration == 'pending':
                        (root/'home/.oxp3-maintenance/pending.json').write_text('{}')
                    with self.assertRaises(RuntimeError):
                        adapter.collect_adoption(root, 'A', expected_key, reader=reader)

    def test_host_cannot_run_target_modifications(self):
            with self.assertRaises(RuntimeError):
                adapter.target_root()

    def test_adapter_shared_parent_is_created_privately_before_model_state(self):
            root = Path('/fixture')
            parent, child = root/'home/.boiler', root/'home/.boiler/oxp3-adapter'
            create = mock.Mock()
            with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR|0o700, st_uid=0)):
                self.assertEqual(adapter.ensure_adapter_state(root, create), child)
            self.assertEqual(create.call_args_list, [mock.call(parent,0o700), mock.call(child,0o700)])
            for mode, uid in ((stat.S_IFDIR|0o755,0), (stat.S_IFDIR|0o700,1000), (stat.S_IFLNK|0o700,0)):
                create.reset_mock()
                with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=mode,st_uid=uid)):
                    with self.assertRaisesRegex(RuntimeError,'private and root-owned'):
                        adapter.ensure_adapter_state(root, create)
                self.assertEqual(create.call_args_list,[mock.call(parent,0o700)])

    def test_legacy_events_are_distinct_and_preserve_chunked_logs_and_results(self):
            output, errors = io.StringIO(), io.StringIO()
            evidence = {'components': {'input': {'status': 'files_installed'}}}
            original = json.dumps(evidence)
            with redirect_stdout(output), redirect_stderr(errors):
                with adapter.legacy_events():
                    print('ordinary log')
                    for chunk in ('OXP_COMP', 'ONENT_', 'RESULT=', original, '\n'):
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
                    print('OXP_COMPONENT_RESULT='+original, file=sys.stderr)
                    sys.stdout.write('trailing OXP_')
            self.assertEqual(output.getvalue(), 'ordinary log\nBOILER_DEVICE_LEGACY_RESULT='+original+'\ntrailing OXP_')
            self.assertEqual(errors.getvalue(), 'BOILER_DEVICE_LEGACY_RESULT='+original+'\n')
            self.assertEqual(evidence, {'components': {'input': {'status': 'files_installed'}}})
            self.assertFalse(any(line.startswith('OXP_COMPONENT_RESULT=') for line in (output.getvalue()+errors.getvalue()).splitlines()))

    def test_staged_verification_compares_actual_bytes_and_private_journals(self):
            import base64
            with tempfile.TemporaryDirectory() as work:
                root = Path(work)
                options = {'repairs': ['input'], 'plugins': []}
                reports = {}
                def write(name, data):
                    path = root/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                for name, target in (('input','etc/input.conf'), ('system-update-hold','etc/hold.conf'),
                                     ('serial-console-policy','etc/serial.conf'), ('maintenance-tool','usr/local/lib/old-maintenance/main.py'),
                                     ('runtime','usr/local/lib/oxp3-integration/main.py'), ('release-note','home/deck/version.md')):
                    group = 'shared' if target.startswith('home/') else 'A'
                    data = (name+' applied\n').encode()
                    write(target, data)
                    journal = {'phase':'installed', 'allowed':[target], 'original':{target:{'exists':False}},
                               'applied':{target:base64.b64encode(data).decode()}, 'metadata':{target:{}}}
                    write('home/.oxp3-installer/integration/'+group+'/'+name+'/state.json', json.dumps(journal).encode())
                    if name not in ('runtime','release-note'):
                        reports[name] = {'status':'files_installed','files':[target]}
                write('etc/passwd', b'deck:x:1000:1000:deck:/home/deck:/bin/sh\n')
                result_path = 'home/.oxp3-installer/integration/A/result.json'
                write(result_path, json.dumps({'schema':1,'slot':'A','options':options,'components':reports}).encode())
                (root/adapter.LINK).parent.mkdir(parents=True,exist_ok=True)
                def read(name, **kwargs):
                    return {'exists':True,'data':base64.b64encode((root/name).read_bytes()).decode(),
                            'mode':0o600 if name.endswith('.json') else 0o644,'uid':0,'gid':0}
                before = {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
                actual_lstat = Path.lstat
                link_parents = set((root/adapter.LINK).parents)
                def lstat(path):
                    if path in link_parents:
                        return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
                    return actual_lstat(path)
                with mock.patch.object(Path, 'is_symlink', autospec=True, side_effect=lambda path: path == root/adapter.LINK), mock.patch.object(adapter.os, 'readlink', return_value=adapter.LINK_TARGET), mock.patch.object(Path,'lstat',autospec=True,side_effect=lstat):
                    proof = adapter.verify_staged(root,'A',options,reader=read)
                    self.assertEqual(len(proof['files']),6)
                    self.assertEqual(proof,adapter.verify_staged(root,'A',options,reader=read))
                    self.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})
                    write('etc/input.conf',b'edited despite successful status\n')
                    with self.assertRaisesRegex(RuntimeError,'differs from its applied journal'):
                        adapter.verify_staged(root,'A',options,reader=read)
                    write('etc/input.conf',before['etc/input.conf'])
                    (root/'home/.oxp3-installer/integration/A/input/state.json').unlink()
                    with self.assertRaisesRegex(RuntimeError,'without verified journal coverage'):
                        adapter.verify_staged(root,'A',options,reader=read)

    def test_deterministic_archive(self):
            with tempfile.TemporaryDirectory() as work:
                source = Path(work)/'source'
                self.fixture(source)
                first, second = Path(work)/'one.zip', Path(work)/'two.zip'
                builder.deterministic_zip(source, first)
                builder.deterministic_zip(source, second)
                self.assertEqual(first.read_bytes(), second.read_bytes())

if __name__ == '__main__':
    unittest.main()
