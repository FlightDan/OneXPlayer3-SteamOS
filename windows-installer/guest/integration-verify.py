"""Independent readonly checks of selected options on both real SteamOS roots."""
import json
import base64
import configparser
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,'/mnt/payload/components')
from runtime_access import verify_runtime_access
from offload_mounts import mount_opt
table=json.loads(subprocess.check_output(['sfdisk','--json','/dev/vdc']))['partitiontable']
parts={p.get('name'):p['node'] for p in table['partitions']}
options=json.loads(Path('/mnt/payload/selection.json').read_text())
target_disk=options.pop('_target_disk',None)
root=Path('/mnt/integration-verify-root'); root.mkdir(exist_ok=True)
requests=[]; home_ids=[]
for slot in ('A','B'):
    mounts=[]
    def mount(node,path,*flags):
        path.mkdir(parents=True,exist_ok=True); subprocess.run(['mount',*flags,node,str(path)],check=True); mounts.append(path)
    try:
        mount(parts['rootfs-'+slot],root,'-t','btrfs','-o','ro,rescue=nologreplay')
        assert subprocess.check_output(['btrfs','property','get','-ts',str(root),'ro'],text=True).strip()=='ro=true'
        mount(parts['var-'+slot],root/'var','-t','ext4','-o','ro,noload')
        mount(parts['home'],root/'home','-t','ext4','-o','ro,noload')
        mount_opt(root,mounts,readonly=True)
        users=[line.split(':') for line in (root/'etc/passwd').read_text().splitlines() if line.startswith('deck:')]
        assert len(users)==1 and users[0][5]=='/home/deck'
        owner=tuple(int(users[0][i]) for i in (2,3))
        for name in ('.local','.local/bin','.local/share','.config','.config/gamescope','.config/gamescope/scripts','.cache'):
            directory=root/'home/deck'/name
            assert directory.is_dir() and not directory.is_symlink(),str(directory)
            info=directory.stat()
            assert (info.st_uid,info.st_gid)==owner and info.st_mode&0o700==0o700, 'Steam user directory is not writable: '+str(directory)
        state=root/'home/.oxp3-installer/integration'/slot
        assert json.loads((state/'request.json').read_text())==options
        results=json.loads((state/'result.json').read_text())
        checked=verify_runtime_access(root,results['components'])
        launcher=root/'home/deck/Desktop/Return.desktop'
        assert launcher.is_file() and launcher.stat().st_uid==owner[0]
        assert os.access(launcher,os.X_OK)
        print('OXP_DECK_RUNTIME_ACCESS='+json.dumps({'slot':slot,'paths':checked,'passed':True}),flush=True)
        installed={name for name,result in results['components'].items() if result['status']=='files_installed'}
        if 'decky' in installed:
            assert (root/'home/deck/.local/share/Steam/.cef-enable-remote-debugging').is_file()
            unit=(root/'etc/systemd/system/plugin_loader.service').read_text()
            assert 'Environment=PRIVILEGED_PATH=/var/lib/oxp3-installer/decky/runtime' in unit
            assert 'Environment=CHOWN_PLUGIN_PATH=0' in unit
            for name,result in results['components'].items():
                for relative in result.get('files',[]):
                    if '/plugins/' in relative and relative.endswith('/plugin.json'):
                        assert relative.startswith('var/lib/oxp3-installer/decky/runtime/plugins/')
                        assert (root/relative).stat().st_uid==0
        if 'input' in installed: assert 'inputplumber.service' in results['services']
        for name,result in results['components'].items():
            assert result['status']=='files_installed' or (name in options['repairs']+options['plugins'] and result['status']=='not_installed' and result.get('safe_to_skip') is True and result.get('reason')), 'Unsafe component result: '+name
        catalog=json.loads(Path('/mnt/payload/components/options.json').read_text())
        for item in catalog['repairs']+catalog['plugins']:
            if item['id'] in installed: assert set(item['dependencies']).issubset(installed), 'Installed component has an unavailable dependency'
        if 'flathub-ustc' in installed:
            definition=configparser.ConfigParser(interpolation=None)
            definition.read(root/'etc/flatpak/remotes.d/flathub.flatpakrepo')
            assert definition['Flatpak Repo']['Url']=='https://mirrors.ustc.edu.cn/flathub'
            assert len(base64.b64decode(definition['Flatpak Repo']['GPGKey'],validate=True))>1024
            config=root/'var/lib/flatpak/repo/config'
            if config.exists():
                existing=configparser.ConfigParser(interpolation=None,strict=False); existing.read(config)
                if existing.has_section('remote "flathub"'):
                    assert existing['remote "flathub"']['url']=='https://mirrors.ustc.edu.cn/flathub'
        assert json.loads((state/'target-disk.json').read_text())==target_disk
        if results['components'].get('xe-dsb',{}).get('status')=='files_installed':
            assert 'options xe enable_dsb=0' in (root/'etc/modprobe.d/xe-oxp3.conf').read_text()
        if results['components'].get('legacy-runtime',{}).get('status')=='files_installed':
            unit=(root/'etc/systemd/system/oxp3-volkey-fix.service').read_text()
            assert 'Type=notify' in unit and 'NotifyAccess=main' in unit and 'TimeoutStartSec=30' in unit
        if results['components'].get('wifi',{}).get('status')=='files_installed':
            for suffix in ('iml.sfi','pci.ddc','pci.sfi','usb.ddc','usb.sfi'):
                relative='usr/lib/firmware/intel/ibt-00a0-0291-'+suffix
                assert any((root/(relative+ext)).is_file() or (root/(relative+ext)).is_symlink() for ext in ('','.xz','.zst')),relative
        if results['components'].get('gm7-resume',{}).get('status')=='files_installed':
            import re
            matched=isinstance(target_disk,dict) and target_disk.get('bus')=='NVMe' and re.search(r'\bGM7\b',target_disk.get('model',''),re.I) is not None
            assert results['components']['gm7-resume']['applicable']==matched
            if matched:
                mount(parts['efi-'+slot],root/'efi','-t','vfat','-o','ro')
                config=(root/'efi/EFI/steamos/grub.cfg').read_text()
                entries=[line for line in config.splitlines() if re.match(r'^\s*(steamenv_boot|linux|linuxefi)\s',line) and '/boot/vmlinuz-' in line]
                assert entries and all('nvme.noacpi=1' in line.split() for line in entries)
                assert 'nvme.noacpi=1' in (root/'etc/default/grub.d/oxp3-nvme.cfg').read_text()
        expected_components=set(options['repairs']+options['plugins'])|({'kde-language'} if options['kde_language']!='system' else set())
        if options.get('set_deck_password',False) or options.get('enable_ssh',False): expected_components.add('deck-access')
        assert set(results['components'])==expected_components
        if results['components']: assert (root/'usr/local/lib/oxp3-integration/slot').read_text().strip()==slot
        if 'gamescope-env' in installed:
            text=(root/'home/deck/.config/systemd/user/gamescope-session.service.d/90-oxp3-desktop-env-isolation.conf').read_text()
            assert 'UnsetEnvironment=WAYLAND_DISPLAY WAYLAND_SOCKET' in text
            assert 'unset-environment WAYLAND_DISPLAY WAYLAND_SOCKET' in text
        if options['kde_language']!='system': assert 'LANGUAGE='+options['kde_language'] in (root/'home/deck/.config/plasma-localerc').read_text()
        if options.get('set_deck_password',False):
            shadow=[line.split(':') for line in (root/'etc/shadow').read_text().splitlines() if line.startswith('deck:')]
            assert len(shadow)==1 and shadow[0][1].startswith('$6$') and len(shadow[0][1])>=90, 'deck password hash was not installed'
        if options.get('enable_ssh',False):
            link=root/'etc/systemd/system/multi-user.target.wants/sshd.service'
            unit=next((root/name for name in ('usr/lib/systemd/system/sshd.service','lib/systemd/system/sshd.service') if (root/name).is_file()),None)
            assert unit is not None and link.is_symlink() and (link.parent/os.readlink(link)).resolve()==unit.resolve(), 'sshd.service is not enabled'
        for name,result in results['components'].items():
            if result['status']=='files_installed':
                for relative in result.get('files',[]): assert (root/relative).is_file(),relative
        if (root/'etc/os-release').read_text().find('3.8.14')>=0:
            for name in ('hdr','desktop-hdr','wifi','input','manager','fan-driver','waydroid'):
                if name in results['components']: assert results['components'][name]['status']=='not_installed'
            assert not (root/'opt/oxp3-desktop-gamma22/6.7.3-1.6').exists()
        else:
            if 'opti2xmx' in installed:
                code="import sys,json;sys.path.insert(0,'/var/lib/oxp3-installer/decky/runtime/plugins/opti2xmx');from manager import Manager;from per_game import compiler_check;p,s,ready=Manager('/home/deck').dependencies();assert ready;ok,report=compiler_check(p);assert ok,report;print('OXP_OPTI2XMX_RUNTIME='+json.dumps({'ready':ready,'compiler':report,'package':str(p),'sr':str(s)}))"
                for command in (['/usr/bin/7z','i'],['/usr/bin/xdotool','--version']):
                    subprocess.run(['chroot',str(root),*command],check=True,stdout=subprocess.DEVNULL)
                base=root/'opt/oxp3-opti2xmx/20261005/runtime'
                for library in [base/'lib/libvulkan_intel.so']:
                    env=['LD_LIBRARY_PATH=/opt/oxp3-opti2xmx/20261005/runtime/igc/igc/local/lib:/opt/oxp3-opti2xmx/20261005/runtime/igc/neo/lib']
                    output=subprocess.check_output(['chroot',str(root),'/usr/bin/env',*env,'/usr/bin/ldd','/'+str(library.relative_to(root))],text=True,stderr=subprocess.STDOUT)
                    assert 'not found' not in output, output
                subprocess.run(['chroot',str(root),'/usr/bin/python3','-I','-B','-c',code],check=True)
                assert not (root/'home/deck/.local/share/opti2xmx/games').exists()
            if 'gyro' in installed:
                assert subprocess.check_output(['chroot',str(root),'/usr/bin/inputplumber','--version'],text=True).strip()=='inputplumber 0.78.0'
                assert subprocess.check_output(['chroot',str(root),'/var/lib/oxp3-gyro-v1/inputplumber','--version'],text=True).strip()=='inputplumber 0.78.0'
                vermagic=subprocess.check_output(['chroot',str(root),'/usr/bin/modinfo','-F','vermagic','/var/lib/oxp3-gyro-v1/oxp3_bmi260.ko'],text=True)
                assert vermagic.split()[0]=='7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9'
                core=subprocess.check_output(['chroot',str(root),'/usr/bin/modinfo','-k','7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9','-F','vermagic','bmi270_core'],text=True)
                assert core.split()[0]==vermagic.split()[0]
                # This Valve core requests the filename directly but does not
                # declare MODULE_FIRMWARE metadata (see bmi270_core.c).
                bmi260=['bmi260-init-data.fw']
                for name in bmi260:
                    assert any(subprocess.run(['chroot',str(root),'/usr/bin/test','-r','/usr/lib/firmware/'+name+suffix]).returncode==0 for suffix in ('','.zst','.xz')), 'Missing firmware: '+name
                print('OXP_GYRO_RUNTIME='+json.dumps({'inputplumber':'0.78.0','module_kernel':vermagic.split()[0],'firmware':bmi260}),flush=True)
                profile=(root/'etc/inputplumber/devices.d/49-onexplayer_3-gyro.yaml').read_text()
                assert 'gyro_bias: [0, 0, 0]' in profile and 'gyro_auto_calibrate: false' in profile
                assert (root/'etc/inputplumber/devices.d/50-onexplayer_3.yaml').is_file()
            if installed & {'oxp3-cpu','charging','native-tdp','legacy-runtime'}:
                subprocess.run(['chroot',str(root),'/usr/bin/python3','-I','-B','-c','import dbus; import gi; import evdev'],check=True)
            # lsinitcpio needs private scratch space even in list mode. The
            # actual roots/var/home and source block device remain read-only.
            mount('tmpfs',root/'tmp','-t','tmpfs')
            mount('/dev',root/'dev','--bind')
            for initramfs in (root/'boot').glob('initramfs*'):
                listing=subprocess.check_output(['chroot',str(root),'/usr/bin/lsinitcpio','-l','/boot/'+initramfs.name],text=True,stderr=subprocess.STDOUT)
                assert 'usr/lib/modules/' in listing and 'failed to' not in listing, 'Cannot inspect initramfs: '+listing
                if 'xe-dsb' in installed:
                    import re
                    # The accepted kernel loads xe from the real root. Refuse a
                    # changed image that would load it before our modprobe file.
                    assert not re.search(r'(^|/)xe\.ko(?:\.(?:zst|xz|gz))?$',listing,re.M), 'Early xe needs its DSB configuration included in initramfs'
                modules=[line for line in listing.splitlines() if any(x in line for x in ('hid-oxp','hid_oxp','oxpec'))]
                print('OXP_INITRAMFS_DRIVERS='+json.dumps({'image':initramfs.name,'entries':modules}),flush=True)
        requests.append(results['options']); home_ids.append((root/'home/.oxp3-installer/integration/shared').stat().st_ino)
        print('OXP_INTEGRATION_VERIFY='+json.dumps({'slot':slot,'records':len(results['components']),'root_protected':True,'readonly':True}),flush=True)
    finally:
        for path in reversed(mounts): subprocess.run(['umount',str(path)],check=True)
assert requests[0]==requests[1] and home_ids[0]==home_ids[1]
