"""Exercise Linux permissions as deck, not as the root installer."""
import os
from pathlib import Path
import tempfile
import unittest
from runtime_access import require_access, verify_runtime_access


class RuntimeAccessChecks(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.root.chmod(0o755)
        for name in ('etc/dbus-1/session.d', 'usr/bin', 'usr/lib', 'usr/share', 'var/lib',
                     'home/deck/.local/lib', 'home/deck/homebrew/plugins/test', 'opt/oxp3-test/lib'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        (self.root/'etc/passwd').write_text('deck:x:1000:1000::/home/deck:/bin/sh\n')
        (self.root/'etc/group').write_text('deck:x:1000:\nshared:x:1002:deck\n')
        self.files = ['etc/dbus-1/session.d/test.conf', 'opt/oxp3-test/lib/test.so',
                      'home/deck/.local/lib/test.so', 'home/deck/homebrew/plugins/test/main.py']
        for name in self.files: (self.root/name).write_text('test\n')
        self.components = {'test': {'status': 'files_installed', 'files': self.files}}

    def tearDown(self): self.scratch.cleanup()

    def test_rejects_each_root_only_ancestor_and_preserves_private_state(self):
        private = self.root/'etc/private'; private.mkdir(mode=0o700)
        (private/'secret').write_text('private\n'); (private/'secret').chmod(0o600)
        self.assertGreater(verify_runtime_access(self.root, self.components), len(self.files))
        for name in ('etc/dbus-1', 'home/deck/.local/lib', 'opt/oxp3-test',
                     'home/deck/homebrew', 'var/lib'):
            path = self.root/name; path.chmod(0o700)
            try:
                with self.assertRaisesRegex(RuntimeError, 'Deck cannot access'):
                    verify_runtime_access(self.root, self.components)
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            finally: path.chmod(0o755)
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        self.assertEqual((private/'secret').stat().st_mode & 0o777, 0o600)

    def test_depmod_outputs_must_be_readable(self):
        path = self.root/'usr/lib/modules/test/modules.dep'; path.parent.mkdir(parents=True)
        path.write_text(''); path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'modules.dep'):
            verify_runtime_access(self.root, self.components)
        path.chmod(0o644)
        verify_runtime_access(self.root, self.components)

    def test_image_groups_and_absolute_symlinks(self):
        target = self.root/'usr/share/group-file'; target.write_text('test')
        os.chown(target, 0, 1002); target.chmod(0o640)
        (self.root/'group-link').symlink_to('/usr/share/group-file')
        self.assertEqual(require_access(self.root, {'group-link': os.R_OK}), 1)
        target.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'group-link'):
            require_access(self.root, {'group-link': os.R_OK})


if __name__ == '__main__': unittest.main()
