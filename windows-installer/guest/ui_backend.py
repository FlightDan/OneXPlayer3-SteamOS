"""Boot UI adapter. Physical execution remains closed; VM devices are explicit."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from install_session import candidate, execute_virtual, handoff_to_esp
from intent_store import IntentStore
from deployment import Deployment, fs


def disks():
    result = subprocess.check_output(['lsblk', '--json', '--bytes', '--output', 'PATH,SIZE,TYPE,SERIAL,RO,PTUUID,LOG-SEC'], text=True)
    return json.loads(result)['blockdevices']


def by_serial(serial):
    matches = [d for d in disks() if d['type'] == 'disk' and d.get('serial') == serial]
    if len(matches) != 1: raise RuntimeError('Required virtual device is missing or duplicated: ' + serial)
    return matches[0]


class BootBackend:
    def __init__(self, selection):
        self.selection = selection; self.available = False
        self.reason = 'Physical installation is not available in this build.'
        self.context = None; self.target = None; self.state = None
        self.source = None; self.journal = None
        vendor = Path('/sys/class/dmi/id/sys_vendor')
        if not vendor.exists() or vendor.read_text().strip() != 'QEMU': return
        contexts = [d for d in disks() if d.get('serial') == 'OXP3-UI-CONTEXT']
        if not contexts: return
        if len(contexts) != 1 or not contexts[0]['ro']: raise RuntimeError('Virtual UI context is not read-only/unique')
        device = contexts[0]['path']; mount = Path('/run/oxp3-ui-context'); mount.mkdir(exist_ok=True)
        # The host exposes one read-only virtual FAT partition, never a host disk.
        subprocess.run(['mount', '-t', 'vfat', '-o', 'ro', device + '1', str(mount)], check=True)
        try:
            file = mount / 'context.json'
            if file.stat().st_size > 128 * 1024: raise RuntimeError('Virtual context is too large')
            context = json.loads(file.read_text())
        finally: subprocess.run(['umount', str(mount)], check=True)
        if context.get('schema') != 1 or context.get('kind') != 'oxp3-isolated-ui-install':
            raise RuntimeError('Unsupported virtual UI context')
        target = by_serial('OXP3-LAB-TARGET'); state = by_serial('OXP3-LAB-STATE')
        if not any(d.get('serial') == 'OXP3-LAB-SOURCE' for d in disks()):
            # Source is attached after boot, so its cloned UUIDs cannot select
            # the recovery OS root/var/home during initramfs discovery.
            with open('/dev/ttyS0', 'w') as file:
                file.write('OXP_UI_WAITING_SOURCE\n'); file.flush()
            deadline = time.monotonic() + 120
            while not any(d.get('serial') == 'OXP3-LAB-SOURCE' for d in disks()):
                if time.monotonic() >= deadline: raise RuntimeError('Read-only virtual source did not arrive')
                time.sleep(0.5)
        source = by_serial('OXP3-LAB-SOURCE')
        if target['size'] != 80 * 1024**3 or target['ro'] or not source['ro'] or state['size'] != 16 * 1024**2 or state['ro']:
            raise RuntimeError('Virtual UI device capacities/access do not match')
        if len({target['path'], source['path'], state['path']}) != 3: raise RuntimeError('Virtual device alias')
        if context['selection'].get('source') != selection.get('source'):
            raise RuntimeError('Virtual context source differs from the boot media')
        self.context = context; self.selection = dict(context['selection'], resources=selection.get('resources', []), components=selection.get('components', []))
        self.target = target['path']; self.source = source['path']; self.state = state['path']
        required = ('sfdisk', 'mount', 'umount', 'blkid', 'btrfs', 'btrfstune', 'mkfs.vfat', 'mkfs.ext4', 'dd', 'chroot')
        missing = [name for name in required if shutil.which(name) is None]
        if missing:
            self.reason = 'Required installation tools are missing: ' + ', '.join(missing); return
        self.available = True; self.reason = ''

    def refresh(self):
        if self.target: return candidate(self.target)
        target = self.selection.get('target')
        if not target: raise RuntimeError('Choose installation space in Windows and recreate the media.')
        identity = (target.get('Identity') or {}).get('DiskGuid', '').lower()
        matches = [d for d in disks() if str(d.get('ptuuid', '')).lower() == identity]
        if len(matches) != 1: raise RuntimeError('Selected GPT disk is missing or duplicated')
        self.target = matches[0]['path']; return candidate(self.target)

    def current(self): return self.refresh()

    def mount_state(self):
        if self.journal: return self.journal
        if not self.available or not self.state: raise RuntimeError(self.reason)
        if fs(self.state) != 'ext4' or fs(self.state, 'LABEL') != 'OXP_INTENT':
            raise RuntimeError('Persistent state filesystem was not prepared by the virtual adapter')
        mount = Path('/run/oxp3-ui-state'); mount.mkdir(exist_ok=True)
        subprocess.run(['mount', '-t', 'ext4', self.state, str(mount)], check=True)
        self.journal = IntentStore(mount / 'oxp3')
        self.journal.require_durable_mount(self.target)
        return self.journal

    def intent(self):
        if not self.available: return None
        return self.mount_state().load()

    def close(self):
        if self.journal:
            subprocess.run(['sync'], check=True)
            subprocess.run(['umount', '/run/oxp3-ui-state'], check=True); self.journal = None

    def run(self, accepted):
        if not self.available: raise RuntimeError(self.reason)
        journal = self.mount_state()
        result = execute_virtual(self.selection, self.source, self.target, accepted, journal=journal)
        handoff_to_esp(result, journal)
        Deployment(result).apply()
        return result
