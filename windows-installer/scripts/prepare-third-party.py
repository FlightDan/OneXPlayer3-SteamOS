"""Cache selected official-store releases; record the exact resolved versions."""
from pathlib import Path
import json
import urllib.request
import zipfile
import io
root=Path(__file__).resolve().parents[1]
opener=urllib.request.build_opener(); opener.addheaders=[('User-Agent','OXP3-SteamOS-Installer/0.1')]; urllib.request.install_opener(opener)
names={'tabmaster':'TabMaster','css-loader':'CSS Loader','autoflatpaks':'AutoFlatpaks','deck-settings':'Deck Settings','hltb':'HLTB for Deck','animation-changer':'Animation Changer'}
with urllib.request.urlopen('https://plugins.deckbrew.xyz/plugins',timeout=30) as response: store=json.load(response)
records=[]
for identifier,name in names.items():
    matches=[x for x in store if x['name']==name]
    if len(matches)!=1 or not matches[0]['versions']: raise RuntimeError('Official store lacks '+name)
    release=matches[0]['versions'][0]
    url=release.get('artifact') or 'https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/'+release['hash']+'.zip'
    if not url.startswith('https://'): raise RuntimeError('HTTPS resource required')
    with urllib.request.urlopen(url,timeout=45) as response: data=response.read(128*1024*1024+1)
    if len(data)>128*1024*1024: raise RuntimeError('Oversized plugin')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        metadata=[x for x in archive.namelist() if x.endswith('/plugin.json')]
        if len(metadata)!=1 or json.loads(archive.read(metadata[0]))['name']!=name: raise RuntimeError('Unexpected plugin identity')
    folder=root/'cache/plugins'/identifier; folder.mkdir(parents=True,exist_ok=True)
    target=folder/(identifier+'-'+release['name']+'.zip')
    if not target.exists(): target.write_bytes(data)
    records.append({'id':identifier,'name':name,'version':release['name'],'url':url,'archive':target.name})
    print(name,release['name'],len(data))
(root/'cache/plugins/third-party.json').write_text(json.dumps(records,indent=2)+'\n')
