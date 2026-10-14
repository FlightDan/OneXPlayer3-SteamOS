"""Exercise real Valve bootconf against disposable configs in an isolated chroot."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('slot_boot', Path(__file__).parent / 'slot-switch/boot.py')
boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)
root = sys.argv[1]
chroot = shutil.which('chroot')
assert chroot, 'chroot is required for the official tool check'
base = Path('/mnt/integration-test-scratch/official-slot-fixture')
base.mkdir()
conf, efi = base / 'conf', base / 'efi'
conf.mkdir(); (efi / 'SteamOS/partsets').mkdir(parents=True)
for slot in ('A', 'B'):
    (efi / 'SteamOS/partsets' / slot).write_text('efi 00000000-0000-4000-8000-000000000001\nrootfs 00000000-0000-4000-8000-000000000002\nvar 00000000-0000-4000-8000-000000000003\n')
current = 'A'
reboots = []


def run(args):
    if args[0] == boot.BUSCTL: return 'de.pengutronix.rauc - - - (activatable)'
    if args[0] == boot.SYSTEMCTL:
        if args[1] == 'show': return 'masked' if 'UnitFileState' in args else 'inactive'
        reboots.append(current); return ''
    if args == [boot.BOOT, 'this-image']: return current
    args = list(args)
    args += ['--conf-dir', '/tmp/official-slot-fixture/conf', '--efi-dir', '/tmp/official-slot-fixture/efi']
    return boot.command([chroot, root, *args])


for slot in ('A', 'B'):
    run([boot.BOOT, 'create', '--image', slot, '--set', 'image-invalid', '0',
         '--set', 'boot-requested-at', '20990101000000' if slot == 'A' else '0'])
with patch.object(boot, 'preflight'), patch.object(boot, 'reboot_lock', return_value=nullcontext()), \
     patch.object(boot.Path, 'read_text', autospec=True, side_effect=lambda path, *a, **k: 'ID=steamos\n' if str(path) == '/etc/os-release' else path.read_bytes().decode()):
    controller = boot.Controller(run, conf, base / 'absent-records')
    for current in ('A', 'B'):
        state = controller.status(); other = state['target']
        original_current = (conf / (current + '.conf')).read_bytes()
        controller.reboot(other, state['token'])
        assert run([boot.BOOT, 'selected-image']) == other
        assert (conf / (current + '.conf')).read_bytes() == original_current
        assert reboots[-1] == current
        print('OXP_OFFICIAL_SLOT_SWITCH=' + current + '->' + other, flush=True)
    print('OXP_OFFICIAL_SLOT_TOOL=passed', flush=True)
