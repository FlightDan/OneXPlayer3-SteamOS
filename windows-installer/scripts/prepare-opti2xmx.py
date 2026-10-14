"""Stage the accepted plugin and a strict public-runtime allowlist, no game state."""
from pathlib import Path, PurePosixPath
import io, json, posixpath, tarfile, shutil, struct

root=Path(__file__).resolve().parents[1]
research=root.parent/'research'
out=root/'cache/integration/opti2xmx'; out.mkdir(parents=True,exist_ok=True)
sr=(root/'cache/opti2xmx/libxess.dll').read_bytes()
at=sr.find(b'\xbd\x04\xef\xfe\x00\x00\x01\x00')
assert sr[:2]==b'MZ' and at>=0
_,_,ms,ls=struct.unpack_from('<4I',sr,at)
assert (ms>>16,ms&65535,ls>>16,ls&65535)==(2,0,2,68)
with tarfile.open(research/'cache/xess-private-payload.tar.gz') as source, tarfile.open(out/'runtime.tar.gz','w:gz') as target:
    members={m.name:m for m in source.getmembers()}
    base='xess-xmx-linux-20261005/'
    def add(name,data,mode):
        item=tarfile.TarInfo(name); item.size=len(data); item.mode=mode; item.mtime=0
        target.addfile(item,io.BytesIO(data))
    for name,item in members.items():
        if not name.startswith(base) or item.isdir():continue
        rel=name[len(base):]
        allowed=rel in ('igdext64.dll','lib/libvulkan_intel.so','tools/cm-compile.sh','tools/cmk_pack.py','LICENSE','THIRD_PARTY.md') or rel.startswith(('igc/igc/local/lib/','igc/neo/bin/','igc/neo/lib/','igc/neo/share/doc/','patches/'))
        if not allowed:continue
        assert not PurePosixPath(rel).is_absolute() and '..' not in PurePosixPath(rel).parts
        actual=item; seen=set()
        while actual.issym():
            assert actual.name not in seen and not actual.linkname.startswith('/')
            seen.add(actual.name)
            destination=posixpath.normpath(posixpath.join(posixpath.dirname(actual.name),actual.linkname))
            assert destination.startswith(base)
            actual=members[destination]
        assert actual.isfile()
        add('runtime/'+rel,source.extractfile(actual).read(),0o755 if actual.mode&0o111 or rel=='tools/cm-compile.sh' else 0o644)
    add('sdk/libxess.dll',sr,0o644)
    add('sdk/XeSS-LICENSE.txt',(root/'cache/opti2xmx/XeSS-LICENSE.txt').read_bytes(),0o644)
sources=root/'cache/integration/sources/opti2xmx';sources.mkdir(parents=True,exist_ok=True)
for name in ('README.md','main.py','manager.py','opti.py','package.json','plugin.json','package_plugin.py','test_manager.py','test_opti.py','test_frontend.mjs','src/index.tsx','src/i18n.ts','rollup.config.js','tsconfig.json','pnpm-lock.yaml'):
    dest=sources/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(research/'xess/decky'/name,dest)
for name in ('per_game.py','test_per_game.py'):
    shutil.copyfile(research/'xess'/name,sources/name)
version=json.loads((research/'xess/decky/package.json').read_text())['version']
(sources/'PROVENANCE.json').write_text(json.dumps({'plugin':'Opti2XMX '+version,'runtime':'https://github.com/HHHHanasak1/xess-xmx-linux/releases/tag/20261005','igc':'2.10.10','ocloc':'25.18.33578.6','sr':'https://github.com/intel/xess/blob/v3.0.2/bin/libxess.dll','sr_version':'2.0.2.68','contains_game_state':False,'contains_generated_kernels':False},indent=2)+'\n')
print(json.dumps({'archive':str(out/'runtime.tar.gz'),'bytes':(out/'runtime.tar.gz').stat().st_size}))
