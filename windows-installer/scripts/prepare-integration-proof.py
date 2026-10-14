from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
catalog=json.loads((root/'components/options.json').read_text(encoding='utf-8'))
options={'schema':1,'repairs':[x['id'] for x in catalog['repairs'] if x['default']],'plugins':[x['id'] for x in catalog['plugins'] if x['default']],'installer_language':'en-US','kde_language':'zh_CN'}
target=root/'work/integration-acceptance-20261013/options.json'
target.write_text(json.dumps(options,indent=2)+'\n',encoding='utf-8')
print(target)
