from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxp3_maintenance.display_language import detect_language


class DisplayLanguageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / '.config'
        self.config.mkdir()

    def detect(self, env):
        with mock.patch('locale.getlocale', return_value=('en_US', 'UTF-8')):
            return detect_language(environ=env, home=self.home)

    def kde(self, content='[Formats]\nLANG=en_US.UTF-8\n[Translations]\nLANGUAGE=zh_CN\n'):
        (self.config / 'plasma-localerc').write_text(content, encoding='utf-8')

    def test_kde_chinese_display_with_english_formats(self):
        self.kde()
        self.assertEqual(self.detect({'LANG': 'en_US.UTF-8'}), 'zh')

    def test_session_translation_precedes_stale_kde_setting(self):
        self.kde()
        self.assertEqual(self.detect({'LANGUAGE': 'en_US:zh_CN'}), 'en')

    def test_language_list_and_variants(self):
        for value in ('fr:zh_CN:en', 'zh-TW.UTF-8', 'zh_HK', 'zh'):
            with self.subTest(value=value):
                self.assertEqual(self.detect({'LANGUAGE': value}), 'zh')

    def test_message_locale_precedes_regional_formats(self):
        self.assertEqual(self.detect({'LC_MESSAGES': 'zh_CN.UTF-8', 'LANG': 'en_US.UTF-8'}), 'zh')
        self.assertEqual(self.detect({'LC_ALL': 'C', 'LC_MESSAGES': 'zh_CN'}), 'en')

    def test_missing_invalid_and_unsupported_settings_fall_back(self):
        for content in ('[broken', '[Translations]\nLANGUAGE=fr_FR\n', '[Formats]\nLANG=zh_CN\n'):
            self.kde(content)
            self.assertEqual(self.detect({'LANG': 'en_US.UTF-8'}), 'en')
        with mock.patch('locale.getlocale', side_effect=ValueError):
            self.assertEqual(detect_language(environ={}, home=self.home), 'en')

    def test_xdg_config_directory_and_no_environment_mutation(self):
        self.kde()
        other = self.home / 'custom'
        other.mkdir()
        (other / 'plasma-localerc').write_text('[Translations]\nLANGUAGE=en\n')
        env = {'XDG_CONFIG_HOME': str(other), 'LANG': 'zh_CN.UTF-8'}
        before = dict(env)
        self.assertEqual(self.detect(env), 'en')
        self.assertEqual(env, before)

    def test_both_frontends_use_shared_detection(self):
        from types import SimpleNamespace
        from oxp3_maintenance import touch_ui, gui
        args = SimpleNamespace(bundle=None, bundle_dir=None)
        with mock.patch.object(touch_ui, 'detect_language', return_value='zh'), \
                mock.patch.object(touch_ui, 'TouchWindow') as window, \
                mock.patch('oxp3_maintenance.desktop_service.DesktopService') as service, \
                mock.patch.object(touch_ui.os, 'geteuid', return_value=1000, create=True):
            touch_ui.run(args)
            self.assertEqual(window.call_args.kwargs['language'], 'zh')
            self.assertEqual(service.call_args.kwargs['language'], 'zh')
        with mock.patch.object(gui, 'detect_language', return_value='zh'), \
                mock.patch.object(gui.shutil, 'which', return_value='/usr/bin/tool'), \
                mock.patch.object(gui.os, 'geteuid', return_value=1000, create=True), \
                mock.patch.object(gui, '_dialog', side_effect=gui.Cancelled) as dialog:
            gui.run(args)
            self.assertEqual(dialog.call_args.args[1], gui.ZH['title'])
