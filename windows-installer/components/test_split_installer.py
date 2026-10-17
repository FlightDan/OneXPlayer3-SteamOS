"""Linux file-transaction checks for combined boot settings and Light ordering."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from integration import apply_files, restore, seed_decky_order
from boot_repairs import gm7_files
from split_lock import GRUB, DROPIN, files as split_files, patch_grub
from decky_order import SETTINGS, PLUGINS


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'Linux root fixture only')
class InstallerBootChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.state = self.root / 'home/.oxp3-installer/integration/A'
        self.state.mkdir(parents=True, mode=0o700)
        self.initial = b'linux /boot/vmlinuz-linux-neptune-72 root=UUID=original quiet\n'
        self.write(GRUB, self.initial)
        self.write('etc/passwd', b'deck:x:1000:1000::/home/deck:/bin/bash\n')
        self.options = {'repairs': [{'id': 'gm7-resume', 'dependencies': []},
                                    {'id': 'split-lock', 'dependencies': []}], 'plugins': []}
        self.write('usr/local/lib/oxp3-integration/options.json', json.dumps(self.options).encode())

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
        return target

    def result(self, components):
        path = self.state / 'result.json'
        path.write_text(json.dumps({'components': components}))
        path.chmod(0o600)

    def install(self, gm7=True):
        reports = {}
        if gm7:
            first = gm7_files(self.root, {'bus': 'NVMe', 'model': 'Predator GM7'})
            first[GRUB]['data'] = patch_grub(first[GRUB]['data'].decode()).encode()
            apply_files(self.root, self.state, 'gm7-resume', first, (1000, 1000))
            reports['gm7-resume'] = {'status': 'files_installed', 'files': list(first)}
        second = split_files(self.root)
        if gm7:
            second.pop(GRUB)
        apply_files(self.root, self.state, 'split-lock', second, (1000, 1000))
        reports['split-lock'] = {'status': 'files_installed', 'files': list(second)}
        self.result(reports)
        return reports

    def test_combined_one_grub_owner_repeat_and_explicit_group_restore(self):
        self.install()
        first_record = (self.state / 'gm7-resume/state.json').read_bytes()
        self.install()
        self.assertEqual((self.state / 'gm7-resume/state.json').read_bytes(), first_record)
        text = (self.root / GRUB).read_text()
        self.assertEqual(text.count('nvme.noacpi=1'), 1)
        self.assertEqual(text.count('split_lock_detect=off'), 1)
        for name in ('gm7-resume', 'split-lock'):
            with self.assertRaisesRegex(RuntimeError, 'boot-repairs'):
                restore(self.root, 'A', name)
        self.assertEqual(restore(self.root, 'A', 'boot-repairs'), [])
        self.assertEqual((self.root / GRUB).read_bytes(), self.initial)
        self.assertFalse((self.root / DROPIN).exists())
        self.assertFalse((self.root / 'etc/default/grub.d/oxp3-nvme.cfg').exists())

    def test_group_conflict_preflights_every_journal_before_any_write(self):
        self.install()
        self.write(GRUB, (self.root / GRUB).read_bytes() + b'# administrator edit\n')
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        errors = restore(self.root, 'A', 'boot-repairs')
        self.assertTrue(errors)
        after = {p.relative_to(self.root).as_posix(): p.read_bytes()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_split_alone_has_independent_restore(self):
        self.install(gm7=False)
        self.assertEqual(restore(self.root, 'A', 'split-lock'), [])
        self.assertEqual((self.root / GRUB).read_bytes(), self.initial)

    def test_light_insertion_secondary_journal_preserves_custom_order(self):
        for folder, name in (('cpu', 'OXP3 CPU'), ('fan', 'OXP3 Fan'), ('battery', 'OXP3 Battery')):
            self.write(PLUGINS + '/' + folder + '/plugin.json', json.dumps({'name': name}).encode())
        seed_decky_order(self.root, self.state, (1000, 1000))
        original_journal = (self.state / 'decky-order/state.json').read_bytes()
        custom = {'pluginOrder': ['OXP3 Fan', 'My plugin', 'OXP3 Battery', 'OXP3 CPU'],
                  'sortPlugins': False, 'language': 'zh-CN'}
        self.write(SETTINGS, json.dumps(custom).encode())
        self.write(PLUGINS + '/light/plugin.json', b'{"name":"OXP3 Light"}')
        seed_decky_order(self.root, self.state, (1000, 1000))
        current = json.loads((self.root / SETTINGS).read_text())
        self.assertEqual(current['pluginOrder'], ['OXP3 Fan', 'My plugin', 'OXP3 Battery', 'OXP3 Light', 'OXP3 CPU'])
        self.assertEqual(current['language'], 'zh-CN')
        seed_decky_order(self.root, self.state, (1000, 1000))
        self.assertEqual((self.state / 'decky-order/state.json').read_bytes(), original_journal)
        self.result({})
        self.assertEqual(restore(self.root, 'A', 'decky-order-light'), [])
        self.assertEqual(json.loads((self.root / SETTINGS).read_text()), custom)


if __name__ == '__main__':
    unittest.main()
