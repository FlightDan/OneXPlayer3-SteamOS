"""Read-only, bounded legacy adoption export with private binary CAS snapshots.

The JSON string decoder reuses the published state_io reader's parsing rules.
Only selected original/current payloads are decoded, directly into private files.
No legacy journal, live target, installed runtime or signing anchor is changed.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from . import adoption_export as legacy
from . import state_io

MAX_FILE = 256*1024**2
MAX_TOTAL = 8*1024**3
MAX_RECEIPT = 8*1024**2
MAX_OPERATIONS = 20000
MAX_COMPONENTS = 1000


@contextmanager
def protected_file(root, name, *, private=False, user_uid=None, missing=False, maximum=MAX_TOTAL):
    """Open a protected inode with held directory descriptors, including absence."""
    root = Path(root).absolute()
    path = root/legacy._relative(name)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags)
    descriptor = None
    try:
        current = Path(path.anchor)
        def check_directory(fd, current):
            info = os.fstat(fd)
            user = user_uid is not None and current.is_relative_to(root/'home/deck')
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in ((0,user_uid) if user else (0,)):
                raise RuntimeError('Untrusted legacy ancestor')
            sticky = info.st_uid == 0 and info.st_mode & stat.S_ISVTX and not current.is_relative_to(root)
            if info.st_mode & 0o022 and not sticky:
                raise RuntimeError('Writable legacy ancestor')
        check_directory(directory,current)
        for part in path.parts[1:-1]:
            current = current/part
            try:
                child = os.open(part,flags,dir_fd=directory)
            except FileNotFoundError:
                if missing:
                    yield None
                    return
                raise
            try:
                check_directory(child,current)
            except BaseException:
                os.close(child)
                raise
            os.close(directory); directory=child
        try:
            descriptor = os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        except FileNotFoundError:
            if missing:
                yield None
                return
            raise
        info = os.fstat(descriptor)
        allowed = (0,user_uid) if user_uid is not None and path.is_relative_to(root/'home/deck') else (0,)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid not in allowed
                or info.st_mode & (0o077 if private else 0o022) or not 0 <= info.st_size <= maximum):
            raise RuntimeError('Invalid or unprotected legacy file')
        with os.fdopen(descriptor,'rb') as stream:
            descriptor=None
            yield stream
            after=os.fstat(stream.fileno())
            fields=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
            if any(getattr(info,key)!=getattr(after,key) for key in fields):
                raise RuntimeError('Legacy inode changed while read')
    except OSError as error:
        raise RuntimeError('Unsafe legacy input path') from error
    finally:
        if descriptor is not None: os.close(descriptor)
        os.close(directory)


class HashReader:
    def __init__(self,stream):
        self.stream=stream; self.digest=hashlib.sha256(); self.size=0
    def read(self,count):
        if not 0 <= count <= state_io.CHUNK_SIZE: raise RuntimeError('Unbounded state read')
        raw=self.stream.read(count)
        self.size+=len(raw)
        if self.size>MAX_TOTAL: raise RuntimeError('Legacy state exceeds byte limit')
        self.digest.update(raw)
        return raw


class BlobStore:
    def __init__(self,directory):
        self.directory=directory; self.records={}; self.total=0; self.pending=set(); self.streams=[]
    def new(self):
        name='.incoming-'+secrets.token_hex(16)
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.directory)
        os.fchmod(fd,0o600); self.pending.add(name)
        stream=os.fdopen(fd,'wb'); self.streams.append(stream)
        return name,stream
    def complete(self,name,stream,result):
        stream.flush(); os.fsync(stream.fileno()); stream.close()
        if result.sha256 not in self.records:
            if len(self.records)>=40000 or self.total+result.size>MAX_TOTAL:
                raise RuntimeError('Adoption blob inventory exceeds limit')
            os.link(name,result.sha256,src_dir_fd=self.directory,dst_dir_fd=self.directory,follow_symlinks=False)
            self.records[result.sha256]={'sha256':result.sha256,'size':result.size}
            self.total+=result.size
        elif self.records[result.sha256]['size']!=result.size:
            raise RuntimeError('Conflicting adoption blob')
        os.unlink(name,dir_fd=self.directory); self.pending.remove(name)
        return result
    def copy(self,stream):
        name,target=self.new(); digest=hashlib.sha256(); size=0
        try:
            while raw:=stream.read(state_io.CHUNK_SIZE):
                size+=len(raw)
                if size>MAX_FILE: raise RuntimeError('Adoption file exceeds size limit')
                target.write(raw); digest.update(raw)
            return self.complete(name,target,state_io.DataDigest(digest.hexdigest(),size))
        finally:
            target.close()
    def cleanup(self):
        for stream in self.streams: stream.close()
        for name in [*self.pending,*self.records]:
            try: os.unlink(name,dir_fd=self.directory)
            except FileNotFoundError: pass
    def prune(self,required):
        for name in set(self.records)-required:
            os.unlink(name,dir_fd=self.directory)
            self.total-=self.records.pop(name)['size']


class _BlobSink(state_io._Base64Digest):
    def __init__(self,store):
        super().__init__(); self.store=store; self.name,self.stream=store.new()
    def feed(self,text):
        if not text: return
        if self.ended: raise state_io.StateJSONError('Invalid snapshot base64')
        try: text.encode('ascii')
        except UnicodeError as error: raise state_io.StateJSONError('Invalid snapshot base64') from error
        text=self.tail+text; length=len(text)//4*4; self.tail=text[length:]
        if not length: return
        encoded=text[:length]
        if not state_io._BASE64.fullmatch(encoded): raise state_io.StateJSONError('Invalid snapshot base64')
        try: raw=base64.b64decode(encoded,validate=True)
        except ValueError as error: raise state_io.StateJSONError('Invalid snapshot base64') from error
        if '=' in encoded:
            self.ended=True
            if self.tail: raise state_io.StateJSONError('Invalid snapshot base64')
        self.size+=len(raw)
        if self.size>MAX_FILE: raise state_io.StateJSONError('Snapshot size limit exceeded')
        self.digest.update(raw); self.stream.write(raw)
    def finish(self):
        result=super().finish()
        return self.store.complete(self.name,self.stream,result)


class _ProjectionReader(state_io._Reader):
    def retained(self,path,key):
        if path==('slots',self.slot,'current') and key in ('id','release','aborted_apply'):
            return True
        return super().retained(path,key)


class _BlobReader(_ProjectionReader):
    def __init__(self,*args,store,**kwargs):
        super().__init__(*args,**kwargs); self.store=store
    def string(self, *, keep, path=(), key=False):
        self.expect('"')
        chunks = [] if keep and not self.payload(path) else None
        sink = _BlobSink(self.store) if keep and self.payload(path) else None
        length = 0
        high = None
        digest = hashlib.sha256() if keep and not key and sink is None else None

        def emit(text):
            nonlocal length
            if not text:
                return
            length += len(text)
            # Selected CAS payloads have a per-file byte limit. Skipped history
            # is validated as JSON under the document budget without retaining
            # its inline payloads.
            if key and length > state_io.MAX_KEY:
                self.error('JSON string limit exceeded')
            if sink is None and (key or not path or path[-1] != 'data'
                    or self.slot is not None and keep):
                self.budget(len(text) * 2)
            if sink is not None:
                sink.feed(text)
            elif chunks is not None:
                chunks.append(text)
                if digest is not None:
                    digest.update(text.encode('utf-8', errors='surrogatepass'))

        def plain(text):
            nonlocal high
            if high is not None:
                emit(chr(high))
                high = None
            emit(text)

        while True:
            if not self.ensure():
                self.error('Unterminated JSON string')
            match = state_io._SPECIAL.search(self.buffer, self.position)
            end = match.start() if match else len(self.buffer)
            if end > self.position:
                plain(self.buffer[self.position:end])
            self.position = end
            if match is None:
                continue
            character = self.buffer[self.position]
            self.position += 1
            if character == '"':
                if high is not None:
                    emit(chr(high))
                break
            if character != '\\':
                self.error('Unescaped JSON control character')
            escape = self.peek()
            if not escape:
                self.error('Unterminated JSON escape')
            self.position += 1
            if escape in state_io._ESCAPES:
                plain(state_io._ESCAPES[escape])
            elif escape == 'u':
                if not self.ensure(4):
                    self.error('Invalid JSON Unicode escape')
                digits = self.buffer[self.position:self.position + 4]
                self.position += 4
                if not state_io._HEX.fullmatch(digits):
                    self.error('Invalid JSON Unicode escape')
                number = int(digits, 16)
                if high is not None and 0xdc00 <= number <= 0xdfff:
                    emit(chr(0x10000 + ((high - 0xd800) << 10) + number - 0xdc00))
                    high = None
                else:
                    if high is not None:
                        emit(chr(high))
                    high = number if 0xd800 <= number <= 0xdbff else None
                    if high is None:
                        emit(chr(number))
            else:
                self.error('Invalid JSON escape')
        if sink is not None:
            return sink.finish()
        if chunks is None:
            return None
        result = ''.join(chunks)
        if digest is not None and length >= state_io.INTERN_THRESHOLD:
            identity = (digest.digest(), length)
            candidates = self.interned.get(identity, ())
            for existing in candidates:
                if existing == result:
                    return existing
            if self.intern_count < state_io.MAX_INTERNED:
                self.interned.setdefault(identity, []).append(result)
                self.intern_count += 1
        return result



class _JournalReader(_BlobReader):
    def retained(self,path,key):
        if not path: return key in ('phase','allowed','original','applied','metadata')
        if len(path)==2 and path[0]=='original': return key in ('exists','mode','uid','gid','data')
        return True
    def payload(self,path):
        return len(path)==2 and path[0]=='applied' or len(path)==3 and path[0]=='original' and path[-1]=='data'


def _state(root,name,slot,*,scopes=(),store=None,journal=False):
    with protected_file(root,name,private=True) as stream:
        hashed=HashReader(stream)
        cls=_JournalReader if journal else _BlobReader if store else _ProjectionReader
        kwargs={'store':store} if store else {}
        reader=cls(hashed,slot,MAX_TOTAL,scopes,**kwargs)
        value=state_io._load(reader)
        return value,{'path':name,'role':'installer-journal' if journal else 'maintenance-index',
                      'size':hashed.size,'sha256':hashed.digest.hexdigest()}


def _fingerprint(root,name,*,private=False,user_uid=None,missing=False,store=None,maximum=MAX_FILE):
    with protected_file(root,name,private=private,user_uid=user_uid,missing=missing,maximum=maximum) as stream:
        if stream is None: return {'exists':False}
        info=os.fstat(stream.fileno())
        if store:
            data=store.copy(stream)
        else:
            digest=hashlib.sha256(); count=0
            while raw:=stream.read(state_io.CHUNK_SIZE):
                count+=len(raw)
                if count>maximum: raise RuntimeError('Legacy file exceeds size limit')
                digest.update(raw)
            data=state_io.DataDigest(digest.hexdigest(),count)
        return {'exists':True,'sha256':data.sha256,'size':data.size,'mode':stat.S_IMODE(info.st_mode),
                'uid':info.st_uid,'gid':info.st_gid,**({'blob':data.sha256} if store else {})}


def _reference(snapshot,store):
    if not isinstance(snapshot,dict) or type(snapshot.get('exists')) is not bool: raise RuntimeError('Invalid legacy snapshot')
    if not snapshot['exists']: return {'exists':False}
    if any(type(snapshot.get(key)) is not int or snapshot[key]<0 for key in ('mode','uid','gid')) or snapshot['mode']>0o7777:
        raise RuntimeError('Invalid legacy snapshot metadata')
    data=snapshot.get('data')
    if not isinstance(data,state_io.DataDigest) or store.records.get(data.sha256)!={'sha256':data.sha256,'size':data.size}:
        raise RuntimeError('Legacy snapshot has no authenticated binary blob')
    return {key:snapshot[key] for key in ('exists','mode','uid','gid')}|{'sha256':data.sha256,'size':data.size,'blob':data.sha256}


def collect(root,slot,key,*,legacy_slot,store,blob_directory):
    """Collect v2 while the caller holds the existing legacy exclusive lock."""
    root=Path(root).absolute()
    if slot not in ('A','B') or not isinstance(legacy_slot,str) or not re.fullmatch(r'(?:partuuid-[a-z0-9-]{8,64}|[AB])',legacy_slot):
        raise RuntimeError('Explicit logical and stable legacy slot identities required')
    evidence=[]
    def exists(name): return os.path.lexists(root/legacy._relative(name))
    def small(name,role=None,private=False):
        with protected_file(root,name,private=private,maximum=MAX_RECEIPT) as stream:
            data=stream.read(MAX_RECEIPT+1)
            if len(data)>MAX_RECEIPT: raise RuntimeError('Legacy metadata exceeds small document limit')
        if role: evidence.append({'path':name,'role':role,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        return data
    def document(name,role,private=True):
        return json.loads(small(name,role,private),object_pairs_hook=legacy._pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('Invalid legacy JSON constant')))
    if exists('home/.oxp3-maintenance/pending.json'): raise RuntimeError('Recover pending legacy transaction before adoption')
    lifecycle='home/.oxp3-maintenance/live-operation.json'
    if exists(lifecycle):
        record=document(lifecycle,'legacy-lifecycle')
        if record.get('phase')!='coherent' or record.get('slot')!=legacy_slot: raise RuntimeError('Recover legacy lifecycle before adoption')
    public=document('usr/local/lib/oxp3-maintenance/current-release.json','legacy-release',False)
    runtime=public.get('maintenance_runtime',public.get('version',''))
    if not isinstance(runtime,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,159}',runtime): raise RuntimeError('Invalid legacy runtime generation')
    key_name='usr/local/lib/oxp3-maintenance/releases/'+runtime+'/trusted-public-key.pem'
    if small(key_name,'trusted-public-key')!=key: raise RuntimeError('Installed legacy public key differs; key replacement forbidden')
    users=[line.split(':') for line in small('etc/passwd').decode().splitlines() if line.startswith('deck:')]
    if len(users)!=1 or len(users[0])!=7: raise RuntimeError('Expected exactly one deck account')
    uid,gid=int(users[0][2]),int(users[0][3])
    if min(uid,gid)<=0: raise RuntimeError('Deck account must not be root')
    operations={}
    def add(name,component,before,after):
        legacy._relative(name)
        if not isinstance(component,str) or not re.fullmatch(r'_?[a-z][a-z0-9-]*',component): raise RuntimeError('Invalid legacy component identity')
        before,after=_reference(before,store),_reference(after,store)
        current=_fingerprint(root,name,user_uid=uid if name.startswith('home/deck/') else None,missing=True)
        if {k:v for k,v in after.items() if k!='blob'}!=current: raise RuntimeError('Legacy target differs from recorded generation: '+name)
        if name in operations or len(operations)>=MAX_OPERATIONS: raise RuntimeError('Duplicate or excessive legacy ownership')
        identity='oxp3:maintenance-runtime' if component=='_maintenance' else 'oxp3:'+component
        operations[name]={'component':identity,'target':name,'before':before,'after':after}
    index_name='home/.oxp3-maintenance/index.json'
    if exists(index_name):
        projected,anchor=_state(root,index_name,legacy_slot)
        generation=projected.get('slots',{}).get(legacy_slot,{}).get('current')
        if (projected.get('format')!=1 or not isinstance(generation,dict) or type(generation.get('id')) is not int
                or not isinstance(generation.get('paths'),dict) or generation.get('aborted_apply')):
            raise RuntimeError('No coherent known legacy maintenance generation')
        scopes=[('shared' if name.startswith(('home/','opt/')) else legacy_slot)+':'+name for name in generation['paths']]
        projected,again=_state(root,index_name,legacy_slot,scopes=scopes,store=store)
        if again!=anchor: raise RuntimeError('Legacy index changed between streaming passes')
        evidence.append(anchor)
        generation=projected['slots'][legacy_slot]['current']
        for name,entry in generation['paths'].items():
            scope=('shared' if name.startswith(('home/','opt/')) else legacy_slot)+':'+name
            if scope not in projected.get('originals',{}) or not isinstance(entry,dict): raise RuntimeError('Missing legacy original')
            add(name,entry.get('component'),projected['originals'][scope],entry.get('snapshot'))
        release=generation.get('release',public); source_format='oxp3-maintenance-format-1'
    else:
        result=document('home/.oxp3-installer/integration/'+slot+'/result.json','installer-result')
        if result.get('schema')!=1 or result.get('slot')!=slot or not isinstance(result.get('components'),dict): raise RuntimeError('Unknown legacy installer result')
        names={name for name,value in result['components'].items() if value.get('status')=='files_installed'}|{'runtime','release-note','desktop-session','decky-order-light'}
        for group in (slot,'shared'):
            for name in sorted(names):
                legacy._relative(name)
                journal='home/.oxp3-installer/integration/'+group+'/'+name+'/state.json'
                if not exists(journal): continue
                record,anchor=_state(root,journal,'',store=store,journal=True)
                if record.get('phase')=='rolled_back': continue
                if record.get('phase')!='installed' or not isinstance(record.get('allowed'),list): raise RuntimeError('Recover incomplete legacy installer journal')
                evidence.append(anchor)
                if len(record['allowed'])!=len(set(record['allowed'])) or set(record.get('original',{}))!=set(record['allowed']) or set(record.get('applied',{}))!=set(record['allowed']):
                    raise RuntimeError('Legacy installer journal coverage differs')
                for target in record['allowed']:
                    original=record['original'][target]; data=record['applied'][target]
                    after={'exists':False} if data is None else dict(original,exists=True,data=data)
                    if data is not None and not original.get('exists'):
                        metadata=record.get('metadata',{}).get(target,{})
                        after.update(mode=metadata.get('mode',0o644),uid=uid if metadata.get('user') else 0,gid=gid if metadata.get('user') else 0)
                    add(target,name,original,after)
        _directory_runtimes(root,names,store,add,evidence)
        release=result.get('release',public); source_format='oxp3-installer-logical-files-v1'
    if not operations: raise RuntimeError('No verified legacy managed files')
    components={}
    for operation in sorted(operations.values(),key=lambda value:value['target']):
        components.setdefault(operation['component'],[]).append({key:operation[key] for key in ('target','before','after')})
    if len(components)>MAX_COMPONENTS: raise RuntimeError('Too many legacy components')
    store.prune({snapshot['blob'] for operation in operations.values() for snapshot in (operation['before'],operation['after']) if snapshot['exists']})
    for anchor in evidence:
        actual=_fingerprint(root,anchor['path'],maximum=MAX_TOTAL)
        if actual.get('size')!=anchor['size'] or actual.get('sha256')!=anchor['sha256']: raise RuntimeError('Legacy evidence changed during export')
    for operation in operations.values():
        actual=_fingerprint(root,operation['target'],user_uid=uid if operation['target'].startswith('home/deck/') else None,missing=True)
        if actual!={key:value for key,value in operation['after'].items() if key!='blob'}: raise RuntimeError('Legacy target changed during export')
    if exists('home/.oxp3-maintenance/pending.json'): raise RuntimeError('Legacy transaction appeared during export')
    return {'schema_version':2,'kind':'LegacyAdoptionReceipt','device_id':'oxp3','slot':slot,'legacy_slot':legacy_slot,
            'source_format':source_format,'source_release':release,'evidence':evidence,
            'trusted_public_key':next(anchor for anchor in evidence if anchor['role']=='trusted-public-key'),
            'components':[{'id':identity,'version':release.get('version',public.get('version')),'operations':items} for identity,items in sorted(components.items())],
            'blob_directory':blob_directory,'blobs':sorted(store.records.values(),key=lambda value:value['sha256']),
            'preserve_legacy':True,'translation_complete':True,'migration_complete':False,
            'remaining':'Review this private bundle, then explicitly adopt with the trusted generic runtime after the old lock is released.'}


def _directory_runtimes(root,names,store,add,evidence):
    from . import adoption
    def tree(prefix,expected):
        expected=adoption._metadata(expected); actual={}; files={}; total=0
        def visit(directory,relative):
            nonlocal total
            info=directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or directory.is_symlink() or info.st_uid!=0 or info.st_mode&0o022: raise RuntimeError('Untrusted legacy runtime directory')
            actual[relative]={'directory':True,'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid}
            for child in sorted(directory.iterdir()):
                name=child.name if relative=='.' else relative+'/'+child.name
                legacy._relative(name)
                if len(actual)>=12000: raise RuntimeError('Legacy runtime tree exceeds limit')
                metadata=child.lstat()
                if stat.S_ISDIR(metadata.st_mode) and not child.is_symlink(): visit(child,name)
                elif stat.S_ISREG(metadata.st_mode):
                    value=_fingerprint(root,child.relative_to(root).as_posix(),store=store)
                    total+=value['size']
                    if total>1024**3: raise RuntimeError('Legacy runtime tree exceeds byte limit')
                    files[name]=value
                    actual[name]={'directory':False,**{key:value[key] for key in ('mode','uid','gid')}}
                else: raise RuntimeError('Unsafe legacy runtime tree member')
        visit(root/prefix,'.')
        if actual!=expected: raise RuntimeError('Legacy runtime tree metadata differs')
        return files
    def inline(value):
        if not value['exists']: return value
        return {key:value[key] for key in ('exists','mode','uid','gid')}|{'data':state_io.DataDigest(value['sha256'],value['size'])}
    for component in sorted(set(names)&adoption._RUNTIMES.keys()):
        prefix=adoption._RUNTIMES[component]; state=(Path(prefix).parent/'.installer-state').as_posix(); journal=state+'/state.json'
        if not os.path.lexists(root/journal): continue
        with protected_file(root,journal,private=True,maximum=MAX_RECEIPT) as stream: raw=stream.read(MAX_RECEIPT+1)
        if len(raw)>MAX_RECEIPT: raise RuntimeError('Legacy runtime journal exceeds metadata limit')
        record=json.loads(raw,object_pairs_hook=legacy._pairs)
        if record.get('destination')!=prefix: raise RuntimeError('Legacy runtime destination differs')
        if record.get('phase')=='rolled_back': continue
        if record.get('phase')!='installed' or type(record.get('original_exists')) is not bool: raise RuntimeError('Recover incomplete legacy runtime')
        evidence.append({'path':journal,'role':'installer-runtime-journal','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        installed=tree(state+'/installed',record.get('installed_metadata')); current=tree(prefix,record.get('installed_metadata'))
        if installed!=current: raise RuntimeError('Legacy runtime bytes changed')
        backups=[state+'/'+name for name in ('original-reference','original') if os.path.lexists(root/state/name)]
        original={}
        if record['original_exists']:
            if not backups: raise RuntimeError('Missing legacy runtime originals')
            for backup in backups:
                candidate=tree(backup,record.get('original_metadata'))
                if original and candidate!=original: raise RuntimeError('Legacy runtime originals disagree')
                original=candidate
                for relative,value in candidate.items(): evidence.append({'path':backup+'/'+relative,'role':'installer-runtime-original','size':value['size'],'sha256':value['sha256']})
            if set(original)-set(installed): raise RuntimeError('Restore legacy runtime with original-only files before adoption')
        elif backups or record.get('original_metadata') is not None: raise RuntimeError('Unexpected legacy runtime originals')
        for name,after in installed.items(): add(prefix+'/'+name,component,inline(original.get(name,{'exists':False})),inline(after))


def export_bundle(root,slot,key,*,legacy_slot,destination):
    """Create-only private bundle; receipt publication is last and atomic."""
    if os.name!='posix' or os.geteuid()!=0: raise RuntimeError('Privileged Linux export required')
    destination=Path(destination)
    parent=legacy._private_directory(destination)
    blob_name=destination.name+'.blobs'; directory=None; created=False; store=None; publishing=False
    try:
        try: os.stat(destination.name,dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError: pass
        else: raise RuntimeError('Adoption destination already exists')
        os.mkdir(blob_name,0o700,dir_fd=parent); created=True
        directory=os.open(blob_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        os.fchmod(directory,0o700)
        store=BlobStore(directory)
        receipt=collect(root,slot,key,legacy_slot=legacy_slot,store=store,blob_directory=blob_name)
        raw=(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
        if len(raw)>MAX_RECEIPT: raise RuntimeError('Adoption receipt metadata exceeds limit')
        os.fsync(directory); os.fsync(parent)
        # A late link/fsync failure can leave the complete receipt visible.
        # Preserve its CAS once publication starts; uncertain orphans are safe
        # private evidence, while deleting referenced blobs would break it.
        publishing=True
        legacy._write_receipt(destination,raw)
        created=False
        return receipt,raw
    finally:
        if created and not publishing and store is not None: store.cleanup()
        if directory is not None: os.close(directory)
        if created and not publishing: os.rmdir(blob_name,dir_fd=parent)
        os.close(parent)
