import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('prepare_overlay',Path(__file__).with_name('prepare-overlay.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class OverlayPayloadTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source';source.mkdir()
        for n in m.SOURCE_NAMES:(source/n).write_text('new '+n)
        store=root/'store';(store/'overlay').mkdir(parents=True)
        files=[]
        for i,(target,name) in enumerate(m.RUNTIME.items()):
            path=f'overlay/{i:03d}.bin';(store/path).write_text('old '+name)
            files.append(dict(target=target,source=path,user=False,mode=0o644))
        manifest={'overlay':dict(files=files),'other':dict(files=[])}
        (store/'manifest.json').write_text(json.dumps(manifest))
        (store/'unchanged.bin').write_bytes(b'preserve')
        return source,store,manifest

    def test_refresh_preserves_manifest_and_other_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,store,manifest=self.fixture(Path(tmp))
            before=(store/'manifest.json').read_bytes()
            paths=m.refresh(source,store)
            self.assertEqual(len(paths),6)
            self.assertEqual((store/'overlay/000.bin').read_bytes(),(source/'telemetry.py').read_bytes())
            self.assertEqual((store/'overlay/001.bin').read_bytes(),(source/'allow-read.py').read_bytes())
            self.assertEqual((store/'manifest.json').read_bytes(),before)
            self.assertEqual((store/'unchanged.bin').read_bytes(),b'preserve')

    def test_invalid_payload_policy_refused_before_writes(self):
        for key,value in [('source','../outside.bin'),('source','C:/outside.bin'),
                          ('source','overlay\\outside.bin'),('mode',0o666),('user',True)]:
            with self.subTest(key=key,value=value),tempfile.TemporaryDirectory() as tmp:
                source,store,manifest=self.fixture(Path(tmp))
                manifest['overlay']['files'][1][key]=value
                (store/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):m.refresh(source,store)
                self.assertEqual((store/'overlay/000.bin').read_text(),'old telemetry.py')

    def test_alias_into_other_component_refused(self):
        for reference in ['overlay/000.bin','overlay/./000.bin','overlay/x/../000.bin']:
            with self.subTest(reference=reference),tempfile.TemporaryDirectory() as tmp:
                source,store,manifest=self.fixture(Path(tmp))
                manifest['other']['files']=[dict(source=reference,target='unrelated')]
                (store/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):m.refresh(source,store)
                self.assertEqual((store/'overlay/000.bin').read_text(),'old telemetry.py')

if __name__=='__main__':unittest.main()
