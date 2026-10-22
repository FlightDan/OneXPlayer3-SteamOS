"""Static package preparation against synthetic public archives; no network."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('static_builder',ROOT/'scripts/build-maintenance.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class StaticPackageTests(unittest.TestCase):
    def fixture(self, root, *, mutate=None):
        lock = json.loads((ROOT/'maintenance-static-lock.json').read_bytes())
        payload = (b'# OXP3 accepted display workaround. Re-enabling DSB is a separate later hardware trial.\n'
                   b'options xe enable_dsb=0\n')
        manifest = {'xe-dsb': {'files': [{'target':lock['target'],'source':'xe-dsb/000.bin','mode':420,'user':False}],
                               'units':[],'packages':{},'missing':[]}}
        files = {'build-info.json':json.dumps({'source_commit':'a'*40,'package_channel':'public-release'}).encode(),
                 'components/release.json':json.dumps({'version':'1.0.6'}).encode(),
                 'cache/integration/manifest.json':json.dumps(manifest).encode(),
                 lock['source']:payload, 'LICENSE':b'Project license\n',
                 'licenses/upstream-fixes-MIT.txt':b'Original upstream MIT notice\n',
                 'research/private.py':b'never export', 'app/installer.exe':b'never export'}
        if mutate:
            mutate(files)
        archive = root/'public.zip'
        with zipfile.ZipFile(archive,'w') as target:
            for name,data in files.items():
                target.writestr(name,data)
        upstream = {'repository':'FlightDan/OneXPlayer3-SteamOS','source_commit':'a'*40,'release_tag':'fixture',
                    'asset':{'size':archive.stat().st_size,'sha256':builder.common.digest(archive)}}
        upstream_path = root/'upstream.json'
        upstream_path.write_text(json.dumps(upstream),encoding='utf-8')
        lock['upstream_lock_sha256'] = builder.common.digest(upstream_path)
        lock_path = root/'static.json'
        lock_path.write_text(json.dumps(lock),encoding='utf-8')
        return archive,lock_path,upstream_path

    def test_inventory_fixed_ownership_no_hooks_and_stable_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive,lock,upstream = self.fixture(root)
            manifests = []
            for name in ('one','two'):
                output = root/name
                manifest = builder.build(archive,output,lock_path=lock,upstream_path=upstream)
                manifests.append(manifest)
                self.assertEqual(manifest['id'],'device:oxp3-maintenance')
                self.assertEqual(manifest['purpose'],'maintenance')
                component = manifest['components'][0]
                self.assertEqual(component['version'],'1.0.6')
                self.assertTrue(component['retain_owned_paths'])
                self.assertNotIn('hooks',component)
                self.assertNotIn('maintenance_entry',manifest)
                self.assertEqual([(item['target'],item['mode']) for item in component['files']],
                                 [('etc/modprobe.d/xe-oxp3.conf',420)])
                actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
                self.assertEqual(actual,{'manifest.json','payload/xe-oxp3.conf','LICENSE','licenses/upstream-fixes-MIT.txt'})
                for item in manifest['files']:
                    raw = (output/item['path']).read_bytes()
                    self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(item['size'],item['sha256']))
                builder.common.deterministic_zip(output,root/(name+'.zip'))
            self.assertEqual(manifests[0],manifests[1])
            self.assertEqual((root/'one.zip').read_bytes(),(root/'two.zip').read_bytes())

    def test_payload_tamper_and_changed_full_ownership_refuse_before_output(self):
        def bad_payload(files): files['cache/integration/xe-dsb/000.bin'] += b'unsafe change\n'
        def extra_path(files):
            value = json.loads(files['cache/integration/manifest.json'])
            value['xe-dsb']['files'].append({'target':'etc/extra.conf','source':'xe-dsb/000.bin','mode':420,'user':False})
            files['cache/integration/manifest.json'] = json.dumps(value).encode()
        def bad_release(files): files['components/release.json'] = b'{"version":"1.0.7"}'
        def units(files):
            value = json.loads(files['cache/integration/manifest.json'])
            value['xe-dsb']['units'] = ['unexpected.service']
            files['cache/integration/manifest.json'] = json.dumps(value).encode()
        for mutation in (bad_payload,extra_path,bad_release,units):
            with self.subTest(mutation=mutation.__name__),tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive,lock,upstream = self.fixture(root,mutate=mutation)
                with self.assertRaises(ValueError):
                    builder.build(archive,root/'out',lock_path=lock,upstream_path=upstream)
                self.assertFalse((root/'out').exists())

    def test_full_archive_and_upstream_lock_tamper_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive,lock,upstream = self.fixture(root)
            archive.write_bytes(archive.read_bytes()+b'changed source')
            with self.assertRaises(ValueError): builder.build(archive,root/'out',lock_path=lock,upstream_path=upstream)
            upstream.write_bytes(upstream.read_bytes()+b' ')
            with self.assertRaises(ValueError): builder.build(archive,root/'out',lock_path=lock,upstream_path=upstream)
            self.assertFalse((root/'out').exists())

    def test_production_lock_pins_existing_generation_and_exact_payload(self):
        lock = json.loads((ROOT/'maintenance-static-lock.json').read_bytes())
        self.assertEqual(lock['component_version'],'1.0.6')
        self.assertEqual(lock['upstream_lock_sha256'],builder.common.digest(ROOT/'upstream-lock.json'))
        self.assertEqual((lock['size'],lock['sha256']),(112,'1a1e2c951fec8a8a3c10977c78205e30d7052582c36c3e0700ffd03bd748b690'))


if __name__ == '__main__':
    unittest.main()
