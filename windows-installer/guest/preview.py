#!/usr/bin/env python3
"""Recovery-side preview. This program has no partition or filesystem write path."""
import json
import subprocess
import sys
import signal
from pathlib import Path

selection = json.loads(Path('/usr/local/share/oxp3-installer/selection.json').read_text())
if selection.get('stage') != 'preview_only' or selection.get('allow_disk_write') is not False:
    raise RuntimeError('Unsupported selection capabilities; refusing to proceed')
result = subprocess.run(['lsblk', '--json', '--bytes', '--output', 'NAME,PATH,SIZE,TYPE,PTUUID,LOG-SEC,FSTYPE,LABEL,PARTLABEL,PARTTYPE,MOUNTPOINTS'], text=True, capture_output=True, check=True)
disks = json.loads(result.stdout)['blockdevices']
lines = ['ONEXPLAYER 3 - SteamOS installation preview', '=' * 60,
         'Preview only. Internal disk changes are disabled.',
         'Media system: SteamOS ' + selection['source']['version'] + ' / ' + selection['source']['build'], '']
target = selection.get('target')
if target:
    lines += ['Selected Windows disk: ' + str(target['Disk']) + ' / ' + target['Model'],
              'Planned space: %.1f GiB (not allocated)' % (target['Size'] / 1024**3)]
    try:
        from handoff import bind, guid
        identity = guid((target.get('Identity') or {}).get('DiskGuid'))
        candidates = []
        for disk in disks:
            if disk['type'] != 'disk': continue
            try: same = guid(disk.get('ptuuid')) == identity
            except ValueError: same = False
            if not same: continue
            table = json.loads(subprocess.check_output(['sfdisk', '--json', disk['path']], text=True))['partitiontable']
            candidates.append({'table': table, 'size': int(disk['size']), 'sector_size': int(disk['log-sec'])})
        verified = bind(selection, candidates)
        lines += ['Windows selection verified: ' + verified['device'], 'Original GPT partitions and free space match.']
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        lines += ['Windows selection is NOT verified: ' + str(error), 'Recreate the media after reading the Windows layout again.']
else: lines += ['Target space: not selected. No installation will run.']
if 'waydroid' in selection.get('resources', []):
    lines += ['Waydroid r2 resources: included, not installed.',
              'Requires SteamOS 3.10 build 20260924.1000 and its exact 7.2.4 kernel.',
              'Android 13 + Google Play images are downloaded separately.']
if 'hdr' in selection.get('resources', []):
    lines += ['HDR Gamma22 1100/472 config and restore resources: carried, not active.',
              'Live apply is limited to SteamOS 3.10 / exact kernel / Gamescope 3.16.30-1.']
if 'oxp3-controls' in selection.get('resources', []):
    profile = json.loads(Path('/home/oxp3-resources/oxp3-controls/profile.json').read_text())
    label = 'OXP3 TDP / overlay / fan / CPU' + (' / Battery' if 'charging' in profile['components'] else '')
    lines += [label + ' sources: included, not installed.',
              'Current power, firmware fan mode and CPU settings are preserved.']
    if 'charging' in profile['components']:
        lines += ['CPU / Fan / Battery: Chinese and English frontends included.', 'Current charging policy is preserved.']
lines += ['', 'Disks detected in this boot environment:']
for disk in disks[:8]:
    if disk['type'] != 'disk': continue
    parts = disk.get('children', [])
    lines += ['  %-14s %7.1f GiB   %d partitions' % (disk['path'], int(disk['size']) / 1024**3, len(parts))]
lines += ['', 'This development media cannot install, format or shrink a disk.',
          'Press Ctrl+Alt+Delete to restart and return to your boot menu.']
screen = '\n'.join(lines) + '\n'
print(('\x1b[2J\x1b[H' if '--terminal' in sys.argv else '\n') + screen, flush=True)
# Keep the complete detail in the journal without filling the visible preview.
try:
    subprocess.run(['systemd-cat', '--identifier=oxp3-preview-details'], input=json.dumps({'selection': selection, 'disks': disks}), text=True)
except OSError: pass
if '--terminal' not in sys.argv:
    try:
        subprocess.run(['chvt', '1'], capture_output=True)
        with open('/dev/tty1', 'w') as console:
            console.write('\x1b[2J\x1b[H' + screen); console.flush()
    except OSError: pass
# A QEMU-only serial marker lets the boot probe observe this real service execution.
# Physical devices keep the regular console output above.
vendor = Path('/sys/class/dmi/id/sys_vendor')
if vendor.exists() and vendor.read_text().strip() == 'QEMU':
    try:
        with open('/dev/ttyS0', 'w') as console:
            active = Path('/sys/class/tty/tty0/active')
            console.write('OXP_PREVIEW_VT=' + (active.read_text().strip() if active.exists() else 'unknown') + '\n')
            for framebuffer in Path('/sys/class/graphics').glob('fb*'):
                for name in ('name', 'bits_per_pixel', 'virtual_size', 'stride'):
                    value = framebuffer / name
                    if value.exists(): console.write('OXP_PREVIEW_FB=' + framebuffer.name + ':' + name + '=' + value.read_text().strip() + '\n')
            console.write('OXP_PREVIEW_READY\n')
            console.flush()
    except OSError:
        pass
if '--hold' in sys.argv:
    while True: signal.pause()
