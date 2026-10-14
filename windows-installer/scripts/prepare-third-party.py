"""Cache selected Decky plugins and reproducibly build the TabMaster compatibility archive."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import io
root=Path(__file__).resolve().parents[1]
opener=urllib.request.build_opener(); opener.addheaders=[('User-Agent','OXP3-SteamOS-Installer/0.1')]; urllib.request.install_opener(opener)
names={'tabmaster':'TabMaster','css-loader':'CSS Loader','autoflatpaks':'AutoFlatpaks','deck-settings':'Deck Settings','hltb':'HLTB for Deck','animation-changer':'Animation Changer'}
pinned={
    'hltb': {
        'version':'2.0.12',
        'url':'https://github.com/morwy/hltb-for-deck/releases/download/v2.0.12/hltb-for-deck.zip',
        'archive':'hltb-2.0.12.zip',
        'source':'upstream-prebuilt-release',
    },
    'tabmaster': {
        'version':'2.15.1+oxp3.1',
        'url':'https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/e08333859a32b0c177b8e9a7959c5eeeafe38f946578f7f1d161c721f0e05da5.zip',
        'archive':'tabmaster-2.15.1+oxp3.1.zip',
        'source':'local-compatibility-patch',
        'upstream_version':'2.15.1',
        'upstream_url':'https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/e08333859a32b0c177b8e9a7959c5eeeafe38f946578f7f1d161c721f0e05da5.zip',
        'upstream_archive':'tabmaster-2.15.1.zip',
    },
}
with urllib.request.urlopen('https://plugins.deckbrew.xyz/plugins',timeout=30) as response: store=json.load(response)
records=[]
for identifier,name in names.items():
    if identifier in pinned:
        release=pinned[identifier]
        version,url,archive_name,source=(release[key] for key in ('version','url','archive','source'))
        provenance={key:release[key] for key in ('upstream_version','upstream_url','upstream_archive') if key in release}
    else:
        matches=[x for x in store if x['name']==name]
        if len(matches)!=1 or not matches[0]['versions']: raise RuntimeError('Official store lacks '+name)
        release=matches[0]['versions'][0]
        version=release['name']
        url=release.get('artifact') or 'https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/'+release['hash']+'.zip'
        archive_name=identifier+'-'+version+'.zip'
        source='official-store'
        provenance={}
    if not url.startswith('https://'): raise RuntimeError('HTTPS resource required')
    with urllib.request.urlopen(url,timeout=45) as response: data=response.read(128*1024*1024+1)
    if len(data)>128*1024*1024: raise RuntimeError('Oversized plugin')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        metadata=[x for x in archive.namelist() if x.endswith('/plugin.json')]
        if len(metadata)!=1 or json.loads(archive.read(metadata[0]))['name']!=name: raise RuntimeError('Unexpected plugin identity')
    folder=root/'cache/plugins'/identifier; folder.mkdir(parents=True,exist_ok=True)
    target=folder/archive_name
    if identifier=='tabmaster':
        with tempfile.TemporaryDirectory(prefix='oxp3-tabmaster-') as temporary:
            upstream=Path(temporary)/provenance['upstream_archive']
            upstream.write_bytes(data)
            subprocess.run([
                sys.executable,str(root/'scripts/patch-tabmaster.py'),
                '--source',str(upstream),'--destination',str(target),
                '--patch-directory',str(root/'components/tabmaster-compat'),
            ],check=True)
        with zipfile.ZipFile(target) as archive:
            packages=[x for x in archive.namelist() if x.endswith('/package.json')]
            runtimes=[x for x in archive.namelist() if x.endswith('/dist/index.js')]
            if len(packages)!=1 or len(runtimes)!=1: raise RuntimeError('Incomplete patched TabMaster archive')
            if json.loads(archive.read(packages[0]))['version']!=version: raise RuntimeError('Unexpected patched TabMaster version')
    elif identifier in pinned or not target.exists():
        target.write_bytes(data)
    records.append({'id':identifier,'name':name,'version':version,'url':url,'source':source,'archive':target.name,**provenance})
    print(name,version,target.stat().st_size)
(root/'cache/plugins/third-party.json').write_text(json.dumps(records,indent=2)+'\n')
