"""Conservative read-only ext4 allocation plans for the managed installation VM.

Only filesystem-free blocks may be omitted. Allocated zero blocks, journal,
inode tables (including uninitialized tables), and every backup are retained.
libext2fs, through the pinned dumpe2fs executable, interprets allocation bitmaps;
this module deliberately does not decode their on-disk representation.
"""
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

SCHEMA = 1
TOOL_VERSION = '1.47.3'
MAX_RANGES = 8192
MAX_JSON_BYTES = 1024 * 1024
SUPPORTED_FEATURES = frozenset('has_journal ext_attr resize_inode dir_index filetype extent 64bit flex_bg sparse_super large_file huge_file dir_nlink extra_isize metadata_csum metadata_csum_seed orphan_file uninit_bg casefold'.split())
HOME_TYPE = '933ac7e1-2eb4-4f13-b844-0e14e2aef915'


def canonical_json(plan):
    return json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _require(condition, message):
    if not condition:
        raise RuntimeError('Unsafe home copy plan: ' + message)


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError('Unsafe home copy plan: invalid UUID') from exc
    _require(parsed.int != 0 and str(parsed) == value.lower(), 'noncanonical or zero UUID')
    return str(parsed)


def _integer(value, description, minimum=0):
    _require(isinstance(value, str) and re.fullmatch(r'[0-9]+', value) is not None, 'invalid ' + description)
    number = int(value)
    _require(minimum <= number <= (1 << 63) - 1, 'out-of-range ' + description)
    return number


def _ranges(value, low, high):
    result = []
    if not value:
        return result
    for part in value.split(', '):
        match = re.fullmatch(r'([0-9]+)(?:-([0-9]+))?', part)
        _require(match is not None, 'malformed free-block range')
        start = int(match[1])
        end = int(match[2] or match[1])
        _require(low <= start <= end <= high, 'free-block range outside group')
        _require(not result or start > result[-1][1], 'overlapping or unsorted free blocks')
        result.append((start, end))
    return result


def _has_super(group, sparse):
    if not sparse or group in (0, 1):
        return True
    for base in (3, 5, 7):
        n = group
        while n > 1 and n % base == 0:
            n //= base
        if n == 1:
            return True
    return False


def parse_dump(output, partition_id, partition_offset, partition_size):
    """Parse successful LC_ALL=C dumpe2fs output, after e2fsck -fn passed.

    This pure entry point is also used by tests; production callers use generate,
    which additionally enforces block-device read-only and unmounted state.
    """
    _require(type(partition_offset) is int and partition_offset >= 0 and partition_offset % 512 == 0, 'invalid partition offset')
    _require(type(partition_size) is int and 0 < partition_size <= (1 << 63) - 1 and partition_size % 512 == 0, 'invalid partition size')
    _require(partition_offset + partition_size <= (1 << 63) - 1, 'partition end overflow')
    partition_id = _uuid(partition_id)
    lines = output.splitlines()
    first = next((i for i, line in enumerate(lines) if re.match(r'Group [0-9]+:', line)), len(lines))
    header = {}
    for line in lines[:first]:
        if line and not line[0].isspace() and ':' in line:
            key, value = line.split(':', 1)
            _require(key not in header, 'duplicate filesystem header ' + key)
            header[key] = value.strip()
    def number(key, minimum=0):
        _require(key in header, 'missing filesystem header ' + key)
        return _integer(header[key], key, minimum)
    _require(header.get('Filesystem magic number') == '0xEF53', 'not an ext filesystem')
    _require(header.get('Filesystem state') == 'clean', 'filesystem is not clean')
    _require(header.get('Filesystem revision #', '').startswith('1 '), 'unsupported filesystem revision')
    fs_uuid = _uuid(header.get('Filesystem UUID'))
    _require('Filesystem features' in header, 'missing filesystem features')
    features = header['Filesystem features'].split()
    _require(len(features) == len(set(features)) and all(re.fullmatch(r'[a-z0-9_]+', f) for f in features), 'malformed filesystem features')
    _require('needs_recovery' not in features, 'journal recovery required')
    _require('journal_dev' not in features and 'Journal device' not in header and 'Journal UUID' not in header, 'external journal is not a standalone home filesystem')
    block_size = number('Block size', 1024)
    _require(block_size in (1024, 2048, 4096, 8192, 16384, 32768, 65536), 'invalid block size')
    block_count = number('Block count', 1)
    free_count = number('Free blocks')
    _require(free_count <= block_count, 'invalid filesystem free count')
    _require(block_count * block_size == partition_size, 'filesystem and partition sizes differ')
    plan = dict(schema=SCHEMA, mode='ext4-used-v1', partition_id=partition_id,
                partition_offset=partition_offset, partition_size=partition_size,
                fs_uuid=fs_uuid, block_size=block_size, block_count=block_count,
                used_bytes=0, features=sorted(features), ranges=[])
    def full(reason):
        plan.update(mode='full', fallback_reason=reason, used_bytes=partition_size, ranges=[[0, partition_size]])
        return plan
    unsupported = sorted(set(features) - SUPPORTED_FEATURES)
    if unsupported:
        return full('unsupported-features:' + ','.join(unsupported))
    if block_size != 4096:
        return full('unsupported-block-size')
    _require('has_journal' in features and 'extent' in features and 'filetype' in features, 'not the expected ext4 filesystem')
    _require(number('First block') == 0, 'unexpected first block')
    per_group = number('Blocks per group', 1)
    _require(per_group <= block_size * 8 and per_group % 8 == 0, 'invalid blocks per group')
    inode_size = number('Inode size', 128)
    _require(inode_size <= block_size and inode_size & (inode_size - 1) == 0, 'invalid inode size')
    inodes_per_group = number('Inodes per group', 1)
    _require(inodes_per_group <= block_size * 8, 'invalid inodes per group')
    inode_blocks = (inodes_per_group * inode_size + block_size - 1) // block_size
    group_count = (block_count + per_group - 1) // per_group
    _require(number('Inode count', 1) == inodes_per_group * group_count, 'inode count contradicts group geometry')
    desc_size = number('Group descriptor size', 32) if 'Group descriptor size' in header else 32
    _require(desc_size == (64 if '64bit' in features else 32), 'invalid group descriptor size')
    desc_blocks = (group_count * desc_size + block_size - 1) // block_size
    reserved_gdt = number('Reserved GDT blocks') if 'Reserved GDT blocks' in header else 0
    _require(not reserved_gdt or 'resize_inode' in features, 'reserved GDT without resize feature')
    groups = []
    for line in lines[first:]:
        if line.startswith('Group '):
            match = re.fullmatch(r'Group ([0-9]+): \(Blocks ([0-9]+)-([0-9]+)\)(?: csum 0x[0-9a-f]+)?(?: \[([A-Z_, ]+)\])?', line)
            _require(match is not None, 'malformed group header or checksum mismatch')
            index, start, end = map(int, match.group(1, 2, 3))
            _require(index == len(groups) and index < group_count, 'missing, duplicated or reordered group')
            _require(start == index * per_group and end == min(block_count, start + per_group) - 1, 'incorrect group bounds')
            flags = (match[4] or '').split(', ') if match[4] else []
            _require(len(flags) == len(set(flags)) and set(flags) <= {'INODE_UNINIT', 'BLOCK_UNINIT', 'ITABLE_ZEROED'}, 'unknown group flags')
            groups.append(dict(index=index, start=start, end=end, metadata=[], kinds=set()))
        elif line.strip():
            _require(bool(groups), 'group data without header')
            groups[-1].setdefault('lines', []).append(line.strip())
    _require(len(groups) == group_count, 'incomplete block group list')
    all_free = []
    metadata = []
    for group in groups:
        kinds = group['kinds']
        def add(kind, start, end=None):
            _require(kind not in kinds, 'duplicate metadata ' + kind)
            kinds.add(kind)
            end = start if end is None else end
            _require(0 <= start <= end < block_count, 'metadata outside filesystem')
            group['metadata'].append((start, end))
            return start, end
        for line in group.get('lines', []):
            match = re.fullmatch(r'(Primary|Backup) superblock at ([0-9]+), Group descriptors at ([0-9]+)-([0-9]+)', line)
            if match:
                _require(match[1] == ('Primary' if group['index'] == 0 else 'Backup'), 'incorrect superblock kind')
                start, _ = add('super', int(match[2]))
                a, b = add('gdt', int(match[3]), int(match[4]))
                _require(start == group['start'] and a == start + 1 and b - a + 1 == desc_blocks, 'incorrect superblock or GDT range')
                continue
            match = re.fullmatch(r'Reserved GDT blocks at ([0-9]+)-([0-9]+)', line)
            if match:
                a, b = add('reserved', int(match[1]), int(match[2]))
                _require(a == group['start'] + 1 + desc_blocks and b - a + 1 == reserved_gdt, 'incorrect reserved GDT range')
                continue
            match = re.fullmatch(r'(Block bitmap|Inode bitmap) at ([0-9]+)(?: \((?:\+[0-9]+|bg #[0-9]+ \+ [0-9]+)\))?(?:, csum 0x[0-9a-f]+)?', line)
            if match:
                add(match[1], int(match[2]))
                continue
            match = re.fullmatch(r'Inode table at ([0-9]+)-([0-9]+)(?: \((?:\+[0-9]+|bg #[0-9]+ \+ [0-9]+)\))?', line)
            if match:
                a, b = add('table', int(match[1]), int(match[2]))
                _require(b - a + 1 == inode_blocks, 'incomplete inode table')
                continue
            match = re.fullmatch(r'([0-9]+) free blocks, [0-9]+ free inodes, [0-9]+ directories(?:, [0-9]+ unused inodes)?', line)
            if match:
                _require('count' not in group, 'duplicate group free count')
                group['count'] = int(match[1])
                continue
            if line.startswith('Free blocks:'):
                _require('free' not in group, 'duplicate free block list')
                group['free'] = _ranges(line[len('Free blocks:'):].strip(), group['start'], group['end'])
                continue
            if line.startswith('Free inodes:'):
                _require('inodes' not in kinds, 'duplicate free inode list')
                kinds.add('inodes')
                _ranges(line[len('Free inodes:'):].strip(), group['index'] * inodes_per_group + 1, (group['index'] + 1) * inodes_per_group)
                continue
            _require(False, 'unrecognized block group data')
        expected = {'Block bitmap', 'Inode bitmap', 'table', 'inodes'}
        if _has_super(group['index'], 'sparse_super' in features):
            expected |= {'super', 'gdt'}
            if reserved_gdt:
                expected.add('reserved')
        _require(kinds == expected and 'free' in group and 'count' in group, 'missing or unexpected group metadata')
        if 'flex_bg' not in features:
            _require(all(group['start'] <= a <= b <= group['end'] for a, b in group['metadata']), 'metadata outside group without flex_bg')
        _require(sum(b - a + 1 for a, b in group['free']) == group['count'], 'group free count mismatch')
        all_free.extend(group['free'])
        metadata.extend(group['metadata'])
    _require(sum(b - a + 1 for a, b in all_free) == free_count, 'filesystem free count mismatch')
    # Metadata can live in another group when flex_bg is enabled. Compare against
    # the complete map, never only the group whose descriptor printed it.
    free_index = 0
    previous_end = -1
    for start, end in sorted(metadata):
        _require(start > previous_end, 'overlapping filesystem metadata')
        previous_end = end
        while free_index < len(all_free) and all_free[free_index][1] < start:
            free_index += 1
        _require(free_index == len(all_free) or all_free[free_index][0] > end, 'filesystem metadata marked free')
    cursor = 0
    for start, end in all_free:
        if cursor < start:
            plan['ranges'].append([cursor * block_size, (start - cursor) * block_size])
        cursor = end + 1
    if cursor < block_count:
        plan['ranges'].append([cursor * block_size, (block_count - cursor) * block_size])
    plan['used_bytes'] = sum(length for _, length in plan['ranges'])
    _require(plan['used_bytes'] == partition_size - free_count * block_size, 'used byte count mismatch')
    if len(plan['ranges']) > MAX_RANGES:
        return full('range-limit')
    if len(canonical_json(plan).encode('ascii')) > MAX_JSON_BYTES:
        return full('json-size-limit')
    return plan


def _run(*args):
    environment = dict(os.environ, LC_ALL='C', LANG='C')
    environment.pop('DUMPE2FS_IGNORE_80COL', None)
    result = subprocess.run(args, text=True, capture_output=True, env=environment, check=False)
    _require(result.returncode == 0, args[0] + ' failed: ' + (result.stderr + result.stdout)[-2048:])
    return result


def _check_version(tool):
    result = _run(tool, '-V')
    _require(re.search(r'^' + re.escape(tool) + r' ' + re.escape(TOOL_VERSION) + r'(?=\s|$)', result.stdout + result.stderr, re.MULTILINE) is not None, 'unexpected ' + tool + ' version')


def _assert_source(node):
    source = os.stat(node)
    _require(stat.S_ISBLK(source.st_mode), 'source must be a block device')
    major_minor = str(os.major(source.st_rdev)) + ':' + str(os.minor(source.st_rdev))
    _require(_run('blockdev', '--getro', node).stdout.strip() == '1', 'source must be read-only')
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        _require(len(fields) >= 6, 'malformed mount table')
        _require(fields[2] != major_minor, 'source is mounted')


def generate(node, partition_id, partition_offset, partition_size):
    """Build a plan from an unmounted, kernel-enforced read-only ext4 device."""
    _assert_source(node)
    _require(_run('blockdev', '--getsize64', node).stdout.strip() == str(partition_size), 'device size differs from GPT')
    _check_version('e2fsck')
    _check_version('dumpe2fs')
    _run('e2fsck', '-f', '-n', node)
    dump = _run('dumpe2fs', node)
    _require(re.fullmatch(r'dumpe2fs 1\.47\.3 \([^\n]+\)\s*', dump.stderr) is not None, 'dumpe2fs reported warnings or errors')
    plan = parse_dump(dump.stdout, partition_id, partition_offset, partition_size)
    _assert_source(node)
    return plan


def generate_managed_home():
    _require(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'QEMU', 'managed VM required')
    _require(Path('/sys/class/block/vdc/ro').read_text().strip() == '1', 'source disk must be read-only')
    table = json.loads(_run('sfdisk', '--json', '/dev/vdc').stdout)['partitiontable']
    _require(table.get('label') == 'gpt' and table.get('unit') == 'sectors', 'source must have sector-based GPT')
    sector_size = table.get('sectorsize')
    _require(type(sector_size) is int and sector_size in (512, 4096), 'invalid GPT sector size')
    homes = [p for p in table['partitions'] if p.get('name') == 'home']
    _require(len(homes) == 1, 'exactly one home partition required')
    home = homes[0]
    _require(home.get('type', '').lower() == HOME_TYPE, 'unexpected home partition type')
    _require(re.fullmatch(r'/dev/vdc[1-9][0-9]*', home.get('node', '')) is not None, 'unexpected home device')
    _require(type(home.get('start')) is int and type(home.get('size')) is int, 'invalid GPT home geometry')
    return generate(home['node'], home['uuid'], home['start'] * sector_size, home['size'] * sector_size)


if __name__ == '__main__':
    print('OXP_HOME_COPY_PLAN=' + canonical_json(generate_managed_home()), flush=True)
