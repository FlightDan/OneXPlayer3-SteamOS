"""Portable strict INI comparison and live-file settings recovery tests."""
import contextlib
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from opti import OptiMixin, ini_equivalent


class Equivalence(unittest.TestCase):
    def test_bom_spacing_comments_and_order(self):
        self.assertTrue(ini_equivalent(b'[A]\nOne=true\nTwo=2\n',
                                     b'\xef\xbb\xbf; SimpleIni\n[A]\n\nTwo = 2\nOne = true\n'))

    def test_value_name_section_and_default_identity(self):
        original=b'[DEFAULT]\nBase=1\n[A]\nFlag=true\n'
        for changed in (b'[DEFAULT]\nBase=1\n[A]\nFlag=True\n',
                        b'[DEFAULT]\nBase=1\n[A]\nflag=true\n',
                        b'[DEFAULT]\nBase=1\n[a]\nFlag=true\n',
                        b'[A]\nBase=1\nFlag=true\n'):
            with self.subTest(changed=changed):self.assertFalse(ini_equivalent(original,changed))

    def test_duplicate_invalid_or_non_utf8_is_never_equivalent(self):
        for invalid in (b'[A]\nX=1\nX=1\n',b'[A]\nX=1\n[A]\nY=2\n',
                        b'not an ini\n',b'[A]\nX=\xff\n'):
            with self.subTest(invalid=invalid):self.assertFalse(ini_equivalent(invalid,invalid))

    def test_colon_separator_is_rejected(self):
        colon=b'[A]\nX:1\n'
        self.assertFalse(ini_equivalent(colon,colon))
        self.assertFalse(ini_equivalent(b'[A]\nX=1\n',colon))

    def test_default_and_casefold_duplicates_are_rejected(self):
        for invalid in (b'[DEFAULT]\nX=1\n[DEFAULT]\nY=2\n',
                        b'[DEFAULT]\nX=1\n[default]\nY=2\n',
                        b'[A]\nX=1\n[a]\nY=2\n',
                        b'[A]\nFoo=1\nfoo=2\n',
                        b'[DEFAULT]\nFoo=1\nfoo=2\n'):
            with self.subTest(invalid=invalid):self.assertFalse(ini_equivalent(invalid,invalid))

    def test_section_header_ambiguity_is_rejected(self):
        for invalid in (b'[A]ignored\nX=1\n',b'[ A ]\nX=1\n',b'[[A]]\nX=1\n'):
            with self.subTest(invalid=invalid):self.assertFalse(ini_equivalent(invalid,invalid))

    def test_non_ascii_whitespace_and_vertical_tab_are_rejected(self):
        for text in ('[A]\n\u00a0X=1\n','[A]\nX=\u00a01\n','[A]\nX=1\u00a0\n',
                     '[A]\n\vX=1\n','[A]\nX=1\v\n','[A]\n\v; comment\nX=1\n'):
            invalid=text.encode('utf-8')
            with self.subTest(text=text):
                self.assertFalse(ini_equivalent(invalid,invalid))
                self.assertFalse(ini_equivalent(b'[A]\nX=1\n',invalid))

    def test_comment_whitespace_does_not_change_values(self):
        self.assertTrue(ini_equivalent(b'[A]\nX=1\n', '[A]\n \t; comment\u00a0\v\nX=1\n'.encode('utf-8')))


class Manager(OptiMixin):
    def __init__(self, root):
        self.root=root; self.ini=root/'game/OptiScaler.ini';self.ini.parent.mkdir()
        self.folder=self.opti_path(42).parent/'settings-fixture';self.folder.mkdir(parents=True)
        self.mirror=self.folder/'mirror.ini'
        self.before=b'[DEFAULT]\nKeep=yes\n[FrameGen]\nEnabled=false\n'
        self.after=b'[DEFAULT]\nKeep=yes\n[FrameGen]\nEnabled=true\n'
        self.formatted=b'\xef\xbb\xbf[DEFAULT]\nKeep = yes\n\n[FrameGen]\nEnabled = true\n'
        (self.folder/'before.ini').write_bytes(self.before)
        (self.folder/'after.ini').write_bytes(self.after)
        files=[]
        for n,path in enumerate((self.ini,self.mirror)):
            path.write_bytes(self.after)
            saved=self.folder/f'observed-{n}.ini';saved.write_bytes(self.before+b'; mirror\n'*n)
            files.append(dict(path=str(path),observed=str(saved)))
        self.record=dict(version='0.9.4',executable='game.exe',settings_undo=dict(
            status='saved',folder=str(self.folder),ini=str(self.ini),version='0.9.4',
            executable='game.exe',before=str(self.folder/'before.ini'),after=str(self.folder/'after.ini'),files=files))
        self.copy_fail=None;self.save_fail=None
        self.rt=SimpleNamespace(prefix_lock=lambda p:contextlib.nullcontext(),game_idle=lambda *a:None,
                                no_symlink_parents=lambda p:None,atomic_copy=self.atomic_copy)

    def runtime(self):return self.rt
    def _settings_regular(self,path):
        if not path.is_file() or path.is_symlink():raise RuntimeError('普通文件')
    def _settings_context(self,*args):
        return copy.deepcopy(self.record),dict(prefix=str(self.root/'prefix')),self.ini,[self.ini,self.mirror]
    def opti_save(self,appid,record):
        if self.save_fail and self.save_fail(record):raise OSError('journal interrupted')
        self.record=copy.deepcopy(record)
    def atomic_copy(self,source,target):
        if self.copy_fail and self.copy_fail(source,target):raise OSError('copy interrupted')
        shutil.copyfile(source,target)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.m=Manager(Path(self.tmp.name))
    def restored(self):
        journal=self.m.record['settings_undo']
        self.assertEqual(journal['status'],'restored')
        for f in journal['files']:self.assertEqual(Path(f['path']).read_bytes(),Path(f['observed']).read_bytes())
        self.assertEqual((self.m.folder/'live-formatted.ini').read_bytes(),self.m.formatted)
    def test_formatted_live_is_archived_and_originals_restored(self):
        self.m.ini.write_bytes(self.m.formatted);self.m.opti_restore_settings(42);self.restored()
    def test_semantic_change_rejected_before_any_mirror_write(self):
        self.m.ini.write_bytes(self.m.formatted.replace(b'true',b'false'))
        with self.assertRaisesRegex(RuntimeError,'外部修改'):self.m.opti_restore_settings(42)
        self.assertEqual(self.m.mirror.read_bytes(),self.m.after)
        self.assertFalse((self.m.folder/'live-formatted.ini').exists())
    def test_duplicate_and_invalid_live_rejected(self):
        for invalid in (self.m.formatted+b'Enabled=true\n',b'not ini',b'\xff'):
            self.m.ini.write_bytes(invalid)
            with self.assertRaisesRegex(RuntimeError,'外部修改'):self.m.opti_restore_settings(42)
            self.assertEqual(self.m.mirror.read_bytes(),self.m.after)
    def test_formatted_mirror_rejected(self):
        self.m.ini.write_bytes(self.m.formatted);self.m.mirror.write_bytes(self.m.formatted)
        with self.assertRaisesRegex(RuntimeError,'外部修改'):self.m.opti_restore_settings(42)
        self.assertEqual(self.m.ini.read_bytes(),self.m.formatted)
        self.assertFalse((self.m.folder/'live-formatted.ini').exists())
    def test_applying_does_not_accept_formatting(self):
        self.m.record['settings_undo']['status']='applying';self.m.ini.write_bytes(self.m.formatted)
        with self.assertRaisesRegex(RuntimeError,'外部修改'):self.m.opti_restore_settings(42)
    def test_retry_after_capture_before_journal_write(self):
        self.m.ini.write_bytes(self.m.formatted);self.m.save_fail=lambda r:True
        with self.assertRaises(OSError):self.m.opti_restore_settings(42)
        self.assertEqual(self.m.record['settings_undo']['status'],'saved')
        self.assertEqual((self.m.folder/'live-formatted.ini').read_bytes(),self.m.formatted)
        self.m.save_fail=None;self.m.opti_restore_settings(42);self.restored()
    def test_retry_before_live_restore(self):
        self.m.ini.write_bytes(self.m.formatted);self.m.copy_fail=lambda s,t:t==self.m.ini
        with self.assertRaisesRegex(RuntimeError,'设置恢复未完成'):self.m.opti_restore_settings(42)
        self.assertEqual(self.m.record['settings_undo']['status'],'restoring')
        self.m.copy_fail=None;self.m.opti_restore_settings(42);self.restored()
    def test_retry_after_live_restore_or_final_journal_failure(self):
        for boundary in ('mirror','journal'):
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as d:
                    self.m=Manager(Path(d));self.m.ini.write_bytes(self.m.formatted)
                    if boundary=='mirror':self.m.copy_fail=lambda s,t:t==self.m.mirror
                    else:self.m.save_fail=lambda r:r['settings_undo']['status']=='restored'
                    with self.assertRaisesRegex(RuntimeError,'设置恢复未完成'):self.m.opti_restore_settings(42)
                    self.m.copy_fail=None;self.m.save_fail=None;self.m.opti_restore_settings(42);self.restored()
    def test_conflicting_capture_refused(self):
        self.m.ini.write_bytes(self.m.formatted);(self.m.folder/'live-formatted.ini').write_bytes(b'external')
        with self.assertRaisesRegex(RuntimeError,'格式备份'):self.m.opti_restore_settings(42)
        self.assertEqual(self.m.ini.read_bytes(),self.m.formatted)
    def test_capture_journal_escape_refused(self):
        self.m.record['settings_undo']['live_format_capture']=str(self.m.root/'outside.ini')
        with self.assertRaisesRegex(RuntimeError,'备份路径'):self.m.opti_restore_settings(42)


if __name__=='__main__':unittest.main()
