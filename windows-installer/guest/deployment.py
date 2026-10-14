"""Range-bound SteamOS deployment core. Physical execution remains release-gated.

The development adapter supplies fresh GPT metadata and block devices. No disk
or partition number is assumed by this core; protected partition dictionaries
must survive unchanged. Journal entries describe work, not device acceptance.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import signal
import uuid

from layout import plan as space_plan
from media_layer import inspect as inspect_media, detach as detach_media, SELECTION
from resources import stage_resources
from component_choice import selected as selected_components, request as component_request
from bootstrap_payload import library as bootstrap_library, stage as stage_bootstrap
from fs_metadata import probe as fs, normalize_uuid

ROLES = ('esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home')
ESP_TYPE = 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def table(device):
    return json.loads(run('sfdisk', '--json', device, capture=True))['partitiontable']


def resolve(selection, actual):
    """Validate all metadata before returning the only allowed write nodes."""
    if selection.get('schema') != 1 or selection.get('mode') != 'virtual_install':
        raise ValueError('Unaccepted installation capabilities')
    expected = selection['target_table']
    for key in ('device', 'label', 'id', 'sectorsize', 'firstlba', 'lastlba'):
        if actual.get(key) != expected.get(key): raise ValueError('Target disk metadata changed: ' + key)
    if actual.get('label') != 'gpt' or actual.get('sectorsize') != 512:
        raise ValueError('Unsupported target GPT/sector format')
    start, size = selection['range']['start'], selection['range']['size']
    selected = [p for p in expected['partitions'] if start <= p['start'] * 512 < start + size]
    protected = [p for p in expected['partitions'] if p not in selected]
    # Reconstruct the pre-append table, then reuse the validated space planner.
    before = dict(expected, partitions=protected)
    layout = space_plan(before, start, size)
    if len(selected) != len(ROLES): raise ValueError('Unexpected selected partition count')
    by_name = {p.get('name'): p for p in selected}
    if set(by_name) != set(ROLES): raise ValueError('Ambiguous target partition roles')
    if len(actual['partitions']) != len(expected['partitions']): raise ValueError('Target partition count changed')
    current = {p['node']: p for p in actual['partitions']}
    if len(current) != len(actual['partitions']): raise ValueError('Duplicate block nodes')
    for old in protected:
        if current.get(old['node']) != old: raise ValueError('Protected partition metadata changed')
    nodes = {}
    for item in layout:
        old = by_name[item['name']]; now = current.get(old['node'])
        if now is None: raise ValueError('Selected partition disappeared')
        # Only the shared ESP has the EFI system type. The stock mapping helper
        # interprets every EFI-type partition as shared esp, so slot EFIs must
        # retain the basic-data type specified by our layout.
        allowed_types = {item['type'].upper()}
        if str(old.get('type')).upper() not in allowed_types or str(now.get('type')).upper() not in allowed_types:
            raise ValueError('Unexpected selected partition type')
        if {k: v for k, v in now.items() if k != 'type'} != {k: v for k, v in old.items() if k != 'type'}:
            raise ValueError('Selected partition identity changed')
        if (old['start'], old['size']) != (item['start'], item['size']):
            raise ValueError('Selected partition does not match the planned range')
        nodes[item['name']] = old['node']
    return nodes


class InjectedFailure(RuntimeError):
    pass


def can_recover_root(state, slot, identity):
    """Only an unfinished, journaled configuration owns a writable root."""
    return (state.get('status') in ('running', 'failed')
            and state.get('phase') == 'configure-' + slot
            and slot not in state.get('configured', [])
            and state.get('copied', {}).get('rootfs-' + slot) == identity)


class Deployment:
    def __init__(self, selection, fault=None):
        self.selection = selection
        self.fault = fault
        self.mounts = []
        self.root_mount = None
        self.state = None
        self.state_owned = False
        self.state_path = Path('/mnt/oxp3-install-state/oxp3/install-state.json')
        self.root = Path('/mnt/oxp3-install-root')
        self.nodes = resolve(selection, table(selection['target_table']['device']))

    def preflight(self):
        # Release gate: current execution is confined to tool-created QEMU fixtures.
        if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
            raise RuntimeError('Physical installation has not passed release acceptance')
        source, target = self.selection['source_table']['device'], self.selection['target_table']['device']
        if table(source) != self.selection['source_table']: raise RuntimeError('Source metadata changed')
        source_parts = self.selection['source_table']['partitions']
        if [p.get('name') for p in source_parts] != ['esp', 'efi-A', 'rootfs-A', 'var-A', 'home']:
            raise RuntimeError('Unsupported recovery source')
        if os.stat(source).st_rdev == os.stat(target).st_rdev: raise RuntimeError('Source and target are identical')
        if Path('/sys/class/block', Path(source).name, 'ro').read_text().strip() != '1':
            raise RuntimeError('Recovery source must be attached read-only')
        if Path('/sys/class/block', Path(target).name, 'ro').read_text().strip() != '0':
            raise RuntimeError('Target is read-only')
        devices = [target] + [p['node'] for p in self.selection['target_table']['partitions']]
        numbers = set()
        for node in [source] + devices:
            if not node.startswith('/dev/') or os.path.realpath(node) != node or not stat.S_ISBLK(os.stat(node).st_mode):
                raise RuntimeError('Only canonical block devices are allowed')
        for node in devices:
            info = os.stat(node); numbers.add(f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}')
            if node != target and Path('/sys/class/block', Path(node).name).resolve().parent.name != Path(target).name:
                raise RuntimeError('Partition node is not a child of the target disk')
        if any(line.split()[2] in numbers for line in Path('/proc/self/mountinfo').read_text().splitlines()):
            raise RuntimeError('Target or one of its partitions is already mounted')
        self.source_root = source_parts[2]['node']
        if source_parts[2]['size'] * 512 > min(self.part_size('rootfs-A'), self.part_size('rootfs-B')):
            raise RuntimeError('Source root does not fit the selected slots')
        probe = Path('/mnt/oxp3-install-source')
        self.mount(self.source_root, probe, '-t', 'btrfs', '-o', 'ro,rescue=nologreplay')
        self.check_os(probe)
        self.media_layer = inspect_media(probe)
        self.media_selection = json.loads((probe / SELECTION).read_text()) if self.media_layer else None
        if self.media_selection: selected_components(self.media_selection)
        self.bootstrap_available = bootstrap_library(probe) is not None if self.media_selection else False
        if self.media_selection and selected_components(self.media_selection) and not self.bootstrap_available: raise RuntimeError('Selected component lacks bootstrap source')
        if self.media_layer: print('OXP_DEPLOY_SOURCE=owned-detachable-recovery-layer', flush=True)
        if run('btrfs', 'property', 'get', '-ts', str(probe), 'ro', capture=True).strip() != 'ro=true':
            raise RuntimeError('Unsupported recovery root protection')
        self.unmount(probe)

    def part_size(self, role):
        return next(p['size'] * 512 for p in self.selection['target_table']['partitions'] if p['node'] == self.nodes[role])

    def check_os(self, root):
        values = dict(line.split('=', 1) for line in (root / 'etc/os-release').read_text().splitlines() if '=' in line)
        source = (values.get('VERSION_ID', '').strip('"'), values.get('BUILD_ID', '').strip('"'))
        if source not in (('3.8.14', '20260707.10'), ('3.10', '20260924.1000')):
            raise RuntimeError('Unsupported source system version')

    def mount(self, device, destination, *options):
        destination.mkdir(parents=True, exist_ok=True)
        run('mount', *options, device, str(destination)); self.mounts.append(destination)

    def unmount(self, destination):
        run('umount', str(destination)); self.mounts.remove(destination)

    def cleanup(self):
        errors = []
        if self.root_mount is not None:
            try: run('btrfs', 'property', 'set', '-ts', str(self.root_mount), 'ro', 'true')
            except Exception as error: errors.append(str(error))
        run('sync')
        for destination in reversed(self.mounts[:]):
            try: self.unmount(destination)
            except Exception as error: errors.append(str(error))
        self.root_mount = None
        if errors: raise RuntimeError('Cleanup needs recovery: ' + '; '.join(errors))

    def save(self):
        if not self.state_owned: raise RuntimeError('Installation journal ownership is unverified')
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.pending')
        with temporary.open('w') as file:
            json.dump(self.state, file, indent=2); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, self.state_path)
        fd = os.open(self.state_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def phase(self, value):
        self.assert_protected()
        self.state.update(status='running', phase=value, error=None, updated_at=int(time.time()))
        self.save(); print('OXP_DEPLOY_PHASE=' + value, flush=True)

    def open_state(self):
        esp = self.nodes['esp']; initial = not fs(esp)
        if initial:
            if any(fs(node) for node in self.nodes.values()):
                raise RuntimeError('Selected partitions contain filesystems without an installation journal')
            run('mkfs.vfat', '-F', '32', '-n', 'OXP3_STAGE', esp)
        self.mount(esp, self.state_path.parents[1])
        if self.state_path.exists():
            if self.state_path.stat().st_size > 4 * 1024**2: raise RuntimeError('Installation journal too large')
            self.state = json.loads(self.state_path.read_text())
            prior = self.state.get('selection', {})
            if self.state.get('schema') != 1 or prior.get('source_table') != self.selection['source_table'] or prior.get('range') != self.selection['range']:
                raise RuntimeError('Journal does not match this source and selected range')
            resolve(prior, self.selection['target_table'])
            if not set(self.state.get('formatted', {})) <= set(ROLES) or not set(self.state.get('copied', {})) <= {'rootfs-A', 'rootfs-B'}:
                raise RuntimeError('Unexpected journal filesystem roles')
            if len(self.state.get('configured', [])) != len(set(self.state.get('configured', []))) or not set(self.state.get('configured', [])) <= {'A', 'B'}:
                raise RuntimeError('Unexpected journal slot records')
            encoding = self.state.get('uuid_encoding')
            if encoding not in (None, 'plain_uuid_v1'): raise RuntimeError('Unsupported journal UUID encoding')
            normalized = {}
            for field in ('formatted', 'copied'):
                normalized[field] = {}
                for role, value in self.state[field].items():
                    if encoding == 'plain_uuid_v1' and isinstance(value, str) and value.startswith('/dev/'):
                        raise RuntimeError('Journal contradicts its UUID encoding')
                    identity = normalize_uuid(value, self.nodes[role])
                    if fs(self.nodes[role], 'UUID') != identity:
                        raise RuntimeError('Journal filesystem identity changed: ' + role)
                    kind = 'btrfs' if role.startswith('rootfs-') else 'vfat' if role == 'esp' or role.startswith('efi-') else 'ext4'
                    if fs(self.nodes[role]) != kind: raise RuntimeError('Journal filesystem type changed: ' + role)
                    normalized[field][role] = identity
            if 'esp' not in normalized['formatted']: raise RuntimeError('Journal ESP identity is missing')
            root_ids = list(normalized['copied'].values())
            if len(root_ids) != len(set(root_ids)) or fs(self.source_root, 'UUID') in root_ids:
                raise RuntimeError('Journal roots have duplicate or recovery-source UUIDs')
            self.state_owned = True
            if encoding is None or any(self.state[field] != normalized[field] for field in ('formatted', 'copied')):
                self.state.update(normalized, uuid_encoding='plain_uuid_v1'); self.save()
                print('OXP_DEPLOY_RECOVER=legacy-uuid-fields-verified-and-normalized', flush=True)
        else:
            # Recover a loss between formatting the new ESP and saving the first journal.
            existing = list(self.state_path.parents[1].iterdir())
            if not initial and (fs(esp, 'LABEL') != 'OXP3_STAGE' or existing or any(fs(self.nodes[r]) for r in ROLES[1:])):
                raise RuntimeError('Existing ESP is not an empty installation staging filesystem')
            self.state = {'schema': 1, 'uuid_encoding': 'plain_uuid_v1', 'selection': self.selection, 'formatted': {'esp': fs(esp, 'UUID')},
                          'copied': {}, 'configured': [], 'status': 'new'}
            self.state_owned = True
            self.save()

        if self.bootstrap_available:
            existing_request = self.state.get('component_request')
            operation_id = self.selection.get('append_intent', {}).get('id') or (existing_request or {}).get('id') or str(uuid.uuid4())
            wanted = component_request(self.media_selection, operation_id)
            if existing_request is not None and existing_request != wanted: raise RuntimeError('Component request differs from durable installation journal')
            if existing_request is None:
                if self.state['configured']: raise RuntimeError('Previously configured installation needs an explicit bootstrap migration')
                self.state.update(component_request=wanted, bootstrap_staged=[]); self.save()
        elif self.state.get('component_request') is not None:
            raise RuntimeError('Recorded bootstrap source is missing')

    def format_partitions(self):
        for role in ('efi-A', 'efi-B', 'var-A', 'var-B', 'home'):
            if role in self.state['formatted']:
                if fs(self.nodes[role], 'UUID') != self.state['formatted'][role]:
                    raise RuntimeError('Formatted partition identity changed: ' + role)
                continue
            self.phase('format-' + role)
            if role.startswith('efi-'): run('mkfs.vfat', '-F', '32', self.nodes[role])
            elif role == 'home': run('mkfs.ext4', '-F', '-O', 'casefold', '-T', 'huge', '-m', '0', self.nodes[role])
            else: run('mkfs.ext4', '-F', self.nodes[role])
            self.state['formatted'][role] = fs(self.nodes[role], 'UUID'); self.save()

    def copy_roots(self):
        for role in ('rootfs-A', 'rootfs-B'):
            if role in self.state['copied']:
                if fs(self.nodes[role], 'UUID') != self.state['copied'][role]: raise RuntimeError('Copied root identity changed')
                print('OXP_DEPLOY_REUSE=' + role, flush=True); continue
            self.phase('copy-' + role)
            run('dd', 'if=' + self.source_root, 'of=' + self.nodes[role], 'bs=16M', 'conv=fsync')
            run('btrfstune', '-f', '-u', self.nodes[role])
            identity = fs(self.nodes[role], 'UUID')
            if not identity or identity == fs(self.source_root, 'UUID') or identity in self.state['copied'].values():
                raise RuntimeError('Copied slots do not have distinct filesystem UUIDs')
            self.state['copied'][role] = identity; self.save()

    def configure(self, slot):
        root_node = self.nodes['rootfs-' + slot]
        # Read protection without log replay before deciding whether any write is owned.
        self.mount(root_node, self.root, '-t', 'btrfs', '-o', 'ro,rescue=nologreplay')
        self.check_os(self.root)
        needs_recovery = run('btrfs', 'property', 'get', '-ts', str(self.root), 'ro', capture=True).strip() != 'ro=true'
        if needs_recovery and not can_recover_root(self.state, slot, fs(root_node, 'UUID')):
            raise RuntimeError('Writable root is not owned by an unfinished configuration')
        self.unmount(self.root)
        self.mount(root_node, self.root, '-t', 'btrfs')
        self.root_mount = self.root
        self.check_os(self.root)
        if needs_recovery:
            run('btrfs', 'property', 'set', '-ts', str(self.root), 'ro', 'true')
            print('OXP_DEPLOY_RECOVER=protected-unfinished-root-' + slot, flush=True)
        if slot not in self.state['configured']:
            self.phase('configure-' + slot)
            run('btrfs', 'filesystem', 'resize', 'max', str(self.root))
            run('btrfs', 'property', 'set', '-ts', str(self.root), 'ro', 'false')
            if self.media_layer and detach_media(self.root, self.media_layer):
                print('OXP_DEPLOY_MEDIA=preview-layer-detached-' + slot, flush=True)
        for role, directory in [('efi-' + slot, 'efi'), ('esp', 'esp'), ('var-' + slot, 'var'), ('home', 'home')]:
            self.mount(self.nodes[role], self.root / directory)
        if slot not in self.state['configured']:
            if self.fault == 'configure-' + slot: raise InjectedFailure('Injected failure with writable root and mounted filesystems')
            if self.fault == 'pause-configure-' + slot:
                # Development fault boundary: the host will kill QEMU, not this process.
                run('sync')
                print('OXP_DEPLOY_HARDSTOP=configure-' + slot + ':root-writable', flush=True)
                while True: signal.pause()
            if self.media_selection and self.media_selection.get('resources'):
                source_home = Path('/mnt/oxp3-install-resources')
                self.mount(self.selection['source_table']['partitions'][4]['node'], source_home, '-o', 'ro')
                try:
                    stage_resources(self.media_selection, source_home / 'oxp3-resources', self.root / 'home')
                    print('OXP_DEPLOY_MEDIA=resources-carried-not-installed', flush=True)
                finally: self.unmount(source_home)
            run('install', '-d', '-o', '1000', '-g', '1000', str(self.root / 'home/deck'))
            if self.bootstrap_available:
                source_root = Path('/mnt/oxp3-bootstrap-source')
                self.mount(self.source_root, source_root, '-t', 'btrfs', '-o', 'ro,rescue=nologreplay')
                try:
                    staged = stage_bootstrap(self.root, source_root, self.state['component_request'])
                    if staged['request'] != self.state['component_request']: raise RuntimeError('Bootstrap request publication changed')
                finally: self.unmount(source_root)
                if slot not in self.state['bootstrap_staged']:
                    self.state['bootstrap_staged'].append(slot); self.save()
                print('OXP_DEPLOY_FIRSTBOOT=shared-explicit-request-staged-' + slot + ':service-not-started', flush=True)
            for path in ('efi/SteamOS', 'esp/SteamOS/conf'): (self.root / path).mkdir(parents=True, exist_ok=True)
            for directory in ('dev', 'proc', 'sys', 'run'): self.mount('/' + directory, self.root / directory, '--bind')
            # A plain /sys bind excludes its efivarfs child. UEFI helpers need
            # the existing firmware-variable mount; BIOS guests have none.
            if Path('/sys/firmware/efi/efivars').is_mount():
                self.mount('/sys/firmware/efi/efivars', self.root / 'sys/firmware/efi/efivars', '--bind')
            self.mount('tmpfs', self.root / 'tmp', '-t', 'tmpfs')
            def target(*args): run('chroot', str(self.root), *args)
            # Upstream refuses an existing output directory. Generate beside it,
            # validate allowed UUID references, then preserve the previous mapping.
            pending = self.root / 'efi/SteamOS' / ('.oxp3-partsets-' + uuid.uuid4().hex)
            target('steamos-partsets', '--devices', ' '.join(self.nodes[r] for r in ROLES), '/efi/SteamOS/' + pending.name)
            allowed = {p['uuid'].lower() for p in self.selection['target_table']['partitions'] if p['node'] in self.nodes.values()}
            references = set()
            for file in pending.iterdir():
                if not file.is_file() or file.is_symlink(): raise RuntimeError('Unexpected generated partition mapping entry')
                for line in file.read_text().splitlines():
                    fields = line.split()
                    if len(fields) != 2 or fields[1].lower() not in allowed:
                        raise RuntimeError('Generated mapping refers outside selected SteamOS partitions')
                    references.add(fields[1].lower())
            if references != allowed: raise RuntimeError('Generated mapping does not cover all selected partitions')
            destination = pending.parent / 'partsets'
            if destination.exists():
                if not destination.is_dir() or destination.is_symlink(): raise RuntimeError('Unexpected existing partition mapping')
                destination.rename(pending.parent / ('.oxp3-partsets-before-' + uuid.uuid4().hex))
            pending.rename(destination)
            run('sync')
            boot_args = ('--image', slot, '--conf-dir', '/esp/SteamOS/conf', '--efi-dir', '/efi', '--set', 'title', slot)
            try:
                target('steamos-bootconf', 'create', *boot_args)
            except subprocess.CalledProcessError as error:
                if error.returncode != 17: raise
                # EEXIST from create: use the supported atomic update operation,
                # require an existing config and preserve its other boot fields.
                target('steamos-bootconf', 'config', '--no-create', *boot_args)
                print('OXP_DEPLOY_REUSE=existing-boot-config-' + slot, flush=True)
            target('grub-mkimage'); target('update-grub')
            config = self.root / 'efi/EFI/steamos/grub.cfg'
            lines = config.read_text().splitlines(); matched = 0
            for index, line in enumerate(lines):
                if 'steamenv_boot' in line and '/boot/vmlinuz-' in line:
                    lines[index] = '\t' + ' '.join(w for w in line.split() if w != 'fsck.mode=auto') + ' console=ttyS0,115200'
                    matched += 1
            if not matched: raise RuntimeError('Missing generated boot entry')
            config.write_text('\n'.join(lines) + '\n')
            if slot == 'A': target('steamcl-install', '--flags', 'restricted', '--force-extra-removable')
            run('btrfs', 'property', 'set', '-ts', str(self.root), 'ro', 'true')
            # Save completion only after the slot has been protected and unmounted.
        if not (self.root / 'efi/EFI/steamos/grub.cfg').is_file(): raise RuntimeError('Configured slot boot files disappeared')
        for destination in reversed(self.mounts[:]):
            if destination == self.root or self.root in destination.parents: self.unmount(destination)
        self.root_mount = None
        if slot not in self.state['configured']:
            self.state['configured'].append(slot); self.save()
        self.assert_protected()

    def assert_protected(self):
        resolve(self.selection, table(self.selection['target_table']['device']))

    def apply(self):
        try:
            self.preflight(); self.open_state(); self.assert_protected()
            self.format_partitions(); self.copy_roots()
            self.configure('A'); self.configure('B'); self.assert_protected()
            self.state.update(status='complete', phase='complete', error=None, configured=['A', 'B']); self.save()
            print('OXP_DEPLOY_CORE=completed', flush=True)
        except Exception as error:
            if self.state_owned:
                self.state.update(status='failed', error=str(error)); self.save()
            raise
        finally:
            self.cleanup()
