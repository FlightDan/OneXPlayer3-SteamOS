"""Private binary adoption export; synthetic fixtures, never a physical device."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance import adoption_stream as implementation, state_io
from oxp3_maintenance.transactions import Store

SOURCE=Path(__file__).resolve().parents[1]
NATIVE=os.name=='posix' and os.geteuid()==0
LIVE_SLOT='partuuid-5136a001-2345-6789-abcd-0123456789ab'


class MemoryStore:
    def __init__(self): self.records={}; self.data={}; self.count=0
    def new(self): self.count+=1; return str(self.count),io.BytesIO()
    def complete(self,name,stream,result):
        raw=stream.getvalue(); stream.close()
        if hashlib.sha256(raw).hexdigest()!=result.sha256 or len(raw)!=result.size: raise AssertionError('spooled bytes differ')
        self.records[result.sha256]={'sha256':result.sha256,'size':result.size}; self.data[result.sha256]=raw
        return result


class StreamingDecoderTests(unittest.TestCase):
    def test_decoded_payload_is_spooled_with_json_escapes_and_boundary_chunks(self):
        raw=bytes(range(256))*1000
        encoded=base64.b64encode(raw).decode().replace('/','\\/').replace('A','\\u0041')
        text='{"originals":{"'+LIVE_SLOT+':etc/a":{"exists":true,"data":"'+encoded+'","mode":420,"uid":0,"gid":0}},"slots":{"'+LIVE_SLOT+'":{"current":{"id":7,"release":{"version":"1.0.6"},"paths":{}}}},"format":1}'
        store=MemoryStore()
        with mock.patch.object(state_io,'CHUNK_SIZE',97):
            value=state_io._load(implementation._BlobReader(io.BytesIO(text.encode()),LIVE_SLOT,implementation.MAX_TOTAL,
                               [LIVE_SLOT+':etc/a'],store=store))
        digest=value['originals'][LIVE_SLOT+':etc/a']['data']
        self.assertIsInstance(digest,state_io.DataDigest)
        self.assertEqual(store.data[digest.sha256],raw)
        self.assertEqual(value['slots'][LIVE_SLOT]['current']['id'],7)
        self.assertEqual(value['slots'][LIVE_SLOT]['current']['release']['version'],'1.0.6')

    def test_invalid_payload_or_duplicate_keys_refuse_before_a_receipt(self):
        for payload in ('@@==','QQ=','QQ==QQ=='):
            document={'format':1,'originals':{LIVE_SLOT+':etc/a':{'data':payload}},'slots':{}}
            with self.subTest(payload=payload),self.assertRaises(state_io.StateJSONError):
                state_io._load(implementation._BlobReader(io.BytesIO(json.dumps(document).encode()),LIVE_SLOT,implementation.MAX_TOTAL,
                               [LIVE_SLOT+':etc/a'],store=MemoryStore()))
        with self.assertRaises(state_io.StateJSONError):
            state_io._load(implementation._BlobReader(io.BytesIO(b'{"format":1,"format":1}'),LIVE_SLOT,100,store=MemoryStore()))

    def test_unselected_history_is_scanned_without_spooling_or_retaining_payloads(self):
        history='historical non-base64 data is outside the selected snapshot contract'*20000
        value={'format':1,'originals':{'other:etc/a':{'data':history}},'slots':{'other':{'current':{'paths':{'a':{'snapshot':{'data':history}}}}},
              LIVE_SLOT:{'current':{'id':1,'paths':{},'previous':{'snapshot':{'data':history}}}}}}
        store=MemoryStore()
        result=state_io._load(implementation._BlobReader(io.BytesIO(json.dumps(value).encode()),LIVE_SLOT,implementation.MAX_TOTAL,store=store))
        self.assertEqual(store.records,{})
        self.assertEqual(set(result),{'format','slots'})
        self.assertEqual(set(result['slots']),{LIVE_SLOT})
        self.assertNotIn('previous',result['slots'][LIVE_SLOT]['current'])


@unittest.skipUnless(NATIVE,'Protected bundle filesystem tests require Linux root')
class NativeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(dir='/root'); self.addCleanup(self.temporary.cleanup)
        self.work=Path(self.temporary.name); self.root=self.work/'target'; self.root.mkdir(mode=0o700)
        self.key=(SOURCE/'trusted-public-key.pem').read_bytes()
    def write(self,name,data,mode=0o600):
        path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(mode);return path
    def snapshot(self,data):
        return {'exists':True,'data':base64.b64encode(data).decode(),'mode':0o644,'uid':0,'gid':0}
    def fixture(self,maintenance=True,*,absent=False):
        (self.root/'home/.oxp3-maintenance').mkdir(parents=True,mode=0o700)
        self.write('usr/local/lib/oxp3-maintenance/current-release.json',json.dumps({'version':'1.0.6','maintenance_runtime':'1.0.6+maintenance.11'}).encode(),0o644)
        self.write('usr/local/lib/oxp3-maintenance/releases/1.0.6+maintenance.11/trusted-public-key.pem',self.key,0o644)
        self.write('etc/passwd',b'deck:x:1000:1000:deck:/home/deck:/bin/sh\n',0o644)
        after=b'applied configuration\n';before=b'original configuration\n'
        self.write('etc/model.conf',after,0o644)
        original={'etc/model.conf':self.snapshot(before)}
        applied={'etc/model.conf':self.snapshot(after)}
        if absent:
            original['etc/no-parent/missing.conf']={'exists':False};applied['etc/no-parent/missing.conf']={'exists':False}
            original['etc/deleted.conf']=self.snapshot(b'removed original\n');applied['etc/deleted.conf']={'exists':False}
        if maintenance:
            index={'format':1,'originals':{LIVE_SLOT+':'+name:value for name,value in original.items()},
                   'slots':{LIVE_SLOT:{'current':{'id':9,'release':{'version':'1.0.6+maintenance.11'},
                           'paths':{name:{'component':'input','snapshot':value} for name,value in applied.items()}}}}}
            self.write('home/.oxp3-maintenance/index.json',json.dumps(index).encode())
        else:
            self.write('home/.oxp3-installer/integration/B/result.json',json.dumps({'schema':1,'slot':'B','release':{'version':'1.0.6'},'components':{'input':{'status':'files_installed'}}}).encode())
            self.write('home/.oxp3-installer/integration/B/input/state.json',json.dumps({'phase':'installed','allowed':list(original),
                       'original':original,'applied':{name:value.get('data') for name,value in applied.items()},'metadata':{}}).encode())
        self.write('home/.oxp3-maintenance/live-operation.json',json.dumps({'phase':'coherent','slot':LIVE_SLOT}).encode())
        return before,after
    def export(self,name='receipt.json'):
        store=Store(self.root,self.root/'home/.oxp3-maintenance',enforce_owner=True)
        destination=self.work/name
        with store.lock():
            value,raw=implementation.export_bundle(self.root,'B',self.key,legacy_slot=LIVE_SLOT,destination=destination)
        return destination,value,raw
    def test_both_formats_export_exact_private_binary_blobs_without_live_changes(self):
        for maintenance in (True,False):
            with self.subTest(maintenance=maintenance):
                self.root=self.work/('maintenance' if maintenance else 'installer');self.root.mkdir(mode=0o700)
                before,after=self.fixture(maintenance,absent=True)
                original={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                destination,receipt,raw=self.export(('maintenance' if maintenance else 'installer')+'.json')
                self.assertEqual(receipt['schema_version'],2)
                self.assertEqual(json.loads(raw),receipt)
                self.assertNotIn('"data":',raw.decode())
                directory=destination.parent/receipt['blob_directory']
                self.assertEqual({p.name for p in directory.iterdir()},{value['sha256'] for value in receipt['blobs']})
                self.assertEqual({p.read_bytes() for p in directory.iterdir()},{before,after,b'removed original\n'})
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode),0o700)
                self.assertTrue(all(stat.S_IMODE(p.stat().st_mode)==0o600 and p.stat().st_uid==0 for p in directory.iterdir()))
                self.assertEqual({p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name!='lock'},
                                 {name:data for name,data in original.items() if name!='home/.oxp3-maintenance/lock'})
                with self.assertRaises(RuntimeError): self.export(destination.name)
    def test_refuses_changes_pending_key_and_unsafe_or_preexisting_bundle(self):
        self.fixture()
        self.write('etc/model.conf',b'user edit',0o644)
        with self.assertRaisesRegex(RuntimeError,'differs'): self.export()
        self.assertFalse((self.work/'receipt.json').exists());self.assertFalse((self.work/'receipt.json.blobs').exists())
        self.write('etc/model.conf',b'applied configuration\n',0o644)
        self.write('home/.oxp3-maintenance/pending.json',b'{}')
        with self.assertRaisesRegex(RuntimeError,'pending'): self.export()
        (self.root/'home/.oxp3-maintenance/pending.json').unlink()
        key_name='usr/local/lib/oxp3-maintenance/releases/1.0.6+maintenance.11/trusted-public-key.pem'
        self.write(key_name,b'different key',0o644)
        with self.assertRaisesRegex(RuntimeError,'key differs'): self.export()
        self.write(key_name,self.key,0o644)
        self.write('home/.oxp3-maintenance/live-operation.json',json.dumps({'phase':'applying','slot':LIVE_SLOT}).encode())
        with self.assertRaisesRegex(RuntimeError,'lifecycle'): self.export()
        self.write('home/.oxp3-maintenance/live-operation.json',json.dumps({'phase':'coherent','slot':LIVE_SLOT}).encode())
        writable=self.work/'writable';writable.mkdir();writable.chmod(0o777)
        private=writable/'private';private.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError,'protected root-owned'): self.export('writable/private/receipt.json')
        (self.work/'receipt.json.blobs').mkdir(mode=0o700)
        with self.assertRaises(FileExistsError): self.export()

    def test_malformed_selected_base64_closes_pending_streams_and_removes_partial_bundle(self):
        self.fixture()
        path=self.root/'home/.oxp3-maintenance/index.json'
        value=json.loads(path.read_text());value['slots'][LIVE_SLOT]['current']['paths']['etc/model.conf']['snapshot']['data']='QQ='
        path.write_text(json.dumps(value));path.chmod(0o600)
        with self.assertRaises(state_io.StateJSONError): self.export()
        self.assertFalse((self.work/'receipt.json').exists());self.assertFalse((self.work/'receipt.json.blobs').exists())

    def test_late_receipt_directory_fsync_failure_preserves_published_receipt_and_blobs(self):
        self.fixture()
        destination=self.work/'late-fsync.json'
        original=os.fsync
        def failing(descriptor):
            if destination.exists() and stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError('Simulated receipt directory fsync failure')
            return original(descriptor)
        with mock.patch.object(implementation.os,'fsync',side_effect=failing),self.assertRaisesRegex(OSError,'Simulated'):
            self.export(destination.name)
        self.assertTrue(destination.exists())
        receipt=json.loads(destination.read_bytes());directory=self.work/receipt['blob_directory']
        self.assertEqual({path.name for path in directory.iterdir()},{item['sha256'] for item in receipt['blobs']})
        for item in receipt['blobs']:
            self.assertEqual(hashlib.sha256((directory/item['sha256']).read_bytes()).hexdigest(),item['sha256'])
        if os.environ.get('BOILER_INSTALLER_SOURCE'):
            sys.path.insert(0,os.environ['BOILER_INSTALLER_SOURCE'])
            from maintenance import Engine
            engine=Engine(self.root);result=engine.adopt(destination)
            self.assertTrue(result['migration_complete']);self.assertTrue(engine.verify('oxp3:input')['ok'])

    def test_index_change_and_input_links_refuse_and_remove_only_created_bundle(self):
        self.fixture()
        original=implementation._state
        calls=[]
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            if not calls:
                path=self.root/'home/.oxp3-maintenance/index.json'
                value=json.loads(path.read_text());value['slots'][LIVE_SLOT]['current']['id']+=1
                path.write_text(json.dumps(value));path.chmod(0o600)
            calls.append(True)
            return result
        with mock.patch.object(implementation,'_state',side_effect=changed),self.assertRaisesRegex(RuntimeError,'between streaming passes'):
            self.export()
        self.assertFalse((self.work/'receipt.json').exists());self.assertFalse((self.work/'receipt.json.blobs').exists())
        index=self.root/'home/.oxp3-maintenance/index.json'
        real=index.with_name('original-index.json');index.rename(real);index.symlink_to(real)
        with self.assertRaises(RuntimeError): self.export()
        self.assertEqual(real.read_bytes(),index.read_bytes())
        self.assertFalse((self.work/'receipt.json.blobs').exists())

    def test_large_snapshot_above_inline_limit_is_streamed_with_bounded_memory(self):
        import resource
        before_memory=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.fixture()
        size=138485536
        target=self.root/'etc/large.bin'
        block=bytes(range(256))*(3*1024*1024//256)
        expected=hashlib.sha256()
        with target.open('wb') as stream:
            remaining=size
            while remaining:
                data=block[:min(len(block),remaining)];stream.write(data);expected.update(data);remaining-=len(data)
        target.chmod(0o644)
        marker='BASE64_STREAM'
        value={'format':1,'originals':{LIVE_SLOT+':etc/large.bin':{'exists':False}},'slots':{LIVE_SLOT:{'current':{
               'id':10,'release':{'version':'1.0.6+maintenance.11'},'paths':{'etc/large.bin':{'component':'input',
               'snapshot':{'exists':True,'mode':0o644,'uid':0,'gid':0,'data':marker}}}}}}}
        prefix,separator,suffix=json.dumps(value).partition('"'+marker+'"')
        self.assertTrue(separator)
        index=self.root/'home/.oxp3-maintenance/index.json'
        with index.open('wb') as stream,target.open('rb') as source:
            stream.write(prefix.encode()+b'"')
            while data:=source.read(3*1024*1024): stream.write(base64.b64encode(data))
            stream.write(b'"'+suffix.encode())
        index.chmod(0o600)
        destination,receipt,raw=self.export('large.json')
        self.assertLess(len(raw),32*1024)
        self.assertEqual(receipt['blobs'],[{'sha256':expected.hexdigest(),'size':size}])
        blob=destination.parent/receipt['blob_directory']/expected.hexdigest()
        self.assertEqual(blob.stat().st_size,size)
        self.assertLess(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss-before_memory,64*1024,
                        'Streaming export must not retain a 138MB file or its base64 encoding')

    def test_installer_directory_runtime_originals_are_streamed_and_verified(self):
        from oxp3_maintenance import adoption
        self.fixture(False)
        prefix=adoption._RUNTIMES['desktop-hdr'];state=(Path(prefix).parent/'.installer-state').as_posix()
        original,applied=b'original directory runtime\n',b'installed directory runtime\n'
        self.write(prefix+'/tool.py',applied,0o644)
        self.write(state+'/installed/tool.py',applied,0o644)
        self.write(state+'/original/tool.py',original,0o644)
        metadata={'.':{'directory':True,'mode':stat.S_IMODE((self.root/prefix).stat().st_mode),'uid':0,'gid':0},
                  'tool.py':{'directory':False,'mode':0o644,'uid':0,'gid':0}}
        self.write(state+'/state.json',json.dumps({'destination':prefix,'phase':'installed','original_exists':True,
                   'installed_metadata':metadata,'original_metadata':metadata}).encode())
        result=self.root/'home/.oxp3-installer/integration/B/result.json'
        value=json.loads(result.read_text());value['components']['desktop-hdr']={'status':'files_installed'}
        result.write_text(json.dumps(value));result.chmod(0o600)
        destination,receipt,raw=self.export('directory-runtime.json')
        component=next(item for item in receipt['components'] if item['id']=='oxp3:desktop-hdr')
        self.assertEqual(component['operations'][0]['target'],prefix+'/tool.py')
        self.assertEqual(component['operations'][0]['before']['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(component['operations'][0]['after']['sha256'],hashlib.sha256(applied).hexdigest())
        self.assertIn('installer-runtime-original',{item['role'] for item in receipt['evidence']})
        if os.environ.get('BOILER_INSTALLER_SOURCE'):
            sys.path.insert(0,os.environ['BOILER_INSTALLER_SOURCE'])
            from maintenance import Engine
            engine=Engine(self.root);result=engine.adopt(destination)
            self.assertTrue(engine.verify('oxp3:desktop-hdr')['ok'])
            for transaction in reversed(result['transactions']): engine.restore(transaction)
            self.assertEqual((self.root/prefix/'tool.py').read_bytes(),original)
    @unittest.skipUnless(os.environ.get('BOILER_INSTALLER_SOURCE'),'Set explicit new-runtime source for separate integration')
    def test_export_then_generic_adopt_verify_restore_with_old_lock_released(self):
        sys.path.insert(0,os.environ['BOILER_INSTALLER_SOURCE'])
        from maintenance import Engine
        for maintenance in (True,False):
            self.root=self.work/('generic-maintenance' if maintenance else 'generic-installer');self.root.mkdir(mode=0o700)
            before,after=self.fixture(maintenance,absent=True)
            destination,receipt,raw=self.export(('generic-maintenance' if maintenance else 'generic-installer')+'.json')
            engine=Engine(self.root);result=engine.adopt(destination)
            self.assertTrue(result['migration_complete']);self.assertEqual((self.root/'etc/model.conf').read_bytes(),after)
            self.assertFalse((self.root/'etc/deleted.conf').exists())
            for component in receipt['components']: self.assertTrue(engine.verify(component['id'])['ok'])
            for transaction in reversed(result['transactions']): engine.restore(transaction)
            self.assertEqual((self.root/'etc/model.conf').read_bytes(),before)
            self.assertEqual((self.root/'etc/deleted.conf').read_bytes(),b'removed original\n')
            self.assertEqual((self.root/'usr/local/lib/oxp3-maintenance/releases/1.0.6+maintenance.11/trusted-public-key.pem').read_bytes(),self.key)


if __name__=='__main__': unittest.main()
