"""Exercise the boot-visible /opt mount on an isolated Linux scratch filesystem."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,'/mnt/payload/components')
from offload_mounts import mount_opt, mount_etc


class OffloadChecks(unittest.TestCase):
    def test_etc_password_ssh_and_update_masks_survive_lower_root_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            unit=root/'usr/lib/systemd/system/etc.mount';unit.parent.mkdir(parents=True)
            unit.write_text('[Mount]\nWhere=/etc\nWhat=overlay\nType=overlay\nOptions=lowerdir=/etc,upperdir=/var/lib/overlays/etc/upper,workdir=/var/lib/overlays/etc/work,index=off\n')
            (root/'etc/systemd/system').mkdir(parents=True)
            (root/'etc/shadow').write_text('deck:locked\n')
            (root/'etc/removed-setting').write_text('stock setting\n')
            mounts=[]
            try:
                self.assertTrue(mount_etc(root,mounts))
                (root/'etc/shadow').write_text('deck:installed-password-hash\n')
                (root/'etc/systemd/system/atomupd.service').write_bytes(b'')
                (root/'etc/removed-setting').unlink()
                wants=root/'etc/systemd/system/multi-user.target.wants';wants.mkdir()
                (wants/'sshd.service').symlink_to('../../../../usr/lib/systemd/system/sshd.service')
            finally:
                for path in reversed(mounts):subprocess.run(['umount',str(path)],check=True)
            upper=root/'var/lib/overlays/etc/upper'
            self.assertEqual((upper/'shadow').read_text(),'deck:installed-password-hash\n')
            self.assertEqual((root/'etc/shadow').read_text(),'deck:locked\n')
            # An official update replaces the lower root, keeping only /var.
            (root/'etc/shadow').write_text('deck:updated-stock-default\n')
            mounts=[]
            try:
                self.assertTrue(mount_etc(root,mounts,readonly=True))
                self.assertEqual((root/'etc/shadow').read_text(),'deck:installed-password-hash\n')
                self.assertEqual((root/'etc/systemd/system/atomupd.service').read_bytes(),b'')
                self.assertFalse((root/'etc/removed-setting').exists(), 'Read-only merged view must respect whiteouts')
                self.assertTrue((root/'etc/systemd/system/multi-user.target.wants/sshd.service').is_symlink())
                with self.assertRaises(OSError):(root/'etc/shadow').write_text('must not change')
            finally:
                for path in reversed(mounts):subprocess.run(['umount',str(path)],check=True)

    def test_unknown_etc_overlay_is_refused_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            unit=root/'usr/lib/systemd/system/etc.mount';unit.parent.mkdir(parents=True)
            unit.write_text('[Mount]\nWhat=overlay\nWhere=/etc\nOptions=lowerdir=/unexpected\n')
            with self.assertRaises(RuntimeError):mount_etc(root,[])
            self.assertFalse((root/'var').exists())

    def test_effective_etc_mount_overrides_are_refused(self):
        for location in ('usr/lib/systemd/system/etc.mount.d/custom.conf',
                         'etc/systemd/system/etc.mount.d/custom.conf',
                         'var/lib/overlays/etc/upper/systemd/system/etc.mount.d/custom.conf'):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                unit=root/'usr/lib/systemd/system/etc.mount';unit.parent.mkdir(parents=True)
                unit.write_text('[Mount]\nWhere=/etc\nWhat=overlay\nType=overlay\nOptions=lowerdir=/etc,upperdir=/var/lib/overlays/etc/upper,workdir=/var/lib/overlays/etc/work,index=off\n')
                (root/'etc').mkdir()
                custom=root/location;custom.parent.mkdir(parents=True,exist_ok=True)
                custom.write_text('[Mount]\nOptions=lowerdir=/other\n')
                with self.assertRaisesRegex(RuntimeError,'Custom'):
                    mount_etc(root,[])

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
