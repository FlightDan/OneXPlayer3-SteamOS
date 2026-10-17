"""Opti lifecycle with per-game journals; no upstream setup scripts are executed."""
import configparser
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
import uuid

RELEASES = {
    '0.9.4': ('v0.9.4', 'Optiscaler_0.9.4-final.20260718._MM.7z', 481819753),
    '0.7.9': ('v0.7.9', 'OptiScaler_0.7.9.7z', 286094187),
}
ASSETS = ['OptiScaler.dll', 'OptiScaler.ini', 'libxess.dll', 'libxess_dx11.dll',
          'libxess_fg.dll', 'libxell.dll', 'amd_fidelityfx_dx12.dll',
          'amd_fidelityfx_framegeneration_dx12.dll', 'amd_fidelityfx_upscaler_dx12.dll',
          'amd_fidelityfx_vk.dll', 'fakenvapi.dll', 'fakenvapi.ini',
          'dlssg_to_fsr3_amd_is_better.dll', 'D3D12_Optiscaler/D3D12Core.dll',
          'Licenses/DirectX_LICENSE.txt', 'Licenses/FidelityFX_v1_LICENSE.md',
          'Licenses/FidelityFX_v2_LICENSE.md', 'Licenses/XeSS_LICENSE.txt']
MIGRATE_NAMES = set(ASSETS) - {'OptiScaler.dll', 'fakenvapi.dll'} | {'dxgi.dll', 'nvapi64.dll', 'nvngx.dll'}


def ini_values(path):
    c = configparser.ConfigParser(interpolation=None, strict=False)
    c.read(path, encoding='utf-8-sig')
    return c


def ini_equivalent(left, right):
    """Compare strict UTF-8 INI data without folding names, values or defaults."""
    def parse(data):
        text=data.decode('utf-8-sig')
        sections=set()
        for line in text.split('\n'):
            if line.lstrip(' \t\r\n').startswith((';','#')):continue
            # ConfigParser strips Unicode whitespace that SimpleIni retains.
            # Reject that syntax ambiguity before splitlines/strip can erase it.
            if any(char.isspace() and char not in ' \t\r\n' for char in line):
                raise ValueError('Ambiguous INI whitespace')
            stripped=line.strip()
            if stripped.startswith('['):
                header=re.fullmatch(r'\[([^\[\]]+)\]',stripped)
                if not header or header[1]!=header[1].strip():
                    raise ValueError('Ambiguous INI section header')
                identity=header[1].casefold()
                # ConfigParser silently merges repeated DEFAULT sections. Also
                # reject case-only aliases: SimpleIni treats them as one name.
                if identity in sections:raise ValueError('Duplicate INI section')
                sections.add(identity)
        config = configparser.ConfigParser(interpolation=None, strict=True, delimiters=('=',))
        config.optionxform = str
        config.read_string(text)
        for values in [config.defaults(),*config._sections.values()]:
            if len({name.casefold() for name in values})!=len(values):
                raise ValueError('Ambiguous INI option names')
        # items(section) inherits DEFAULT values; explicit placement is part of
        # the identity, so retain the separately parsed section dictionaries.
        return dict(config.defaults()), {name: dict(values) for name, values in config._sections.items()}
    try:
        return parse(left) == parse(right)
    except (UnicodeError, configparser.Error, ValueError):
        return False


def system_env():
    # Decky's PyInstaller bundle ships a libstdc++ too old for system 7z.
    env=os.environ.copy()
    original=env.pop('LD_LIBRARY_PATH_ORIG',None)
    if original:env['LD_LIBRARY_PATH']=original
    else:env.pop('LD_LIBRARY_PATH',None)
    return env


class OptiMixin:
    def opti_path(self, appid):
        return self.root / 'opti' / str(appid) / 'current.json'

    def opti_record(self, appid):
        p = self.opti_path(appid)
        self.runtime().no_symlink_parents(p)
        return json.loads(p.read_text()) if p.exists() else None

    def opti_save(self, appid, r):
        p = self.opti_path(appid)
        self.runtime().no_symlink_parents(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.runtime().atomic_text(p, json.dumps(r, ensure_ascii=False, indent=2))

    def opti_status(self, info):
        r = self.opti_record(info['appid'])
        active = r and r.get('status') not in ('removed', 'rolled_back')
        ini = Path(info['game']) / info['optis'][0] if len(info['optis']) == 1 else None
        c = ini_values(ini) if ini else configparser.ConfigParser()
        get = lambda s, k, d: c.get(s, k, fallback=d)
        spoof = get('Spoofing', 'Dxgi', 'auto')
        vendor = get('Spoofing', 'SpoofedVendorId', 'auto').lower()
        fg = get('FrameGen', 'FGOutput', 'nofg').lower()
        if get('FrameGen', 'Enabled', 'false').lower() != 'true': fg = 'native'
        fg_input=get('FrameGen','FGInput','upscaler').lower()
        if fg_input not in ('fsrfg30','fsrfg','dlssg','upscaler'):fg_input='upscaler'
        interpolation=get('XeFG','InterpolationCount','auto').strip()
        multiplier='native' if fg=='native' else {'1':'2','2':'3','3':'4'}.get(interpolation,'2')
        settings_undo=(r or {}).get('settings_undo') or {}
        return dict(managed=bool(active), installed=bool(ini), version=r.get('version', '') if active else '',
                    injection_enabled=r.get('injection_enabled', True) if active else bool(ini),
                    status=r.get('status', '') if r else '', rollback=bool(r and r.get('undo')),
                    pending=r.get('pending') if r else None,
                    settings_rollback=bool(active and settings_undo.get('status') in ('saved','applying','restoring')),
                    settings_recovery=settings_undo.get('status') in ('applying','restoring'),
                    settings=dict(sr=get('Upscalers', 'Dx12Upscaler', 'xess'), fg=fg,
                                  fg_input=fg_input, fg_multiplier=multiplier,
                                  spoof='real' if spoof.lower() == 'false' else
                                  {'0x8086':'intel','0x1002':'amd'}.get(vendor, 'nvidia')))

    def opti_package(self, version, source, operation_id=None):
        owned = operation_id is None
        identity = operation_id or self.progress.begin(None, 'opti_download', version)
        try:
            payload = self._opti_package(version, source, identity)
            if owned: self.progress.finish(identity)
            return payload
        except Exception as error:
            self.progress.finish(identity, error=error)
            raise

    def _opti_package(self, version, source, operation_id):
        if version not in RELEASES or source not in ('github', 'github-api', 'ghfast', 'ghproxy'):
            raise ValueError('请选择支持的版本和下载源')
        tag, filename, asset = RELEASES[version]
        cache = self.root / 'downloads' / tag
        self.runtime().no_symlink_parents(cache / filename)
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / filename
        if not archive.exists():
            url = f'https://github.com/optiscaler/OptiScaler/releases/download/{tag}/{filename}'
            if source == 'github-api':url=f'https://api.github.com/repos/optiscaler/OptiScaler/releases/assets/{asset}?download=1'
            elif source == 'ghfast':url='https://ghfast.top/'+url
            elif source == 'ghproxy':url='https://gh-proxy.com/'+url
            req = urllib.request.Request(url, headers={'User-Agent':'Opti2XMX', 'Accept':'application/octet-stream'})
            part = archive.with_suffix('.part')
            try:
                with urllib.request.urlopen(req, timeout=45) as response, part.open('wb') as out:
                    header = response.headers.get('Content-Length', '')
                    total_bytes = int(header) if str(header).isdigit() and len(str(header)) < 12 else None
                    total = 0
                    self.progress.update(operation_id, 'downloading', 0, total_bytes)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk: break
                        total += len(chunk)
                        if total > 200 * 1024 * 1024: raise RuntimeError('下载文件超过限制')
                        out.write(chunk)
                        self.progress.update(operation_id, 'downloading', total, total_bytes)
                with part.open('rb') as f:
                    if f.read(6) != b'7z\xbc\xaf\x27\x1c': raise RuntimeError('下载源没有返回 7z 安装包，请切换下载源')
                part.replace(archive)
            finally:
                if part.exists(): part.unlink()
        else:
            self.progress.update(operation_id, 'cache-hit', archive.stat().st_size, archive.stat().st_size)
        # Extract only fixed names via stdout: archive paths/symlinks cannot escape.
        payload = cache / 'payload'
        payload.mkdir(exist_ok=True)
        if (payload/'ready.json').exists() and all((payload/n).is_file() and not (payload/n).is_symlink()
                                                   for n in ('OptiScaler.dll','OptiScaler.ini','libxess.dll')):
            return payload
        for name in ASSETS:
            self.progress.update(operation_id, 'extracting')
            p = payload / name
            self.runtime().no_symlink_parents(p)
            if p.is_symlink():raise RuntimeError('缓存文件不能是符号链接')
            result = subprocess.run(['7z','e','-so',str(archive),name], env=system_env(), capture_output=True, timeout=90)
            if result.returncode or not result.stdout:
                if name in ('OptiScaler.dll','OptiScaler.ini','libxess.dll'):
                    raise RuntimeError('安装包缺少必需文件：' + name)
                continue
            if len(result.stdout) > 100 * 1024 * 1024: raise RuntimeError('安装包文件过大')
            if name.endswith('.dll') and not result.stdout.startswith(b'MZ'):
                raise RuntimeError('安装包 DLL 格式无效：' + name)
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(result.stdout)
        (payload/'ready.json').write_text(json.dumps({'version':version,'source':source}))
        return payload

    def opti_context(self, appid, executable, actual, allow_xmx=False):
        rt = self.runtime(); rt.ordinary_user()
        info = self.inspect_game(appid)
        if executable not in info['executables']: raise RuntimeError('请选择检测到的游戏程序')
        game = Path(info['game']); exe = game / executable
        rt.no_symlink_parents(exe)
        prefix = Path(info['prefix'])
        if not (prefix / 'drive_c').is_dir(): raise RuntimeError('请先启动游戏一次以创建 Proton 环境')
        rt.game_idle(prefix, exe.name)
        xmx = info['state']
        if xmx and xmx['status'] not in ('restored','failed'):
            if not allow_xmx or xmx['status'] != 'active': raise RuntimeError('请先关闭 XMX，再安装、回退或卸载 Opti')
            if actual != xmx['launch']: raise RuntimeError('Steam 启动项与 XMX 记录不一致')
        r = self.opti_record(appid)
        self.opti_require_settings_complete(r)
        if r and r.get('pending'): raise RuntimeError('上次操作待完成，请先完成启动项设置或回退')
        known = ['', '%command%', '~/fgmod/fgmod %command%', str(self.home/'fgmod/fgmod')+' %command%']
        if r: known.append(r['launch'])
        if xmx: known.append(xmx.get('launch'))
        if actual not in known: raise RuntimeError('检测到自定义启动项，保留现场，请先处理冲突')
        return info, exe.parent, prefix, r

    def opti_sync(self, appid, paths=None):
        """Refresh owned applied snapshots after our XMX operation, never originals."""
        r = self.opti_record(appid)
        if not r or r['status'] != 'active': return
        for f in r['files']:
            p = Path(f['path'])
            if (paths is None and p.name=='OptiScaler.ini' or paths is not None and str(p) in paths) and p.is_file():
                self.runtime().atomic_copy(p, Path(f['applied']))

    def opti_transaction(self, appid, executable, actual, changes, base, version, previous, kind):
        rt = self.runtime()
        parent = self.opti_path(appid).parent
        rt.no_symlink_parents(parent/'placeholder'); parent.mkdir(parents=True, exist_ok=True)
        folder = parent / ('revision-' + uuid.uuid4().hex); folder.mkdir()
        (folder/'before').mkdir(); (folder/'after').mkdir()
        files = []
        # Validate all targets before writing anything, including removal targets.
        for name, value in changes.items():
            p = Path(name); rt.no_symlink_parents(p)
            if p.is_symlink():raise RuntimeError('不修改符号链接：'+p.name)
            if p.exists() and (not p.is_file() or p.stat().st_uid != os.getuid()):
                raise RuntimeError('文件不可安全修改：' + p.name)
        for n,(name,value) in enumerate(changes.items()):
            p = Path(name); before = folder/'before'/str(n); after=folder/'after'/str(n)
            if p.exists(): shutil.copy2(p,before)
            if value is not None: after.write_bytes(value)
            files.append(dict(path=name, before=str(before) if before.exists() else None,
                              after=str(after) if value is not None else None))
        launch = shlex.quote(str(parent/'launch.sh'))+' %command%'
        # Lifecycle revisions invalidate settings undo, including when that revision
        # is later rolled back. Installation undo remains a separate history.
        previous=copy.deepcopy(previous)
        if previous: previous.pop('settings_undo',None)
        rollback_launch = previous['launch'] if previous and previous['status']=='active' else actual
        r = dict(appid=appid, executable=executable, version=version, status='applying',
                 injection_enabled=previous.get('injection_enabled', True) if previous else True,
                 launch=launch, old_launch=previous['old_launch'] if previous else actual,
                 files=base, undo=dict(folder=str(folder),files=files,previous=previous,launch=rollback_launch),
                 pending=dict(expected=actual,target=launch,kind=kind))
        self.opti_save(appid,r)
        try:
            rt.atomic_text(parent/'launch.sh', '#!/bin/bash\nset -eu\nexport WINEDLLOVERRIDES="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}dxgi=n,b;nvapi64=n,b"\nexec "$@"\n',mode=0o700)
            for f in files:
                p=Path(f['path'])
                p.parent.mkdir(parents=True,exist_ok=True)
                if f['after']: rt.atomic_copy(Path(f['after']),p)
                elif p.exists(): p.unlink()
            r['status']='pending_launch';self.opti_save(appid,r)
        except Exception:
            r['status']='recovery_required';self.opti_save(appid,r)
            raise RuntimeError('操作中断，备份已保存，请点击回退上次操作')
        return r['pending']

    def opti_install(self, appid, executable, actual, version, source):
        identity = self.progress.begin(appid, 'opti_install', version)
        try:
            pending = self._opti_install(appid, executable, actual, version, source, identity)
            self.progress.finish(identity, phase='awaiting-launch')
            return pending
        except Exception as error:
            self.progress.finish(identity, error=error)
            raise

    def _opti_install(self, appid, executable, actual, version, source, operation_id):
        info, folder, prefix, r = self.opti_context(appid,executable,actual)
        if r and not r.get('injection_enabled', True):
            raise RuntimeError('请先开启 Opti 注入，再更换版本')
        if info['optis'] and not (r and r['status']=='active'):
            raise RuntimeError('已存在 Opti，请先迁移现有安装')
        payload=self.opti_package(version,source,operation_id=operation_id)
        self.progress.update(operation_id, 'installing')
        from manager import ini_set
        with self.runtime().prefix_lock(prefix):
            self.runtime().game_idle(prefix,Path(executable).name)
            base=copy.deepcopy(r['files']) if r and r['status']=='active' else []
            self.opti_check_files(base)
            changes={}
            for p in payload.rglob('*'):
                if not p.is_file():continue
                relative=p.relative_to(payload).as_posix()
                if relative not in ASSETS:continue
                name={'OptiScaler.dll':'dxgi.dll','fakenvapi.dll':'nvapi64.dll'}.get(relative,relative)
                target=folder/name
                if name=='dxgi.dll' and target.exists() and not r:
                    raise RuntimeError('游戏已有 dxgi.dll，不能覆盖其他注入器')
                data=p.read_bytes()
                if name=='OptiScaler.ini':
                    text=data.decode('utf-8-sig')
                    # Carry shared SR/menu preferences, never transfer old FG schema blindly.
                    old=ini_values(target) if target.exists() else configparser.ConfigParser()
                    for section,key,default in [('Upscalers','Dx12Upscaler','xess'),('Menu','Scale','auto'),('Menu','ShortcutKey','auto')]:
                        text=ini_set(text,section,key,old.get(section,key,fallback=default))
                    for section,key,value in [('Spoofing','Dxgi','false'),('Spoofing','StreamlineSpoofing','false'),
                                               ('FrameGen','Enabled','false'),('FrameGen','FGInput','nofg'),
                                                ('FrameGen','FGOutput','nofg'),('FrameGen','FGType','nofg'),('OptiFG','Enabled','false'),
                                                ('XeFG','InterpolationCount','auto')]:
                        text=ini_set(text,section,key,value)
                    data=text.encode()
                changes[str(target)]=data
            base=self.opti_baseline(appid,base,changes)
            pending=self.opti_transaction(appid,executable,actual,changes,base,version,r,'install')
            self.opti_refresh_applied(appid)
            return pending

    def opti_baseline(self,appid,base,changes,originals=None):
        rt=self.runtime(); folder=self.opti_path(appid).parent/('baseline-'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        for name in changes:
            if any(f['path']==name for f in base):continue
            n=len(base);p=Path(name)
            original=(originals or {}).get(name,p if p.exists() else None)
            before=folder/(str(n)+'.original');after=folder/(str(n)+'.applied')
            if original is not None: rt.atomic_copy(Path(original),before)
            base.append(dict(path=name,original=str(before) if original is not None else None,applied=str(after)))
        return base

    def opti_refresh_applied(self,appid):
        r=self.opti_record(appid)
        for f in r['files']:
            if f.get('suspended'): continue
            p=Path(f['path'])
            if p.exists():self.runtime().atomic_copy(p,Path(f['applied']))

    def opti_check_files(self,files):
        for f in files:
            p=Path(f['path']);self.runtime().no_symlink_parents(p)
            if p.is_symlink():raise RuntimeError('不修改符号链接：'+p.name)
            if f.get('suspended'):
                source=f.get('suspended_source',f['original'])
                expected=Path(source).read_bytes() if source else None
                if (p.read_bytes() if p.is_file() else None)!=expected or (p.exists() and not p.is_file()):
                    raise RuntimeError('文件已被其他工具修改，请先处理冲突：'+p.name)
                continue
            if p.suffix.lower()=='.ini' and p.is_file():continue  # preserve user edits in operation snapshot
            if not p.is_file() or not Path(f['applied']).exists() or p.read_bytes()!=Path(f['applied']).read_bytes():
                raise RuntimeError('文件已被其他工具修改，请先处理冲突：'+p.name)

    def opti_toggle(self, appid, enabled, actual):
        if type(enabled) is not bool: raise ValueError('开关值无效')
        r=self.opti_record(appid)
        if not r or r['status']!='active': raise RuntimeError('请先安装或迁移 Opti')
        info,folder,prefix,r=self.opti_context(appid,r['executable'],actual,True)
        rt=self.runtime()
        with rt.prefix_lock(prefix):
            rt.game_idle(prefix,Path(r['executable']).name)
            self.opti_check_files(r['files'])
            base=copy.deepcopy(r['files']);changes={}
            for f in base:
                if Path(f['path']).name.lower() not in ('dxgi.dll','nvapi64.dll','nvngx.dll'):continue
                source=f['applied'] if enabled else f['original']
                if not enabled and source:
                    data=Path(source).read_bytes().lower()
                    # Older fgmod backups may themselves contain another injector.
                    if any(s in data for n in ('fakenvapi','optiscaler') for s in (n.encode(),n.encode('utf-16le'))):source=None
                changes[f['path']]=Path(source).read_bytes() if source else None
                f['suspended']=not enabled
                f['suspended_source']=source if not enabled else None
            if str(folder/'dxgi.dll') not in changes:raise RuntimeError('没有已管理的 Opti 注入 DLL')
            self.opti_transaction(appid,r['executable'],actual,changes,base,r['version'],r,'toggle')
            new=self.opti_record(appid)
            new['injection_enabled']=enabled
            # XMX keeps its launcher and runtime; only Opti's entry DLLs change.
            if info['state'] and info['state']['status']=='active':
                new['pending']['target']=actual
                # Retain preferences saved by the in-game overlay on exit.
                for f in info['state']['files']:
                    if Path(f['path']).name!='OptiScaler.ini':continue
                    for key in ('original','applied'):
                        saved=Path(new['undo']['folder'])/('xmx-ini-'+key)
                        rt.atomic_copy(Path(f[key]),saved)
                        rt.atomic_copy(Path(f['path']),Path(f[key]))
            self.opti_save(appid,new)
            return new['pending']

    def opti_migrate(self,appid,executable,actual):
        info,folder,prefix,old=self.opti_context(appid,executable,actual,True)
        if old and old['status']=='active':raise RuntimeError('Opti 已由本插件管理')
        dxgi=folder/'dxgi.dll'
        self.runtime().no_symlink_parents(dxgi)
        if not dxgi.exists() or b'OptiScaler' not in dxgi.read_bytes():raise RuntimeError('只支持已识别的 dxgi 版 Opti 安装')
        fgmod=self.home/'fgmod';changes={};originals={}
        for name in sorted(MIGRATE_NAMES):
            p=folder/name
            if not p.exists():continue
            self.runtime().no_symlink_parents(p)
            if p.is_symlink():raise RuntimeError('不接管符号链接：'+p.name)
            src=fgmod/('OptiScaler.dll' if name=='dxgi.dll' else name)
            matched=src.is_file() and p.read_bytes()==src.read_bytes()
            xmx_file=next((f for f in (info['state'] or {}).get('files',[]) if f['path']==str(p)),None)
            if name!='OptiScaler.ini' and not matched and not xmx_file:
                raise RuntimeError('无法确认现有文件归属，保留原文件：'+name)
            changes[str(p)]=p.read_bytes()
            backup=p.with_name(p.name+'.b')
            self.runtime().no_symlink_parents(backup)
            originals[str(p)]=backup if backup.is_file() else None
        with self.runtime().prefix_lock(prefix):
            self.runtime().game_idle(prefix,Path(executable).name)
            base=self.opti_baseline(appid,[],changes,originals)
            # Metadata adoption leaves loaded game libraries untouched.
            pending=self.opti_transaction(appid,executable,actual,{},base,'0.7.9',None,'migrate')
            self.opti_refresh_applied(appid)
            x=info['state']
            if x and x['status']=='active':
                r=self.opti_record(appid)
                r['old_launch']=x['old_launch'];r['undo']['launch']=x['old_launch']
                r['pending']['target']=actual
                r['pending']['xmx_state']=copy.deepcopy(x)
                self.opti_save(appid,r)
                pending=r['pending']
            return pending

    def opti_confirm(self,appid,actual):
        r=self.opti_record(appid)
        if not r or not r.get('pending') or actual!=r['pending']['target']:
            raise RuntimeError('Opti 启动项尚未确认')
        pending=r['pending']
        if pending.get('xmx_state'):
            x=self.state(appid)
            if x!=pending['xmx_state']:raise RuntimeError('XMX 状态已变化，请刷新')
            rt=self.runtime()
            with rt.prefix_lock(Path(x['prefix'])):
                rt.game_idle(Path(x['prefix']),Path(x['executable']).name)
                for f in x['files']:
                    if Path(f['path']).name=='OptiScaler.ini':
                        for key in ('original','applied'):
                            saved=Path(r['undo']['folder'])/('xmx-ini-'+key)
                            rt.atomic_copy(Path(f[key]),saved)
                            rt.atomic_copy(Path(f['path']),Path(f[key]))
            x['old_launch']=r['launch'];self.save(x)
        if pending['kind']=='rollback':
            previous=r['undo']['previous']
            r=previous or dict(r,status='rolled_back',pending=None,undo=None)
        else:
            r['status']='removed' if pending['kind']=='uninstall' else 'active';r['pending']=None
        self.opti_save(appid,r)
        if r['status']=='active':self.opti_refresh_applied(appid)
        progress = self.progress.snapshot()
        if progress['appid'] == appid and progress['phase'] == 'awaiting-launch':
            self.progress.finish(progress['operation_id'])
        return True

    def opti_rollback(self,appid,actual):
        r=self.opti_record(appid)
        self.opti_require_settings_complete(r)
        if not r or not r.get('undo'):raise RuntimeError('没有可回退的操作')
        info=self.inspect_game(appid);x=info['state']
        if x and x['status'] not in ('restored','failed'):raise RuntimeError('请先关闭 XMX 再回退 Opti')
        prefix=Path(info['prefix']);rt=self.runtime()
        if actual not in (r['launch'],r['old_launch'],(r.get('pending') or {}).get('expected'),(r.get('pending') or {}).get('target')):
            raise RuntimeError('启动项已被外部修改')
        with rt.prefix_lock(prefix):
            rt.game_idle(prefix,Path(r['executable']).name)
            for f in r['undo']['files']:
                p=Path(f['path']);rt.no_symlink_parents(p)
                if p.is_symlink():raise RuntimeError('不修改符号链接：'+p.name)
                expected=[Path(f[k]).read_bytes() if f[k] else None for k in ('before','after')]
                if (p.read_bytes() if p.exists() else None) not in expected:
                    if p.suffix.lower()=='.ini' and p.is_file():
                        rt.atomic_copy(p,Path(r['undo']['folder'])/('later-ini-'+uuid.uuid4().hex))
                        continue
                    raise RuntimeError('文件已有后续改动，不能覆盖：'+p.name)
            r['pending']=dict(expected=actual,target=r['undo']['launch'],kind='rollback');r['status']='recovery_required'
            self.opti_save(appid,r)
            for f in r['undo']['files']:
                p=Path(f['path'])
                if f['before']:rt.atomic_copy(Path(f['before']),p)
                elif p.exists():p.unlink()
            r['status']='pending_launch';self.opti_save(appid,r)
        return r['pending']

    def opti_uninstall(self,appid,actual):
        r=self.opti_record(appid)
        if not r or r['status']!='active':raise RuntimeError('没有本插件管理的 Opti 安装')
        info,folder,prefix,r=self.opti_context(appid,r['executable'],actual)
        with self.runtime().prefix_lock(prefix):
            self.runtime().game_idle(prefix,Path(r['executable']).name)
            self.opti_check_files(r['files'])
            changes={f['path']:Path(f['original']).read_bytes() if f['original'] else None for f in r['files']}
            self.opti_transaction(appid,r['executable'],actual,changes,r['files'],r['version'],r,'uninstall')
            r=self.opti_record(appid)
            # Removal must not relaunch the old installer on the next game start.
            old=r['old_launch'];target='' if 'fgmod/fgmod' in old else old
            r['pending']['target']=target;self.opti_save(appid,r)
            return r['pending']

    def opti_require_settings_complete(self, record):
        if ((record or {}).get('settings_undo') or {}).get('status') in ('applying','restoring'):
            raise RuntimeError('设置保存或恢复未完成，请先恢复上次设置')

    def _settings_regular(self, path):
        rt=self.runtime();rt.no_symlink_parents(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid():
            raise RuntimeError('设置文件必须是当前用户的普通文件：'+path.name)

    def _settings_context(self, appid, recovery=False):
        rt=self.runtime();rt.ordinary_user()
        r=self.opti_record(appid)
        if not r:raise RuntimeError('请先安装或迁移 Opti')
        if r.get('pending'):raise RuntimeError('上次操作待完成，请先完成启动项设置或回退')
        if r['status']!='active':raise RuntimeError('请先安装或迁移 Opti')
        if not recovery:self.opti_require_settings_complete(r)
        info=self.inspect_game(appid)
        x=info['state']
        if x and x['status'] not in ('active','restored','failed'):
            raise RuntimeError('XMX 操作待完成，请先完成或恢复')
        if r['executable'] not in info['executables']:raise RuntimeError('游戏程序已经变化，请刷新')
        exe=Path(info['game'])/r['executable']
        self._settings_regular(exe)
        ini=exe.parent/'OptiScaler.ini'
        targets=[ini]
        owned=next((f for f in r['files'] if f['path']==str(ini)),None)
        if not owned:raise RuntimeError('没有已管理的 Opti 设置文件')
        targets.append(Path(owned['applied']))
        if x and x['status']=='active':
            for f in x['files']:
                if f['path']==str(ini):targets.extend(Path(f[k]) for k in ('applied','original'))
        targets=list(dict.fromkeys(targets))
        # All mutation targets are derived from installed-game/owned journal records,
        # never accepted from a settings RPC or settings-undo journal.
        for path in targets:self._settings_regular(path)
        return r,info,ini,targets

    def _settings_journal(self, appid, r, ini, targets, after):
        rt=self.runtime()
        folder=self.opti_path(appid).parent/('settings-'+uuid.uuid4().hex)
        rt.no_symlink_parents(folder/'placeholder');folder.mkdir(mode=0o700)
        before=folder/'before.ini';before.write_bytes(ini.read_bytes())
        desired=folder/'after.ini';desired.write_bytes(after)
        files=[]
        for n,path in enumerate(targets):
            saved=folder/('observed-'+str(n)+'.ini');saved.write_bytes(path.read_bytes())
            files.append(dict(path=str(path),observed=str(saved)))
        return dict(status='applying',folder=str(folder),ini=str(ini),before=str(before),after=str(desired),
                    version=r['version'],executable=r['executable'],files=files)

    def _settings_validate_journal(self, appid, r, ini, journal):
        folder=Path(journal['folder'])
        if (folder.parent!=self.opti_path(appid).parent or not folder.name.startswith('settings-') or
                '..' in folder.parts or journal.get('ini')!=str(ini) or
                journal.get('version')!=r['version'] or journal.get('executable')!=r['executable']):
            raise RuntimeError('设置恢复记录与当前安装不一致')
        for key in ('before','after'):
            path=Path(journal[key])
            if path.parent!=folder:raise RuntimeError('无效设置备份路径')
            self._settings_regular(path)
        for f in journal['files']:
            path=Path(f['observed'])
            if path.parent!=folder:raise RuntimeError('无效设置备份路径')
            self._settings_regular(path)
        if journal.get('live_format_capture'):
            path=Path(journal['live_format_capture'])
            if path!=folder/'live-formatted.ini':raise RuntimeError('无效设置备份路径')
            self._settings_regular(path)
            if not ini_equivalent(path.read_bytes(),Path(journal['after']).read_bytes()):
                raise RuntimeError('设置格式备份与保存值不一致，保留现场')

    def opti_restore_settings(self,appid):
        r,info,ini,targets=self._settings_context(appid,True)
        rt=self.runtime();prefix=Path(info['prefix'])
        with rt.prefix_lock(prefix):
            rt.game_idle(prefix,Path(r['executable']).name)
            # Reload under the lock so a waiting RPC cannot restore a replaced undo.
            r,info,ini,targets=self._settings_context(appid,True)
            if Path(info['prefix'])!=prefix:raise RuntimeError('游戏 Proton 环境已变化，请刷新')
            journal=r.get('settings_undo')
            if not journal or journal.get('status') not in ('saved','applying','restoring'):
                raise RuntimeError('没有可恢复的设置')
            self._settings_validate_journal(appid,r,ini,journal)
            new=Path(journal['after']).read_bytes()
            captured={f['path']:Path(f['observed']).read_bytes() for f in journal['files']}
            current=set(map(str,targets))
            if ((journal['status']=='saved' and not current.issubset(captured)) or
                    (journal['status'] in ('applying','restoring') and set(captured)!=current)):
                raise RuntimeError('设置恢复目标已变化，保留现场')
            formatted=None
            for path in targets:
                allowed=(new,) if journal['status']=='saved' else (new,captured[str(path)])
                observed=path.read_bytes()
                if observed not in allowed:
                    # SimpleIni rewrites the live INI on game exit. Only that
                    # file may match by strict meaning; owned mirrors stay exact.
                    if (path==ini and journal['status'] in ('saved','restoring') and
                            ini_equivalent(observed,new)):
                        formatted=observed
                        continue
                    raise RuntimeError('设置文件已被外部修改，保留现场：'+path.name)
            if formatted is not None:
                capture=Path(journal['folder'])/'live-formatted.ini'
                rt.no_symlink_parents(capture)
                if capture.exists() or capture.is_symlink():
                    self._settings_regular(capture)
                    if capture.read_bytes()!=formatted:
                        raise RuntimeError('设置格式备份已有后续改动，保留现场')
                else:
                    rt.atomic_copy(ini,capture)
                    if capture.read_bytes()!=formatted:
                        raise RuntimeError('设置文件在备份期间变化，保留现场')
                journal['live_format_capture']=str(capture)
            # When XMX has since been disabled, restore only currently owned mirrors.
            # Keep each target's original observed snapshot: XMX's original INI may
            # intentionally differ from its applied INI and the current game file.
            # Persist the reduced topology before any writes for interrupted retries.
            if journal['status']=='saved':
                journal['files']=[f for f in journal['files'] if f['path'] in current]
            journal['status']='restoring';self.opti_save(appid,r)
            try:
                originals={f['path']:Path(f['observed']) for f in journal['files']}
                for path in targets:rt.atomic_copy(originals[str(path)],path)
                journal['status']='restored';self.opti_save(appid,r)
            except Exception as error:
                raise RuntimeError('设置恢复未完成，已保留恢复记录；请重试恢复上次设置：'+str(error)) from error
        return True

    def opti_settings(self,appid,settings,reset=False,fg_multiplier='2'):
        from manager import ini_set
        r,info,ini,targets=self._settings_context(appid)
        prefix=Path(info['prefix']);rt=self.runtime()
        allowed={'sr':{'xess','fsr31','fsr22','dlss'},'fg':{'native','fsrfg','xefg'},
                 'fg_input':{'fsrfg30','fsrfg','dlssg','upscaler'},'spoof':{'real','nvidia','amd','intel'},
                 'fg_multiplier':{'native','2','3','4'}}
        settings=dict(settings)
        settings.setdefault('fg_multiplier',fg_multiplier)
        if set(settings)!=set(allowed) or any(settings[k] not in v for k,v in allowed.items()):raise ValueError('不支持的设置值')
        # Opti's "auto" interpolation count still defaults to 2x. Relinquish
        # FG interception for game control instead of presenting auto as native.
        if settings['fg']=='xefg' and settings['fg_multiplier']=='native':
            settings['fg']='native'
        with rt.prefix_lock(prefix):
            rt.game_idle(prefix,Path(r['executable']).name)
            r,info,ini,targets=self._settings_context(appid)
            if Path(info['prefix'])!=prefix:raise RuntimeError('游戏 Proton 环境已变化，请刷新')
            if not r['version'].startswith('0.9'):raise RuntimeError('请先升级 Opti 0.9 再使用简化设置')
            x=info['state'];active=x and x['status']=='active'
            if active and (settings['sr']!='xess' or settings['spoof']!='real'):
                raise RuntimeError('XMX 开启时保留 XeSS 和真实显卡；请先关闭 XMX 再改这两项')
            before=ini.read_bytes()
            text=(self.opti_package(r['version'],'github')/'OptiScaler.ini').read_text(encoding='utf-8-sig') if reset else before.decode('utf-8-sig')
            fg=settings['fg'];spoof=settings['spoof']
            vendor,device,name={'nvidia':('0x10de','0x2684','NVIDIA GeForce RTX 4090'),
                                'amd':('0x1002','0x7550','AMD Radeon RX 9070 XT'),
                                'intel':('0x8086','0x56a0','Intel(R) Arc(TM) A770 Graphics'),
                                'real':('auto','auto','auto')}[spoof]
            updates=[('Upscalers','Dx12Upscaler',settings['sr']),('FrameGen','Enabled','false' if fg=='native' else 'true'),
                     ('FrameGen','FGInput','nofg' if fg=='native' else settings['fg_input']),('FrameGen','FGOutput','nofg' if fg=='native' else fg),
                     ('XeFG','InterpolationCount','auto' if settings['fg_multiplier']=='native' else str(int(settings['fg_multiplier'])-1)),
                     ('Spoofing','Dxgi','false' if spoof=='real' else 'true'),('Spoofing','StreamlineSpoofing','false'),
                     ('Spoofing','SpoofedVendorId',vendor),('Spoofing','SpoofedDeviceId',device),('Spoofing','SpoofedGPUName',name)]
            for section,key,value in updates:text=ini_set(text,section,key,value)
            journal=self._settings_journal(appid,r,ini,targets,text.encode('utf-8'))
            r['settings_undo']=journal;self.opti_save(appid,r)
            try:
                for path in targets:rt.atomic_copy(Path(journal['after']),path)
                journal['status']='saved';self.opti_save(appid,r)
            except Exception as error:
                raise RuntimeError('设置保存未完成，已保留恢复记录；请先恢复上次设置：'+str(error)) from error
        return True

    def opti_panel(self,appid):
        info=self.inspect_game(appid)
        if not info['opti']['injection_enabled']:raise RuntimeError('Opti 注入已关闭，当前使用游戏原生功能')
        exe=info['automatic']['executable']
        if not exe or not info['optis']:raise RuntimeError('未找到 Opti 安装')
        c=ini_values(Path(info['game'])/Path(exe).parent/'OptiScaler.ini')
        value=c.get('Menu','ShortcutKey',fallback='auto')
        vk=45 if value=='auto' else int(value,0)
        key={45:'Insert',36:'Home',19:'Pause',**{112+n:'F'+str(n+1) for n in range(12)}}.get(vk)
        if not key:raise RuntimeError('当前面板快捷键不受支持，请在 Opti 中恢复 Insert')
        matches=[]
        for p in Path('/proc').glob('[0-9]*'):
            try:
                if p.stat().st_uid!=os.getuid():continue
                args=p.joinpath('cmdline').read_bytes().decode(errors='replace').split('\0')
                if Path(exe).name.lower() not in [v.replace('\\','/').rsplit('/',1)[-1].lower() for v in args]:continue
                env=dict(v.split('=',1) for v in p.joinpath('environ').read_bytes().decode(errors='replace').split('\0') if '=' in v)
                if env.get('STEAM_COMPAT_DATA_PATH')!=str(Path(info['prefix']).parent) and env.get('WINEPREFIX')!=info['prefix']:continue
                if env.get('DISPLAY'):matches.append((p.name,env))
            except (OSError,ValueError):continue
        if not matches:raise RuntimeError('请先启动选中的游戏，再打开面板')
        time.sleep(.8)  # let the frontend close QAM first
        for pid,source_env in matches:
            env=system_env()
            for k in ('DISPLAY','XAUTHORITY'):
                if k in source_env:env[k]=source_env[k]
            result=subprocess.run(['xdotool','search','--onlyvisible','--pid',pid],env=env,capture_output=True,text=True,timeout=5)
            for window in result.stdout.split():
                subprocess.run(['xdotool','windowactivate','--sync',window],env=env,check=True,timeout=5)
                active=subprocess.check_output(['xdotool','getactivewindow'],env=env,text=True,timeout=5).strip()
                if active!=window:continue
                subprocess.run(['xdotool','key','--clearmodifiers',key],env=env,check=True,timeout=5)
                return True
        raise RuntimeError('未找到该游戏的可见窗口，请回到游戏后重试')
