"""Portable tests for game-controlled FG and explicit XeFG multiplier requests."""
import contextlib
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from opti import OptiMixin


class MultiplierSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.ini = root / 'OptiScaler.ini'
        self.ini.write_text('[FrameGen]\nEnabled=true\nFGOutput=xefg\n[XeFG]\nInterpolationCount=3\n')
        self.mirror = root / 'mirror.ini'
        self.record = dict(version='0.9.4', executable='game.exe', status='active')
        self.info = dict(appid=42, prefix=str(root / 'prefix'), game=str(root),
                         optis=['OptiScaler.ini'], state=None)
        self.manager = OptiMixin()
        self.manager._settings_context = lambda _: (self.record, self.info, self.ini, [self.ini, self.mirror])
        self.manager.opti_record = lambda _: self.record
        self.manager.opti_save = lambda *_: None
        self.manager.runtime = lambda: SimpleNamespace(prefix_lock=lambda _: contextlib.nullcontext(),
                                                       game_idle=lambda *_: None, atomic_copy=shutil.copyfile)

        def journal(_appid, _record, _ini, _targets, data):
            after = root / 'after.ini'
            after.write_bytes(data)
            return dict(after=str(after), status='applying')

        self.manager._settings_journal = journal

    def save(self, multiplier):
        settings = dict(sr='xess', fg='xefg', fg_input='upscaler', spoof='real')
        if multiplier is not None:
            settings['fg_multiplier'] = multiplier
        self.manager.opti_settings(42, settings)
        self.assertEqual(self.ini.read_bytes(), self.mirror.read_bytes())
        return self.manager.opti_status(self.info)['settings']

    def test_four_notches_and_return_to_native_disable_interception(self):
        for multiplier, count in [('2', '1'), ('3', '2'), ('4', '3'), ('native', 'auto')]:
            with self.subTest(multiplier=multiplier):
                saved = self.save(multiplier)
                self.assertEqual(saved['fg_multiplier'], multiplier)
                self.assertIn('InterpolationCount=' + count, self.ini.read_text())
                self.assertEqual(saved['fg'], 'native' if multiplier == 'native' else 'xefg')
        self.assertIn('Enabled=false', self.ini.read_text())
        self.assertIn('FGOutput=nofg', self.ini.read_text())
        self.assertEqual(self.record['settings_undo']['status'], 'saved')

    def test_legacy_request_still_means_two_and_upstream_auto_is_not_native(self):
        self.assertEqual(self.save(None)['fg_multiplier'], '2')
        self.ini.write_text('[FrameGen]\nEnabled=true\nFGOutput=xefg\n[XeFG]\nInterpolationCount=auto\n')
        self.assertEqual(self.manager.opti_status(self.info)['settings']['fg_multiplier'], '2')

    def test_invalid_request_does_not_write(self):
        before = self.ini.read_bytes()
        for invalid in ['1', '5', 'auto', 4]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.save(invalid)
            self.assertEqual(self.ini.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
