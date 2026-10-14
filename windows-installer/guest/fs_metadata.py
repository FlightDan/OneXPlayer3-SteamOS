"""Read blkid's shared default format; BusyBox does not implement util-linux selectors."""
import re
import shlex
import subprocess


def parse_output(output, device=None):
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines: return {}
    if len(lines) != 1 or ': ' not in lines[0]: raise RuntimeError('Ambiguous filesystem probe output')
    node, fields = lines[0].split(': ', 1)
    if not node.startswith('/dev/') or (device is not None and node != device):
        raise RuntimeError('Filesystem probe returned another device')
    result = {}
    for token in shlex.split(fields):
        if '=' not in token: raise RuntimeError('Invalid filesystem probe field')
        key, value = token.split('=', 1)
        if not re.fullmatch(r'[A-Z0-9_]+', key) or key in result:
            raise RuntimeError('Duplicate or invalid filesystem probe field')
        result[key] = value
    return result


def normalize_uuid(value, device=None):
    if not isinstance(value, str): raise RuntimeError('Invalid filesystem UUID record')
    if value.startswith('/dev/'):
        value = parse_output(value, device).get('UUID', '')
    if not re.fullmatch(r'[0-9A-Fa-f-]{4,36}', value):
        raise RuntimeError('Filesystem UUID is not a supported identifier')
    return value.lower()


def probe(device, field='TYPE'):
    if field not in ('TYPE', 'UUID', 'LABEL'): raise ValueError('Unsupported filesystem metadata field')
    result = subprocess.run(['blkid', device], text=True, capture_output=True)
    if result.returncode not in (0, 2): raise RuntimeError('Filesystem metadata probe failed: ' + device)
    value = parse_output(result.stdout, device).get(field, '')
    return normalize_uuid(value) if field == 'UUID' and value else value


if __name__ == '__main__':
    import sys
    print(probe(sys.argv[1], sys.argv[2]))
