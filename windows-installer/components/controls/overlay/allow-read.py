"""Grant only deck read access to the required energy counters; no limits."""
from pathlib import Path
import os
import pwd

paths = [Path('/sys/class/powercap/intel-rapl:0'), Path('/sys/class/powercap/intel-rapl-mmio:0')]
paths += list(Path('/sys/class/powercap').glob('intel-rapl:0:*'))
for path in paths:
    if (path / 'name').read_text().strip() in ('package-0', 'core', 'uncore'):
        # sysfs does not support POSIX ACLs. The private deck primary group
        # receives read access; root retains ownership, nobody gets write access.
        energy = path / 'energy_uj'
        os.chown(energy, -1, pwd.getpwnam('deck').pw_gid)
        energy.chmod(0o440)

# Intel's PTL/0 telemetry exposes VCCGT_ENERGY even when boot-time RAPL
# registration omitted PP1. Grant read access only to this known telemetry
# region, keeping the MSR device and all control registers private.
pmt = []
for path in Path('/sys/class/intel_pmt').glob('telem*'):
    try:
        if (int((path/'guid').read_text(), 16) == 0x03086000
                and int((path/'size').read_text()) == 3352):
            pmt.append(path)
    except (OSError, ValueError):
        continue
if len(pmt) == 1:
    region = pmt[0].resolve()/'telem'
    expected = Path('/sys/devices/pci0000:00/0000:00:0a.0')
    if not region.is_relative_to(expected) or region.is_symlink() or region.stat().st_uid != 0:
        raise RuntimeError('Unexpected PTL telemetry path or owner')
    os.chown(region, -1, pwd.getpwnam('deck').pw_gid, follow_symlinks=False)
    region.chmod(0o440)
