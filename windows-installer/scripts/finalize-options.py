from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
p=root/'components/options.json'; data=json.loads(p.read_text(encoding='utf-8-sig'))
waydroid=next((x for x in data['repairs'] if x['id']=='waydroid'),None)
if waydroid:
    data['repairs'].remove(waydroid); data['plugins'].append(waydroid)
if not any(x['id']=='gamescope-env' for x in data['repairs']):
    data['repairs'].insert(0,{'id':'gamescope-env','zh':'游戏模式启动环境隔离 · 修复桌面切回黑屏','en':'Game mode environment isolation · fix black screen after desktop','default':True,'dependencies':[]})
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# The new archive must contain the runtime assets and all selected plugin caches.
p=root/'scripts/make-development-package.ps1'; s=p.read_text(encoding='utf-8-sig')
anchor="Copy-PackageTree (Join-Path $projectRoot 'components') 'components'"
if "'cache/integration' 'cache/integration'" not in s:
    s=s.replace(anchor,anchor+"\nCopy-PackageTree (Join-Path $projectRoot 'cache/integration') 'cache/integration'\nCopy-PackageTree (Join-Path $projectRoot 'cache/plugins') 'cache/plugins'\nforeach ($name in 'integration.sh','integration-image.py','integration-check.sh') { Copy-Item -LiteralPath (Join-Path $projectRoot \"guest/$name\") -Destination (Join-Path $destination \"guest/$name\") }")
p.write_text(s,encoding='utf-8')
