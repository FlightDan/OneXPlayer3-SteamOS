"""Hard-stop check at a real configuration boundary in a private fixture overlay."""
import json
from pathlib import Path
import sys

from deployment import Deployment, fs, run, table
from layout import GIB

if len(sys.argv) != 2 or sys.argv[1] not in ('interrupt', 'recover'): raise RuntimeError('Unknown test mode')
if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU': raise RuntimeError('Not QEMU')
if Path('/sys/block/vdd/size').read_text().strip() != '167772160': raise RuntimeError('Not 80 GiB fixture')
target = table('/dev/vdd')
if [p.get('name') for p in target['partitions']] != ['Windows EFI fixture', 'Windows data fixture',
        'esp', 'efi-A', 'efi-B', 'rootfs-A', 'rootfs-B', 'var-A', 'var-B', 'home']:
    raise RuntimeError('Not the tool-created fixture')
choice = {'schema': 1, 'mode': 'virtual_install', 'source_table': table('/dev/vdc'),
          'target_table': target, 'range': {'start': 12 * GIB, 'size': 64 * GIB}}

probe = Deployment(choice, fault='pause-configure-A' if sys.argv[1] == 'interrupt' else None)
try:
    probe.preflight(); probe.open_state()
    if sys.argv[1] == 'interrupt':
        if probe.state['status'] != 'complete' or probe.state['configured'] != ['A', 'B']:
            raise RuntimeError('Hard-stop replay requires an already completed fixture baseline')
        # Re-enter configuration only, preserving all formatted/copy milestones.
        # This is a test setup, not proof of interruption at an arbitrary install phase.
        probe.state['hard_stop_test'] = {'copied': dict(probe.state['copied']),
                                        'formatted': dict(probe.state['formatted']),
                                        'protected': target['partitions'][:2]}
        probe.state['configured'].remove('A')
        probe.phase('configure-A')
        probe.configure('A')
        raise RuntimeError('Expected host termination did not occur')
    checkpoint = probe.state.get('hard_stop_test')
    if checkpoint is None or probe.state['status'] != 'running' or probe.state['phase'] != 'configure-A' or 'A' in probe.state['configured']:
        raise RuntimeError('No unfinished abrupt-stop checkpoint')
    probe.mount(probe.nodes['rootfs-A'], probe.root, '-t', 'btrfs', '-o', 'ro,rescue=nologreplay')
    if run('btrfs', 'property', 'get', '-ts', str(probe.root), 'ro', capture=True).strip() != 'ro=false':
        raise RuntimeError('Hard termination did not leave the expected writable root')
    probe.unmount(probe.root)
    print('OXP_DEPLOY_HARDSTOP=verified-writable-root-after-new-vm-boot', flush=True)
finally:
    probe.cleanup()

Deployment(choice).apply()
probe = Deployment(choice)
try:
    probe.preflight(); probe.open_state()
    if probe.state['status'] != 'complete' or probe.state['configured'] != ['A', 'B']:
        raise RuntimeError('Configuration recovery did not complete')
    if probe.state['copied'] != checkpoint['copied'] or probe.state['formatted'] != checkpoint['formatted']:
        raise RuntimeError('Recovery recopied or reformatted completed filesystems')
    if table('/dev/vdd')['partitions'][:2] != checkpoint['protected']:
        raise RuntimeError('Windows partition metadata changed')
    checks = [('rootfs-A', 'btrfs', None, None), ('rootfs-B', 'btrfs', None, None),
              ('home', 'ext4', 'retry-preserved.txt', 'Already formatted home must survive retry.\n')]
    for role, filesystem, filename, expected in checks:
        options = ['-t', filesystem, '-o', 'ro,rescue=nologreplay' if filesystem == 'btrfs' else 'ro']
        probe.mount(probe.nodes[role], probe.root, *options)
        if filename is None:
            probe.check_os(probe.root)
            if run('btrfs', 'property', 'get', '-ts', str(probe.root), 'ro', capture=True).strip() != 'ro=true':
                raise RuntimeError('Recovered root protection is missing: ' + role)
        elif (probe.root / filename).read_text() != expected: raise RuntimeError('Home content lost')
        probe.unmount(probe.root)
    for node, filesystem, filename, expected in [
        ('/dev/vdd1', 'vfat', 'preserved-efi.txt', 'Windows EFI fixture file must survive deployment.\n'),
        ('/dev/vdd2', 'ntfs-3g', 'preserved.txt', 'Windows fixture data must survive partition append.\n')]:
        probe.mount(node, probe.root, '-t', filesystem, '-o', 'ro')
        if (probe.root / filename).read_text() != expected: raise RuntimeError('Windows fixture file changed')
        probe.unmount(probe.root)
    probe.state['hard_stop_test']['recovery_verified'] = True; probe.save()
    print('OXP_DEPLOY_HARDSTOP=recovered-roots-home-windows-preserved', flush=True)
finally:
    probe.cleanup()
