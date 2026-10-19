"""Pure corruption tests plus opt-in real e2fsprogs fixtures.

Run real fixtures in the disposable guest with OXP_EXT4_REAL_FIXTURES=1.
They create only temporary regular files; no block devices are formatted.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ext4_copy_plan as planner

PARTITION_ID = '93a01fc7-adf3-42d9-89fd-e014d8797b70'
FS_UUID = 'b84b3d04-c87f-4bce-8352-de597be912fd'
BLOCK_SIZE = 4096
OFFSET = 1048576
SIZE = 384 * BLOCK_SIZE


def fixture():
    return '''Filesystem UUID: b84b3d04-c87f-4bce-8352-de597be912fd
Filesystem magic number: 0xEF53
Filesystem revision #: 1 (dynamic)
Filesystem features: has_journal ext_attr resize_inode dir_index filetype extent 64bit flex_bg sparse_super large_file huge_file dir_nlink extra_isize metadata_csum orphan_file
Filesystem state: clean
Inode count: 96
Block count: 384
Free blocks: 362
First block: 0
Block size: 4096
Group descriptor size: 64
Reserved GDT blocks: 2
Blocks per group: 128
Inodes per group: 32
Inode size: 256

Group 0: (Blocks 0-127) csum 0x1234 [ITABLE_ZEROED]
  Primary superblock at 0, Group descriptors at 1-1
  Reserved GDT blocks at 2-3
  Block bitmap at 4 (+4), csum 0x12345678
  Inode bitmap at 5 (+5), csum 0x12345678
  Inode table at 6-7 (+6)
  110 free blocks, 21 free inodes, 2 directories, 21 unused inodes
  Free blocks: 16-39, 42-127
  Free inodes: 12-32
Group 1: (Blocks 128-255) csum 0x1234 [INODE_UNINIT, ITABLE_ZEROED]
  Backup superblock at 128, Group descriptors at 129-129
  Reserved GDT blocks at 130-131
  Block bitmap at 8 (bg #0 + 8), csum 0x12345678
  Inode bitmap at 9 (bg #0 + 9), csum 0x12345678
  Inode table at 10-11 (bg #0 + 10)
  124 free blocks, 32 free inodes, 0 directories, 32 unused inodes
  Free blocks: 132-255
  Free inodes: 33-64
Group 2: (Blocks 256-383) csum 0x1234 [INODE_UNINIT, BLOCK_UNINIT, ITABLE_ZEROED]
  Block bitmap at 12 (bg #0 + 12), csum 0x12345678
  Inode bitmap at 13 (bg #0 + 13), csum 0x12345678
  Inode table at 14-15 (bg #0 + 14)
  128 free blocks, 32 free inodes, 0 directories, 32 unused inodes
  Free blocks: 256-383
  Free inodes: 65-96
'''


def parse(text=None, **kwargs):
    args = dict(partition_id=PARTITION_ID, partition_offset=OFFSET, partition_size=SIZE)
    args.update(kwargs)
    return planner.parse_dump(fixture() if text is None else text, **args)


class ParserTests(unittest.TestCase):
    def test_flex_uninit_backups_and_allocated_zero_blocks_retained(self):
        plan = parse()
        self.assertEqual(plan['ranges'], [[0, 16 * BLOCK_SIZE], [40 * BLOCK_SIZE, 2 * BLOCK_SIZE], [128 * BLOCK_SIZE, 4 * BLOCK_SIZE]])
        self.assertEqual(plan['used_bytes'], 22 * BLOCK_SIZE)
        self.assertEqual(plan['mode'], 'ext4-used-v1')
        self.assertEqual(plan['features'], sorted(plan['features']))

    def test_deterministic_canonical_encoding(self):
        plan = parse()
        encoded = planner.canonical_json(plan)
        self.assertEqual(encoded, planner.canonical_json(dict(reversed(list(plan.items())))))
        self.assertEqual(json.loads(encoded), plan)
        self.assertNotIn(' ', encoded)

    def test_contradictory_or_incomplete_dump_rejected(self):
        edits = [
            ('Free blocks: 16-39, 42-127', 'Free blocks: 16-39, 39-127'),
            ('Free blocks: 16-39, 42-127', 'Free blocks: 42-127, 16-39'),
            ('Free blocks: 16-39, 42-127', 'Free blocks: 16-39, 42-128'),
            ('Free blocks: 16-39, 42-127', 'Free blocks: 16-39, 42-126'),
            ('Free blocks: 362', 'Free blocks: 361'),
            ('110 free blocks', '109 free blocks'),
            ('Group 1: (Blocks 128-255)', 'Group 2: (Blocks 128-255)'),
            ('Group 1: (Blocks 128-255)', 'Group 1: (Blocks 129-255)'),
            ('  Inode table at 14-15 (bg #0 + 14)\n', ''),
            ('Inode table at 14-15', 'Inode table at 14-14'),
            ('  Reserved GDT blocks at 130-131\n', ''),
            ('csum 0x1234 [ITABLE_ZEROED]', 'csum 0x1234 (EXPECTED 0x5678) [ITABLE_ZEROED]'),
            ('Filesystem state: clean', 'Filesystem state: clean with errors'),
            ('has_journal ext_attr', 'has_journal needs_recovery ext_attr'),
            ('Block count: 384', 'Block count: 383'),
            ('Inode count: 96', 'Inode count: 95'),
            ('Inode size: 256', 'Inode size: 300'),
            ('Block size: 4096', 'Block size: 4097'),
            ('Filesystem UUID: ' + FS_UUID, 'Filesystem UUID: invalid'),
            ('  Free inodes: 65-96', '  Free inodes: 65-96\n  Surprise metadata at 350'),
        ]
        for before, after in edits:
            with self.subTest(before=before, after=after), self.assertRaises(RuntimeError):
                parse(fixture().replace(before, after))
        with self.assertRaises(RuntimeError):
            parse(fixture().split('Group 2:')[0])

    def test_flex_metadata_marked_free_rejected_even_with_consistent_counts(self):
        # Shift two nominally free blocks onto another group's entire inode table.
        text = fixture().replace('Free blocks: 16-39, 42-127', 'Free blocks: 14-39, 44-127')
        with self.assertRaisesRegex(RuntimeError, 'metadata marked free'):
            parse(text)

    def test_duplicate_header_group_and_metadata_rejected(self):
        for text in [fixture().replace('Block count: 384', 'Block count: 384\nBlock count: 384'),
                     fixture().replace('  Block bitmap at 4 (+4), csum 0x12345678', '  Block bitmap at 4 (+4)\n  Block bitmap at 4 (+4)'),
                     fixture() + 'Group 2:' + fixture().split('Group 2:')[1]]:
            with self.assertRaises(RuntimeError):
                parse(text)

    def test_valid_unsupported_feature_explicit_full_fallback(self):
        for feature in ('bigalloc', 'mmp', 'meta_bg', 'encrypt', 'unknown_future_feature'):
            with self.subTest(feature=feature):
                plan = parse(fixture().replace('orphan_file', 'orphan_file ' + feature))
                self.assertEqual(plan['mode'], 'full')
                self.assertEqual(plan['ranges'], [[0, SIZE]])
                self.assertEqual(plan['used_bytes'], SIZE)
                self.assertIn(feature, plan['fallback_reason'])

    def test_other_valid_block_size_falls_back_but_geometry_still_checked(self):
        text = fixture().replace('Block size: 4096', 'Block size: 2048')
        self.assertEqual(parse(text, partition_size=SIZE // 2)['fallback_reason'], 'unsupported-block-size')
        with self.assertRaises(RuntimeError):
            parse(text)

    def test_casefold_filename_semantics_leave_allocation_plan_unchanged(self):
        plan = parse(fixture().replace('orphan_file', 'orphan_file casefold'))
        self.assertEqual(plan['ranges'], parse()['ranges'])

    def test_external_journal_rejected_even_in_full_fallback(self):
        for text in (fixture().replace('orphan_file', 'orphan_file journal_dev'),
                     fixture().replace('Block count: 384', 'Journal device: 0x0801\nBlock count: 384'),
                     fixture().replace('Block count: 384', 'Journal UUID: ' + FS_UUID + '\nBlock count: 384')):
            with self.assertRaisesRegex(RuntimeError, 'external journal'):
                parse(text)

    def test_overlapping_metadata_and_missing_flex_feature_rejected(self):
        for text in (fixture().replace('Inode bitmap at 13', 'Inode bitmap at 12'), fixture().replace('64bit flex_bg', '64bit')):
            with self.assertRaises(RuntimeError):
                parse(text)

    def test_limits_are_explicit_full_fallback_after_validation(self):
        for name, limit, reason in [('MAX_RANGES', 2, 'range-limit'), ('MAX_JSON_BYTES', 10, 'json-size-limit')]:
            with self.subTest(name=name), patch.object(planner, name, limit):
                plan = parse()
                self.assertEqual(plan['mode'], 'full')
                self.assertEqual(plan['fallback_reason'], reason)
        with patch.object(planner, 'MAX_RANGES', 0), self.assertRaises(RuntimeError):
            parse(fixture().replace('Free blocks: 362', 'Free blocks: 361'))

    def test_invalid_partition_binding_rejected(self):
        for kwargs in [dict(partition_id='00000000-0000-0000-0000-000000000000'), dict(partition_offset=-1), dict(partition_size=SIZE - 512), dict(partition_offset=True), dict(partition_size='1572864')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                parse(**kwargs)

    def test_command_failure_and_tool_version_fail_closed(self):
        result = subprocess.CompletedProcess([], 4, stdout='filesystem errors', stderr='')
        with patch.object(planner.subprocess, 'run', return_value=result), self.assertRaises(RuntimeError):
            planner._run('e2fsck', '-f', '-n', '/not/a/device')
        result = subprocess.CompletedProcess([], 0, stdout='', stderr='dumpe2fs 1.47.2 (date)\n')
        with patch.object(planner, '_run', return_value=result), self.assertRaises(RuntimeError):
            planner._check_version('dumpe2fs')


@unittest.skipUnless(os.environ.get('OXP_EXT4_REAL_FIXTURES') == '1', 'set OXP_EXT4_REAL_FIXTURES=1 in disposable Linux guest')
class RealFilesystemTests(unittest.TestCase):
    def test_mkfs_default_uninit_orphan_and_populated_image(self):
        for tool in ('mkfs.ext4', 'e2fsck', 'dumpe2fs', 'debugfs'):
            self.assertIsNotNone(shutil.which(tool), tool)
        planner._check_version('e2fsck')
        planner._check_version('dumpe2fs')
        with tempfile.TemporaryDirectory(prefix='oxp-ext4-plan-') as directory:
            root = Path(directory)
            for label, gib, features in [('default', 1, []), ('orphan-casefold', 1, ['-O', 'orphan_file,casefold']), ('large64', 64, []), ('large100', 100, [])]:
                with self.subTest(label=label):
                    image = root / (label + '.ext4')
                    size = gib * 1024 ** 3
                    with image.open('wb') as stream:
                        stream.truncate(size)
                    planner._run('mkfs.ext4', '-F', '-q', '-b', '4096', '-E', 'lazy_itable_init=1,lazy_journal_init=1', *features, str(image))
                    # Explicitly allocated zero blocks must survive just as data.
                    planner._run('debugfs', '-w', '-R', 'write /dev/null /allocated-zero', str(image))
                    planner._run('debugfs', '-w', '-R', 'fallocate /allocated-zero 0 15', str(image))
                    planner._run('debugfs', '-w', '-R', 'set_inode_field /allocated-zero size 65536', str(image))
                    planner._run('e2fsck', '-f', '-n', str(image))
                    dump = planner._run('dumpe2fs', str(image))
                    plan = planner.parse_dump(dump.stdout, PARTITION_ID, OFFSET, size)
                    self.assertEqual(plan['mode'], 'ext4-used-v1')
                    if label == 'orphan-casefold':
                        self.assertTrue({'casefold', 'orphan_file'} <= set(plan['features']))
                    self.assertLess(plan['used_bytes'], size // 2)
                    self.assertEqual(planner.canonical_json(plan), planner.canonical_json(planner.parse_dump(dump.stdout, PARTITION_ID, OFFSET, size)))
                    if label in ('large64', 'large100'):
                        self.assertIn('BLOCK_UNINIT', dump.stdout)
                    inode = planner._run('debugfs', '-R', 'stat /allocated-zero', str(image)).stdout
                    self.assertIn('Blockcount: 128', inode)
                    data_blocks = [int(n) for n in planner._run('debugfs', '-R', 'blocks /allocated-zero', str(image)).stdout.split()]
                    self.assertEqual(len(data_blocks), 16)
                    inode_table_zero = int(re.findall(r'Inode table at [0-9]+-([0-9]+)', dump.stdout)[-1])
                    free_block = int(re.search(r'^  Free blocks: ([0-9]+)', dump.stdout, re.MULTILINE)[1])
                    sentinel = b'\xa5' * 4096
                    # Reconstruct a sparse destination using exactly the planned
                    # ranges, then prove its offline filesystem is still sound.
                    reconstructed = root / 'reconstructed.ext4'
                    with image.open('rb') as source, reconstructed.open('wb') as target:
                        target.truncate(size)
                        # A pre-zeroed sparse destination would conceal a writer
                        # that incorrectly skips allocated all-zero source data.
                        for block in (data_blocks[0], inode_table_zero, free_block):
                            target.seek(block * 4096)
                            target.write(sentinel)
                        for block in (data_blocks[0], inode_table_zero):
                            source.seek(block * 4096)
                            self.assertEqual(source.read(4096), b'\0' * 4096)
                        for offset, length in plan['ranges']:
                            source.seek(offset)
                            target.seek(offset)
                            while length:
                                data = source.read(min(length, 1024 * 1024))
                                self.assertTrue(data)
                                target.write(data)
                                length -= len(data)
                    with reconstructed.open('rb') as target:
                        for block in (data_blocks[0], inode_table_zero):
                            target.seek(block * 4096)
                            self.assertEqual(target.read(4096), b'\0' * 4096)
                        target.seek(free_block * 4096)
                        self.assertEqual(target.read(4096), sentinel)
                    planner._run('e2fsck', '-f', '-n', str(reconstructed))
                    extracted = root / 'extracted-zero'
                    planner._run('debugfs', '-R', 'dump /allocated-zero ' + str(extracted), str(reconstructed))
                    self.assertEqual(extracted.read_bytes(), b'\0' * 65536)
                    extracted.unlink()
                    print('OXP_EXT4_FIXTURE=' + planner.canonical_json(dict(
                        name=label, partition_size=size, used_bytes=plan['used_bytes'],
                        range_count=len(plan['ranges']), allocated_zero_and_metadata_overwritten=True,
                        free_sentinel_untouched=True, reconstructed_e2fsck='passed')), flush=True)
                    reconstructed.unlink()
                    image.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
