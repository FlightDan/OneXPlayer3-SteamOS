"""Native Decky ordering defaults, without a running Steam/Decky session."""
import json
from pathlib import Path
import tempfile
import unittest
from decky_order import SETTINGS, PLUGINS, PRIORITY, files


class DeckyOrderChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, relative, data):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')
        return path

    def plugin(self, folder, name):
        self.write(PLUGINS+'/'+folder+'/plugin.json', json.dumps({'name': name}))

    def test_all_installed_names_follow_priority_and_none_sort_before_it(self):
        for index, name in enumerate(['SteamGridDB', *reversed(PRIORITY), 'Custom 用户插件']):
            self.plugin(str(index), name)
        value = json.loads(files(self.root)[SETTINGS]['data'])
        order = value['pluginOrder']
        self.assertEqual(order[:len(PRIORITY)], list(PRIORITY))
        self.assertEqual(set(order), {'SteamGridDB', *PRIORITY, 'Custom 用户插件'})
        self.assertEqual(len(order), len(PRIORITY) + 2)
        self.assertIs(value['sortPlugins'], False)

    def test_only_deployed_plugins_enter_default_order(self):
        self.plugin('cpu', 'OXP3 CPU'); self.plugin('thirdparty', 'SteamGridDB')
        self.assertEqual(json.loads(files(self.root)[SETTINGS]['data'])['pluginOrder'], ['OXP3 CPU', 'SteamGridDB'])

    def test_new_light_inserts_once_without_reordering_custom_preferences(self):
        self.plugin('light', 'OXP3 Light')
        custom = ['Custom', 'OXP3 Battery', 'SteamGridDB', 'OXP3 CPU']
        self.write(SETTINGS, json.dumps({'pluginOrder': custom, 'sortPlugins': False, 'language': 'zh-CN'}))
        data = files(self.root)[SETTINGS]['data']
        value = json.loads(data)
        self.assertEqual(value['pluginOrder'], ['Custom', 'OXP3 Battery', 'OXP3 Light', 'SteamGridDB', 'OXP3 CPU'])
        self.assertEqual([name for name in value['pluginOrder'] if name != 'OXP3 Light'], custom)
        self.assertEqual(value['language'], 'zh-CN')
        self.write(SETTINGS, data.decode())
        self.assertEqual(files(self.root), {})

    def test_new_light_preserves_explicit_alphabetical_sort_and_empty_order(self):
        self.plugin('light', 'OXP3 Light')
        for value in ({'pluginOrder': [], 'sortPlugins': False},
                      {'pluginOrder': ['OXP3 Battery'], 'sortPlugins': True},
                      {'pluginOrder': 'unfamiliar'}, {'sortPlugins': False}):
            self.write(SETTINGS, json.dumps(value))
            self.assertEqual(files(self.root), {})

    def test_no_own_plugins_leaves_defaults_untouched(self):
        self.plugin('thirdparty', 'SteamGridDB')
        self.assertEqual(files(self.root), {})

    def test_existing_order_even_empty_and_explicit_sort_are_preserved(self):
        self.plugin('cpu', 'OXP3 CPU')
        for value in ({'pluginOrder': []}, {'pluginOrder': ['SteamGridDB', 'OXP3 CPU']},
                      {'sortPlugins': True}, {'sortPlugins': False}):
            with self.subTest(value=value):
                path = self.write(SETTINGS, json.dumps(value)); before = path.read_bytes()
                self.assertEqual(files(self.root), {})
                self.assertEqual(path.read_bytes(), before)

    def test_unrelated_settings_survive_default_creation(self):
        self.plugin('cpu', 'OXP3 CPU')
        self.write(SETTINGS, '{"language":"zh-CN","hiddenPlugins":["SteamGridDB"]}')
        value = json.loads(files(self.root)[SETTINGS]['data'])
        self.assertEqual(value['language'], 'zh-CN')
        self.assertEqual(value['hiddenPlugins'], ['SteamGridDB'])

    def test_invalid_existing_settings_are_not_repaired(self):
        self.plugin('cpu', 'OXP3 CPU')
        for data in ('bad json', '[]', 'null'):
            self.write(SETTINGS, data)
            self.assertEqual(files(self.root), {})

    def test_legacy_loader_settings_are_preserved(self):
        self.plugin('cpu', 'OXP3 CPU')
        for relative in ('home/deck/homebrew/loader.json', 'home/deck/homebrew/settings/loader.json'):
            with self.subTest(relative=relative):
                path = self.write(relative, '{"pluginOrder":["Custom","OXP3 CPU"]}')
                self.assertEqual(files(self.root), {})
                path.unlink()

    def test_duplicate_display_names_refused(self):
        self.plugin('one', 'OXP3 CPU'); self.plugin('two', 'OXP3 CPU')
        with self.assertRaisesRegex(RuntimeError, 'duplicate'): files(self.root)

    def test_settings_and_plugin_symlinks_refused(self):
        self.plugin('cpu', 'OXP3 CPU')
        outside = self.write('outside.json', '{}')
        settings = self.root/SETTINGS; settings.parent.mkdir(parents=True)
        settings.symlink_to(outside)
        with self.assertRaises(RuntimeError): files(self.root)
        settings.unlink()
        (self.root/PLUGINS/'linked').symlink_to(self.root/PLUGINS/'cpu', target_is_directory=True)
        with self.assertRaises(RuntimeError): files(self.root)


if __name__ == '__main__': unittest.main()
