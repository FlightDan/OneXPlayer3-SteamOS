import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from plugin_installer import PluginInstaller, PLUGINS


class PluginOperationChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'system'; self.root.mkdir()
        self.resources = Path(self.temporary.name) / 'resources'; self.resources.mkdir()
        (self.resources / 'decky').mkdir()
        # File-layer fixture only. Real executable compatibility is checked separately.
        (self.resources / 'decky/PluginLoader').write_bytes(b'\x7fELF' + b'x' * 1048576)
        for plugin_id in PLUGINS: self.package(plugin_id)
        self.installer = PluginInstaller(self.root, self.resources)

    def package(self, plugin_id, unsafe=False):
        name, version, folder = PLUGINS[plugin_id]
        directory = self.resources / plugin_id; directory.mkdir(exist_ok=True)
        with zipfile.ZipFile(directory / (plugin_id + '-' + version + '.zip'), 'w') as archive:
            archive.writestr(folder + '/plugin.json', json.dumps({'name': name}))
            archive.writestr(folder + '/package.json', json.dumps({'version': version}))
            archive.writestr(folder + '/main.py', 'plugin backend fixture')
            archive.writestr(folder + '/dist/index.js', 'plugin frontend fixture')
            if unsafe: archive.writestr('../escape.py', 'refuse')

    def tearDown(self): self.temporary.cleanup()

    def test_dependency_and_restore_order(self):
        with self.assertRaises(RuntimeError): self.installer.apply('protondb')
        self.installer.apply('decky'); self.installer.apply('protondb')
        with self.assertRaises(RuntimeError): self.installer.rollback('decky')
        self.installer.rollback('protondb'); self.installer.rollback('decky')
        self.assertFalse(self.installer.unit.exists())

    def test_single_failure_retry_does_not_reinstall_other_plugins(self):
        self.installer.apply('decky'); self.installer.apply('steamgriddb')
        first_epoch = self.installer.epoch('steamgriddb', False)[1]['epoch']
        self.package('protondb', unsafe=True)
        with self.assertRaises(RuntimeError): self.installer.apply('protondb')
        self.assertFalse((self.root / 'escape.py').exists())
        self.package('protondb'); self.installer.apply('protondb')
        self.assertEqual(self.installer.epoch('steamgriddb', False)[1]['epoch'], first_epoch)
        self.installer.rollback('protondb'); self.installer.rollback('steamgriddb'); self.installer.rollback('decky')

    def test_repeat_restore_and_fresh_reinstall(self):
        for iteration in range(2):
            for component in ('decky', 'steamgriddb', 'protondb'):
                self.installer.apply(component); self.installer.apply(component)
            for component in ('protondb', 'steamgriddb', 'decky'): self.installer.rollback(component)
        self.assertFalse((self.installer.code / 'services').exists())

    def test_unknown_existing_loader_is_preserved(self):
        self.installer.unit.write_bytes(b'Existing independent loader unit')
        with self.assertRaises(RuntimeError): self.installer.apply('decky')
        self.installer.rollback('decky')
        self.assertEqual(self.installer.unit.read_bytes(), b'Existing independent loader unit')


if __name__ == '__main__': unittest.main()
