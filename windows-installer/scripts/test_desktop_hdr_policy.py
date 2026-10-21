"""Regression checks for the pinned desktop-HDR runtime payload gate."""
from pathlib import Path
import io
import tarfile
import tempfile
import unittest

from desktop_hdr_policy import (
    DesktopHdrPolicyError,
    POLICY_MARKER,
    TRIAL_MARKER,
    read_desktop_hdr_runtime,
    validate_desktop_hdr_runtime,
)


CONTROL = 'bin/oxp3-mapped-hdr-control'
KWIN = 'lib/libkwin.so.6.7.3'
KWIN_SONAME = 'lib/libkwin.so.6'
KWIN_LINK = 'lib/libkwin.so'


def _archive(path, binaries, extra=()):
    with tarfile.open(path, 'w') as archive:
        for name, data in (*binaries.items(), *extra):
            info = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                if data[0] == 'directory':
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.type = tarfile.SYMTYPE
                    info.linkname = data[0]
                    info.mode = 0o777
                    archive.addfile(info)
            else:
                info.mode = 0o755 if name.startswith('bin/') else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))


class DesktopHdrPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'runtime.tar'
        self.good = {
            CONTROL: b'frontend ' + POLICY_MARKER + TRIAL_MARKER,
            KWIN: b'compositor ' + POLICY_MARKER + TRIAL_MARKER,
            'bin/oxp3-hdr-pattern': b'HDR10 renderer ' + TRIAL_MARKER,
        }

    def test_edid_only_runtime_is_accepted_and_readable(self):
        _archive(self.path, self.good, extra=(
            (KWIN_SONAME, ('libkwin.so.6.7.3',)),
            (KWIN_LINK, ('libkwin.so.6',)),
        ))
        validate_desktop_hdr_runtime(self.path)
        files, modes = read_desktop_hdr_runtime(self.path)
        self.assertEqual(files[CONTROL], self.good[CONTROL])
        self.assertEqual(files[KWIN], self.good[KWIN])
        self.assertEqual(files[KWIN_SONAME], self.good[KWIN])
        self.assertEqual(files[KWIN_LINK], self.good[KWIN])
        self.assertEqual(modes[CONTROL], 0o755)

    def test_loaded_soname_cannot_be_a_stale_regular_file(self):
        _archive(self.path, self.good, extra=(
            (KWIN_SONAME, b'ONE-NETBOOK ONEXPLAYER 3'),
            (KWIN_LINK, ('libkwin.so.6',)),
        ))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'SONAME entry must be a symbolic link'):
            validate_desktop_hdr_runtime(self.path)

    def test_soname_must_resolve_to_the_validated_compositor(self):
        _archive(self.path, {**self.good, 'lib/old-kwin.so': b'old compositor'},
                 extra=(
                     (KWIN_SONAME, ('old-kwin.so',)),
                     (KWIN_LINK, ('libkwin.so.6',)),
                 ))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'does not resolve to the validated compositor'):
            validate_desktop_hdr_runtime(self.path)

    def test_soname_aliases_cannot_be_directories(self):
        _archive(self.path, self.good, extra=(
            (KWIN_SONAME, ('directory',)),
            (KWIN_LINK, ('directory',)),
        ))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'SONAME entry must be a symbolic link'):
            validate_desktop_hdr_runtime(self.path)

    def test_required_binary_cannot_be_a_directory(self):
        _archive(self.path, {KWIN: self.good[KWIN]}, extra=((CONTROL, ('directory',)),))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'Required desktop-HDR binary must be a regular file'):
            validate_desktop_hdr_runtime(self.path)

    def test_both_kwin_links_are_required(self):
        _archive(self.path, self.good)
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'missing a KWin SONAME link'):
            validate_desktop_hdr_runtime(self.path)

    def test_old_renderer_or_missing_trial_profile_is_rejected(self):
        for name in self.good:
            with self.subTest(name=name):
                binaries = dict(self.good)
                binaries[name] = binaries[name].replace(TRIAL_MARKER, b'old')
                _archive(self.path, binaries)
                with self.assertRaisesRegex(DesktopHdrPolicyError, '475/700 trial marker'):
                    validate_desktop_hdr_runtime(self.path)

    def test_renderer_must_be_present(self):
        binaries = {name: data for name, data in self.good.items() if name != 'bin/oxp3-hdr-pattern'}
        _archive(self.path, binaries, extra=((KWIN_SONAME, ('libkwin.so.6.7.3',)), (KWIN_LINK, ('libkwin.so.6',))))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'missing required binaries'):
            validate_desktop_hdr_runtime(self.path)

    def test_old_model_locked_runtime_is_rejected(self):
        stale = {CONTROL: b'ONE-NETBOOK ONEXPLAYER 3', KWIN: b'/sys/class/dmi/id/product_name'}
        _archive(self.path, stale)
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'EDID-only policy marker'):
            validate_desktop_hdr_runtime(self.path)

    def test_runtime_with_new_marker_but_dmi_gate_is_rejected(self):
        for token in (b'ONE-NETBOOK', b'ONEXPLAYER 3', b'/sys/class/dmi/id/sys_vendor',
                      '/sys/class/dmi/id/product_name'.encode('utf-16le')):
            with self.subTest(token=token):
                binaries = dict(self.good)
                binaries[KWIN] += token
                _archive(self.path, binaries)
                with self.assertRaisesRegex(DesktopHdrPolicyError, 'model hard gate'):
                    validate_desktop_hdr_runtime(self.path)

    def test_both_frontend_and_compositor_need_the_new_marker(self):
        binaries = dict(self.good)
        binaries[KWIN] = b'old compositor'
        _archive(self.path, binaries)
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'EDID-only policy marker'):
            validate_desktop_hdr_runtime(self.path)

    def test_unsafe_paths_and_links_are_rejected(self):
        _archive(self.path, self.good, extra=(('../../../outside', b'escape'),))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'Unsafe desktop-HDR runtime archive path'):
            validate_desktop_hdr_runtime(self.path)
        _archive(self.path, self.good, extra=(('lib/libkwin.so', ('../../outside',)),))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'External desktop-HDR runtime link'):
            validate_desktop_hdr_runtime(self.path)

    def test_required_binary_cannot_be_substituted_by_a_symlink(self):
        binaries = {KWIN: self.good[KWIN]}
        _archive(self.path, binaries, extra=((CONTROL, ('kwin.so.6.7.3',)),))
        with self.assertRaisesRegex(DesktopHdrPolicyError, 'must be a regular file'):
            validate_desktop_hdr_runtime(self.path)

    def test_maintenance_and_installer_guards_are_byte_synchronized(self):
        repository = Path(__file__).resolve().parents[2]
        installer = Path(__file__).resolve().parent / 'desktop_hdr_policy.py'
        maintenance = repository / 'steamos-maintenance/desktop_hdr_policy.py'
        self.assertEqual(installer.read_bytes(), maintenance.read_bytes())


if __name__ == '__main__':
    unittest.main()
