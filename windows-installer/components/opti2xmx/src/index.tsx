import { t } from './i18n';
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses, Navigation } from '@decky/ui';
import { callable, definePlugin, FileSelectionType, openFilePicker, toaster } from '@decky/api';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

type Reply<T> = { ok: boolean; data?: T; error?: string };
type Setup = { status: string; launch?: string; old_launch: string; imported?: boolean };
type Game = { appid: number; name: string };
type Settings = { sr: string; fg: string; fg_input: string; spoof: string; fg_multiplier?: string };
type FsrStatus = { ready: boolean; version: string; reason: string };
type GameFsrStatus = FsrStatus & { prepared: boolean; bridge_ready: boolean; opti_version: string };
type Pending = { expected: string; target: string; kind: string };
type Info = Game & { executables: string[]; libraries: { path: string; version: number[] | null }[];
  optis: string[]; runtime_ready: boolean; prefix_ready: boolean; external_managed: boolean;
  automatic: { executable: string; route: string; reason: string; candidates: string[] }; state: Setup | null;
  fsr?: GameFsrStatus;
  opti?: { managed: boolean; installed: boolean; incomplete?: boolean; injection_enabled: boolean; version: string; status: string; rollback: boolean; pending?: Pending; settings_rollback?: boolean; settings_recovery?: boolean; settings: Settings } };
type Registration = { unregister(): void };
type RuntimeStatus = {ready:boolean;available:boolean;version:string;size_bytes:number;host_issue:string;error:string;availability_message:string};
type Operation = {schema:number;instance_id:string;operation_id:string|null;appid:number|null;kind:string;version:string;phase:string;running:boolean;downloaded_bytes:number;total_bytes:number|null;error:string|null;revision:number};
// Steam moves dropdown menus out of Quick Access and unmounts Content. Menu
// callbacks must update the session, not only a component that no longer exists.
type DownloadSource = 'github' | 'ghfast' | 'ghproxy';
type Selection = { appid: number; executables: Record<number, string>; source: DownloadSource;
  srDrafts: Record<number, string>; srDirty: Record<number, boolean> };
let selection: Selection = { appid: 0, executables: {}, source: 'github', srDrafts: {}, srDirty: {} };
const selectionListeners = new Set<() => void>();
const selectionSnapshot = () => selection;
function subscribeSelection(listener: () => void) {
  selectionListeners.add(listener);
  return () => { selectionListeners.delete(listener); };
}
function updateSelection(next: Selection) {
  selection = next;
  for (const listener of selectionListeners) listener();
}
function setSource(value: string) {
  if (value === 'github' || value === 'ghfast' || value === 'ghproxy')
    updateSelection({...selection, source:value});
}
function setSRDraft(appid: number, value: string) {
  if (selection.appid !== appid || !['xess','fsr_xmx','fsr31','fsr22','dlss'].includes(value)) return;
  updateSelection({...selection, srDrafts:{...selection.srDrafts,[appid]:value},
    srDirty:{...selection.srDirty,[appid]:true}});
}
function commitSRDraft(appid: number, value: string) {
  updateSelection({...selection, srDrafts:{...selection.srDrafts,[appid]:value},
    srDirty:{...selection.srDirty,[appid]:false}});
}
declare const SteamClient: { Apps: {
  RegisterForAppDetails(id: number, callback: (...args: unknown[]) => void): Registration;
  SetAppLaunchOptions(id: number, value: string): void;
}};
const inventory = callable<[], Reply<Game[]>>('inventory');
const inspect = callable<[number], Reply<Info>>('inspect_game');
const enable = callable<[number, string, string, string], Reply<Setup>>('enable');
const confirm = callable<[number, string], Reply<Setup>>('confirm_launch');
const restore = callable<[number, string], Reply<Setup>>('restore');
const optiInstall = callable<[number, string, string, string, string], Reply<Pending>>('opti_install');
const optiMigrate = callable<[number, string, string], Reply<Pending>>('opti_migrate');
const optiRollback = callable<[number, string], Reply<Pending>>('opti_rollback');
const optiUninstall = callable<[number, string], Reply<Pending>>('opti_uninstall');
const optiConfirm = callable<[number, string], Reply<boolean>>('opti_confirm');
const optiToggle = callable<[number, boolean, string], Reply<Pending>>('opti_toggle');
const optiSettings = callable<[number, Settings, boolean], Reply<boolean>>('opti_settings');
const optiRestoreSettings = callable<[number], Reply<boolean>>('opti_restore_settings');
const optiPanel = callable<[number], Reply<boolean>>('opti_panel');
const operationProgress = callable<[], Reply<Operation>>('operation_progress');
const runtimeStatus = callable<[], Reply<RuntimeStatus>>('runtime_status');
const runtimeInstall = callable<[], Reply<RuntimeStatus>>('runtime_install');
const fsrStatus = callable<[], Reply<FsrStatus>>('fsr_status');
const fsrImport = callable<[string], Reply<FsrStatus>>('fsr_import');
const fsrPrepare = callable<[number, string, string, string], Reply<Pending>>('fsr_prepare');
function unwrap<T>(r: Reply<T>): T {
  if (!r.ok || r.data === undefined) throw new Error(t(r.error || '操作失败'));
  return r.data;
}
function readLaunch(id: number): Promise<string> {
  return new Promise((resolve, reject) => {
    let reg: Registration | undefined;
    let done = false;
    const timeout = setTimeout(() => { done = true; reg?.unregister(); reject(new Error(t('读取 Steam 启动项超时'))); }, 8000);
    reg = SteamClient.Apps.RegisterForAppDetails(id, (...args) => {
      const details = args.find((a): a is { strLaunchOptions: string } =>
        typeof a === 'object' && a !== null && 'strLaunchOptions' in a && typeof a.strLaunchOptions === 'string');
      if (done || !details) return;
      done = true; clearTimeout(timeout); resolve(details.strLaunchOptions);
      queueMicrotask(() => reg?.unregister());
    });
  });
}
async function writeLaunch(id: number, desired: string, expected: string): Promise<string> {
  if (await readLaunch(id) !== expected) throw new Error(t('启动项刚被其他工具修改，请刷新后重试'));
  SteamClient.Apps.SetAppLaunchOptions(id, desired);
  for (let n = 0; n < 10; n++) {
    await new Promise(resolve => setTimeout(resolve, 150));
    const actual = await readLaunch(id);
    if (actual === desired) return actual;
  }
  throw new Error(t('Steam 启动项写入尚未确认，请使用继续开启或恢复'));
}
function Content() {
  const [games, setGames] = useState<Game[]>([]);
  const [appid, setAppid] = useState(0);
  const [info, setInfo] = useState<Info | null>(null);
  const [manualExe, setManualExe] = useState('');
  const [actualLaunch, setActualLaunch] = useState('');
  const [localBusy, setBusy] = useState(false);
  const [message, setMessage] = useState(t('正在读取游戏列表…'));
  const [error, setError] = useState(false);
  const lock = useRef(false);
  const [advanced, setAdvanced] = useState(false);
  const [version, setVersion] = useState('0.9.4');
  const [settings, setSettings] = useState<Settings>({sr:'xess',fg:'native',fg_input:'upscaler',spoof:'real',fg_multiplier:'native'});
  const [removeConfirm, setRemoveConfirm] = useState(false);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [progressDisconnected, setProgressDisconnected] = useState(false);
  const latestOperation = useRef<Operation | null>(null);
  const mounted = useRef(true);
  const selected = useRef(0);
  const loadSequence = useRef(0);
  const progressRequest = useRef(0);
  const acceptedRequest = useRef(0);
  const refreshNeeded = useRef<{appid:number;instance:string;operation:string|null} | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [fsr, setFsr] = useState<FsrStatus | null>(null);
  const session = useSyncExternalStore(subscribeSelection, selectionSnapshot);
  const source = session.source;
  const busy = localBusy || operation?.running === true;
  function acceptOperation(value: Operation) {
    if (!mounted.current || value.schema !== 1 || !Number.isSafeInteger(value.revision)
      || (latestOperation.current?.instance_id === value.instance_id && value.revision < latestOperation.current.revision)) return false;
    latestOperation.current = value; setOperation(value);
    return true;
  }
  async function readOperation(allowed = () => mounted.current) {
    const request = ++progressRequest.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const reply = await Promise.race([operationProgress(), new Promise<Reply<Operation>>((_, reject) => {
        timer = setTimeout(() => reject(new Error('progress timeout')), 5000);
      })]);
      const value = unwrap(reply);
      if (request < acceptedRequest.current || !allowed()) return null;
      acceptedRequest.current = request;
      setProgressDisconnected(false);
      return acceptOperation(value) ? value : null;
    } catch (e) {
      acceptedRequest.current = Math.max(acceptedRequest.current, request);
      if (allowed()) setProgressDisconnected(true);
      throw e;
    } finally { if (timer !== undefined) clearTimeout(timer); }
  }
  async function load(id: number) {
    const sequence = ++loadSequence.current;
    const [data, launch] = await Promise.all([inspect(id).then(unwrap), readLaunch(id)]);
    if (!mounted.current || selected.current !== id || sequence !== loadSequence.current) return data;
    const remembered = selection.executables[id] || '';
    const valid = data.automatic.candidates.includes(remembered) && data.executables.includes(remembered);
    if (remembered && !valid) {
      const executables = {...selection.executables}; delete executables[id];
      updateSelection({...selection, executables});
    }
    setInfo(data); setActualLaunch(launch); setManualExe(valid ? remembered : '');
    if (data.fsr) setFsr({ready:data.fsr.ready,version:data.fsr.version,reason:data.fsr.reason});
    if (data.opti) {
      const dirty = selection.srDirty[id] === true;
      const sr = dirty ? selection.srDrafts[id] || data.opti.settings.sr : data.opti.settings.sr;
      if (!dirty) updateSelection({...selection, srDrafts:{...selection.srDrafts,[id]:sr},
        srDirty:{...selection.srDirty,[id]:false}});
      setSettings({...data.opti.settings,sr});
    }
    setRemoveConfirm(false);
    return data;
  }
  async function task(progress: string, fn: () => Promise<void>, reattach = false) {
    if (lock.current || (!reattach && latestOperation.current?.running)) return;
    lock.current = true; setBusy(true); setError(false); setMessage(progress);
    try { await fn(); }
    catch (e) {
      const text = t(e instanceof Error ? e.message : String(e));
      setError(true); setMessage(text);
      toaster.toast({ title: t('Opti2XMX：未完成'), body: text });
    } finally { lock.current = false; setBusy(false); }
  }
  async function select(id: number) {
    if (!games.some(game => game.appid === id)) return;
    localStorage.setItem('opti2xmx-selected', String(id));
    if (selection.appid !== id) updateSelection({...selection, appid:id});
    if (!mounted.current) return;
    await task(t('正在检查这个游戏…'), async () => {
      setAppid(id); setInfo(null); setManualExe('');
      selected.current = id;
      await load(id); setMessage('');
    });
  }
  useEffect(() => {
    if (!busy && session.appid && selected.current !== session.appid && games.some(g => g.appid === session.appid))
      void select(session.appid);
  }, [session.appid, games, busy]);
  useEffect(() => {
    mounted.current = true;
    let alive = true, polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      try {
        const before = latestOperation.current;
        const next = await readOperation(() => alive && mounted.current);
        if (!alive || !next) return;
        const restarted = before && before.instance_id !== next.instance_id;
        const confirmed = before?.operation_id === next.operation_id && before?.phase === 'awaiting-launch' && next.phase === 'completed';
        if (before?.running && !next.running && next.kind === 'runtime_install')
          setRuntime(unwrap(await runtimeStatus()));
        if ((restarted || (before?.running && !next.running) || confirmed) && selected.current > 0
          && (restarted || next.appid === selected.current || next.kind === 'runtime_install'))
          refreshNeeded.current = {appid:selected.current,instance:next.instance_id,operation:next.operation_id};
        const refresh = refreshNeeded.current;
        if (refresh && (refresh.appid !== selected.current || refresh.instance !== next.instance_id || refresh.operation !== next.operation_id))
          refreshNeeded.current = null;
        else if (refresh && !lock.current) {
          await load(refresh.appid);
          if (refreshNeeded.current === refresh) refreshNeeded.current = null;
        }
      } catch { /* Keep the last running snapshot; a failed poll must not unlock it. */ }
      finally { polling = false; }
    }
    void poll();
    const timer = setInterval(() => { void poll(); }, 500);
    return () => { alive = false; mounted.current = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    void task(t('正在读取游戏列表…'), async () => {
      try { await readOperation(); } catch { /* Inventory remains usable while snapshot polling reconnects. */ }
      setRuntime(unwrap(await runtimeStatus()));
      try { setFsr(unwrap(await fsrStatus())); }
      catch { setFsr({ready:false,version:'',reason:t('当前插件后台不支持 FSR 模型导入，请更新插件。')}); }
      const list = unwrap(await inventory()); if (!mounted.current) return; setGames(list);
      const previous = Number(localStorage.getItem('opti2xmx-selected')) || selection.appid;
      const attached = latestOperation.current;
      const attach = attached?.running || attached?.phase === 'awaiting-launch';
      const id = (attach ? list.find(g => g.appid === attached?.appid)?.appid : undefined) || list.find(g => g.appid === previous)?.appid || list[0]?.appid;
      if (id) { selected.current = id; setAppid(id); updateSelection({...selection,appid:id}); await load(id); setMessage(''); }
      else setMessage(t('未找到已安装的 Steam 游戏。'));
    }, true);
  }, []);
  async function finish(id: number, setup: Setup, restoring = false) {
    const before = await readLaunch(id);
    const target = restoring ? setup.old_launch : setup.launch!;
    if (before !== setup.old_launch && before !== setup.launch)
      throw new Error(t('启动项已被其他工具修改，请检查后再试。'));
    const actual = before === target ? before : await writeLaunch(id, target, before);
    unwrap(await confirm(id, actual));
  }
  const state = info?.state;
  const active = state?.status === 'active' && actualLaunch === state.launch;
  const managed = !!state && !['restored', 'failed'].includes(state.status);
  const pending = managed && state?.status !== 'active';
  const rememberedExe = session.executables[appid] || manualExe;
  const validManualExe = info?.executables.includes(rememberedExe) && info.automatic.candidates.includes(rememberedExe) ? rememberedExe : '';
  const executable = info?.automatic.executable || validManualExe;
  const needsChoice = !!info && !info.automatic.executable && info.automatic.candidates.length > 1;
  const reason = needsChoice && validManualExe && info?.automatic.reason === '发现多个游戏程序，请在下面确认一次。'
    ? '' : info?.automatic.reason || '';
  const blocked = !managed && (!!reason || !executable);
  async function toggle(want: boolean) {
    if (!info) return;
    const id = info.appid;
    await task(want ? t('正在开启 XMX，请稍候…') : t('正在关闭 XMX，恢复原配置…'), async () => {
      try {
        const before = await readLaunch(id);
        if (want) {
          const setup = managed ? state! : unwrap(await enable(id, executable, info.automatic.route, before));
          if (!['active', 'pending_launch'].includes(setup.status)) throw new Error(t('上次设置未完成，请先点击恢复。'));
          await finish(id, setup);
        } else {
          await finish(id, unwrap(await restore(id, before)), true);
        }
        setMessage(want ? t('已开启。直接从 Steam 启动游戏即可。') : t('已关闭，原文件和启动项已恢复。'));
        toaster.toast({ title: 'Opti2XMX', body: want ? t('XMX 已开启') : t('XMX 已关闭') });
      } finally { await load(id); }
    });
  }
  const opti = info?.opti;
  const gameFsr = info?.fsr;
  const fsrReady = gameFsr?.ready ?? fsr?.ready ?? false;
  const fsrReason = gameFsr?.reason || fsr?.reason || '请导入本地 FSR 模型包。';
  const selectedSR = session.srDrafts[appid] || settings.sr;
  const migrateOpti = !!opti?.installed && !opti.incomplete;
  const installReason = !info?.prefix_ready ? '请先从 Steam 用 Proton 启动游戏一次，退出后点击刷新。'
    : !executable ? '请先选择要运行的游戏程序。'
    : !migrateOpti && managed ? '请先关闭 XMX，再安装、回退或卸载 Opti' : '';
  const optiPending = !!opti?.pending;
  const configBlocked = optiPending || !!opti?.settings_recovery;
  async function toggleOpti(want: boolean) {
    await task(want ? t('正在开启 Opti 注入…') : t('正在关闭 Opti 注入，保留 XMX…'), async () => {
      try {
        const before = await readLaunch(appid);
        const next = unwrap(await optiToggle(appid, want, before));
        const actual = before === next.target ? before : await writeLaunch(appid, next.target, before);
        unwrap(await optiConfirm(appid, actual));
        setMessage(want ? t('Opti 注入已开启，下次启动生效。') : t('Opti 注入已关闭；XMX 设置保留，使用游戏原生功能。'));
      } finally { await load(appid); }
    });
  }
  async function optiAction(kind: 'install' | 'migrate' | 'rollback' | 'uninstall' | 'finish') {
    const id = appid;
    await task(kind === 'install' ? t('正在下载并安装 Opti，请稍候…') : t('正在处理 Opti 配置…'), async () => {
      try {
        const before = await readLaunch(id);
        const next = kind === 'install' ? unwrap(await optiInstall(id, executable, before, version, source))
          : kind === 'migrate' ? unwrap(await optiMigrate(id, executable, before))
          : kind === 'rollback' ? unwrap(await optiRollback(id, before))
          : kind === 'uninstall' ? unwrap(await optiUninstall(id, before)) : opti!.pending!;
        if (!mounted.current) return;
        if (before !== next.expected && before !== next.target) throw new Error(t('启动项已变化，请检查后重试'));
        const actual = before === next.target ? before : await writeLaunch(id, next.target, before);
        if (!mounted.current) return;
        unwrap(await optiConfirm(id, actual));
        setMessage(t('Opti 操作完成，下次启动游戏生效。'));
        toaster.toast({title:'Opti2XMX',body:t('Opti 配置已完成')});
      } finally { await load(id); }
    });
  }
  async function saveSettings(reset = false) {
    await task(reset ? t('正在恢复推荐默认设置…') : t('正在保存设置…'), async () => {
      const id = appid;
      const desired: Settings = reset ? {sr:'xess',fg:'native',fg_input:'upscaler',spoof:'real',fg_multiplier:'native'}
        : {...settings,sr:session.srDrafts[id] || settings.sr};
      if (desired.sr === 'fsr_xmx') {
        desired.spoof = 'real';
        await saveFSRSettings(id, desired);
      } else unwrap(await optiSettings(id, desired, reset));
      commitSRDraft(id, desired.sr);
      await load(id);
      setMessage(t('设置已保存，下次启动游戏生效。'));
    });
  }
  async function applyPendingLaunch(id: number, before: string, next: Pending) {
    if (before !== next.expected && before !== next.target) throw new Error(t('启动项已变化，请检查后重试'));
    const actual = before === next.target ? before : await writeLaunch(id, next.target, before);
    unwrap(await optiConfirm(id, actual));
  }
  async function saveFSRSettings(id: number, desired: Settings) {
    let currentInfo = await load(id);
    let launch = await readLaunch(id);
    let xmxActive = currentInfo.state?.status === 'active' && launch === currentInfo.state.launch;
    if (currentInfo.state?.status === 'active' && !xmxActive)
      throw new Error(t('启动项已变化，请刷新后恢复 XMX，再保存 FSR。'));
    if (!currentInfo.fsr?.prepared && xmxActive) {
      await finish(id, unwrap(await restore(id, launch)), true);
      currentInfo = await load(id); launch = await readLaunch(id); xmxActive = false;
    }
    if (!currentInfo.fsr?.prepared) {
      const exe = currentInfo.automatic.executable || executable;
      if (!exe) throw new Error(t('请先选择要运行的游戏程序。'));
      const next = unwrap(await fsrPrepare(id, exe, launch, source));
      await applyPendingLaunch(id, launch, next);
      currentInfo = await load(id); launch = await readLaunch(id);
      xmxActive = currentInfo.state?.status === 'active' && launch === currentInfo.state.launch;
    }
    if (xmxActive && !currentInfo.fsr?.bridge_ready) {
      await finish(id, unwrap(await restore(id, launch)), true);
      currentInfo = await load(id); launch = await readLaunch(id); xmxActive = false;
    }
    if (!xmxActive) {
      const exe = currentInfo.automatic.executable || executable;
      if (!exe) throw new Error(t('请先选择要运行的游戏程序。'));
      const setup = unwrap(await enable(id, exe, currentInfo.automatic.route, launch));
      if (!['active','pending_launch'].includes(setup.status)) throw new Error(t('上次设置未完成，请先点击恢复。'));
      await finish(id, setup);
      currentInfo = await load(id); launch = await readLaunch(id);
      xmxActive = currentInfo.state?.status === 'active' && launch === currentInfo.state.launch;
    }
    if (!xmxActive || !currentInfo.fsr?.bridge_ready)
      throw new Error(t(currentInfo.fsr?.reason || 'FSR XMX 兼容组件尚未就绪，请刷新后重试。'));
    unwrap(await optiSettings(id, desired, false));
  }
  async function importFSRModel() {
    await task(t('正在选择 FSR 模型包…'), async () => {
      const picked = await openFilePicker(FileSelectionType.FILE, '/home/deck/Downloads', true, false, undefined, ['zip']);
      const path = picked?.realpath || picked?.path;
      if (!path) { setMessage(''); return; }
      if (!path.toLowerCase().endsWith('.zip')) throw new Error(t('请选择 ZIP 格式的 FSR 模型包。'));
      const status = unwrap(await fsrImport(path));
      setFsr(status);
      if (appid) await load(appid);
      setMessage(status.ready ? t('FSR 模型包已导入并验证。') : t(status.reason || 'FSR 模型包尚未就绪。'));
    });
  }
  const options = (items: [string,string][]) => items.map(([data,label])=>({data,label}));
  const multipliers = ['native', '2', '3', '4'];
  const runtimeReady = runtime?.ready ? t('XMX 运行环境已就绪') : '';
  const runtimeControl = !runtime?.ready && <ButtonItem layout="below" disabled={busy || !runtime || !runtime.available || !!runtime.host_issue}
      description={runtime
        ? t(runtime.error || runtime.availability_message || runtime.host_issue || '下载后校验并配置到当前用户目录。')
        : t('正在检查 XMX 运行环境…')}
      onClick={() => task(t('正在下载并配置 XMX 运行环境…'), async () => {
        try {
          setRuntime(unwrap(await runtimeInstall()));
          setMessage(t('XMX 运行环境已配置。选择游戏后开启 XMX。'));
        } finally {
          setRuntime(unwrap(await runtimeStatus()));
          if (appid) await load(appid);
        }
      })}>{t('下载并配置 XMX 运行环境')}</ButtonItem>;
  return <PanelSection>
    {progressDisconnected && <PanelSectionRow><div role="status">{t('进度连接暂不可用，正在重试。')}</div></PanelSectionRow>}
    <DropdownItem label={t('游戏')} layout="below" disabled={busy} selectedOption={appid} strDefaultLabel={t('选择游戏')}
      rgOptions={games.map(g => ({ data: g.appid, label: g.name }))} onChange={v => void select(Number(v.data))} />
    {info ? <>
      {needsChoice && !managed && <DropdownItem label={t('确认游戏程序')} layout="below" selectedOption={validManualExe}
        description={t('选择与 Steam 启动选项一致的版本。')} disabled={busy}
        strDefaultLabel={t('请选择要运行的版本')} rgOptions={info.automatic.candidates.map(p => ({data:p,label:p}))}
        onChange={v => {
          const value = String(v.data), id = info.appid;
          if (selection.appid !== id || !info.executables.includes(value) || !info.automatic.candidates.includes(value)) return;
          updateSelection({...selection, executables:{...selection.executables,[id]:value}});
          if (mounted.current) setManualExe(value);
        }} />}
      <ToggleField label={t('XMX 加速')} checked={active} disabled={busy || blocked || pending || configBlocked}
        description={t(blocked ? reason || '请先选择要运行的游戏程序。' : '仅限 Intel；更改前请退出游戏。')} onChange={want => void toggle(want)} />
      {opti?.managed && <ToggleField label={t('Opti 注入')} checked={opti.injection_enabled} disabled={busy || pending || configBlocked}
        description={t('原生 XeSS 帧生成请关闭。')}
        onChange={want => void toggleOpti(want)} />}
      {opti?.installed && !opti.incomplete && opti.injection_enabled !== false && <ButtonItem layout="below" disabled={busy || configBlocked} onClick={() => task(t('正在切换 Opti 面板…'), async () => {
        Navigation.CloseSideMenus(); unwrap(await optiPanel(appid)); setMessage(t('已发送面板快捷键。'));
      })}>{t('打开 / 关闭 Opti 面板')}</ButtonItem>}
      {runtimeControl}
      {opti && !opti.managed && !optiPending && <>
        {!migrateOpti && <DropdownItem layout="below" label={t('下载源')} selectedOption={source} disabled={busy}
          description={t('默认官方源；镜像由第三方提供。')}
          rgOptions={options([['github',t('GitHub 官方')],['ghfast',t('ghfast.top（第三方备用）')],['ghproxy',t('gh-proxy.com（第三方备用）')]])} onChange={v=>setSource(String(v.data))} />}
        <ButtonItem layout="below" disabled={busy || !!installReason}
          description={installReason ? t(installReason) : opti.incomplete ? t('缺少注入文件；备份现有文件后重新安装，可回退。') : migrateOpti ? t('保留文件并建立回退备份。') : undefined}
          onClick={()=>optiAction(migrateOpti?'migrate':'install')}>{opti.incomplete?t('修复安装 Opti 0.9.4'):migrateOpti?t('迁移现有 Opti'):t('安装 Opti 0.9.4')}</ButtonItem>
      </>}
      {optiPending && <ButtonItem layout="below" disabled={busy || opti?.status==='recovery_required'} onClick={()=>optiAction('finish')}>{t('完成 Opti 启动设置')}</ButtonItem>}
      {pending && state?.status === 'pending_launch' && <ButtonItem layout="below" disabled={busy} onClick={() => toggle(true)}>{t('继续开启')}</ButtonItem>}
      {managed && (!active || pending) && <ButtonItem layout="below" disabled={busy} onClick={() => toggle(false)}>{t('恢复原配置')}</ButtonItem>}
      {(opti?.managed || opti?.rollback) && <>
        <ButtonItem layout="below" disabled={busy} description={[opti.version ? 'Opti '+opti.version : '', runtimeReady].filter(Boolean).join(' · ')} onClick={()=>setAdvanced(!advanced)}>{advanced?t('收起高级设置'):t('高级设置')}</ButtonItem>
        {advanced && <>
          {opti.managed && (opti.version.startsWith('0.9') || opti.version.startsWith('10.')) && <>
            <DropdownItem layout="below" label={t('超分输出')} disabled={busy || configBlocked} selectedOption={selectedSR}
              description={active?t('XMX 开启时可选择 XeSS 或 FSR 4.1.2 Lite；先退出游戏，保存后下次启动生效。'):
                selectedSR==='fsr_xmx'?t('FSR 4.1.2 Lite 通过 XMX 兼容组件运行；保存时会准备此游戏。'):undefined}
              rgOptions={options(active ? [['xess','XeSS'],['fsr_xmx',t('FSR 4.1.2 Lite XMX')]]
                : [['xess','XeSS'],['fsr_xmx',t('FSR 4.1.2 Lite XMX')],['fsr31','FSR 3.1'],['fsr22','FSR 2.2'],['dlss',t('DLSS（需要支持的显卡）')]])}
              onChange={v=>{const value=String(v.data);setSRDraft(appid,value);setSettings({...settings,sr:value});}} />
            {selectedSR==='fsr_xmx' && <>
              <PanelSectionRow><div style={{fontSize:13,lineHeight:1.5}}>
                <div role="status">{t(!fsrReady ? fsrReason
                  : gameFsr?.bridge_ready ? 'FSR 4.1.2 Lite XMX 已就绪；退出游戏后保存设置并从 Steam 重新启动。'
                  : gameFsr?.prepared ? '此游戏的 FSR 文件已准备；保存时会刷新 XMX 兼容组件。'
                  : 'FSR 模型包已就绪；保存时会为此游戏准备 Opti 10 和模型。')}</div>
                {!active && <div role="note">{t(gameFsr?.prepared
                  ? 'FSR 需要 XMX；保存后会自动开启 XMX，退出游戏后从 Steam 启动。'
                  : 'FSR 需要 XMX；保存时会为此游戏准备 FSR 并自动开启 XMX。')}</div>}
              </div></PanelSectionRow>
              {!fsrReady && <ButtonItem layout="below" disabled={busy || configBlocked} description={t(fsrReason)}
                onClick={()=>void importFSRModel()}>{t('导入 FSR 模型包')}</ButtonItem>}
            </>}
            <DropdownItem layout="below" label={t('帧生成输出')} disabled={busy || configBlocked} selectedOption={settings.fg}
              description={opti.injection_enabled ? undefined : t('开启 Opti 注入后生效。')}
              rgOptions={options([['native',t('游戏原生（不接管）')],['fsrfg',t('FSR 帧生成')],['xefg',t('XeSS 帧生成（实验）')]])}
              onChange={v=>setSettings({...settings,fg:String(v.data),fg_multiplier:v.data==='native'?'native':settings.fg_multiplier==='native'?'2':settings.fg_multiplier || '2'})} />
            {settings.fg!=='fsrfg' && <SliderField label={t('插帧倍率')+(settings.fg==='native'?' · '+t('游戏原生控制'):'')}
              disabled={busy || configBlocked} value={settings.fg==='native' ? 0 : Math.max(1, multipliers.indexOf(settings.fg_multiplier || '2'))}
              min={0} max={3} step={1} validValues="steps" notchCount={4} notchTicksVisible showValue={false}
              notchLabels={[t('原生'), '2×', '3×', '4×'].map((label, notchIndex) => ({label, notchIndex}))}
              onChange={value=>setSettings({...settings,fg:value===0?'native':'xefg',fg_multiplier:multipliers[value]})} />}
            {settings.fg!=='native' && <DropdownItem layout="below" label={t('游戏 FG 类型')} disabled={busy || configBlocked} selectedOption={settings.fg_input}
              description={t('选择游戏支持的帧生成类型。')}
              rgOptions={options([['fsrfg30','FSR 3.0 FG'],['fsrfg','FSR 3.1 FG'],['dlssg','DLSS FG'],['upscaler',t('无原生 FG：使用超分输入')]])}
              onChange={v=>setSettings({...settings,fg_input:String(v.data)})} />}
            <DropdownItem layout="below" label={t('显卡伪装')} disabled={busy || active || configBlocked || selectedSR==='fsr_xmx'} selectedOption={selectedSR==='fsr_xmx'?'real':settings.spoof}
              description={active || selectedSR==='fsr_xmx'?t('XMX 开启时保留真实 Intel 身份。'):t('实验兼容选项；改身份不保证解锁功能。')}
              rgOptions={options([['real',t('真实显卡（推荐）')],['nvidia','NVIDIA'],['amd','AMD'],['intel','Intel Arc']])}
              onChange={v=>setSettings({...settings,spoof:String(v.data)})} />
            <ButtonItem layout="below" disabled={busy || optiPending || !!opti.settings_recovery || (selectedSR==='fsr_xmx' && (!fsrReady || pending || blocked))} onClick={()=>saveSettings()}>{t('保存设置')}</ButtonItem>
            <ButtonItem layout="below" disabled={busy || optiPending || !!opti.settings_recovery} description={t('恢复 XeSS、真实显卡、由游戏管理帧生成；先退出游戏。')} onClick={()=>saveSettings(true)}>{t('恢复默认')}</ButtonItem>
            {(opti.settings_rollback || opti.settings_recovery) && <ButtonItem layout="below" disabled={busy || optiPending}
              description={t('恢复上次保存前的配置；保留安装回退记录。先退出游戏。')}
              onClick={()=>task(t('正在撤销上次设置…'),async()=>{unwrap(await optiRestoreSettings(appid));await load(appid);setMessage(t('已恢复上次保存前的设置，下次启动生效。'));})}>
              {opti.settings_recovery?t('恢复中断的设置'):t('撤销上次设置')}</ButtonItem>}
          </>}
          <DropdownItem layout="below" label={t('Opti 版本')} disabled={busy || configBlocked} selectedOption={version}
            rgOptions={options([['0.9.4',t('0.9.4（当前稳定版）')],['0.7.9',t('0.7.9（兼容旧版）')]])} onChange={v=>setVersion(String(v.data))} />
          <DropdownItem layout="below" label={t('下载源')} disabled={busy || configBlocked} selectedOption={source}
            description={t('默认官方源；镜像由第三方提供。')}
            rgOptions={options([['github',t('GitHub 官方')],['ghfast',t('ghfast.top（第三方备用）')],['ghproxy',t('gh-proxy.com（第三方备用）')]])} onChange={v=>setSource(String(v.data))} />
          <ButtonItem layout="below" disabled={busy || managed || configBlocked || !opti.injection_enabled} description={managed?t('先关闭 XMX，再更换 Opti 版本。'):t('开启 Opti 注入后可更换版本；保留回退备份。')} onClick={()=>optiAction('install')}>{t('安装所选版本')}</ButtonItem>
          <ButtonItem layout="below" disabled={busy || managed || configBlocked || !opti.rollback} description={t('撤销上次安装、迁移或卸载；需先关闭 XMX。')} onClick={()=>optiAction('rollback')}>{t('回退上次操作')}</ButtonItem>
          <ButtonItem layout="below" disabled={busy || managed || configBlocked || !opti.managed} description={t('卸载本插件管理的 Opti 文件并恢复原文件；需先关闭 XMX。')} onClick={()=>removeConfirm ? optiAction('uninstall') : setRemoveConfirm(true)}>{removeConfirm?t('确认卸载 Opti'):t('卸载 Opti')}</ButtonItem>
        </>}
      </>}
      {message && <PanelSectionRow><div role={error ? 'alert' : 'status'} style={{fontSize:13,lineHeight:1.5}}>{t(message)}</div></PanelSectionRow>}
    </> : <>{runtimeControl}<PanelSectionRow><div role="status" style={{fontSize:13,lineHeight:1.5}}>{t(message)}</div></PanelSectionRow></>}
    {operation?.operation_id && (operation.appid === appid || operation.running || operation.kind === 'runtime_install') && <PanelSectionRow>
      <div role={operation.phase === 'failed' ? 'alert' : 'status'} style={{fontSize:13,lineHeight:1.5}}>
        {t(((operation.kind === 'runtime_install' ? {started:'正在准备 XMX 运行环境…',downloading:'正在下载 XMX 运行环境…',extracting:'正在解压 XMX 运行环境…',installing:'正在验证并配置 XMX 运行环境…',completed:'XMX 运行环境配置完成。',failed:'XMX 运行环境配置未完成。'} : {started:'正在准备 Opti…',downloading:'正在下载 Opti…','cache-hit':'正在复用 Opti 缓存…',extracting:'正在解压 Opti…',installing:'正在安装 Opti…','awaiting-launch':'Opti 已准备，等待确认启动设置。',completed:'Opti 操作已完成。',failed:'Opti 操作未完成。'}) as Record<string,string>)[operation.phase] || '正在处理 Opti 配置…')}
        {operation.downloaded_bytes > 0 && <> · {(operation.downloaded_bytes / 1048576).toFixed(1)} MiB
          {operation.total_bytes !== null && operation.total_bytes > 0 && operation.downloaded_bytes <= operation.total_bytes
            && <> / {(operation.total_bytes / 1048576).toFixed(1)} MiB · {(operation.downloaded_bytes * 100 / operation.total_bytes).toFixed(0)}%</>}</>}
        {operation.error && <> · {t(operation.error)}</>}
      </div>
    </PanelSectionRow>}
    {runtimeReady && !(opti?.managed || opti?.rollback) && <PanelSectionRow><div role="status">{runtimeReady}</div></PanelSectionRow>}
    <ButtonItem layout="below" disabled={busy} onClick={() => task(t('正在刷新…'), async () => {
      setRuntime(unwrap(await runtimeStatus())); setGames(unwrap(await inventory())); if (appid) await load(appid); setMessage('');
    })}>{t('刷新')}</ButtonItem>
  </PanelSection>;
}
export default definePlugin(() => ({
  name: 'Opti2XMX', titleView: <div className={staticClasses.Title}>Opti2XMX</div>,
  content: <Content />, icon: <span style={{ fontWeight: 700 }}>X</span>, onDismount() {},
}));
