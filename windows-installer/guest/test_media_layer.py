"""Deletion boundaries and interrupted-copy recovery, using temporary roots."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from media_layer import begin, finalize, inspect, detach, OWNED, MANIFEST, SELECTION, WANT, SOURCE


def prepared(root):
    (root / 'etc').mkdir()
    (root / 'etc/keep.conf').write_text('preserve stock configuration\n')
    begin(root)
    for name in OWNED:
        path = root / name
        if name.endswith(('.service', '.target')): path.parent.mkdir(parents=True, exist_ok=True); path.write_text('owned unit\n')
        else: path.mkdir(parents=True, exist_ok=True)
    (root / 'usr/local/lib/oxp3-installer/preview.py').write_text('owned preview\n')
    (root / WANT).symlink_to('../oxp3-preview.service')
    (root / SELECTION).write_text(json.dumps({'schema': 1, 'stage': 'preview_only', 'allow_disk_write': False,
                                             'source': SOURCE, 'resources': [], 'components': [], 'plugins': []}))
    return finalize(root)


class MediaLayerChecks(unittest.TestCase):
    def test_only_owned_layer_removed_stock_unchanged_and_repeat_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); profile = prepared(root)
            self.assertEqual(inspect(root), profile)
            self.assertTrue(detach(root, profile)); self.assertFalse(detach(root, profile))
            self.assertEqual((root / 'etc/keep.conf').read_text(), 'preserve stock configuration\n')
            self.assertFalse(any((root / name).exists() for name in OWNED))

    def test_existing_paths_are_not_claimed(self):
        for name in OWNED:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); path = root / name; path.mkdir(parents=True)
                with self.assertRaises(RuntimeError): begin(root)
                self.assertTrue(path.is_dir())

    def test_foreign_file_rejected_before_any_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); profile = prepared(root)
            (root / 'usr/local/lib/oxp3-installer/user-file').write_text('keep')
            with self.assertRaises(RuntimeError): inspect(root)
            with self.assertRaises(RuntimeError): detach(root, profile)
            self.assertTrue((root / SELECTION).is_file())

    def test_foreign_link_and_redirected_parent_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); profile = prepared(root)
            file = root / 'usr/local/lib/oxp3-installer/preview.py'; file.unlink(); file.symlink_to(root / 'etc/keep.conf')
            with self.assertRaises(RuntimeError): detach(root, profile)
            self.assertTrue((root / 'etc/keep.conf').is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'outside').mkdir(); (root / 'usr').symlink_to(root / 'outside')
            with self.assertRaises(RuntimeError): begin(root)

    def test_partial_detach_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); profile = prepared(root)
            (root / WANT).unlink(); (root / 'usr/local/lib/oxp3-installer/preview.py').unlink()
            self.assertTrue(detach(root, profile)); self.assertFalse((root / MANIFEST).exists())

    def test_legacy_and_unfinished_media_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / SELECTION).parent.mkdir(parents=True); (root / SELECTION).write_text('{}')
            with self.assertRaises(RuntimeError): inspect(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); begin(root)
            with self.assertRaises(RuntimeError): inspect(root)

    def test_changed_record_or_selection_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); profile = prepared(root)
            altered = copy.deepcopy(profile); altered['source']['version'] = 'foreign'
            (root / MANIFEST).write_text(json.dumps(altered))
            with self.assertRaises(RuntimeError): detach(root, profile)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); prepared(root)
            value = json.loads((root / SELECTION).read_text()); value['allow_disk_write'] = True
            (root / SELECTION).write_text(json.dumps(value))
            with self.assertRaises(RuntimeError): inspect(root)


if __name__ == '__main__': unittest.main(verbosity=2)
