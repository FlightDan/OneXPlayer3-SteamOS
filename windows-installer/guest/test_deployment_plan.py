"""Safety checks: metadata changes must be rejected before any deployment writes."""
import copy
import unittest
from deployment import resolve, ESP_TYPE, can_recover_root
from layout import plan, GIB


def fixture():
    before = {'device': '/dev/nvme2n1', 'label': 'gpt', 'id': 'fixture-gpt-id', 'sectorsize': 512,
              'firstlba': 2048, 'lastlba': 80 * GIB // 512 - 34,
              'partitions': [
                  {'node': '/dev/nvme2n1p1', 'start': 2048, 'size': 131072, 'type': ESP_TYPE,
                   'name': 'Windows EFI', 'uuid': 'windows-efi', 'attrs': 'GUID:63'},
                  {'node': '/dev/nvme2n1p4', 'start': 133120, 'size': 20971520,
                   'type': 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7', 'name': 'Windows', 'uuid': 'windows-data'}]}
    selected = plan(before, 12 * GIB, 64 * GIB)
    for index, item in enumerate(selected): item.update(node=f'/dev/nvme2n1p{index+7}', uuid=f'new-{index}')
    actual = copy.deepcopy(before); actual['partitions'] += selected
    choice = {'schema': 1, 'mode': 'virtual_install', 'target_table': copy.deepcopy(actual),
              'range': {'start': 12 * GIB, 'size': 64 * GIB}}
    return choice, actual


class DeploymentPlanChecks(unittest.TestCase):
    def test_only_owned_unfinished_configuration_can_recover_writable_root(self):
        state = {'status': 'running', 'phase': 'configure-A', 'configured': ['B'], 'copied': {'rootfs-A': 'owned-root'}}
        self.assertTrue(can_recover_root(state, 'A', 'owned-root'))
        for key, value in [('status', 'complete'), ('phase', 'copy-rootfs-A'), ('configured', ['A', 'B']), ('copied', {'rootfs-A': 'foreign'})]:
            damaged = dict(state, **{key: value})
            self.assertFalse(can_recover_root(damaged, 'A', 'owned-root'))
        self.assertFalse(can_recover_root(state, 'B', 'owned-root'))

    def test_nodes_follow_metadata_instead_of_partition_numbers(self):
        choice, actual = fixture()
        actual['partitions'].reverse()
        nodes = resolve(choice, actual)
        self.assertEqual(nodes['rootfs-A'], '/dev/nvme2n1p10')
        self.assertEqual(nodes['home'], '/dev/nvme2n1p14')
        self.assertNotIn('/dev/nvme2n1p1', nodes.values())

    def test_windows_metadata_change_is_rejected(self):
        for field, value in [('start', 4096), ('type', 'foreign'), ('attrs', ''), ('uuid', 'changed')]:
            choice, actual = fixture(); actual['partitions'][0][field] = value
            with self.assertRaises(ValueError): resolve(choice, actual)

    def test_disk_identity_and_added_partition_are_rejected(self):
        choice, actual = fixture(); actual['id'] = 'different-disk'
        with self.assertRaises(ValueError): resolve(choice, actual)
        choice, actual = fixture(); actual['partitions'].append(copy.deepcopy(actual['partitions'][0]))
        with self.assertRaises(ValueError): resolve(choice, actual)

    def test_selected_uuid_or_bounds_change_is_rejected(self):
        for field, value in [('uuid', 'changed'), ('size', 1), ('start', 1)]:
            choice, actual = fixture(); actual['partitions'][5][field] = value
            with self.assertRaises(ValueError): resolve(choice, actual)

    def test_duplicate_roles_and_nodes_are_rejected(self):
        choice, actual = fixture(); choice['target_table']['partitions'][3]['name'] = 'esp'
        with self.assertRaises(ValueError): resolve(choice, actual)
        choice, actual = fixture(); actual['partitions'][3]['node'] = actual['partitions'][2]['node']
        with self.assertRaises(ValueError): resolve(choice, actual)

    def test_slot_efi_type_change_is_rejected_to_avoid_shared_esp_alias(self):
        choice, actual = fixture(); actual['partitions'][3]['type'] = ESP_TYPE
        with self.assertRaises(ValueError): resolve(choice, actual)
        choice, actual = fixture()
        actual['partitions'][5]['type'] = ESP_TYPE
        with self.assertRaises(ValueError): resolve(choice, actual)

    def test_preview_capabilities_and_overlapping_range_are_rejected(self):
        choice, actual = fixture(); choice['mode'] = 'preview_only'
        with self.assertRaises(ValueError): resolve(choice, actual)
        choice, actual = fixture(); choice['range']['start'] = 1024**2
        with self.assertRaises(ValueError): resolve(choice, actual)


if __name__ == '__main__': unittest.main(verbosity=2)
