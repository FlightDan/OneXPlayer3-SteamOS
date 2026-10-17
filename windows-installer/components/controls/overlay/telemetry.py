"""Read-only RAPL telemetry for the OXP3 MangoApp overlay."""
import json
import os
from pathlib import Path
import sys
import time

BASE = Path('/sys/class/powercap/intel-rapl:0')
CACHE = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'oxp3-overlay.json'

def pmt_gpu_counter():
    # Intel PTL/0 schema: GUID 0x03086000, Container205 VCCGT_ENERGY,
    # uint64LE at 205*8; vr_energy = raw/16384 joules.
    sensors = []
    for path in Path('/sys/class/intel_pmt').glob('telem*'):
        try:
            if (int((path/'guid').read_text(), 16) == 0x03086000
                    and int((path/'size').read_text()) == 3352):
                sensors.append(path)
        except (OSError, ValueError):
            continue
    if len(sensors) != 1:
        raise ValueError('PTL GPU energy sensor unavailable or ambiguous')
    path = sensors[0]
    with (path/'telem').open('rb', buffering=0) as stream:
        raw = os.pread(stream.fileno(), 8, 1640)
    if len(raw) != 8:
        raise ValueError('Short GPU energy read')
    return int.from_bytes(raw, 'little'), str(path.resolve())

def pmt_gpu_watts(current, previous):
    if previous is None:
        return None
    raw, source, mono, boot = current
    old_raw, old_source, old_mono, old_boot = previous
    elapsed = mono - old_mono
    # Rebaseline across sensor changes, counter reset/wrap, long gaps or suspend.
    # The 64-bit PMT schema does not specify a 32-bit rollover assumption.
    if (source != old_source or raw < old_raw or not 0 < elapsed <= 3
            or abs((boot - old_boot) - elapsed) > 0.1):
        return None
    watts = (raw - old_raw) / 16384 / elapsed
    return watts if 0 <= watts <= 160 else None

def fan_text():
    # RPM telemetry must remain available when the curve controller is stopped.
    # Select by driver name: hwmon indices change, and acpi_fan may return EIO.
    try:
        sensors = []
        for path in Path('/sys/class/hwmon').glob('hwmon*'):
            try:
                if (path / 'name').read_text().strip() == 'oxp_ec':
                    sensors.append(path)
            except OSError:
                continue
        if len(sensors) != 1:
            raise ValueError('fan sensor unavailable or ambiguous')
        rpm = int((sensors[0] / 'fan1_input').read_text())
        if not 0 <= rpm <= 30000:
            raise ValueError('invalid rpm')
        return f'{rpm} RPM'
    except (OSError, ValueError):
        return 'N/A'

def display_text(data, which):
    def watts(key):
        value = data['watts'].get(key)
        return 'N/A' if value is None else f'{value:.1f}W'
    if which == 'domains':
        return f"{watts('core')} / {watts('uncore')}"
    limits = data['limits']
    if len(limits) == 2 and all(limits):
        pl1 = min(x[0] for x in limits)
        mismatch = ' *' if limits[0] != limits[1] else ''
        limit = f'{pl1:g}W{mismatch}'
    else:
        limit = 'N/A'
    return f"{watts('package-0')} / {limit}"

def write_display_cache(data):
    # /proc/uptime uses BOOTTIME, including suspend, unlike the RAPL sample clock.
    stamp = int(time.clock_gettime(time.CLOCK_BOOTTIME))
    for which, value in (('domains', display_text(data, 'domains')),
                         ('limits', display_text(data, 'limits')),
                         ('fan', fan_text())):
        path = CACHE.with_name(f'oxp3-overlay-{which}.txt')
        temp = path.with_suffix('.tmp')
        temp.write_text(f'{stamp} {value}\n')
        temp.replace(path)

def counters():
    roots = [BASE] + list(BASE.parent.glob(BASE.name + ':*'))
    result = {}
    for root in roots:
        name = (root / 'name').read_text().strip()
        if name in ('package-0', 'core', 'uncore'):
            result[name] = (int((root / 'energy_uj').read_text()),
                            int((root / 'max_energy_range_uj').read_text()))
    return result

def collect():
    previous = None
    gpu_previous = None
    while True:
        now = time.monotonic()
        data = {'time': now, 'watts': {}, 'limits': []}
        try:
            current = counters()
            if previous:
                old_time, old = previous
                for key, (value, maximum) in current.items():
                    if key not in old:
                        continue
                    delta = value - old[key][0]
                    if delta < 0:
                        delta += maximum
                    watts = delta / 1e6 / (now - old_time)
                    if 0 <= watts <= 160:
                        data['watts'][key] = watts
            previous = (now, current)
        except (OSError, ValueError):
            previous = None
        # PMT and PP1 report the same GT energy. Keep the native RAPL source
        # when available; use PMT when the boot did not register uncore.
        if 'uncore' not in data['watts']:
            try:
                raw, source = pmt_gpu_counter()
                gpu_current = (raw, source, time.monotonic(),
                               time.clock_gettime(time.CLOCK_BOOTTIME))
                watts = pmt_gpu_watts(gpu_current, gpu_previous)
                if watts is not None:
                    data['watts']['uncore'] = watts
                    data['gpu_source'] = 'intel-pmt-vccgt'
                gpu_previous = gpu_current
            except (OSError, ValueError):
                gpu_previous = None
        else:
            gpu_previous = None
        for path in (BASE, Path('/sys/class/powercap/intel-rapl-mmio:0')):
            try:
                data['limits'].append([int((path / f'constraint_{n}_power_limit_uw').read_text()) / 1e6 for n in (0, 1)])
            except (OSError, ValueError):
                data['limits'].append(None)
        temp = CACHE.with_suffix('.tmp')
        temp.write_text(json.dumps(data))
        temp.replace(CACHE)
        write_display_cache(data)
        time.sleep(1)

def show(which):
    if which == 'fan':
        print(fan_text())
        return
    try:
        data = json.loads(CACHE.read_text())
        if not 0 <= time.monotonic() - data['time'] <= 3:
            raise ValueError('stale')
    except (OSError, ValueError, KeyError):
        data = {'watts': {}, 'limits': []}
    print(display_text(data, which))

if __name__ == '__main__':
    if sys.argv[1:] == ['collect']:
        collect()
    else:
        show(sys.argv[1] if len(sys.argv) > 1 else 'domains')
