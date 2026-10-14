"""Build the standalone Decky ZIP from an explicit file list."""
import json
from pathlib import Path
import zipfile

base = Path(__file__).resolve().parent
version = json.loads((base / 'package.json').read_text(encoding='utf-8'))['version']
output = base / f'opti2xmx-{version}.zip'
files = ['plugin.json', 'package.json', 'main.py', 'manager.py', 'opti.py', 'download_progress.py',
         'per_game.py', 'dist/index.js', 'README.md', 'README.zh-CN.md',
         'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/RUNTIME.md',
         'assets/screenshots/main-en.png', 'assets/screenshots/advanced-en.png']
for file in files:
    if not (base / file).is_file():
        raise SystemExit('Missing build file: ' + file)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        archive.write(base / file, 'opti2xmx/' + file)
print(output)
