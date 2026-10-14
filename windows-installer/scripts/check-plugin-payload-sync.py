"""Check maintained bilingual plugin bytes against what the installer stages."""
import json
from pathlib import Path
import zipfile
import tarfile

root=Path(__file__).resolve().parents[1]
research=root.parent/'research'
manifest=json.loads((root/'cache/integration/manifest.json').read_text())
checks=[]
for component,folder,source in (
    ('oxp3-cpu','OXP3-CPU','overlay/cpu-plugin-index.js'),
    ('oxp3-fan','OXP3-Fan','overlay/fan-plugin-index.js'),
    ('charging','OXP3-battery','charging/battery-plugin-index.js'),
    ('opti2xmx','opti2xmx','xess/decky/dist/index.js'),
):
    entry=next(x for x in manifest[component]['files'] if x['target']==f'home/deck/homebrew/plugins/{folder}/dist/index.js')
    assert (root/'cache/integration'/entry['source']).read_bytes()==(research/source).read_bytes(), component
    checks.append({'component':component,'frontend_matches':True})
for name in ('main.py','manager.py','opti.py','plugin.json','package.json','README.md'):
    entry=next(x for x in manifest['opti2xmx']['files'] if x['target'].endswith('/'+name))
    assert (root/'cache/integration'/entry['source']).read_bytes()==(research/'xess/decky'/name).read_bytes(),name
entry=next(x for x in manifest['opti2xmx']['files'] if x['target'].endswith('/per_game.py'))
assert (root/'cache/integration'/entry['source']).read_bytes()==(research/'xess/per_game.py').read_bytes()
profile=json.loads((root/'cache/components/oxp3-controls/profile.json').read_text())
with zipfile.ZipFile(root/'cache/components/oxp3-controls'/profile['archive']) as z:
    for source in ('overlay/cpu-plugin-index.js','overlay/fan-plugin-index.js','charging/battery-plugin-index.js'):
        assert z.read(source)==(research/source).read_bytes(),source
with tarfile.open(root/'cache/integration/opti2xmx/runtime.tar.gz') as runtime:
    entries=runtime.getmembers()
    assert runtime.getmember('runtime/tools/cm-compile.sh').mode&0o111
    assert any(x.name.startswith('runtime/igc/neo/bin/ocloc') and x.mode&0o111 for x in entries)
    assert not any('kernels' in Path(x.name).parts for x in entries)
result={'plugins':checks,'opti2xmx_version':json.loads((research/'xess/decky/package.json').read_text())['version'],'controls_archive_matches':True,'compiler_archive_permissions':True,'contains_generated_kernels':False,'device_deployment_checked':False}
(root/'logs/plugin-payload-sync.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
