"""Persistent intent rejection boundaries and replay against fresh metadata."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from intent_store import IntentStore
from install_session import prepare_intent, review, reconcile_intent, resume_review
from test_handoff import fixture


def prepared():
    choice, before = fixture()
    source = {'table': copy.deepcopy(before['table']), 'root_uuid': 'source-root',
              'media_layer': {'source': 'fixture'}, 'selection': {'resources': []}}
    record = prepare_intent(choice, before, review(choice, [before]), source)
    return record, before


def appended(record, count=8, device=None):
    current = copy.deepcopy(record['before'])
    current['table']['partitions'] += [dict(p, node=f'/dev/nvme7n1p{index + 5}') for index, p in enumerate(record['planned'][:count])]
    if device:
        current['table']['device'] = device
        for index, p in enumerate(current['table']['partitions']): p['node'] = device + 'p' + str(index + 1)
    return current


class IntentChecks(unittest.TestCase):
    def test_durable_prepared_record_and_prefix_progress(self):
        record, before = prepared()
        self.assertEqual(reconcile_intent(record, before)['count'], 0)
        for count in (1, 3, 8):
            state = reconcile_intent(record, appended(record, count))
            self.assertEqual(state['count'], count); self.assertEqual(len(state['remaining']), 8 - count)

    def test_complete_append_is_reused_after_device_renaming(self):
        record, before = prepared(); current = appended(record, device='/dev/nvme9n1')
        result = resume_review(record, current)
        self.assertEqual(result['device'], '/dev/nvme9n1'); self.assertEqual(result['remaining'], [])

    def test_unknown_partition_or_guid_and_partial_nonprefix_rejected(self):
        for field, value in [('uuid', '99999999-9999-9999-9999-999999999999'), ('start', 1), ('type', 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'), ('name', 'foreign')]:
            record, _ = prepared(); current = appended(record); current['table']['partitions'][-1][field] = value
            with self.assertRaises(RuntimeError): reconcile_intent(record, current)
        record, _ = prepared(); current = appended(record, 3); current['table']['partitions'].pop(2)
        with self.assertRaises(RuntimeError): reconcile_intent(record, current)

    def test_protected_metadata_and_disk_boundaries_rejected(self):
        record, _ = prepared()
        for field, value in [('uuid', '99999999-9999-9999-9999-999999999999'), ('start', 4096), ('attrs', 'foreign')]:
            current = appended(record); current['table']['partitions'][0][field] = value
            with self.assertRaises(RuntimeError): reconcile_intent(record, current)
        current = appended(record); current['table']['lastlba'] -= 1
        with self.assertRaises(RuntimeError): reconcile_intent(record, current)
        current = appended(record); current['size'] += 1
        with self.assertRaises(RuntimeError): reconcile_intent(record, current)

    def test_saved_plan_confirmation_or_duplicate_guid_rejected(self):
        record, before = prepared()
        for modify in (lambda r: r['planned'][0].update(size=1),
                       lambda r: r['planned'][1].update(uuid=r['planned'][0]['uuid']),
                       lambda r: r['confirmation']['range'].update(size=1)):
            changed = copy.deepcopy(record); modify(changed)
            with self.assertRaises((RuntimeError, ValueError)): reconcile_intent(changed, before)

    def test_appended_status_cannot_hide_missing_partitions(self):
        record, before = prepared(); record['status'] = 'appended'
        with self.assertRaises(RuntimeError): reconcile_intent(record, before)
        self.assertEqual(reconcile_intent(record, appended(record))['count'], 8)

    def test_store_survives_reopen_and_prevents_foreign_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntentStore(Path(directory)); record, _ = prepared()
            with store.locked(): store.save(record, create=True)
            self.assertEqual(IntentStore(Path(directory)).load(), record)
            with store.locked():
                with self.assertRaises(RuntimeError): store.save(record, create=True)
                changed = dict(record, id='foreign')
                with self.assertRaises(RuntimeError): store.save(changed)
            self.assertEqual(os.stat(store.path).st_mode & 0o777, 0o600)

    def test_store_lock_symlink_and_user_writable_paths_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntentStore(Path(directory))
            with store.locked():
                with self.assertRaises(RuntimeError):
                    with IntentStore(Path(directory)).locked(): pass
            (Path(directory) / 'outside.json').write_text('{}')
            store.path.symlink_to(Path(directory) / 'outside.json')
            with self.assertRaises(OSError): store.load()
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o777)
            with self.assertRaises(RuntimeError): IntentStore(Path(directory))

    def test_malformed_persistent_record_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = IntentStore(Path(directory)); store.path.write_text('{unfinished'); os.chmod(store.path, 0o600)
            with self.assertRaises(json.JSONDecodeError): store.load()
            with self.assertRaises(json.JSONDecodeError): store.save({'id': 'foreign'}, create=True)
            self.assertEqual(store.path.read_text(), '{unfinished')


if __name__ == '__main__': unittest.main(verbosity=2)
