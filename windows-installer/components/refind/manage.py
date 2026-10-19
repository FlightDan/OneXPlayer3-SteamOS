"""Transactional rEFInd deployment for an explicitly selected mounted SteamOS ESP.

No partitioning or firmware writes. Bytes, not hashes, identify managed files.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import struct
import uuid

OWN = 'EFI/OXP3-rEFInd'
STATE = OWN + '/state.json'
FALLBACK = 'EFI/BOOT/BOOTX64.EFI'
LEGACY_FILES = [OWN+'/steamcl-original.efi', OWN+'/refind_x64.efi', OWN+'/manage.py',
         OWN+'/icons/os_linux.png', OWN+'/icons/os_win.png', OWN+'/icons/func_shutdown.png',
         OWN+'/refind.conf', 'EFI/BOOT/refind.conf', FALLBACK]
ICONS = ('os_linux.png','os_win.png','func_shutdown.png','func_about.png','func_reset.png',
         'func_firmware.png','vol_internal.png','vol_external.png','vol_optical.png','vol_net.png','vol_efi.png')
PRE_THEME_FILES = LEGACY_FILES[:3] + [OWN+'/icons/'+n for n in ICONS] + LEGACY_FILES[-3:]
THEME = ('background.png', 'selection-big.png', 'selection-small.png', 'font.png')
THEME_FILES = PRE_THEME_FILES[:-3] + [OWN+'/theme/'+n for n in THEME] + PRE_THEME_FILES[-3:]
GAMEPAD_DRIVER = 'drivers_x64/UsbXbox360Dxe.efi'
GAMEPAD_CONFIG = 'EFI/Xbox360/config.ini'
FILES = THEME_FILES[:-3] + [OWN+'/'+GAMEPAD_DRIVER, OWN+'/gamepad.ini', GAMEPAD_CONFIG] + THEME_FILES[-3:]


def path_at(root, name):
    if name not in FILES + [STATE]:
        raise ValueError('Unrecognized managed path')
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError('Redirected ESP')
    p = root
    for part in Path(name).parts:
        p = p / part
        if p.is_symlink():
            raise ValueError('Redirected ESP path')
    if p.exists() and not p.is_file():
        raise ValueError('Managed path is not a file')
    return p


def read(root, name):
    p = path_at(root, name)
    return p.read_bytes() if p.exists() else None


def encode(value):
    return None if value is None else base64.b64encode(value).decode('ascii')


def decode(value):
    return None if value is None else base64.b64decode(value, validate=True)


def flush_directory(path):
    if os.name == 'nt':
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(root, name, value):
    p = path_at(root, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if value is None:
        p.unlink(missing_ok=True)
    else:
        temporary = p.with_name(p.name+'.oxp3-new')
        if temporary.is_symlink():
            raise ValueError('Redirected temporary file')
        with temporary.open('wb') as f:
            f.write(value); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, p)
    flush_directory(p.parent)
    if read(root, name) != value:
        raise IOError('File readback differs: '+name)


def pe(data):
    if not data or len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('Expected an EFI executable')
    offset = struct.unpack_from('<I', data, 60)[0]
    if offset + 26 > len(data) or data[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H',data,offset+4)[0] != 0x8664:
        raise ValueError('Expected x86-64 EFI executable')


def configuration(default, timeout, esp, windows):
    if default not in ('SteamOS', 'Windows') or type(timeout) is not int or not 0 <= timeout <= 3600:
        raise ValueError('Invalid default system or timeout')
    esp = str(uuid.UUID(esp))
    windows = str(uuid.UUID(windows)) if windows else None
    if default == 'Windows' and not windows:
        raise ValueError('No identified Windows ESP; choose SteamOS')
    # GNU-EFI 0.14.2 builds may fail to clear the default ShowTools array.
    # Explicitly fill all 23 parsed slots; unused slots name an excluded tool.
    tools = ','.join(['shutdown','reboot','firmware','about'] + ['gptsync']*19)
    result = f'''# Managed by ONEXPLAYER SteamOS Installer
timeout {timeout}
default_selection "{default}"
scanfor manual
use_nvram false
icons_dir /EFI/OXP3-rEFInd/icons
banner /EFI/OXP3-rEFInd/theme/background.png
banner_scale fillscreen
selection_big /EFI/OXP3-rEFInd/theme/selection-big.png
selection_small /EFI/OXP3-rEFInd/theme/selection-small.png
font /EFI/OXP3-rEFInd/theme/font.png
hideui hints,badges
showtools {tools}
dont_scan_tools gptsync_x64.efi,gptsync_ia32.efi,gptsync.efi
# Xbox-compatible controller: D-pad/left stick select, A confirms, B returns.
scan_driver_dirs /EFI/OXP3-rEFInd/drivers_x64
big_icon_size 256
small_icon_size 96
menuentry "SteamOS" {{
    icon /{OWN}/icons/os_linux.png
    volume {esp}
    loader /EFI/steamos/steamcl.efi
    graphics on
}}
'''
    if windows:
        result += f'''menuentry "Windows" {{
    icon /{OWN}/icons/os_win.png
    volume {windows}
    loader /EFI/Microsoft/Boot/bootmgfw.efi
    graphics on
}}
'''
    return result.encode('utf-8')


def load(root):
    raw = read(root, STATE)
    if raw is None:
        return None
    if len(raw) > 16*1024*1024:
        raise ValueError('Oversized state')
    state = json.loads(raw)
    if state.get('schema') != 1 or state.get('phase') not in ('installing','installed','removing','removed'):
        raise ValueError('Unknown state')
    for key in ('original', 'before', 'desired'):
        if set(state[key]) in (set(LEGACY_FILES), set(PRE_THEME_FILES), set(THEME_FILES)):
            # Migrate earlier payload layouts without adopting existing files.
            state[key].update({n:None for n in FILES if n not in state[key]})
        if set(state[key]) != set(FILES):
            raise ValueError('Unexpected managed files')
        for value in state[key].values():
            decode(value)
    return state


def save(root, state):
    write(root, STATE, json.dumps(state, indent=2).encode())


def require(root, states):
    # Check every path before changing any file, including self and the backup loader.
    for name in FILES:
        if read(root, name) not in [decode(s[name]) for s in states]:
            raise RuntimeError('Managed file changed; preserve it and review: '+name)


def apply(root, state, fault_after=None):
    removing = state['phase'] == 'removing'
    target = state['original'] if removing else state['desired']
    require(root, [state['before'], target])
    order = [FALLBACK] + [n for n in reversed(FILES) if n != FALLBACK] if removing else FILES
    for i, name in enumerate(order, 1):
        current = read(root, name)
        if current not in (decode(state['before'][name]), decode(target[name])):
            raise RuntimeError('Concurrent change: '+name)
        write(root, name, decode(target[name]))
        if i == fault_after:
            raise RuntimeError('Injected interruption')
    state['phase'] = 'removed' if removing else 'installed'
    save(root, state)
    return state


def install(root, payload, default, timeout, esp, windows=None, fault_after=None):
    config = configuration(default, timeout, esp, windows)
    state = load(root)
    if state and state['phase'] in ('installing','removing'):
        raise RuntimeError('Interrupted transaction; run resume or uninstall first')
    if state:
        require(root, [state['desired'] if state['phase'] == 'installed' else state['original']])
    before = {n: encode(read(root,n)) for n in FILES}
    original = state['original'] if state else before.copy()
    if not state:
        if any(original[n] is not None for n in FILES if n != FALLBACK):
            raise RuntimeError('Existing rEFInd files are not owned by this installer')
    loader = decode(original[FALLBACK]); pe(loader)
    official = Path(root)/'EFI/steamos/steamcl.efi'
    if official.is_symlink() or not official.is_file():
        raise RuntimeError('Official SteamOS A/B loader is missing')
    pe(official.read_bytes())
    payload = Path(payload)
    binary = (payload/'refind_x64.efi').read_bytes(); pe(binary)
    if loader == binary:
        raise RuntimeError('Original loader is already rEFInd without an ownership record')
    desired = {OWN+'/steamcl-original.efi': loader, OWN+'/refind_x64.efi': binary,
               OWN+'/manage.py': Path(__file__).read_bytes(), FALLBACK: binary,
               OWN+'/refind.conf': config, 'EFI/BOOT/refind.conf': config}
    for name in ICONS:
        desired[OWN+'/icons/'+name] = (payload/'icons'/name).read_bytes()
    for name in THEME:
        desired[OWN+'/theme/'+name] = (payload/'theme'/name).read_bytes()
    driver = (payload/GAMEPAD_DRIVER).read_bytes(); pe(driver)
    offset = struct.unpack_from('<I', driver, 60)[0]
    if offset + 94 > len(driver) or struct.unpack_from('<H', driver, offset+92)[0] != 11:
        raise ValueError('Expected an EFI boot-service driver')
    desired[OWN+'/'+GAMEPAD_DRIVER] = driver
    gamepad = (payload/'gamepad.ini').read_bytes()
    desired[OWN+'/gamepad.ini'] = gamepad
    desired[GAMEPAD_CONFIG] = gamepad
    state = dict(schema=1, version='0.14.2', phase='installing', original=original, before=before,
                 desired={n:encode(desired[n]) for n in FILES}, esp=str(uuid.UUID(esp)),
                 windows=str(uuid.UUID(windows)) if windows else None, default=default, timeout=timeout)
    save(root, state)
    return apply(root,state,fault_after)


def uninstall(root, fault_after=None):
    state = load(root)
    if not state:
        raise RuntimeError('No owned rEFInd installation')
    if state['phase'] == 'removed':
        require(root,[state['original']]); return state
    allowed = [state['desired']]
    if state['phase'] == 'installing': allowed.append(state['before'])
    if state['phase'] == 'removing': allowed = [state['before'],state['original']]
    require(root,allowed)
    state['before'] = {n:encode(read(root,n)) for n in FILES}
    state['phase'] = 'removing'; save(root,state)
    return apply(root,state,fault_after)


def resume(root):
    state=load(root)
    if not state or state['phase'] not in ('installing','removing'):
        raise RuntimeError('No interrupted transaction')
    return apply(root,state)


def verify(root):
    state=load(root)
    if not state or state['phase'] != 'installed':
        raise RuntimeError('rEFInd installation is incomplete')
    require(root,[state['desired']]); return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['install','configure','verify','uninstall','resume'])
    p.add_argument('--esp', required=True, type=Path)
    p.add_argument('--payload', type=Path, default=Path(__file__).parent)
    p.add_argument('--esp-guid'); p.add_argument('--windows-guid')
    p.add_argument('--default', choices=['SteamOS','Windows'], default='SteamOS'); p.add_argument('--timeout',type=int,default=2)
    a=p.parse_args()
    if a.action == 'configure':
        current=verify(a.esp)
        result=install(a.esp,a.payload,a.default,a.timeout,current['esp'],current['windows'])
    elif a.action == 'install': result=install(a.esp,a.payload,a.default,a.timeout,a.esp_guid,a.windows_guid)
    else: result=globals()[a.action](a.esp)
    print(json.dumps({'phase':result['phase'],'default':result['default'],'timeout':result['timeout']}))


if __name__ == '__main__': main()
