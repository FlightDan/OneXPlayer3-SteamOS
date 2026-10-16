"""Check maintained bilingual plugin bytes against what the installer stages."""
import json
from pathlib import Path
import zipfile
import tarfile
from opti_payload import read_plugin_tree, FILES, RUNTIME_SHA256, RUNTIME_SIZE
import hashlib

root=Path(__file__).resolve().parents[1]
research=root.parent/'research'
manifest=json.loads((root/'cache/integration/manifest.json').read_text())
opti=root/'components/opti2xmx'
if not opti.is_dir():opti=research/'xess/decky'
checks=[]
for component,folder,source in (
    ('oxp3-cpu','OXP3-CPU','overlay/cpu-plugin-index.js'),
    ('oxp3-fan','OXP3-Fan','overlay/fan-plugin-index.js'),
    ('charging','OXP3-battery','charging/battery-plugin-index.js'),
    ('oxp3-light','OXP3-Light','light/dist/index.js'),
):
    entry=next(x for x in manifest[component]['files'] if x['target']==f'home/deck/homebrew/plugins/{folder}/dist/index.js')
    maintained=(root/'components/controls/cpu/cpu-plugin-index.js') if component=='oxp3-cpu' else (root/'components/light/dist/index.js') if component=='oxp3-light' else research/source
    assert (root/'cache/integration'/entry['source']).read_bytes()==maintained.read_bytes(), component
    checks.append({'component':component,'frontend_matches':True})
for name in ('main.py','light_control.py','plugin.json','package.json','dist/index.js',
             'LICENSE','LICENSE-HHD','LICENSE-HueSync','THIRD_PARTY_NOTICES.md','README.md'):
    entry=next(x for x in manifest['oxp3-light']['files'] if x['target']==f'home/deck/homebrew/plugins/OXP3-Light/{name}')
    assert (root/'cache/integration'/entry['source']).read_bytes()==(root/'components/light'/name).read_bytes(),name
records=read_plugin_tree(opti)
for name in FILES:
    entry=next(x for x in manifest['opti2xmx']['files'] if x['target']=='home/deck/homebrew/plugins/opti2xmx/'+name)
    assert (root/'cache/integration'/entry['source']).read_bytes()==records[name],name
runtime_path=root/'cache/integration/opti2xmx/runtime.tar.gz'
assert runtime_path.stat().st_size==RUNTIME_SIZE
with runtime_path.open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()==RUNTIME_SHA256
checks.append({'component':'opti2xmx','frontend_matches':True,'all_release_members_match':True})
profile=json.loads((root/'cache/components/oxp3-controls/profile.json').read_text())
with zipfile.ZipFile(root/'cache/components/oxp3-controls'/profile['archive']) as z:
    for source in ('overlay/cpu-plugin-index.js','overlay/fan-plugin-index.js','charging/battery-plugin-index.js'):
        maintained=(root/'components/controls/cpu/cpu-plugin-index.js') if source=='overlay/cpu-plugin-index.js' else research/source
        assert z.read(source)==maintained.read_bytes(),source
with tarfile.open(root/'cache/integration/opti2xmx/runtime.tar.gz') as runtime:
    entries=runtime.getmembers()
    assert runtime.getmember('runtime/tools/cm-compile.sh').mode&0o111
    assert any(x.name.startswith('runtime/igc/neo/bin/ocloc') and x.mode&0o111 for x in entries)
    assert not any('kernels' in Path(x.name).parts for x in entries)
result={'plugins':checks,'opti2xmx_version':json.loads(records['package.json'])['version'],'runtime_sha256':RUNTIME_SHA256,'controls_archive_matches':True,'compiler_archive_permissions':True,'contains_generated_kernels':False,'device_deployment_checked':False}
(root/'logs/plugin-payload-sync.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
