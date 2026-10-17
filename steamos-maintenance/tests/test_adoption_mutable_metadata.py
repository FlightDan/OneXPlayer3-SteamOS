"""Narrow legacy-writer and VFAT metadata compatibility; no service actions."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oxp3_maintenance import adoption
from oxp3_maintenance.transactions import Store


GRUB = 'efi/EFI/steamos/grub.cfg'
CONFIG = 'var/lib/oxp3-fan/config.json'


def image(data, mode):
    return {'exists': True, 'data': base64.b64encode(data).decode(), 'mode': mode, 'uid': 0, 'gid': 0}


class MutableMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'root'
        self.root.mkdir()
        self.probe = {'slot': {'label': 'A'}, 'uid': 1000, 'gid': 1000}

    def write(self, relative, data, mode=0o644):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def constrain_efi_writes(self, store):
        original = store._write
        def effective_write(relative, snapshot, **kwargs):
            if relative == GRUB and snapshot['exists']:
                self.assertEqual((snapshot['mode'], snapshot['uid'], snapshot['gid']), (0o700, 0, 0))
            return original(relative, snapshot, **kwargs)
        store._write = effective_write

    def mount_witness(self, *, options='rw,fmask=0077,dmask=0077', filesystem='vfat',
                      source_mode=stat.S_IFBLK, device_matches=True, target_owner=0,
                      directory_mode=0o700, mountpoint=None, duplicate=False, source_device_matches=True):
        efi = self.root / 'efi'
        target = self.root / GRUB
        device = 71
        mountpoint = mountpoint or efi.as_posix()
        text = f'10 1 1:7 / {mountpoint} rw - {filesystem} /dev/test-efi {options}'
        if duplicate: text += '\n' + text
        target_info = SimpleNamespace(st_dev=device if device_matches else 72,
            st_mode=stat.S_IFREG | 0o700, st_uid=target_owner, st_gid=0)
        efi_info = SimpleNamespace(st_dev=device, st_mode=stat.S_IFDIR | directory_mode, st_uid=0, st_gid=0)
        source_info = SimpleNamespace(st_mode=source_mode, st_rdev=device if source_device_matches else 72)
        def read_stat(path):
            return {target: target_info, efi: efi_info, Path('/dev/test-efi'): source_info}[path]
        return (patch.object(adoption, '_mountinfo_text', return_value=text),
                patch.object(adoption, '_mount_stat', side_effect=read_stat),
                patch.object(adoption, '_mount_device', return_value=device))

    def recognize_mount(self, **kwargs):
        first, second, third = self.mount_witness(**kwargs)
        with first, second, third:
            return adoption._gm7_vfat_metadata(self.root, GRUB, image(b'old', 0o755), image(b'old', 0o700))

    def test_gm7_requires_kernel_mount_and_effective_root_metadata(self):
        witness = self.recognize_mount()
        self.assertEqual(witness['mode'], 0o700)
        self.assertEqual(witness['filesystem'], 'vfat')
        for kwargs in ({'filesystem': 'ext4'}, {'options': 'rw,fmask=0000,dmask=0077'},
                       {'options': 'rw,fmask=0077,dmask=0000'}, {'options': 'rw,fmask=0077,dmask=0077,uid=1000'},
                       {'options': 'rw,fmask=0077,dmask=0077,gid=1000'}, {'options': 'rw,fmask=0077,dmask=0077,showexec'},
                       {'options': 'ro,fmask=0077,dmask=0077'}, {'options': 'rw,fmask=0077'},
                       {'options': 'rw,fmask=0077,dmask=0077,fmask=0000'},
                       {'source_mode': stat.S_IFREG}, {'device_matches': False},
                       {'source_device_matches': False}, {'duplicate': True},
                       {'target_owner': 1000}, {'directory_mode': 0o777},
                       {'mountpoint': (self.root / 'other').as_posix()}):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(self.recognize_mount(**kwargs))

    def test_gm7_exception_does_not_cover_other_paths_or_arbitrary_modes(self):
        for relative, old, current in ((CONFIG, 0o755, 0o700), (GRUB, 0o644, 0o700),
                                       (GRUB, 0o755, 0o777), (GRUB, 0o755, 0o600)):
            with self.subTest(relative=relative, old=old, current=current):
                self.assertIsNone(adoption._gm7_vfat_metadata(self.root, relative, image(b'x', old), image(b'x', current)))

    def test_fan_requires_both_pinned_recorded_and_live_protected_writers(self):
        writers = {path: ('fixture ' + path).encode() for path in adoption._FAN_WRITERS}
        pins = {path: hashlib.sha256(data).hexdigest() for path, data in writers.items()}
        record = {'applied': {path: base64.b64encode(data).decode() for path, data in writers.items()}}
        snapshots = {self.root / path: image(data, 0o644) for path, data in writers.items()}
        def read_file(path, boundary):
            return snapshots[path]
        with patch.object(adoption, '_FAN_WRITERS', pins), patch.object(adoption, '_file', side_effect=read_file):
            self.assertIsNotNone(adoption._fan_writer_metadata(self.root, CONFIG, record, image(b'auto', 0o600), image(b'user', 0o644)))
            for mode, uid, gid in ((0o666, 0, 0), (0o664, 0, 0), (0o644, 1000, 0), (0o644, 0, 1000)):
                with self.subTest(mode=mode, uid=uid, gid=gid):
                    self.assertIsNone(adoption._fan_writer_metadata(self.root, CONFIG, record, image(b'auto', 0o600),
                        dict(image(b'user', mode), uid=uid, gid=gid)))
            for path in writers:
                with self.subTest(writer=path):
                    original = snapshots[self.root / path]
                    snapshots[self.root / path] = image(b'changed code', 0o644)
                    self.assertIsNone(adoption._fan_writer_metadata(self.root, CONFIG, record, image(b'auto', 0o600), image(b'user', 0o644)))
                    snapshots[self.root / path] = dict(original, mode=0o666)
                    self.assertIsNone(adoption._fan_writer_metadata(self.root, CONFIG, record, image(b'auto', 0o600), image(b'user', 0o644)))
                    snapshots[self.root / path] = original
            wrong = copy.deepcopy(record); wrong['applied'][next(iter(writers))] = base64.b64encode(b'changed record').decode()
            self.assertIsNone(adoption._fan_writer_metadata(self.root, CONFIG, wrong, image(b'auto', 0o600), image(b'user', 0o644)))

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Native isolated Linux ownership/Store fixture')
    def test_gm7_effective_original_survives_store_apply_rollback_and_restore(self):
        grub = self.write(GRUB, b'legacy GM7 settings', 0o700)
        (self.root / 'efi').chmod(0o700)
        original = image(b'before GM7 settings', 0o755)
        record = {'phase': 'installed', 'allowed': [GRUB], 'original': {GRUB: original},
                  'applied': {GRUB: base64.b64encode(grub.read_bytes()).decode()}, 'metadata': {GRUB: {}}}
        journal = self.write('home/.oxp3-installer/integration/A/gm7-resume/state.json', json.dumps(record).encode())
        before = journal.read_bytes()
        source = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=grub.stat().st_dev)
        real_stat = adoption._mount_stat
        def read_stat(path):
            return source if path == Path('/dev/test-efi') else real_stat(path)
        text = f'10 1 1:7 / {(self.root / "efi").as_posix()} rw - vfat /dev/test-efi rw,fmask=0077,dmask=0077'
        with patch.object(adoption, '_trusted'), patch.object(adoption, '_mountinfo_text', return_value=text), \
             patch.object(adoption, '_mount_stat', side_effect=read_stat), \
             patch.object(adoption, '_mount_device', return_value=grub.stat().st_dev):
            adopted = adoption.import_originals(self.root, self.probe, ['gm7-resume'])
            adoption.validate_current(self.root, adopted, self.probe)
        self.assertEqual(adopted[GRUB]['original']['mode'], 0o700)
        self.assertEqual(adopted[GRUB]['legacy_metadata']['original'], original)
        store = Store(self.root, self.root.parent / 'state', enforce_owner=False)
        engine = {'usr/local/lib/oxp3-maintenance/entry.py': {'data': b'fixture bootstrap', 'mode': 0o644,
                  'component': '_maintenance', 'user': False}}
        store.apply(engine, {'version': 'bootstrap'}, ['_maintenance'], 'A', legacy_selected=['gm7-resume'])
        self.constrain_efi_writes(store)
        files = dict(engine, **{GRUB: {'data': b'updated GM7 settings', 'mode': 0o700, 'component': 'gm7-resume', 'mutable': True, 'user': False}})
        store.apply(files, {'version': 'test'}, ['_maintenance', 'gm7-resume'], 'A', adopt=adopted, legacy_selected=[])
        store.rollback('A'); self.assertEqual(grub.read_bytes(), b'legacy GM7 settings')
        store.rollback('A'); self.assertEqual(grub.read_bytes(), b'updated GM7 settings')
        store.restore('A'); self.assertEqual(grub.read_bytes(), b'before GM7 settings')
        self.assertEqual(stat.S_IMODE(grub.stat().st_mode), 0o700)
        self.assertEqual(journal.read_bytes(), before)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Native isolated Linux ownership/Store fixture')
    def test_gm7_custom_boot_bytes_keep_effective_baseline_through_restore(self):
        user = b'legacy GM7 plus user boot options'
        grub = self.write(GRUB, user, 0o700)
        (self.root / 'efi').chmod(0o700)
        record = {'phase': 'installed', 'allowed': [GRUB], 'original': {GRUB: image(b'preproject', 0o755)},
                  'applied': {GRUB: base64.b64encode(b'legacy GM7').decode()}, 'metadata': {GRUB: {}}}
        journal = self.write('home/.oxp3-installer/integration/A/gm7-resume/state.json', json.dumps(record).encode())
        before = journal.read_bytes()
        source = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=grub.stat().st_dev)
        real_stat = adoption._mount_stat
        text = f'10 1 1:7 / {(self.root / "efi").as_posix()} rw - vfat /dev/test-efi rw,fmask=0077,dmask=0077'
        with patch.object(adoption, '_trusted'), patch.object(adoption, '_mountinfo_text', return_value=text), \
             patch.object(adoption, '_mount_stat', side_effect=lambda path: source if path == Path('/dev/test-efi') else real_stat(path)), \
             patch.object(adoption, '_mount_device', return_value=grub.stat().st_dev):
            adopted = adoption.import_originals(self.root, self.probe, ['gm7-resume'])
            adoption.validate_current(self.root, adopted, self.probe)
        self.assertEqual(adopted[GRUB]['baseline']['mode'], 0o700)
        self.assertTrue(adopted[GRUB]['preserve'])
        store = Store(self.root, self.root.parent / 'state', enforce_owner=False)
        engine = {'usr/local/lib/oxp3-maintenance/entry.py': {'data': b'fixture bootstrap', 'mode': 0o644,
                  'component': '_maintenance', 'user': False}}
        store.apply(engine, {'version': 'bootstrap'}, ['_maintenance'], 'A', legacy_selected=['gm7-resume'])
        self.constrain_efi_writes(store)
        files = dict(engine, **{GRUB: {'data': user, 'mode': 0o700, 'component': 'gm7-resume', 'mutable': True, 'user': False}})
        store.apply(files, {'version': 'test'}, ['_maintenance', 'gm7-resume'], 'A', adopt=adopted, legacy_selected=[])
        store.rollback('A'); store.rollback('A'); store.restore('A')
        self.assertEqual(grub.read_bytes(), user)
        self.assertEqual(stat.S_IMODE(grub.stat().st_mode), 0o700)
        self.assertEqual(journal.read_bytes(), before)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Native isolated Linux ownership/Store fixture')
    def test_fan_current_content_preserved_through_store_and_old_journal_unchanged(self):
        config = self.write(CONFIG, b'{"mode":"custom","curve":[[40,40],[85,100]]}', 0o644)
        writers = {path: ('fixture ' + path).encode() for path in adoption._FAN_WRITERS}
        pins = {path: hashlib.sha256(data).hexdigest() for path, data in writers.items()}
        for path, data in writers.items(): self.write(path, data)
        allowed = [*writers, CONFIG]
        record = {'phase': 'installed', 'allowed': allowed, 'original': {path: {'exists': False} for path in allowed},
                  'applied': {**{path: base64.b64encode(data).decode() for path, data in writers.items()}, CONFIG: base64.b64encode(b'{"mode":"auto"}').decode()},
                  'metadata': {path: {'mode': 0o600 if path == CONFIG else 0o644} for path in allowed}}
        journal = self.write('home/.oxp3-installer/integration/A/oxp3-fan/state.json', json.dumps(record).encode())
        before, user_config = journal.read_bytes(), config.read_bytes()
        with patch.object(adoption, '_trusted'), patch.object(adoption, '_FAN_WRITERS', pins):
            adopted = adoption.import_originals(self.root, self.probe, ['oxp3-fan'])
            adoption.validate_current(self.root, adopted, self.probe)
        self.assertEqual(adopted[CONFIG]['baseline']['mode'], 0o644)
        self.assertTrue(adopted[CONFIG]['preserve'])
        store = Store(self.root, self.root.parent / 'state', enforce_owner=False)
        files = {path: {'data': user_config if path == CONFIG else writers[path], 'mode': 0o644,
                        'component': 'oxp3-fan', 'mutable': path == CONFIG, 'user': False} for path in allowed}
        store.apply(files, {'version': 'test'}, ['oxp3-fan'], 'A', adopt=adopted)
        store.restore('A')
        self.assertEqual(config.read_bytes(), user_config)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o644)
        self.assertEqual(journal.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
