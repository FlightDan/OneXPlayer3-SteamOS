"""OXP3 CPU power controls; all hardware access belongs to the RAPL provider."""

import json
import os
from pathlib import Path
import subprocess
import sys

BUS_NAME = 'org.onexplayer.SteamOSManager.PowerControl'
OBJECT_PATH = '/org/onexplayer/SteamOSManager/PowerControl'
TDP_INTERFACE = 'com.steampowered.SteamOSManager1.TdpLimit1'
POWER_INTERFACE = 'org.onexplayer.SteamOSManager.PowerLimits1'


def request(operation, watts=None):
    # Decky's frozen interpreter does not ship _dbus_bindings. Run only this
    # fixed helper with the system interpreter that owns the native bindings.
    if operation not in ('status', 'set-pl1', 'set-pl2'):
        raise ValueError('Unknown power operation')
    arguments = ['/usr/bin/python3', '-I', '-B', str(Path(__file__).resolve()), operation]
    if operation != 'status':
        maximum = 40 if operation == 'set-pl1' else 80
        if type(watts) is not int or not 10 <= watts <= maximum:
            raise ValueError(f'Power limit must be an integer from 10 to {maximum} W')
        arguments.append(str(watts))
    elif watts is not None:
        raise ValueError('Status takes no power limit')
    environment = os.environ.copy()
    # PyInstaller changes this path for its own native libraries. Do not pass
    # the frozen process's library directory to the system Python executable.
    original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is None:
        environment.pop('LD_LIBRARY_PATH', None)
    else:
        environment['LD_LIBRARY_PATH'] = original
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=12, env=environment)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Power controller request failed')
    return json.loads(result.stdout)


def _connect():
    # Keep module import safe when the provider or system bus is unavailable.
    import dbus
    bus = dbus.SystemBus()
    proxy = bus.get_object(BUS_NAME, OBJECT_PATH, introspect=False)
    return (dbus, dbus.Interface(proxy, 'org.freedesktop.DBus.Properties'),
            dbus.Interface(proxy, POWER_INTERFACE))


def _status(power):
    result = power.GetLimits(timeout=5)
    scalars = ('pl1_watts', 'pl2_watts', 'pl1_min_watts', 'pl1_max_watts',
               'pl2_min_watts', 'pl2_max_watts')
    values = {key: int(result[key]) for key in scalars}
    for key in ('pl1_values', 'pl2_values'):
        values[key] = [int(value) for value in result[key]]
        if len(values[key]) != 2:
            raise RuntimeError('The RAPL provider did not return both power domains')
    return values


def get_status():
    _, _, power = _connect()
    return _status(power)


def set_pl1(watts):
    if type(watts) is not int or not 10 <= watts <= 40:
        raise ValueError('PL1 must be an integer from 10 to 40 W')
    dbus, properties, power = _connect()
    # Use exactly the property that Steam reads/writes; the provider emits its
    # existing invalidation signal to both root/session SteamOS Managers.
    properties.Set(TDP_INTERFACE, 'TdpLimit', dbus.UInt32(watts), timeout=5)
    actual = _status(power)
    if actual['pl1_values'] != [watts, watts]:
        raise RuntimeError(f'PL1 request did not remain applied: {actual}')
    return actual


def set_pl2(watts):
    if type(watts) is not int or not 10 <= watts <= 80:
        raise ValueError('PL2 must be an integer from 10 to 80 W')
    dbus, _, power = _connect()
    # The shared controller checks PL2 >= both live PL1 values under its mutex.
    power.SetPl2(dbus.UInt32(watts), timeout=5)
    actual = _status(power)
    if actual['pl2_values'] != [watts, watts]:
        raise RuntimeError(f'PL2 request did not remain applied: {actual}')
    return actual


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['status']:
            result = get_status()
        elif len(sys.argv) == 3 and sys.argv[1] in ('set-pl1', 'set-pl2'):
            setter = set_pl1 if sys.argv[1] == 'set-pl1' else set_pl2
            result = setter(int(sys.argv[2]))
        else:
            raise ValueError('Expected status, set-pl1 W or set-pl2 W')
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
