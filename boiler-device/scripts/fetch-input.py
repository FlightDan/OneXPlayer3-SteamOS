"""Download only the pinned already-public model input; verify before accepting."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
lock = json.loads((Path(__file__).resolve().parents[1]/'upstream-lock.json').read_text())['asset']
if args.output.exists():
    raise SystemExit('Input destination already exists')
args.output.parent.mkdir(parents=True, exist_ok=True)
temporary = args.output.with_name(args.output.name+'.partial')
digest, size = hashlib.sha256(), 0
with urllib.request.urlopen(lock['url'], timeout=60) as response, temporary.open('xb') as target:
    while block := response.read(1024*1024):
        size += len(block)
        if size > lock['size']:
            raise SystemExit('Public input exceeds locked size; partial input retained for inspection')
        digest.update(block)
        target.write(block)
if size != lock['size'] or digest.hexdigest() != lock['sha256']:
    raise SystemExit('Public input hash mismatch; partial input retained for inspection')
temporary.replace(args.output)
print(json.dumps({'size': size, 'sha256': digest.hexdigest()}))
