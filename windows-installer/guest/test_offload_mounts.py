"""Exercise the boot-visible /opt mount on an isolated Linux scratch filesystem."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,'/mnt/payload/components')
from offload_mounts import mount_opt


class OffloadChecks(unittest.TestCase):
    def test_installed_runtime_survives_boot_mount_and_is_readonly_in_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            unit=root/'usr/lib/systemd/system/opt.mount';unit.parent.mkdir(parents=True)
            unit.write_text('[Mount]\nWhat=/home/.steamos/offload/opt\nWhere=/opt\nOptions=bind\n')
            (root/'opt').mkdir();(root/'opt/hidden-root-file').write_text('base root')
            mounts=[]
            try:
                self.assertTrue(mount_opt(root,mounts))
                (root/'opt/runtime.txt').write_text('installed runtime')
                self.assertEqual((root/'home/.steamos/offload/opt/runtime.txt').read_text(),'installed runtime')
            finally:
                for path in reversed(mounts):subprocess.run(['umount',str(path)],check=True)
            self.assertFalse((root/'opt/runtime.txt').exists())
            mounts=[]
            try:
                self.assertTrue(mount_opt(root,mounts,readonly=True))
                self.assertEqual((root/'opt/runtime.txt').read_text(),'installed runtime')
                with self.assertRaises(OSError):(root/'opt/runtime.txt').write_text('must not change')
            finally:
                for path in reversed(mounts):subprocess.run(['umount',str(path)],check=True)

    def test_unknown_mount_is_refused_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            unit=root/'usr/lib/systemd/system/opt.mount';unit.parent.mkdir(parents=True)
            unit.write_text('[Mount]\nWhat=/other/path\nWhere=/opt\nOptions=bind\n')
            with self.assertRaises(RuntimeError):mount_opt(root,[])
            self.assertFalse((root/'home').exists())


if __name__=='__main__':unittest.main()
