"""Offline update-hold tests; never invoke services, devices, or the Steam client."""
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import update_hold as hold

COMPONENTS = Path(__file__).resolve().parent
sys.path.insert(0, str(COMPONENTS))

OFFICIAL = (b'# vendor configuration retained\n[Server]\n'
            b'ImagesUrl = https://steamdeck-images.steamos.cloud/\n'
            b'MetaUrl = https://steamdeck-atomupd.steamos.cloud/meta\n'
            b'Variants = steamdeck\n'
            b'Branches = stable;rc;beta;bc;preview;pc;main\n'
            b'BranchesDev = main;staging\n')
RELEASE = b'ID=steamos\nVERSION_ID="3.10"\nBUILD_ID=20260924.1000\n'
GENERIC_RELEASE = b'NAME="SteamOS"\nID=steamos\nID_LIKE=arch\nVERSION_CODENAME=holo\n'
ATOM_UNIT = (b'[Unit]\nDescription=Atomic Update Daemon\n[Service]\n'
             b'Type=dbus\nBusName=com.steampowered.Atomupd1\n'
             b'ExecStartPre=-/usr/bin/true\nExecStart=/usr/lib/atomupd-daemon\n')
MANIFEST = {'product': 'steamos', 'release': 'holo', 'variant': 'steamdeck', 'arch': 'amd64',
            'version': '3.10.0', 'buildid': '20260924.1000', 'branch': 'main', 'default_update_branch': 'main',
            'introduces_checkpoint': 0, 'requires_checkpoint': 0, 'shadow_checkpoint': False,
            'estimated_size': 100, 'skip': False}


class CandidateChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard = patch.object(hold, '_ROOT_UID', os.geteuid() if os.name == 'posix' else 0)
        guard.start(); self.addCleanup(guard.stop)
        guard = patch.object(hold, '_ROOT_GID', os.getegid() if os.name == 'posix' else 0)
        guard.start(); self.addCleanup(guard.stop)
        self.put('usr/lib/os-release', GENERIC_RELEASE)
        self.put('etc/os-release', RELEASE)
        self.put(hold.VENDOR_CLIENT, OFFICIAL)
        self.put(hold.VENDOR_MANIFEST, json.dumps(MANIFEST).encode())
        if os.name == 'nt':
            # Standard links are represented only for pure mapping tests on
            # Windows; dedicated symlink tests still use actual OS symlinks.
            for relative in (hold.STANDARD_CLIENT, hold.STANDARD_MANIFEST): self.put(relative, b'fixture standard link')
            original = hold._expected_link
            def expected(root, relative, targets, required=True):
                path = root/relative
                if relative in (hold.STANDARD_CLIENT, hold.STANDARD_MANIFEST) and not path.is_symlink() and path.read_bytes() == b'fixture standard link': return
                return original(root, relative, targets, required)
            guard = patch.object(hold, '_expected_link', side_effect=expected);guard.start();self.addCleanup(guard.stop)
            original_readlink = os.readlink
            def readlink(path, *args, **kwargs):
                if Path(path) == self.root/hold.STANDARD_MANIFEST and not Path(path).is_symlink() and Path(path).read_bytes() == b'fixture standard link':
                    return '/usr/lib/steamos-atomupd/manifest.json'
                return original_readlink(path, *args, **kwargs)
            guard = patch.object(hold.os, 'readlink', side_effect=readlink);guard.start();self.addCleanup(guard.stop)
        else:
            self.link(hold.STANDARD_CLIENT, '/usr/lib/steamos-atomupd/client.conf')
            self.link(hold.STANDARD_MANIFEST, '/usr/lib/steamos-atomupd/manifest.json')
        self.put('usr/lib/systemd/system/atomupd.service', ATOM_UNIT)
        self.put('usr/lib/systemd/system/rauc.service', b'[Service]\nExecStart=/usr/bin/rauc service\n')
        self.put(hold.STOCK_RAUC, hold.STOCK_RAUC_DATA)
        self.put('etc/steamos-atomupd/preferences.conf', b'[Preferences]\nBranch=beta\n')

    def put(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if os.name == 'posix': path.chmod(0o644)
        return path

    def link(self, relative, target, directory=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try: path.symlink_to(target, target_is_directory=directory)
        except OSError as error: self.skipTest('Fixture symlinks unavailable: ' + str(error))
        return path

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): ('link', os.readlink(p)) if p.is_symlink()
                else ('file', p.read_bytes()) for p in self.root.rglob('*') if p.is_file() or p.is_symlink()}

    def stage(self):
        output = hold.files(self.root)
        for name, item in output.items(): self.put(name, item['data'])
        return output

    def test_read_only_regular_file_map_preserves_identity_and_preferences(self):
        before = self.snapshot(); output = hold.files(self.root)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(output), 18)
        self.assertTrue(all(set(item) == {'data', 'mode'} and type(item['data']) is bytes
                            and item['mode'] == 0o644 for item in output.values()))
        self.assertFalse(set(output) & {'etc/os-release', 'usr/lib/os-release', hold.STANDARD_CLIENT,
                                       hold.VENDOR_CLIENT, 'etc/steamos-atomupd/manifest.json',
                                       'etc/steamos-atomupd/preferences.conf'})
        expected = OFFICIAL.replace(b'https://steamdeck-atomupd.steamos.cloud/meta', hold.FEED_URL.encode())
        self.assertEqual(output[hold.CLIENT]['data'], expected)
        self.assertEqual(output[hold.DROPIN]['data'], hold.DROPIN_DATA)
        self.assertNotIn(b'ExecStartPre', hold.DROPIN_DATA)
        self.assertEqual((self.root/'usr/lib/systemd/system/atomupd.service').read_bytes(), ATOM_UNIT)

    def test_complete_empty_metadata_for_release_and_development_branches(self):
        output = hold.files(self.root)
        prefix = hold.BASE + '/feed/holo/steamos/amd64/steamdeck/'
        for branch in ('stable', 'rc', 'beta', 'bc', 'preview', 'pc', 'main', 'staging'):
            for suffix in (branch+'.json', branch+'/3.10.0/20260924.1000.json'):
                self.assertEqual(output[prefix+suffix]['data'], b'{}\n')

    def test_exact_candidate_retry_is_idempotent(self):
        output = self.stage(); before = self.snapshot()
        self.assertEqual(hold.files(self.root), output)
        self.assertEqual(self.snapshot(), before)

    def test_unsupported_effective_image_fails_without_mutation(self):
        for release in (RELEASE.replace(b'3.10', b'3.8'), RELEASE.replace(b'20260924.1000', b'other'),
                        RELEASE.replace(b'steamos', b'arch'), GENERIC_RELEASE):
            self.put('etc/os-release', release); before = self.snapshot()
            with self.assertRaisesRegex(RuntimeError, 'Unsupported image'): hold.files(self.root)
            self.assertEqual(self.snapshot(), before)

    def test_effective_etc_identity_overrides_generic_vendor_without_writes(self):
        self.assertEqual((self.root/'usr/lib/os-release').read_bytes(), GENERIC_RELEASE)
        before = self.snapshot()
        self.assertEqual(len(hold.files(self.root)), 18)
        self.assertEqual(self.snapshot(), before)
        # A correct vendor file cannot rescue an unsupported effective /etc file.
        self.put('usr/lib/os-release', RELEASE)
        self.put('etc/os-release', RELEASE.replace(b'3.10', b'3.8'))
        with self.assertRaisesRegex(RuntimeError, 'Unsupported image'): hold.files(self.root)

    def test_official_release_symlink_is_supported_without_following_host(self):
        self.put('usr/lib/os-release', RELEASE)
        path = self.root/'etc/os-release'; path.unlink()
        self.link('etc/os-release', '../usr/lib/os-release')
        self.assertEqual(len(hold.files(self.root)), 18)
        path.unlink(); self.link('etc/os-release', '/usr/lib/os-release')
        self.assertEqual(len(hold.files(self.root)), 18)
        self.put('usr/lib/os-release', GENERIC_RELEASE)
        with self.assertRaisesRegex(RuntimeError, 'Unsupported image'): hold.files(self.root)

    def test_arbitrary_standard_config_link_and_regular_copy_are_refused(self):
        path = self.root/hold.STANDARD_CLIENT; path.unlink()
        sentinel = self.put('sentinel', OFFICIAL)
        self.link(hold.STANDARD_CLIENT, sentinel)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected official link'): hold.files(self.root)
        self.assertEqual(sentinel.read_bytes(), OFFICIAL)
        path.unlink(); self.put(hold.STANDARD_CLIENT, OFFICIAL)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected official link'): hold.files(self.root)

    def test_standard_relative_vendor_link_is_supported(self):
        (self.root/hold.STANDARD_CLIENT).unlink()
        self.link(hold.STANDARD_CLIENT, '../../usr/lib/steamos-atomupd/client.conf')
        self.assertEqual(len(hold.files(self.root)), 18)

    @unittest.skipUnless(os.name == 'posix', 'POSIX link targets preserve literal backslashes')
    def test_backslashes_do_not_make_a_posix_link_an_official_target(self):
        for relative, target in ((hold.STANDARD_CLIENT, r'\usr\lib\steamos-atomupd\client.conf'),
                                 (hold.STANDARD_MANIFEST, r'..\..\lib\steamos-atomupd\manifest.json')):
            path = self.root/relative
            original = os.readlink(path)
            path.unlink(); self.link(relative, target)
            with self.assertRaisesRegex(RuntimeError, 'Unexpected official link'): hold.files(self.root)
            path.unlink(); self.link(relative, original)

    def test_manifest_identity_checkpoint_legacy_and_unknown_schema_are_refused(self):
        for change in ({'version':'3.8.28'}, {'buildid':'other'}, {'variant':'other'}, {'arch':'x86_64'},
                       {'introduces_checkpoint':1}, {'requires_checkpoint':1}, {'checkpoint':True},
                       {'legacyvariant':'steamdeck-main'}, {'shadow_checkpoint':True}, {'schema':2}):
            with self.subTest(change=change):
                data = dict(MANIFEST, **change); self.put(hold.VENDOR_MANIFEST, json.dumps(data).encode())
                before = self.snapshot()
                with self.assertRaisesRegex(RuntimeError, 'Unsupported official manifest'): hold.files(self.root)
                self.assertEqual(self.snapshot(), before)

    def test_official_manifest_lib_alias_is_verified_inside_image(self):
        path = self.root/hold.STANDARD_MANIFEST; path.unlink()
        self.link(hold.STANDARD_MANIFEST, '../../lib/steamos-atomupd/manifest.json')
        self.link('lib', 'usr/lib', directory=True)
        self.assertEqual(len(hold.files(self.root)), 18)
        (self.root/'lib').unlink(); self.link('lib', 'outside', directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected official link'): hold.files(self.root)

    def test_vendor_link_and_output_ancestor_link_are_refused(self):
        source = self.root/hold.VENDOR_CLIENT; source.unlink()
        sentinel = self.put('sentinel', OFFICIAL); self.link(hold.VENDOR_CLIENT, sentinel)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'): hold.files(self.root)
        source.unlink(); self.put(hold.VENDOR_CLIENT, OFFICIAL)
        self.link('etc/oxp3-installer', self.root/'elsewhere', directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'): hold.files(self.root)
        self.assertFalse((self.root/'elsewhere').exists())

    def test_existing_mask_or_custom_unit_is_refused(self):
        for directory in ('etc/systemd/system', 'run/systemd/system', 'usr/local/lib/systemd/system',
                          'etc/systemd/system.attached', 'run/systemd/system.attached'):
            for service in hold.SERVICES:
                for data in (b'', b'[Service]\nExecStart=/custom\n'):
                    with self.subTest(directory=directory, service=service, data=data):
                        path = self.put(directory+'/'+service, data)
                        with self.assertRaisesRegex(RuntimeError, 'Conflicting updater unit'): hold.files(self.root)
                        self.assertEqual(path.read_bytes(), data); path.unlink()

    def test_mask_symlink_and_modified_vendor_execstart_are_refused(self):
        self.link('etc/systemd/system/atomupd.service', '/dev/null')
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'): hold.files(self.root)
        (self.root/'etc/systemd/system/atomupd.service').unlink()
        self.put('usr/lib/systemd/system/atomupd.service', ATOM_UNIT.replace(b'ExecStart=/usr/lib/atomupd-daemon', b'ExecStart=/custom'))
        with self.assertRaisesRegex(RuntimeError, 'Unsupported official atomupd'): hold.files(self.root)

    def test_any_other_service_or_global_dropin_is_refused(self):
        for path in ('etc/systemd/system/atomupd.service.d/00-custom.conf',
                     'usr/lib/systemd/system/atomupd.service.d/vendor.conf',
                     'run/systemd/system/rauc.service.d/custom.conf',
                     'etc/systemd/system/service.d/custom.conf'):
            with self.subTest(path=path):
                target = self.put(path, b'[Service]\nEnvironment=CUSTOM=1\n')
                with self.assertRaisesRegex(RuntimeError, 'Conflicting updater drop-in'): hold.files(self.root)
                target.unlink()

    def test_exact_official_rauc_dropin_is_preserved_and_never_a_target(self):
        before = self.snapshot(); output = hold.files(self.root)
        self.assertEqual(len(hold.STOCK_RAUC_DATA), 461)
        self.assertNotIn(hold.STOCK_RAUC, output)
        self.assertEqual((self.root/hold.STOCK_RAUC).read_bytes(), hold.STOCK_RAUC_DATA)
        self.assertEqual(self.snapshot(), before)

    def test_changed_official_rauc_dropin_is_refused_without_overwriting(self):
        for data in (hold.STOCK_RAUC_DATA+b'# personal\n',
                     hold.STOCK_RAUC_DATA.replace(b'rauc-override.sh', b'personal.sh'), b''):
            path = self.put(hold.STOCK_RAUC, data)
            with self.assertRaisesRegex(RuntimeError, 'Conflicting stock RAUC'): hold.files(self.root)
            self.assertEqual(path.read_bytes(), data)

    @unittest.skipUnless(os.name == 'posix', 'Unix mode and group ownership required')
    def test_official_rauc_dropin_requires_exact_mode_and_root_group(self):
        path = self.root/hold.STOCK_RAUC; path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'stock RAUC.*ownership or mode'): hold.files(self.root)
        path.chmod(0o644)
        with patch.object(hold, '_ROOT_GID', os.getegid()+1):
            with self.assertRaisesRegex(RuntimeError, 'stock RAUC.*ownership or mode'): hold.files(self.root)

    def test_own_file_conflict_is_preserved(self):
        for relative in (hold.CLIENT, hold.DROPIN,
                         hold.BASE+'/feed/holo/steamos/amd64/steamdeck/staging.json'):
            with self.subTest(relative=relative):
                path = self.put(relative, b'personal state')
                with self.assertRaisesRegex(RuntimeError, 'Conflicting candidate-owned'): hold.files(self.root)
                self.assertEqual(path.read_bytes(), b'personal state'); path.unlink()

    def test_unknown_candidate_directory_content_is_refused(self):
        path = self.put(hold.BASE+'/manifest.json', b'{}')
        with self.assertRaisesRegex(RuntimeError, 'Conflicting unknown'): hold.files(self.root)
        self.assertEqual(path.read_bytes(), b'{}')

    def test_changed_official_branches_and_metadata_url_are_refused(self):
        for data in (OFFICIAL.replace(b'main;staging', b'main'),
                     OFFICIAL.replace(b'https://steamdeck-atomupd.steamos.cloud/meta', b'https://custom/meta'),
                     b'[DEFAULT]\nExtra=yes\n'+OFFICIAL, OFFICIAL+b'Extra=yes\n'):
            self.put(hold.VENDOR_CLIENT, data)
            with self.assertRaisesRegex(RuntimeError, 'Unsupported official updater'): hold.files(self.root)

    def test_vendor_unit_type_and_bus_name_must_match_official_profile(self):
        for data in (ATOM_UNIT.replace(b'Type=dbus', b'Type=simple'),
                     ATOM_UNIT.replace(b'com.steampowered.Atomupd1', b'custom.Bus')):
            self.put('usr/lib/systemd/system/atomupd.service', data)
            with self.assertRaisesRegex(RuntimeError, 'Unsupported official atomupd'): hold.files(self.root)

    @unittest.skipUnless(os.name == 'posix', 'Unix permissions required')
    def test_writable_path_wrong_owner_and_own_file_mode_are_refused(self):
        path = self.root/'etc'; path.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'permissions'): hold.files(self.root)
        path.chmod(0o755)
        with patch.object(hold, '_ROOT_UID', os.geteuid()+1):
            with self.assertRaisesRegex(RuntimeError, 'permissions'): hold.files(self.root)
        self.stage(); path = self.root/hold.CLIENT; path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'file mode'): hold.files(self.root)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'Real integration journal requires Linux root')
    def test_real_apply_files_journal_restores_originals_and_preserves_later_edits(self):
        import integration
        before = self.snapshot(); output = hold.files(self.root)
        # One candidate file predates this transaction and must be retained.
        existing = self.put(hold.CLIENT, output[hold.CLIENT]['data'])
        state = self.root/'journal/slots/A'
        integration.apply_files(self.root, state, 'firstboot-update-hold-candidate', output, (0, 0))
        self.assertEqual(hold.files(self.root), output)
        transaction = integration.LogicalFiles(state/'firstboot-update-hold-candidate', self.root, output, (0,0))
        self.assertEqual(transaction.rollback(), [])
        self.assertEqual(existing.read_bytes(), output[hold.CLIENT]['data'])
        for relative in output:
            if relative != hold.CLIENT: self.assertFalse((self.root/relative).exists())
        for relative, value in before.items():
            if value[0] == 'file': self.assertEqual((self.root/relative).read_bytes(), value[1])
            else: self.assertEqual(os.readlink(self.root/relative), value[1])
        integration.apply_files(self.root, state, 'firstboot-update-hold-candidate', output, (0, 0))
        changed = self.put(hold.DROPIN, b'[Service]\nExecStart=/personal\n')
        transaction = integration.LogicalFiles(state/'firstboot-update-hold-candidate', self.root, output, (0,0))
        errors = transaction.rollback()
        self.assertEqual([e['path'] for e in errors], [str(changed)])
        self.assertEqual(changed.read_bytes(), b'[Service]\nExecStart=/personal\n')


if __name__ == '__main__': unittest.main()
