"""Build the standalone Decky ZIP from an explicit file list."""
import json
from pathlib import Path
import zipfile

base = Path(__file__).resolve().parent
version = json.loads((base / 'package.json').read_text(encoding='utf-8'))['version']
output = base / f'opti2xmx-{version}.zip'
files = ['plugin.json', 'package.json', 'main.py', 'manager.py', 'opti.py', 'download_progress.py', 'runtime_setup.py', 'runtime-source.json',
         'per_game.py', 'dist/index.js', 'README.md', 'README.zh-CN.md',
         'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/RUNTIME.md', 'docs/FRAME_GENERATION.md']
files += ['fsr.py', 'fsr_cm.py', 'fsr-source.json', 'docs/FSR_XMX.md', 'fsr_compat/manifest.json']
compat = json.loads((base / 'fsr_compat/manifest.json').read_text(encoding='utf-8'))
import hashlib
for row in compat['files'] + compat['distribution_files']:
    relative = Path(row['path'])
    if relative.is_absolute() or '..' in relative.parts or '\\' in row['path']:
        raise SystemExit('Unsafe compatibility member: ' + row['path'])
    path = base / 'fsr_compat' / relative
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != row['size']
            or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
        raise SystemExit('Compatibility member checksum mismatch: ' + row['path'])
    files.append('fsr_compat/' + row['path'])
for file in files:
    if not (base / file).is_file():
        raise SystemExit('Missing build file: ' + file)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        archive.write(base / file, 'opti2xmx/' + file)
print(output)
