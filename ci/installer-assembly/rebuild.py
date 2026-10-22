"""Recreate a reviewed immutable release ZIP from a pinned public base."""
from pathlib import Path
import hashlib,json,os,urllib.parse,urllib.request,zlib

root=Path(__file__).resolve().parent
m=json.loads((root/'manifest.json').read_text())
assert m['schema']==1 and m['source_commit']=='e181a9055e1c94e8d758e2b9575f60fb5fc5109c'
assert m['target_name']=='oxp3-steamos-installer-1.0.6-20261022-220437.zip'
assert m['target_size']==555684389 and m['target_sha256']=='d8bee8bad14f4cd136c814ebcaa3299fa59202b6cdc6d26ec9c52af0e055f4d4'
assert m['base_sha256']=='b25254efff45caaf864d3e89d72b50dd2ff3a1af0678c075bbcf023ca8e2a3a1' and m['base_size']==555682046
assert m['base_url']=='https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/v1.0.6%2Binstaller.20261022.024839/oxp3-steamos-installer-1.0.6-20261022-024839.zip'
class Redirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  p=urllib.parse.urlsplit(newurl)
  assert p.scheme=='https' and p.hostname in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com') and not p.username and not p.password
  return super().redirect_request(req,fp,code,msg,headers,newurl)
base=root/'base.zip';hasher=hashlib.sha256();total=0
with urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect()).open(m['base_url'],timeout=60) as incoming,base.open('xb') as output:
 while chunk:=incoming.read(1024*1024):
  total+=len(chunk);assert total<=m['base_size'];hasher.update(chunk);output.write(chunk)
assert total==m['base_size'] and hasher.hexdigest()==m['base_sha256']
compressed=(root/'literal.zlib').read_bytes();assert hashlib.sha256(compressed).hexdigest()==m['compressed_sha256']
assert len(compressed)<2*1024*1024 and m['literal_size']<2*1024*1024
decoder=zlib.decompressobj();literal=decoder.decompress(compressed,m['literal_size']+1)
assert decoder.eof and not decoder.unused_data and len(literal)==m['literal_size'] and hashlib.sha256(literal).hexdigest()==m['literal_sha256']
hasher=hashlib.sha256();total=0;target=root/m['target_name']
with base.open('rb') as source,target.open('xb') as output:
 for kind,offset,size in m['parts']:
  assert kind in (0,1) and isinstance(offset,int) and isinstance(size,int) and offset>=0 and size>0
  assert offset+size<=(m['base_size'] if kind==0 else len(literal))
  if kind==0:source.seek(offset)
  while size:
   count=min(size,1024*1024)
   data=source.read(count) if kind==0 else literal[offset:offset+count]
   assert len(data)==count;total+=count;assert total<=m['target_size'];hasher.update(data);output.write(data);offset+=count;size-=count
assert total==m['target_size'] and hasher.hexdigest()==m['target_sha256']
print('EXACT_REVIEWED_ZIP='+hasher.hexdigest())
