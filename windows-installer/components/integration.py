"""Offline repair/plugin installation with required OS image update hold.

Restore update-hold files using the existing per-slot journal offline, or
reboot after restoration before relying on the original update source.
This installer never stops or restarts services. Unattended first-boot
completion remains unverified; see the 0.1.3 release notes.
"""
import argparse
import base64
import configparser
import errno
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_transaction import FileTransaction, atomic_write, directory_fd, snapshot
from hdr.installer import ensure_directory, ensure_user_directory
from directory_transaction import DirectoryTransaction
from release_notes import render as render_release_note
from shared_storage import validate_mounts, files as shared_storage_files
from update_hold import files as update_hold_files

KERNEL='7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9'
VERSION={'ID':'steamos','VERSION_ID':'3.10','BUILD_ID':'20260924.1000'}
PLUGIN_ROOT='var/lib/oxp3-installer/decky/runtime/plugins'

def prepare_css_themes(root, owner):
    """Make only CSS Loader's writable data directory user-owned."""
    path=Path(root)/'home/deck/homebrew/themes'
    ensure_directory(path,0o755,owner)
    fd=directory_fd(path)
    try:
        info=os.fstat(fd)
        if info.st_uid not in (0,owner[0]): raise RuntimeError('CSS theme directory belongs to another account')
        if info.st_mode&0o700!=0o700: raise RuntimeError('CSS theme directory is not owner-writable/searchable')
        if (info.st_uid,info.st_gid)!=tuple(owner): os.fchown(fd,*owner); os.fsync(fd)
    finally: os.close(fd)

def managed_plugin_files(files):
    """Keep plugin code in the root-owned directory actually scanned by Decky."""
    prefix='home/deck/homebrew/plugins/'
    result={}
    for path,entry in files.items():
        if path.startswith(prefix):
            path=PLUGIN_ROOT+'/'+path[len(prefix):]
            entry=dict(entry,user=False)
        result[path]=entry
    return result

RETURN_TO_GAME=b'[Desktop Entry]\nType=Application\nName=Return to Gaming Mode\nName[zh_CN]=\xe8\xbf\x94\xe5\x9b\x9e\xe6\xb8\xb8\xe6\x88\x8f\xe6\xa8\xa1\xe5\xbc\x8f\nExec=/usr/bin/steamos-session-select gamescope\nIcon=steam\nTerminal=false\nCategories=Game;\n'

def desktop_names(files, language):
    """Pin installed launcher names to the installer choice, independently of KDE."""
    for path, entry in files.items():
        if not path.endswith('.desktop'): continue
        lines=entry['data'].decode('utf-8').splitlines()
        start=next((i for i,line in enumerate(lines) if line=='[Desktop Entry]'),None)
        if start is None: continue
        end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('[')),len(lines))
        body=lines[start+1:end]
        values=dict(line.split('=',1) for line in body if '=' in line)
        name=values.get('Name[zh_CN]',values.get('Name')) if language=='zh-CN' else values.get('Name')
        if name is None: continue
        body=[('Name='+name if line.startswith('Name=') else line) for line in body if not line.startswith('Name[')]
        entry['data']=('\n'.join(lines[:start+1]+body+lines[end:])+'\n').encode('utf-8')
    return files

def shared_managed(state, component, relative):
    record=state.parent/'shared'/component/'state.json'
    if not record.exists(): return False
    value=json.loads(base64.b64decode(snapshot(record,maximum=256*1024*1024)['data']))
    return value['phase']!='rolled_back' and relative in value['allowed']

def release(root):
    return dict((k,v.strip('"')) for line in (Path(root)/'etc/os-release').read_text().splitlines() if '=' in line for k,v in [line.split('=',1)])

def package_version(root, name):
    found=[]
    # SteamOS stores its image-owned database outside the per-slot /var mount.
    database=Path(root)/'usr/lib/holo/pacmandb/local'
    if not database.is_dir(): database=Path(root)/'var/lib/pacman/local'
    for path in database.glob(name+'-*/desc'):
        lines=path.read_text().splitlines()
        if '%NAME%' in lines and lines[lines.index('%NAME%')+1]==name:
            found.append(lines[lines.index('%VERSION%')+1])
    return found[0] if len(found)==1 else None

def validate(options, catalog):
    required={'schema','repairs','plugins','installer_language','kde_language'}
    optional={'set_deck_password','enable_ssh','storage_mounts'}
    if not required.issubset(options) or set(options)-required-optional or options['schema']!=1: raise ValueError('Unsupported options schema')
    for key in ('set_deck_password','enable_ssh'):
        if key in options and type(options[key]) is not bool: raise ValueError('Invalid Deck access choice')
    validate_mounts(options.get('storage_mounts',[]))
    if options['installer_language'] not in catalog['languages'] or options['kde_language'] not in catalog['kde_languages']: raise ValueError('Unknown language')
    for category in ('repairs','plugins'):
        choices=options[category]
        if not isinstance(choices,list) or any(type(x)!=str for x in choices) or len(set(choices))!=len(choices): raise ValueError('Duplicate/invalid choice')
        if set(choices)-{x['id'] for x in catalog[category]}: raise ValueError('Unknown component')
    selected=set(options['repairs']+options['plugins'])
    for item in catalog['repairs']+catalog['plugins']:
        if item['id'] in selected and not item.get('available',True):
            key='unavailable_en' if options['installer_language']=='en-US' else 'unavailable_zh'
            raise ValueError(item.get(key) or 'Component is not available for installation: '+item['id'])
        if item['id'] in selected and set(item['dependencies'])-selected: raise ValueError('Disabled dependency for '+item['id'])
    return options

def trusted_tree(path):
    path=Path(path)
    for entry in [path,*path.rglob('*')]:
        info=entry.lstat()
        if info.st_uid!=0 or info.st_mode&0o022 or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)): raise RuntimeError('Untrusted install payload: '+str(entry))

class LogicalFiles(FileTransaction):
    def snapshot(self,path):
        return snapshot(path,maximum=64*1024*1024)
    def __init__(self, state, root, files, owner):
        self.root=Path(root).absolute(); self.files=files; self.owner=owner
        super().__init__(state,[self.root/item for item in files])
    def installed_metadata(self,path,original):
        if original['exists']: return super().installed_metadata(path,original)
        metadata=self.files[str(Path(path).relative_to(self.root))]
        uid,gid=self.owner if metadata.get('user') else (0,0)
        return {'mode':metadata.get('mode',0o644),'uid':uid,'gid':gid}
    def save(self,value):
        stored=dict(value,allowed=[str(Path(p).relative_to(self.root)) for p in value['allowed']],
                    metadata={p:{k:v for k,v in item.items() if k in ('user','mode')} for p,item in self.files.items()})
        for name in ('original','applied','accepted'): stored[name]={str(Path(p).relative_to(self.root)):v for p,v in value.get(name,{}).items()}
        atomic_write(self.state,(json.dumps(stored)+'\n').encode(),0o600)
    def load(self):
        saved=snapshot(self.state,maximum=256*1024*1024)
        if saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('Untrusted repair journal')
        value=json.loads(base64.b64decode(saved['data']))
        if value['allowed']!=list(self.files): raise RuntimeError('Repair target set changed')
        value['allowed']=list(self.allowed)
        for name in ('original','applied','accepted'): value[name]={str(self.root/p):v for p,v in value.get(name,{}).items()}
        return value

class LogicalDirectory(DirectoryTransaction):
    def __init__(self,root,component='desktop-hdr'):
        self.root=Path(root).absolute()
        self.prefix={'desktop-hdr':'opt/oxp3-desktop-gamma22/6.7.3-1.6','opti2xmx':'opt/oxp3-opti2xmx/20261005'}[component]
        # Keep rename journals on the same filesystem as the compositor. Home
        # is a separate ext4 partition on real installations.
        parent=(self.root/self.prefix).parent
        super().__init__(parent/'.installer-state',self.root/self.prefix,parent)
    def save(self,value):
        stored=dict(value,destination=self.prefix)
        atomic_write(self.state,(json.dumps(stored)+'\n').encode(),0o600,0,0)
    def load(self):
        saved=snapshot(self.state)
        if saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('Untrusted compositor journal')
        value=json.loads(base64.b64decode(saved['data']))
        if value['destination']!=self.prefix: raise RuntimeError('Component destination changed')
        value['destination']=str(self.destination)
        return value

def config_file(root, relative, group, values):
    path=Path(root)/relative
    saved=snapshot(path)
    text=base64.b64decode(saved['data']).decode() if saved['exists'] else ''
    # KDE configuration supports duplicate key groups and localized keys; edit
    # only the requested group's plain keys, keeping unrelated text verbatim.
    lines=text.splitlines(); start=next((i for i,l in enumerate(lines) if l.strip()=='['+group+']'),None)
    if start is None: lines+=['','['+group+']']; start=len(lines)-1
    end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('[')),len(lines))
    body=lines[start+1:end]
    for key,value in values.items():
        matches=[i for i,line in enumerate(body) if line.split('=',1)[0].strip()==key]
        if len(matches)>1: raise RuntimeError('Ambiguous KDE setting '+key)
        if matches: body[matches[0]]=key+'='+value
        else: body.append(key+'='+value)
    return ('\n'.join(lines[:start+1]+body+lines[end:])+'\n').encode()

def flathub_files(root, payload):
    # Flatpak supports complete, signed system remote definitions in remotes.d.
    # Do not invent an OSTree repo/config for a fresh image: Flatpak must create
    # the repository and import the Flathub signing key itself on first use.
    parser=configparser.ConfigParser(interpolation=None)
    parser.optionxform=str
    parser.read_string((Path(payload)/'components/flathub.flatpakrepo').read_text())
    definition=parser['Flatpak Repo']
    if definition.get('Url')!='https://dl.flathub.org/repo/' or len(base64.b64decode(definition['GPGKey'],validate=True))<1024:
        raise RuntimeError('Invalid bundled Flathub remote definition')
    definition['Url']='https://mirrors.ustc.edu.cn/flathub'
    output=io.StringIO(); parser.write(output,space_around_delimiters=False)
    files={'etc/flatpak/remotes.d/flathub.flatpakrepo':{'data':output.getvalue().encode()}}
    relative='var/lib/flatpak/repo/config'
    saved=snapshot(Path(root)/relative)
    if saved['exists']:
        existing=configparser.ConfigParser(interpolation=None,strict=False)
        existing.read_string(base64.b64decode(saved['data']).decode())
        if existing.has_section('remote "flathub"'):
            files[relative]={'data':config_file(root,relative,'remote "flathub"',{'url':definition['Url']})}
    return files

def zip_files(archive, prefix):
    with zipfile.ZipFile(archive) as package:
        entries=package.infolist()
        if len(entries)>3000 or sum(x.file_size for x in entries)>128*1024*1024: raise RuntimeError('Oversized plugin archive')
        tops={PurePosixPath(x.filename).parts[0] for x in entries if PurePosixPath(x.filename).parts}
        if len(tops)!=1: raise RuntimeError('Plugin must have one root folder')
        top=next(iter(tops)); output={}; seen=set()
        for item in entries:
            path=PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16) or item.filename in seen: raise RuntimeError('Unsafe plugin path')
            seen.add(item.filename)
            if item.is_dir(): continue
            if stat.S_IFMT(item.external_attr>>16) not in (0,stat.S_IFREG): raise RuntimeError('Special plugin entry')
            if len(path.parts)<2: raise RuntimeError('Invalid plugin folder')
            output[prefix+'/'+path.as_posix()]={'data':package.read(item),'user':False,'mode':0o644}
        return output,top

def apply_files(root,state,name,files,owner):
    if name in ('desktop-hdr','opti2xmx'):
        prefix={'desktop-hdr':'opt/oxp3-desktop-gamma22/6.7.3-1.6','opti2xmx':'opt/oxp3-opti2xmx/20261005'}[name]
        bundle={p:v for p,v in files.items() if p.startswith(prefix+'/')}
        if bundle:
            import tempfile,shutil
            parent=(Path(root)/prefix).parent
            ensure_directory(parent,0o755)
            stage_path=Path(tempfile.mkdtemp(prefix='.stage-',dir=parent))
            stage_path.chmod(0o755)
            try:
                for path,item in bundle.items():
                    destination=stage_path/path[len(prefix)+1:]
                    ensure_directory(destination.parent,0o755)
                    atomic_write(destination,item['data'],item.get('mode',0o644),0,0)
                transaction=LogicalDirectory(root,name)
                if transaction.state.exists() and transaction.load()['phase']=='rolled_back':
                    import uuid
                    transaction.directory.rename(transaction.directory.with_name('.installer-history-'+uuid.uuid4().hex))
                    transaction=LogicalDirectory(root,name)
                transaction.apply(stage_path)
            finally: shutil.rmtree(stage_path)
            files={p:v for p,v in files.items() if p not in bundle}
    for path,metadata in files.items():
        relative=PurePosixPath(path)
        if relative.is_absolute() or '..' in relative.parts or '\\' in path: raise RuntimeError('Unsafe install target')
        parent = Path(root)/path.rsplit('/',1)[0]
        if metadata.get('user'):
            ensure_user_directory(parent, 0o755, owner, Path(root)/'home/deck')
        else:
            ensure_directory(parent, 0o755)
    # Home targets have one original across both slots. Root files are per slot.
    for shared in (False,True):
        selected={p:v for p,v in files.items() if p.startswith('home/')==shared}
        if not selected: continue
        directory=(state.parent/'shared' if shared else state)/name
        if (directory/'state.json').exists():
            previous=json.loads(base64.b64decode(snapshot(directory/'state.json',maximum=256*1024*1024)['data']))
            if previous['phase']=='rolled_back':
                import uuid
                directory.rename(directory.with_name(name+'-history-'+uuid.uuid4().hex))
        transaction=LogicalFiles(directory,root,selected,owner)
        transaction.apply({str(Path(root)/p):v['data'] for p,v in selected.items()})

def seed_decky_order(root, state, owner):
    from decky_order import SETTINGS, files as order_files
    journal=state/'decky-order'
    if (journal/'state.json').exists():
        transaction=LogicalFiles(journal,root,{SETTINGS:{}},owner)
        value=transaction.load()
        # This is a first-install default, never a recurring sorting policy.
        if value['phase']=='installed': return [SETTINGS]
        encoded=value.get('applied',{}).get(str(root/SETTINGS))
        if value['phase']!='rolled_back' and encoded is not None:
            files={SETTINGS:{'data':base64.b64decode(encoded)}}
        else: files=order_files(root)
    else: files=order_files(root)
    if files: apply_files(root,state,'decky-order',files,owner)
    return list(files)


def shared_storage_transaction_exists(state):
    """Any previous transaction evidence prevents a preflight-only skip."""
    for directory in (state/'shared-storage', state.parent/'shared/shared-storage'):
        try: directory.lstat()
        except FileNotFoundError: continue
        return True
    return False


def verify_shared_storage_skip(state, report):
    """Readonly verification must not accept a skipped partial transaction."""
    if (report.get('status')!='not_installed' or report.get('safe_to_skip') is not True or
            not isinstance(report.get('reason'),str) or not report['reason'].strip() or
            report.get('files') or report.get('mounts') or shared_storage_transaction_exists(state)):
        raise RuntimeError('Unsafe shared storage skip or existing transaction evidence')


def stage_shared_storage(root, state, mounts, owner):
    # File generation is readonly. Once apply_files starts, even a failure before
    # the journal commit may have created directories or changed target metadata.
    # Never downgrade that failure or a failed retry of an older transaction.
    previous=shared_storage_transaction_exists(state)
    try:
        files=shared_storage_files(root,mounts,owner,managed=(state/'shared-storage/state.json').exists())
    except (OSError,ValueError,RuntimeError) as error:
        if (previous or shared_storage_transaction_exists(state) or
                isinstance(error,OSError) and error.errno not in
                (errno.ENOENT,errno.ENOTDIR,errno.ELOOP,errno.EACCES,errno.EPERM)):
            raise
        report={'status':'not_installed','safe_to_skip':True,'reason':str(error) or type(error).__name__}
        verify_shared_storage_skip(state,report)
        return report
    apply_files(root,state,'shared-storage',files,owner)
    return {'status':'files_installed','files':list(files),
        'mounts':[{'partuuid':item['partuuid'],'filesystem':item['filesystem'],
                   'path':'/mnt/shared/'+item['mount_name']} for item in mounts],
        'activation':'on_access_after_boot','steam_library_added':False}


def refuse_legacy_update_policy(root):
    """Do not silently carry an old installer pause into a newly prepared image."""
    reason=('This image contains a legacy installer system-update-policy. '
            'Prepare again from the original SteamOS image to allow system updates; '
            'existing updater files and recovery journals were preserved.')
    if os.path.lexists(root/'var/lib/oxp3-installer/system-update-policy.json'):
        raise RuntimeError(reason)
    for slot in ('A','B'):
        directory=root/'home/.oxp3-installer/integration'/slot/'system-update-policy'
        if not os.path.lexists(directory): continue
        try:
            saved=snapshot(directory/'state.json',maximum=256*1024*1024)
            value=json.loads(base64.b64decode(saved['data'])) if saved['exists'] else None
            restored=(saved['exists'] and saved['uid']==0 and not saved['mode']&0o077 and
                      isinstance(value,dict) and value.get('phase')=='rolled_back')
        except (OSError,ValueError,RuntimeError): restored=False
        if not restored: raise RuntimeError(reason)


def stage(root, payload, options, slot, deck_password_hash=None, target_disk=None):
    root=Path(root).absolute(); payload=Path(payload); validate(options,json.loads((payload/'components/options.json').read_text()))
    if os.geteuid()!=0: raise RuntimeError('Root required')
    refuse_legacy_update_policy(root)
    # Mandatory, read-only preflight precedes even home/journal directory writes.
    # The builder admits only the supported original 3.10/build20260924.1000.
    hold_files=update_hold_files(root)
    trusted_tree(payload/'components'); trusted_tree(payload/'integration')
    bundle_release=json.loads((payload/'components/release.json').read_text())
    if bundle_release.get('schema')!=1 or bundle_release.get('product')!='OXP3 SteamOS' or not isinstance(bundle_release.get('version'),str): raise RuntimeError('Invalid integration release metadata')
    user=[line.split(':') for line in (root/'etc/passwd').read_text().splitlines() if line.startswith('deck:')]
    if len(user)!=1 or user[0][5]!='/home/deck': raise RuntimeError('Expected deck account')
    owner=tuple(int(user[0][i]) for i in (2,3))
    if min(owner)<=0: raise RuntimeError('Non-root desktop user required')
    ensure_directory(root/'home/deck',0o755,owner)
    state=root/'home/.oxp3-installer/integration'/slot
    ensure_directory(state,0o700)
    for directory in [state,*state.parents]:
        if not directory.is_relative_to(root/'home/.oxp3-installer'): break
        info=directory.lstat()
        if info.st_uid!=0 or info.st_mode&0o022: raise RuntimeError('Untrusted integration state ancestor')
    saved=snapshot(state/'request.json')
    encoded=(json.dumps(options,sort_keys=True)+'\n').encode()
    if saved['exists'] and (saved['uid']!=0 or saved['mode']&0o077 or base64.b64decode(saved['data'])!=encoded): raise RuntimeError('Changed options conflict with existing installation')
    if not saved['exists']: atomic_write(state/'request.json',encoded,0o600,0,0)
    # Steam creates its own files on first launch. Preparing only leaf files
    # leaves root-owned XDG ancestors on a fresh home and blocks that launch.
    for relative in ('.local', '.local/bin', '.local/share', '.config',
                     '.config/gamescope', '.config/gamescope/scripts', '.cache'):
        ensure_user_directory(root/'home/deck'/relative, 0o755, owner, root/'home/deck')
    # Bind a repeated image preparation to the same reviewed destination.
    disk_record=state/'target-disk.json'
    disk_data=(json.dumps(target_disk,sort_keys=True)+'\n').encode()
    previous_disk=snapshot(disk_record)
    if previous_disk['exists'] and base64.b64decode(previous_disk['data'])!=disk_data:
        raise RuntimeError('Prepared repair target disk changed')
    if not previous_disk['exists']: atomic_write(disk_record,disk_data,0o600,0,0)
    manifest_path=payload/'integration/manifest.json'
    manifests=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    reports={}; selected=set(options['repairs']+options['plugins']); services=[]
    catalog=json.loads((payload/'components/options.json').read_text())
    items={x['id']:x for x in catalog['repairs']+catalog['plugins']}
    compatible=all(release(root).get(k)==v for k,v in VERSION.items())
    # This is a required preparation invariant, outside optional repair handling.
    # stage is already called for each A/B slot by the existing image pipeline.
    apply_files(root,state,'system-update-hold',hold_files,owner)
    reports['system-update-hold']={
        'status':'files_installed','activation':'next-boot','files':list(hold_files),
        'os_image_updates':'held','steam_client_updates':'unchanged',
        'steam_game_updates':'unchanged',
        'restore':'Restore this component journal in both slots offline, or reboot after restoring before using the original update source.'}
    print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':'system-update-hold',**reports['system-update-hold']}),flush=True)
    if options.get('set_deck_password',False) or options.get('enable_ssh',False):
        files={}; ssh_link_created=False; ssh_link_target=None
        if options.get('set_deck_password',False):
            if not isinstance(deck_password_hash,str) or not re.fullmatch(r'\$6\$(?:rounds=\d+\$)?[A-Za-z0-9./]{1,16}\$[A-Za-z0-9./]{20,100}',deck_password_hash):
                raise RuntimeError('A valid SHA-512 crypt hash is required for the selected deck password')
            shadow=root/'etc/shadow'; saved=snapshot(shadow)
            if not saved['exists'] or saved['uid']!=0 or saved['mode']&0o077: raise RuntimeError('A private root-owned shadow file is required')
            text=base64.b64decode(saved['data']).decode('utf-8'); lines=text.splitlines()
            matches=[i for i,line in enumerate(lines) if line.startswith('deck:')]
            if len(matches)!=1: raise RuntimeError('Expected exactly one deck shadow entry')
            fields=lines[matches[0]].split(':')
            if len(fields)!=9: raise RuntimeError('Malformed deck shadow entry')
            fields[1]=deck_password_hash; lines[matches[0]]=':'.join(fields)
            files['etc/shadow']={'data':(('\n'.join(lines)+'\n') if text.endswith('\n') else '\n'.join(lines)).encode('utf-8')}
        if options.get('enable_ssh',False):
            unit=next((name for name in ('usr/lib/systemd/system/sshd.service','lib/systemd/system/sshd.service') if (root/name).is_file()),None)
            if unit is None: raise RuntimeError('The SteamOS sshd.service unit is missing')
            link=root/'etc/systemd/system/multi-user.target.wants/sshd.service'
            ensure_directory(link.parent,0o755)
            ssh_link_target=os.path.relpath(root/unit,link.parent)
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or os.readlink(link)!=ssh_link_target: raise RuntimeError('Conflicting sshd.service enablement')
            else:
                os.symlink(ssh_link_target,link); ssh_link_created=True
            services.append('sshd.service')
        if files: apply_files(root,state,'deck-access',files,owner)
        reports['deck-access']={'status':'files_installed','activation':'boot-prepared','files':list(files),
            'ssh_link_created':ssh_link_created,'ssh_link_target':ssh_link_target}
        print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':'deck-access',**reports['deck-access']}),flush=True)
    order=['decky','windows-reboot','steamgriddb','protondb','tabmaster','css-loader','autoflatpaks','deck-settings','hltb','animation-changer','waydroid','manager','fan-driver']+[x for x in options['repairs'] if x not in ('manager','fan-driver')]
    for name in dict.fromkeys(order):
        if name not in selected: continue
        applying=False
        service_count=len(services)
        try:
            missing=[d for d in items[name]['dependencies'] if reports.get(d,{}).get('status')!='files_installed']
            if missing: raise RuntimeError('Dependency not installed: '+', '.join(missing))
            if name in options['repairs'] and name not in ('keyboard','gamescope-env','flathub-ustc') and not compatible: raise RuntimeError('Requires SteamOS 3.10 build 20260924.1000 and exact 7.2.4 kernel')
            files={}; metadata=manifests.get(name,{})
            if name in options['repairs'] and name not in ('slot-switch','keyboard','gamescope-env','flathub-ustc','hdr','gm7-resume','multifunction') and name not in manifests:
                raise RuntimeError('Component resource manifest is missing: '+name)
            for package,version in metadata.get('packages',{}).items():
                if package_version(root,package)!=version: raise RuntimeError('Incompatible package: '+package+' '+version)
            if metadata.get('missing'): raise RuntimeError('; '.join(metadata['missing']))
            managed=set()
            record=snapshot(state/name/'state.json',maximum=256*1024*1024)
            if record['exists']:
                previous=json.loads(base64.b64decode(record['data']))
                if previous['phase']!='rolled_back': managed=set(previous['allowed'])
            for entry in metadata.get('files',[]):
                target=entry['target']
                if entry.get('missing_only') and target not in managed and any(os.path.lexists(str(root/target)+suffix) for suffix in ('','.xz','.zst')):
                    continue # Preserve image-owned firmware, including compressed files/links.
                files[target]=dict(entry,data=(payload/'integration'/entry['source']).read_bytes())
            if name=='gm7-resume':
                from boot_repairs import gm7_files
                files=gm7_files(root,target_disk)
            if metadata.get('runtime_archive'):
                runtime_prefix={'desktop-hdr':'opt/oxp3-desktop-gamma22/6.7.3-1.6/','opti2xmx':'opt/oxp3-opti2xmx/20261005/'}[name]
                with tarfile.open(payload/'integration'/metadata['runtime_archive']) as archive:
                    members={x.name.removeprefix('./'):x for x in archive.getmembers() if x.name not in ('.','./')}
                    for path,item in members.items():
                        part=PurePosixPath(path)
                        if part.is_absolute() or '..' in part.parts or '\\' in path: raise RuntimeError('Unsafe desktop runtime path')
                        if item.isdir(): continue
                        seen=set(); actual=item
                        while actual.issym():
                            if actual.name in seen: raise RuntimeError('Cyclic desktop runtime link')
                            seen.add(actual.name); link=PurePosixPath(actual.linkname)
                            if link.is_absolute() or '..' in link.parts: raise RuntimeError('External desktop runtime link')
                            actual=members[str(PurePosixPath(actual.name.removeprefix('./')).parent/link)]
                        if not actual.isfile() or actual.size>(256 if name=='opti2xmx' else 64)*1024*1024: raise RuntimeError('Invalid runtime entry')
                        files[runtime_prefix+path]={'data':archive.extractfile(actual).read(),'mode':0o755 if actual.mode&0o111 else 0o644}
            if name in ('oxp3-fan','oxp3-cpu'):
                target='var/lib/'+('oxp3-fan' if name=='oxp3-fan' else 'oxp3-cpu')+'/config.json'
                existing=snapshot(root/target)
                default={'mode':'auto'} if name=='oxp3-fan' else {'enabled':False,'epp':'balance_performance','p_mhz':4700,'e_mhz':3600,'lp_mhz':3100}
                files[target]={'data':base64.b64decode(existing['data']) if existing['exists'] else (json.dumps(default)+'\n').encode(),'mode':0o600}
            if name=='hdr':
                if package_version(root,'gamescope')!='3.16.30-1': raise RuntimeError('Incompatible Gamescope')
                from hdr.generate import generate
                files={'home/deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua':{'data':generate().encode(),'user':True}}
            elif name=='flathub-ustc':
                files=flathub_files(root,payload)
            elif name=='keyboard':
                if not (root/'usr/share/applications/org.kde.plasma.keyboard.desktop').is_file(): raise RuntimeError('Plasma Keyboard dependency is not installed')
                relative='home/deck/.config/kwinrc'
                files={relative:{'data':config_file(root,relative,'Wayland',{'InputMethod':'/usr/share/applications/org.kde.plasma.keyboard.desktop','VirtualKeyboardMode':'1'}),'user':True}}
            elif name=='multifunction':
                relative='etc/inputplumber/capability_maps.d/oxp3-installer.yaml'
                mapping=root/relative
                if not mapping.exists(): mapping=root/'usr/share/inputplumber/capability_maps/oxp3-installer.yaml'
                text=mapping.read_text()
                start=text.index('  - name: Keyboard key (Ctrl+Meta+O)'); end=text.index('  - name: Orange Button',start); block=text[start:end]
                old='    target_event:\n      gamepad:\n        button: Keyboard'
                already=old.replace('Keyboard','RightPaddle2')
                if block.count(old)!=1 and block.count(already)!=1: raise RuntimeError('Unsupported multifunction mapping')
                files={relative:{'data':(text[:start]+block.replace(old,old.replace('Keyboard','RightPaddle2'))+text[end:]).encode()}}
            elif name=='decky':
                binary=(payload/'plugins/decky/PluginLoader').read_bytes()
                if not binary.startswith(b'\x7fELF'): raise RuntimeError('Invalid Linux Decky binary')
                from plugin_installer import UNIT
                files={'var/lib/oxp3-installer/decky/runtime/services/PluginLoader':{'data':binary,'mode':0o755},'etc/systemd/system/plugin_loader.service':{'data':UNIT}}
                marker='home/deck/.local/share/Steam/.cef-enable-remote-debugging'
                ensure_user_directory((root/marker).parent,0o755,owner,root/'home/deck')
                # Include our shared marker on repeated A/B preparation so its
                # original and restore record stay stable. Preserve preexisting markers.
                if not (root/marker).exists() or shared_managed(state,'decky',marker): files[marker]={'data':b'','user':True}
                services.append('plugin_loader.service')
            elif name=='windows-reboot':
                from windows_reboot import files as windows_reboot_files
                files=windows_reboot_files(root,payload/'components')
            elif name=='slot-switch':
                from slot_switch import files as slot_switch_files
                files=slot_switch_files(root,payload/'components')
            elif name=='waydroid':
                if not compatible: raise RuntimeError('Waydroid r2 requires the accepted SteamOS 3.10 build')
                profile=json.loads((payload/'waydroid/profile.json').read_text())
                with tarfile.open(payload/'waydroid'/profile['archive']) as bundle:
                    for member in bundle.getmembers():
                        path=PurePosixPath(member.name)
                        if path.is_absolute() or '..' in path.parts or '\\' in member.name: raise RuntimeError('Unsafe Waydroid bundle')
                        if not member.isfile():
                            if not member.isdir(): raise RuntimeError('Special Waydroid bundle entry')
                            continue
                        relative=PurePosixPath(*path.parts[1:]).as_posix()
                        files['usr/local/lib/oxp3-waydroid/'+relative]={'data':bundle.extractfile(member).read()}
                desktop='[Desktop Entry]\nType=Application\nName=Install Waydroid\nName[zh_CN]=安装 Waydroid\nExec=konsole -e sudo waydroid init -s GAPPS\nIcon=waydroid\nTerminal=false\nCategories=System;\n'.encode('utf-8')
                # The applications directory only adds a menu entry. KDE's
                # desktop also needs its own executable, deck-owned launcher.
                files['home/deck/Desktop/oxp3-waydroid-setup.desktop']={'data':desktop,'mode':0o755,'user':True}
                files['home/deck/.local/share/applications/oxp3-waydroid-setup.desktop']={'data':desktop,'user':True}
            elif name in options['plugins']:
                pinned={'protondb':'protondb-1.3.4.zip','hltb':'hltb-2.0.12.zip',
                        'tabmaster':'tabmaster-2.15.1+oxp3.1.zip'}
                archives=([payload/'plugins'/name/pinned[name]] if name in pinned else
                          list((payload/'plugins'/name).glob('*.zip')))
                archives=[path for path in archives if path.is_file()]
                if len(archives)!=1: raise RuntimeError('Plugin resource is missing or ambiguous')
                files,folder=zip_files(archives[0],PLUGIN_ROOT)
                plugin=json.loads(files[PLUGIN_ROOT+'/'+folder+'/plugin.json']['data'])
                required={'steamgriddb':'SteamGridDB','protondb':'ProtonDB Badges','tabmaster':'TabMaster','css-loader':'CSS Loader','autoflatpaks':'AutoFlatpaks','deck-settings':'Deck Settings','hltb':'HLTB for Deck','animation-changer':'Animation Changer'}[name]
                if plugin['name']!=required: raise RuntimeError('Selected plugin identity does not match archive')
                if name in ('protondb','hltb','tabmaster'):
                    prefix=PLUGIN_ROOT+'/'+folder+'/'
                    package=json.loads(files[prefix+'package.json']['data'])
                    expected={'protondb':'1.3.4','hltb':'2.0.12','tabmaster':'2.15.1+oxp3.1'}[name]
                    if package['version']!=expected: raise RuntimeError('Selected plugin version does not match the pinned release')
                    runtime={'protondb':('main.py','settings.py','dist/index.js'),
                             'hltb':('dist/index.js',),'tabmaster':('dist/index.js',)}[name]
                    if any(prefix+relative not in files for relative in runtime): raise RuntimeError('Missing pinned plugin runtime file')
                    if name=='tabmaster':
                        expected_patch='Allow absent Steam achievement cache during initialization'
                        bundle=files[prefix+'dist/index.js']['data'].decode('utf-8')
                        if package.get('oxp3_compatibility_patch')!=expected_patch or any(
                            marker not in bundle for marker in (
                                'm_achievementProgress?.mapCache?.size ?? 0',
                                'm_achievementProgress?.mapCache?.get(appOverview.appid)',
                            )
                        ):
                            raise RuntimeError('TabMaster compatibility patch is missing from its frontend runtime')
                if name=='css-loader': prepare_css_themes(root,owner)
            if not files and name!='gm7-resume': raise RuntimeError('No install payload')
            # Only failures before mutation are safe to skip. An interrupted
            # transaction may contain partial files and must stop deployment.
            if files:
                applying=True
                files=desktop_names(managed_plugin_files(files),options['installer_language'])
                apply_files(root,state,name,files,owner)
            services+=metadata.get('units',[])
            if name=='input' and 'inputplumber.service' not in services: services.append('inputplumber.service')
            reports[name]={'status':'files_installed','activation':'firstboot-pending' if name in options['repairs'] or name in ('decky','waydroid') else 'decky-session-pending','files':list(files)}
            if name=='gm7-resume': reports[name]['applicable']=bool(files)
        except (OSError,ValueError,RuntimeError,KeyError,zipfile.BadZipFile,tarfile.TarError) as error:
            if applying or isinstance(error,OSError) and error.errno in (errno.EIO,errno.ENOSPC,errno.EROFS,errno.ENODEV): raise
            del services[service_count:]
            reason=('Component resource missing: ' if isinstance(error,FileNotFoundError) else '')+str(error)
            reports[name]={'status':'not_installed','safe_to_skip':True,'reason':reason}
        if name!='decky':
            print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':name,**reports[name]}),flush=True)
    if reports.get('decky',{}).get('status')=='files_installed':
        reports['decky']['files']+=seed_decky_order(root,state,owner)
    if 'decky' in reports:
        print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':'decky',**reports['decky']}),flush=True)
    if options['kde_language']!='system':
        language=options['kde_language']; relative='home/deck/.config/plasma-localerc'
        data=config_file(root,relative,'Translations',{'LANGUAGE':language})
        apply_files(root,state,'kde-language',{relative:{'data':data,'user':True}},owner)
        reports['kde-language']={'status':'files_installed','language':language,'activation':'next-login'}
        print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':'kde-language',**reports['kde-language']}),flush=True)
    # The required update hold was applied before optional repairs; there is no
    # live updater activation or service stop in offline image preparation.
    mounts=options.get('storage_mounts',[])
    if mounts:
        reports['shared-storage']=stage_shared_storage(root,state,mounts,owner)
        print('OXP_COMPONENT_RESULT='+json.dumps({'slot':slot,'id':'shared-storage',**reports['shared-storage']}),flush=True)
    # The version note lives in shared home and is tracked once across A/B slots.
    # Fresh reconstructed homes do not inherit the recovery image's KDE launcher.
    launcher='home/deck/Desktop/Return.desktop'
    if not (root/launcher).exists() or shared_managed(state,'desktop-session',launcher):
        apply_files(root,state,'desktop-session',desktop_names({
            launcher:{'data':RETURN_TO_GAME,'mode':0o755,'user':True}},options['installer_language']),owner)
    apply_files(root,state,'release-note',{
        'home/deck/OXP3-SteamOS-Version.md':{
            'data':render_release_note(bundle_release).encode('utf-8'),
            'user':True}},owner)
    # Runtime records and entry are immutable per slot; service enablement is
    # performed offline, but no running system or hardware is changed here.
    runtime={}
    if not reports:
        result={'schema':1,'release':bundle_release,'system':release(root),'options':options,'components':reports,'services':services,'slot':slot}
        atomic_write(state/'result.json',(json.dumps(result)+'\n').encode(),0o600,0,0)
        return result
    for name in ('integration_runtime.py','system_update_policy.py','update_hold.py','boot_repairs.py','waydroid_setup.py','file_transaction.py','integration.py','shared_storage.py','decky_order.py','plugin_installer.py','directory_transaction.py','shared_state.py','options.json','release.json','release_notes.py'):
        runtime['usr/local/lib/oxp3-integration/'+name]={'data':(payload/'components'/name).read_bytes()}
    runtime['usr/local/lib/oxp3-integration/slot']={'data':(slot+'\n').encode()}
    for name in ('installer.py','generate.py','upstream.lua','UPSTREAM_LICENSE'):
        runtime['usr/local/lib/oxp3-integration/hdr/'+name]={'data':(payload/'components/hdr'/name).read_bytes()}
    runtime['etc/systemd/system/oxp3-selected-components.service']={'data':b'[Unit]\nDescription=Selected OXP3 repair and plugin activation\nAfter=local-fs.target\nBefore=display-manager.service\nRequiresMountsFor=/home\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py run\nTimeoutStartSec=180\n[Install]\nWantedBy=multi-user.target\n'}
    apply_files(root,state,'runtime',runtime,owner)
    result={'schema':1,'release':bundle_release,'system':release(root),'options':options,'components':reports,'services':services,'slot':slot}
    atomic_write(state/'result.json',(json.dumps(result)+'\n').encode(),0o600,0,0)
    link=root/'etc/systemd/system/multi-user.target.wants/oxp3-selected-components.service'; ensure_directory(link.parent,0o755)
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or os.readlink(link)!='../oxp3-selected-components.service': raise RuntimeError('Conflicting runtime service enablement')
    else: os.symlink('../oxp3-selected-components.service',link)
    return result

def restore(root,slot,name):
    root=Path(root).absolute(); base=root/'home/.oxp3-installer/integration'
    catalog=json.loads((root/'usr/local/lib/oxp3-integration/options.json').read_text())
    result_path=base/slot/'result.json'
    results=json.loads(base64.b64decode(snapshot(result_path,maximum=2*1024*1024)['data']))
    dependents=[x['id'] for x in catalog['repairs']+catalog['plugins'] if name in x['dependencies'] and results['components'].get(x['id'],{}).get('status')=='files_installed']
    if dependents: raise RuntimeError('Restore dependent components first: '+', '.join(dependents))
    users=[line.split(':') for line in (root/'etc/passwd').read_text().splitlines() if line.startswith('deck:')]
    owner=tuple(int(users[0][i]) for i in (2,3))
    errors=[]
    if name=='decky' and (base/slot/'decky-order/state.json').exists():
        errors=restore(root,slot,'decky-order')
        if errors: return errors
    if name=='opti2xmx':
        for record in (root/'home/deck/.local/share/opti2xmx/opti').glob('*/current.json'):
            data=json.loads(base64.b64decode(snapshot(record)['data']))
            if data.get('pending') or data.get('status') not in ('removed','rolled_back'):
                raise RuntimeError('Uninstall managed Opti games in Opti2XMX before removing the plugin')
        games=root/'home/deck/.local/share/opti2xmx/games'
        for pointer in games.glob('*/current.json'):
            data=json.loads(base64.b64decode(snapshot(pointer)['data']))
            relative=PurePosixPath(data['state'])
            if not str(relative).startswith('/home/deck/.local/share/opti2xmx/games/') or '..' in relative.parts: raise RuntimeError('Invalid Opti2XMX game state')
            state_path=root/str(relative).lstrip('/')/'plugin.json'
            if json.loads(base64.b64decode(snapshot(state_path)['data'])).get('status')!='restored': raise RuntimeError('Restore configured games in Opti2XMX before removing its runtime')
        if (root/'opt/oxp3-opti2xmx/.installer-state/state.json').exists():LogicalDirectory(root,name).rollback()
    if name=='desktop-hdr' and (root/'opt/oxp3-desktop-gamma22/.installer-state/state.json').exists():
        LogicalDirectory(root).rollback()
    if name in ('windows-reboot','slot-switch'):
        # Keep both entry points and their privileged helper together when the
        # user has edited a launcher or administrator-managed component file.
        for group in (slot,'shared'):
            state=base/group/name
            if not (state/'state.json').exists(): continue
            record=json.loads(base64.b64decode(snapshot(state/'state.json',maximum=256*1024*1024)['data']))
            transaction=LogicalFiles(state,root,{p:record['metadata'][p] for p in record['allowed']},owner)
            value=transaction.load()
            if value['phase']=='rolled_back': continue
            for path in value['applied']:
                current=transaction.snapshot(path); original=value['original'][path]
                if current==original: continue
                if (current.get('data') not in [value['applied'][path],*value.get('accepted',{}).get(path,[])] or
                    any(current.get(key)!=expected for key,expected in transaction.installed_metadata(path,original).items())):
                    return [{'path':path,'error':'Reboot component file changed; preserve user changes before restoring'}]
    for group in (slot,'shared'):
        state=base/group/name
        if not (state/'state.json').exists(): continue
        record=json.loads(base64.b64decode(snapshot(state/'state.json',maximum=256*1024*1024)['data']))
        files={p:record['metadata'][p] for p in record['allowed']}
        transaction=LogicalFiles(state,root,files,owner)
        if name=='gyro':
            # Keep the launch script, service and profile together if any file
            # was edited (including a device-specific calibration).
            value=transaction.load()
            for path in value['applied']:
                current=transaction.snapshot(path); original=value['original'][path]
                if current==original: continue
                if current.get('data') not in [value['applied'][path],*value.get('accepted',{}).get(path,[])]:
                    raise RuntimeError('Gyro configuration changed; preserve calibration before restoring: '+path)
                if any(current.get(key)!=expected for key,expected in transaction.installed_metadata(path,original).items()):
                    raise RuntimeError('Gyro file metadata changed: '+path)
        errors+=transaction.rollback()
    if not errors and name=='deck-access':
        access=results['components'].get(name,{})
        if access.get('ssh_link_created'):
            link=root/'etc/systemd/system/multi-user.target.wants/sshd.service'
            if not link.is_symlink() or os.readlink(link)!=access.get('ssh_link_target'):
                errors.append('SSH enablement changed after installation; preserve the current unit link')
            else: link.unlink()
    if not errors:
        groups={slot}
        if (base/'shared'/name/'state.json').exists(): groups.update(('A','B'))
        for group in groups:
            path=base/group/'result.json'
            if not path.exists(): continue
            value=json.loads(base64.b64decode(snapshot(path,maximum=2*1024*1024)['data']))
            if name in value['components']:
                value['components'][name]['status']='restored' if group==slot else 'shared_files_restored'
                atomic_write(path,(json.dumps(value)+'\n').encode(),0o600,0,0)
    return errors

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['stage','restore']); parser.add_argument('--root',required=True); parser.add_argument('--slot',choices=['A','B'],required=True); parser.add_argument('--payload'); parser.add_argument('--options'); parser.add_argument('--component')
    args=parser.parse_args()
    if args.action=='stage': print(json.dumps(stage(args.root,args.payload,json.loads(Path(args.options).read_text()),args.slot)))
    else: print(json.dumps(restore(args.root,args.slot,args.component)))
