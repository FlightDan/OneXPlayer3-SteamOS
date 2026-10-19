"""Exercise the guest scripts' EFI mount branches against separate slot files."""
import ast
from pathlib import Path
import shutil
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
GRUB = 'efi/EFI/steamos/grub.cfg'


def efi_branch(filename):
    tree = ast.parse((HERE / filename).read_text(encoding='utf-8'))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                        and child.func.id == 'mount' and any(isinstance(value, ast.Constant)
                        and value.value == 'vfat' for value in child.args)
                        for statement in node.body for child in ast.walk(statement)))


def execute(node, scope):
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<guest-efi-branch>', 'exec'), scope)


class EfiMountChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.parts = {}
        self.calls = []
        for slot in ('A', 'B'):
            esp = Path(self.temp.name) / ('efi-' + slot)
            file = esp / 'EFI/steamos/grub.cfg'
            file.parent.mkdir(parents=True)
            file.write_text('slot=' + slot)
            self.parts['efi-' + slot] = esp

    def mount(self, node, path, *flags):
        self.calls.append((node, path, flags))
        shutil.copytree(node, path)

    def scope(self, slot, **extra):
        return dict(root=self.root, parts=self.parts, slot=slot, mount=self.mount, **extra)

    def clear_mount(self):
        if (self.root / 'efi').exists():
            shutil.rmtree(self.root / 'efi')

    def test_writer_mounts_each_selected_boot_repair(self):
        branch = efi_branch('integration-image.py')
        for slot in ('A', 'B'):
            for repairs in (['split-lock'], ['gm7-resume'], ['gm7-resume', 'split-lock']):
                with self.subTest(slot=slot, repairs=repairs):
                    execute(branch, self.scope(slot, options={'repairs': repairs}))
                    self.assertEqual((self.root / GRUB).read_text(), 'slot=' + slot)
                    self.assertEqual(self.calls[-1][2], ('-t', 'vfat'))
                    self.clear_mount()
        count = len(self.calls)
        execute(branch, self.scope('A', options={'repairs': ['xe-dsb']}))
        self.assertEqual(len(self.calls), count)

    def test_verifier_mounts_reported_efi_before_generic_file_check(self):
        branch = efi_branch('integration-verify.py')
        tree = ast.parse((HERE / 'integration-verify.py').read_text(encoding='utf-8'))
        file_check = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                          and isinstance(node.target, ast.Tuple)
                          and ast.unparse(node.target) == '(name, result)'
                          and any(isinstance(child, ast.Assert)
                                  and ast.unparse(child.test) == '(root / relative).is_file()'
                                  for child in ast.walk(node)))
        self.assertLess(branch.lineno, file_check.lineno)
        for slot in ('A', 'B'):
            for component in ('split-lock', 'gm7-resume'):
                with self.subTest(slot=slot, component=component):
                    results = {'components': {component: {'status': 'files_installed', 'files': [GRUB]}}}
                    scope = self.scope(slot, results=results, desktop_shortcut=lambda value: False)
                    # Reproduce the reported failure with an unmounted ESP.
                    with self.assertRaisesRegex(AssertionError, 'grub.cfg'):
                        execute(file_check, scope)
                    execute(branch, scope)
                    execute(file_check, scope)
                    self.assertEqual((self.root / GRUB).read_text(), 'slot=' + slot)
                    self.assertEqual(self.calls[-1][2], ('-t', 'vfat', '-o', 'ro'))
                    # A genuinely missing file still fails after the mount.
                    (self.root / GRUB).unlink()
                    with self.assertRaisesRegex(AssertionError, 'grub.cfg'):
                        execute(file_check, scope)
                    self.clear_mount()

    def test_no_efi_mount_for_skipped_or_non_boot_components(self):
        branch = efi_branch('integration-verify.py')
        for result in ({'status': 'not_installed', 'files': [GRUB]},
                       {'status': 'files_installed', 'files': []},
                       {'status': 'files_installed', 'files': ['etc/example.conf']}):
            execute(branch, self.scope('A', results={'components': {'component': result}}))
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
