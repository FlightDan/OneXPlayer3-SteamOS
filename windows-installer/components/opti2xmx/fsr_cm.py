"""FSR PRE resource-table correction, chained after the pinned CM compiler.

Copied into each newly enabled game's state so plugin replacement cannot change
an existing launcher's compiler. XeSS and all other kernels pass unchanged.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

PRE_HASH = '46fe6c9997eb76ed'


def correct_pre(path):
    path = Path(path)
    if not path.name.startswith(PRE_HASH + '_'):
        return False
    data = path.read_bytes()
    if (len(data) < 472 or data[:4] != b'CMK2'
            or struct.unpack_from('<4I', data, 168) != (0xffffffff, 0, 0, 11)
            or struct.unpack_from('<11I', data, 280) != tuple(range(11))
            or struct.unpack_from('<11I', data, 376) != (0,) * 11):
        raise RuntimeError('FSR PRE compiler metadata differs from the verified profile')
    fixed = bytearray(data)
    struct.pack_into('<3I', fixed, 168, 1, 2, 4)
    temporary = path.with_name(path.name + '.fsr-fixed')
    with temporary.open('xb') as output:
        output.write(fixed)
    temporary.replace(path)
    record = {'profile': 1, 'kernel': PRE_HASH, 'heap_set': 1, 'binding': 2, 'table_pc_base': 4,
              'before_sha256': hashlib.sha256(data).hexdigest(),
              'after_sha256': hashlib.sha256(fixed).hexdigest()}
    path.with_suffix(path.suffix + '.fsr-profile.json').write_text(json.dumps(record, indent=2))
    return True


def main(argv):
    if len(argv) != 4:
        raise ValueError('Expected compiler helper, SPIR-V, options and output paths')
    helper, spv, options, output = argv
    result = subprocess.run(['bash', helper, spv, options, output])
    if result.returncode:
        return result.returncode
    correct_pre(output)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        print('Opti2XMX FSR compiler: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
