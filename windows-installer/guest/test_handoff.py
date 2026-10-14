import copy
import unittest
from handoff import bind
from layout import GIB, plan


def fixture():
    table = {'device': '/dev/nvme7n1', 'id': '11111111-1111-1111-1111-111111111111', 'label': 'gpt',
             'sectorsize': 512, 'firstlba': 2048, 'lastlba': 80 * GIB // 512 - 34, 'partitions': [
                 {'node': '/dev/nvme7n1p1', 'start': 2048, 'size': 131072, 'name': 'Windows EFI',
                  'uuid': '22222222-2222-2222-2222-222222222222', 'type': 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'},
                 {'node': '/dev/nvme7n1p4', 'start': 133120, 'size': 20971520, 'name': 'Windows',
                  'uuid': '33333333-3333-3333-3333-333333333333', 'type': 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'}]}
    identity = {'DiskGuid': table['id'].upper(), 'SectorSize': 512, 'Partitions': [
        {'Number': index + 1, 'Guid': p['uuid'].upper(), 'Offset': p['start'] * 512, 'Size': p['size'] * 512, 'GptType': p['type']}
        for index, p in enumerate(table['partitions'])]}
    layout = [{'name': p['name'], 'start': p['start'] * 512, 'size': p['size'] * 512,
               'filesystem': 'vfat' if p['name'] == 'esp' or p['name'].startswith('efi-') else 'btrfs' if p['name'].startswith('rootfs-') else 'ext4'}
              for p in plan(table, 12 * GIB, 64 * GIB)]
    selection = {'schema': 1, 'handoff_schema': 1, 'stage': 'preview_only', 'allow_disk_write': False,
                 'target': {'Disk': 0, 'Model': 'Windows display name', 'DiskSize': 80 * GIB,
                            'Start': 12 * GIB, 'Size': 64 * GIB, 'Identity': identity}, 'layout': layout}
    return selection, {'size': 80 * GIB, 'sector_size': 512, 'table': table}


class HandoffChecks(unittest.TestCase):
    def test_windows_number_and_linux_name_are_independent(self):
        selection, candidate = fixture()
        result = bind(selection, [candidate])
        self.assertEqual(result['device'], '/dev/nvme7n1')
        self.assertFalse(result['allow_disk_write'])

    def test_missing_or_duplicate_disk_is_rejected(self):
        selection, candidate = fixture()
        for candidates in ([], [candidate, copy.deepcopy(candidate)]):
            with self.assertRaises(ValueError): bind(selection, candidates)

    def test_changed_capacity_sector_or_partition_is_rejected(self):
        selection, candidate = fixture()
        for field, value in [('size', 81 * GIB), ('sector_size', 4096)]:
            changed = copy.deepcopy(candidate); changed[field] = value
            with self.assertRaises(ValueError): bind(selection, [changed])
        for field, value in [('start', 4096), ('size', 1), ('uuid', '44444444-4444-4444-4444-444444444444'), ('type', '44444444-4444-4444-4444-444444444444')]:
            changed = copy.deepcopy(candidate); changed['table']['partitions'][0][field] = value
            with self.assertRaises(ValueError): bind(selection, [changed])

    def test_edited_plan_or_legacy_selection_is_rejected(self):
        selection, candidate = fixture(); selection['layout'][0]['size'] += 1024**2
        with self.assertRaises(ValueError): bind(selection, [candidate])
        selection, candidate = fixture(); del selection['target']['Identity']
        with self.assertRaises(ValueError): bind(selection, [candidate])

    def test_write_capability_and_boolean_byte_count_are_rejected(self):
        selection, candidate = fixture(); selection['allow_disk_write'] = True
        with self.assertRaises(ValueError): bind(selection, [candidate])
        selection, candidate = fixture(); selection['target']['Start'] = True
        with self.assertRaises(ValueError): bind(selection, [candidate])


if __name__ == '__main__': unittest.main(verbosity=2)
