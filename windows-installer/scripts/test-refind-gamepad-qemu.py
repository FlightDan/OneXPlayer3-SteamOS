"""Boot rEFInd with the controller driver present; QEMU has no physical OXP3 pad."""
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refind_qemu', Path(__file__).with_name('test-refind-qemu.py'))
qemu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu)
original_prepare = qemu.prepare


def prepare(directory, source, default, timeout, graphical):
    esp = original_prepare(directory, source, default, timeout, graphical)
    driver = esp/'EFI/OXP3-rEFInd/drivers_x64'
    shutil.copytree(source/'drivers_x64', driver)
    config = esp/'EFI/Xbox360/config.ini'
    config.parent.mkdir(parents=True)
    shutil.copyfile(source/'gamepad.ini', config)
    with (esp/'EFI/BOOT/refind.conf').open('a', encoding='ascii') as stream:
        stream.write('\nscan_driver_dirs /EFI/OXP3-rEFInd/drivers_x64\n')
    return esp


qemu.prepare = prepare
base = ROOT/'work'/('refind-gamepad-qemu-'+uuid.uuid4().hex)
base.mkdir()
print('REFIND_TEST_DIRECTORY='+str(base), flush=True)
source = ROOT/'components/refind'
results = [qemu.run_case(base, source, *case) for case in (
    ('countdown-with-driver', 'SteamOS', 3),
    ('keyboard-confirm-with-driver', 'Windows', 0, True))]
report = dict(passed=all(r['passed'] for r in results), cases=results, directory=str(base),
              scope='OVMF/rEFInd startup with driver and config present, countdown and injected keyboard Enter to EFI probes; no physical controller or real OS acceptance')
(base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
raise SystemExit(0 if report['passed'] else 1)
