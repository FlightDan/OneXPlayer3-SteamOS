// Follow the Steam page language, with its browser locale as a fallback.
function language() {
    const locale = (typeof document !== 'undefined' && document.documentElement.lang)
        || (typeof navigator !== 'undefined' && navigator.language) || 'zh-CN';
    return /^(zh|schinese|tchinese)/i.test(locale) ? 'zh' : 'en';
}
const english = {
    '进度连接暂不可用，正在重试。': 'Progress connection is temporarily unavailable. Retrying.',
    '正在准备 Opti…': 'Preparing Opti…', '正在下载 Opti…': 'Downloading Opti…', '正在复用 Opti 缓存…': 'Reusing the Opti cache…',
    '正在解压 Opti…': 'Extracting Opti…', '正在安装 Opti…': 'Installing Opti…', 'Opti 已准备，等待确认启动设置。': 'Opti is prepared; confirm the launch setup.',
    'Opti 操作已完成。': 'Opti operation completed.', 'Opti 操作未完成。': 'Opti operation did not complete.',
    'Opti 操作仍在进行，请等待完成。': 'An Opti operation is still running. Wait for it to finish.',
    '仅支持 Intel 设备。': 'Intel devices only.',
    '为游戏启用 XMX 加速，使兼容的游戏中的 XeSS 帧生成可以正常使用。': 'Enable XMX acceleration so XeSS Frame Generation can work in compatible games.',
    '更改状态前请先关闭游戏！': 'Close the game before changing this setting!',
    '游戏原生支持 XeSS 帧生成时，请关闭此选项。': 'If the game natively supports XeSS Frame Generation, turn this option off.',
    '使用 ': 'Use ',
    ' 修改游戏内的超分辨率/帧生成设置': ' to change in-game upscaling/frame generation settings',
    '游戏': 'Game', '选择游戏': 'Select a game', 'XMX 加速': 'XMX acceleration', 'Opti 注入': 'Opti injection',
    '打开 Opti 面板': 'Open Opti overlay', '高级设置': 'Advanced settings', '收起高级设置': 'Hide advanced settings',
    '刷新': 'Refresh', '下载源': 'Download source', 'GitHub 官方': 'GitHub (official)',
    'ghfast.top（第三方备用）': 'ghfast.top (third-party mirror)', 'gh-proxy.com（第三方备用）': 'gh-proxy.com (third-party mirror)',
    '默认使用官方；备用镜像由第三方提供。已有缓存时直接复用。': 'Uses the official source by default. Mirrors are provided by third parties. Cached downloads are reused.',
    '迁移现有 Opti': 'Migrate existing Opti', '安装 Opti 0.9.4': 'Install Opti 0.9.4',
    '保留现有文件，建立统一管理和回退记录。': 'Keep existing files and add managed backups and rollback.',
    '安装 Opti 0.9.4；有原生 XeSS 的游戏可直接使用 XMX。': 'Install Opti 0.9.4. Games with native XeSS can use XMX directly.',
    '完成 Opti 启动设置': 'Finish Opti launch setup', '确认游戏程序': 'Confirm game executable',
    '检测到多个版本，只需确认一次。': 'Multiple executables found. Select the one you use.',
    '请选择要运行的版本': 'Select the version to launch', '继续开启': 'Continue setup', '恢复原配置': 'Restore original setup',
    '超分输出': 'Upscaling output', 'XMX 开启时使用 XeSS。': 'XeSS is used while XMX is enabled.',
    'DLSS（需要支持的显卡）': 'DLSS (supported GPU required)', '帧生成输出': 'Frame generation output',
    '这是 Opti 的输出；XeFG 输入尚未实现。原生 XeSS FG 可关闭 Opti 注入测试。': 'This is the Opti output. XeFG input is not implemented. Turn off Opti injection to test native XeSS FG.',
    'Opti 注入已关闭；这里的设置将在重新开启后生效。': 'Opti injection is off. These settings apply when it is turned back on.',
    '游戏原生（不接管）': 'Native (no FG interception)', 'FSR 帧生成': 'FSR Frame Generation', 'XeSS 帧生成（实验）': 'XeSS Frame Generation (experimental)',
    '游戏 FG 类型': 'Game FG input', '选择游戏实际支持的类型，并在游戏里开启对应帧生成。无原生 FG 才选超分输入。': 'Select a supported input and enable it in the game. Use upscaler input when the game has no native FG.',
    '无原生 FG：使用超分输入': 'No native FG: use upscaler input', '显卡伪装': 'GPU spoofing',
    'XMX 开启时保留真实 Intel 身份。': 'XMX retains the real Intel GPU identity.',
    '实验兼容选项；改身份不保证解锁功能。': 'Experimental compatibility option. Spoofing does not guarantee feature support.',
    '真实显卡（推荐）': 'Real GPU (recommended)', '保存设置': 'Save settings', '恢复默认': 'Reset to defaults',
    '恢复 XeSS、真实显卡、由游戏管理帧生成；先退出游戏。': 'Restore XeSS, real GPU identity and native FG. Exit the game first.',
    'Opti 版本': 'Opti version', '0.9.4（当前稳定版）': '0.9.4 (stable)', '0.7.9（兼容旧版）': '0.7.9 (legacy compatibility)',
    '先关闭 XMX，再更换 Opti 版本。': 'Turn off XMX before changing the Opti version.',
    '开启 Opti 注入后可更换版本；保留回退备份。': 'Enable Opti injection before changing versions. Rollback backups are retained.',
    '安装所选版本': 'Install selected version', '回退上次操作': 'Undo last operation',
    '撤销上次安装、迁移或卸载；需先关闭 XMX。': 'Undo the last installation, migration, toggle or removal. Turn off XMX first.',
    '卸载 Opti': 'Uninstall Opti', '确认卸载 Opti': 'Confirm Opti removal',
    '卸载本插件管理的 Opti 文件并恢复原文件；需先关闭 XMX。': 'Remove managed Opti files and restore originals. Turn off XMX first.',
    '操作失败': 'Operation failed', 'Opti2XMX：未完成': 'Opti2XMX: not completed',
    '读取 Steam 启动项超时': 'Timed out reading Steam launch options',
    '启动项刚被其他工具修改，请刷新后重试': 'Launch options changed elsewhere. Refresh and try again.',
    'Steam 启动项写入尚未确认，请使用继续开启或恢复': 'Steam has not confirmed the launch options. Continue setup or restore.',
    '正在读取游戏列表…': 'Loading games…', '正在检查这个游戏…': 'Checking this game…',
    '未找到已安装的 Steam 游戏。': 'No installed Steam games found.',
    '启动项已被其他工具修改，请检查后再试。': 'Launch options changed elsewhere. Check them before retrying.',
    '发现多个游戏程序，请在下面确认一次。': 'Multiple game executables found. Select one below.',
    '正在开启 XMX，请稍候…': 'Enabling XMX…', '正在关闭 XMX，恢复原配置…': 'Disabling XMX and restoring the original setup…',
    '上次设置未完成，请先点击恢复。': 'The previous setup is incomplete. Restore it first.',
    '已开启。直接从 Steam 启动游戏即可。': 'Enabled. Launch the game from Steam.',
    '已关闭，原文件和启动项已恢复。': 'Disabled. Original files and launch options restored.',
    'XMX 已开启': 'XMX enabled', 'XMX 已关闭': 'XMX disabled',
    '上次设置未完成，请用下面的按钮继续或恢复。': 'Setup is incomplete. Use the buttons below to continue or restore.',
    '启动设置已变化。打开开关可重新应用；也可以恢复原配置。': 'Launch options changed. Enable to reapply, or restore the original setup.',
    '已就绪，打开开关即可。启用或关闭前请先退出游戏。': 'Ready to enable. Exit the game before switching.',
    '正在开启 Opti 注入…': 'Enabling Opti injection…', '正在关闭 Opti 注入，保留 XMX…': 'Disabling Opti injection while keeping XMX…',
    'Opti 注入已开启，下次启动生效。': 'Opti injection enabled for the next launch.',
    'Opti 注入已关闭；XMX 设置保留，使用游戏原生功能。': 'Opti injection disabled. XMX settings are retained; native game features will be used.',
    '正在下载并安装 Opti，请稍候…': 'Downloading and installing Opti…', '正在处理 Opti 配置…': 'Updating Opti setup…',
    '启动项已变化，请检查后重试': 'Launch options changed. Check them and try again.',
    'Opti 操作完成，下次启动游戏生效。': 'Opti setup complete. Changes apply on the next launch.',
    'Opti 配置已完成': 'Opti setup complete', '正在恢复推荐默认设置…': 'Restoring recommended defaults…',
    '正在保存设置…': 'Saving settings…', '设置已保存，下次启动游戏生效。': 'Settings saved for the next launch.',
    '正在打开 Opti 面板…': 'Opening the Opti overlay…', '已发送面板快捷键。': 'Overlay shortcut sent.', '正在刷新…': 'Refreshing…',
    '游戏仍在运行。请从 Steam 退出游戏，再操作 XMX 开关。': 'The game is still running. Exit it from Steam before changing the switches.',
    '游戏仍在运行，请退出后重试。': 'The game is still running. Exit it and try again.',
    'Opti 注入已关闭，当前使用游戏原生功能': 'Opti injection is off; native game features are in use.',
    '请先启动选中的游戏，再打开面板': 'Start the selected game before opening the overlay.',
    '未找到该游戏的可见窗口，请回到游戏后重试': 'No visible window found for this game. Return to the game and try again.',
    '此游戏已有其他 XMX 配置，需要先迁移后才能用此开关。': 'This game has another XMX setup. Migrate it before using this switch.',
    'XMX 运行组件未就绪。': 'XMX runtime components are not ready.',
    '请先从 Steam 用 Proton 启动游戏一次，退出后点击刷新。': 'Launch this game once with Proton, exit, then refresh.',
    '尚未发现 XeSS。请先为此游戏安装 OptiScaler 并运行一次，再刷新。': 'XeSS was not found. Install OptiScaler for this game, run it once, then refresh.',
    '未识别到可接入的游戏程序，请检查游戏安装。': 'No compatible executable found. Check the game installation.',
    'OptiScaler 文件不完整，需要同目录的 dxgi.dll 和 libxess.dll。': 'OptiScaler is incomplete. dxgi.dll and libxess.dll must be beside the executable.',
    '请先开启 Opti 注入，再更换版本': 'Enable Opti injection before changing versions.',
    '请先关闭 XMX，再安装、回退或卸载 Opti': 'Turn off XMX before installing, rolling back or removing Opti.',
    '上次操作待完成，请先完成启动项设置或回退': 'The previous operation is pending. Complete launch setup or roll back.',
    '文件已被其他工具修改，请先处理冲突：': 'A file was changed by another tool. Resolve the conflict: ',
    '操作中断，备份已保存，请点击回退上次操作': 'Operation interrupted. Backups were saved. Use Undo last operation.',
};
function t(text) {
    if (language() === 'zh')
        return text;
    if (english[text])
        return english[text];
    for (const [prefix, translated] of Object.entries(english)) {
        if (prefix.endsWith('：') && text.startsWith(prefix))
            return translated + text.slice(prefix.length);
    }
    return text;
}

const manifest = {"name":"Opti2XMX"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const toaster = api.toaster;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

const inventory = callable('inventory');
const inspect = callable('inspect_game');
const enable = callable('enable');
const confirm = callable('confirm_launch');
const restore = callable('restore');
const optiInstall = callable('opti_install');
const optiMigrate = callable('opti_migrate');
const optiRollback = callable('opti_rollback');
const optiUninstall = callable('opti_uninstall');
const optiConfirm = callable('opti_confirm');
const optiToggle = callable('opti_toggle');
const optiSettings = callable('opti_settings');
const optiPanel = callable('opti_panel');
const operationProgress = callable('operation_progress');
function unwrap(r) {
    if (!r.ok || r.data === undefined)
        throw new Error(t(r.error || '操作失败'));
    return r.data;
}
function readLaunch(id) {
    return new Promise((resolve, reject) => {
        let reg;
        let done = false;
        const timeout = setTimeout(() => { done = true; reg?.unregister(); reject(new Error(t('读取 Steam 启动项超时'))); }, 8000);
        reg = SteamClient.Apps.RegisterForAppDetails(id, (...args) => {
            const details = args.find((a) => typeof a === 'object' && a !== null && 'strLaunchOptions' in a && typeof a.strLaunchOptions === 'string');
            if (done || !details)
                return;
            done = true;
            clearTimeout(timeout);
            resolve(details.strLaunchOptions);
            queueMicrotask(() => reg?.unregister());
        });
    });
}
async function writeLaunch(id, desired, expected) {
    if (await readLaunch(id) !== expected)
        throw new Error(t('启动项刚被其他工具修改，请刷新后重试'));
    SteamClient.Apps.SetAppLaunchOptions(id, desired);
    for (let n = 0; n < 10; n++) {
        await new Promise(resolve => setTimeout(resolve, 150));
        const actual = await readLaunch(id);
        if (actual === desired)
            return actual;
    }
    throw new Error(t('Steam 启动项写入尚未确认，请使用继续开启或恢复'));
}
function Content() {
    const [games, setGames] = SP_REACT.useState([]);
    const [appid, setAppid] = SP_REACT.useState(0);
    const [info, setInfo] = SP_REACT.useState(null);
    const [manualExe, setManualExe] = SP_REACT.useState('');
    const [actualLaunch, setActualLaunch] = SP_REACT.useState('');
    const [localBusy, setBusy] = SP_REACT.useState(false);
    const [message, setMessage] = SP_REACT.useState(t('正在读取游戏列表…'));
    const [error, setError] = SP_REACT.useState(false);
    const lock = SP_REACT.useRef(false);
    const [advanced, setAdvanced] = SP_REACT.useState(false);
    const [version, setVersion] = SP_REACT.useState('0.9.4');
    const [source, setSource] = SP_REACT.useState('github');
    const [settings, setSettings] = SP_REACT.useState({ sr: 'xess', fg: 'native', fg_input: 'upscaler', spoof: 'real' });
    const [removeConfirm, setRemoveConfirm] = SP_REACT.useState(false);
    const [operation, setOperation] = SP_REACT.useState(null);
    const [progressDisconnected, setProgressDisconnected] = SP_REACT.useState(false);
    const latestOperation = SP_REACT.useRef(null);
    const mounted = SP_REACT.useRef(true);
    const selected = SP_REACT.useRef(0);
    const loadSequence = SP_REACT.useRef(0);
    const progressRequest = SP_REACT.useRef(0);
    const acceptedRequest = SP_REACT.useRef(0);
    const refreshNeeded = SP_REACT.useRef(null);
    const busy = localBusy || operation?.running === true;
    function acceptOperation(value) {
        if (!mounted.current || value.schema !== 1 || !Number.isSafeInteger(value.revision)
            || (latestOperation.current?.instance_id === value.instance_id && value.revision < latestOperation.current.revision))
            return false;
        latestOperation.current = value;
        setOperation(value);
        return true;
    }
    async function readOperation(allowed = () => mounted.current) {
        const request = ++progressRequest.current;
        let timer;
        try {
            const reply = await Promise.race([operationProgress(), new Promise((_, reject) => {
                    timer = setTimeout(() => reject(new Error('progress timeout')), 5000);
                })]);
            const value = unwrap(reply);
            if (request < acceptedRequest.current || !allowed())
                return null;
            acceptedRequest.current = request;
            setProgressDisconnected(false);
            return acceptOperation(value) ? value : null;
        }
        catch (e) {
            acceptedRequest.current = Math.max(acceptedRequest.current, request);
            if (allowed())
                setProgressDisconnected(true);
            throw e;
        }
        finally {
            if (timer !== undefined)
                clearTimeout(timer);
        }
    }
    async function load(id) {
        const sequence = ++loadSequence.current;
        const [data, launch] = await Promise.all([inspect(id).then(unwrap), readLaunch(id)]);
        if (!mounted.current || selected.current !== id || sequence !== loadSequence.current)
            return data;
        setInfo(data);
        setActualLaunch(launch);
        setManualExe('');
        if (data.opti)
            setSettings(data.opti.settings);
        setRemoveConfirm(false);
        return data;
    }
    async function task(progress, fn, reattach = false) {
        if (lock.current || (!reattach && latestOperation.current?.running))
            return;
        lock.current = true;
        setBusy(true);
        setError(false);
        setMessage(progress);
        try {
            await fn();
        }
        catch (e) {
            const text = t(e instanceof Error ? e.message : String(e));
            setError(true);
            setMessage(text);
            toaster.toast({ title: t('Opti2XMX：未完成'), body: text });
        }
        finally {
            lock.current = false;
            setBusy(false);
        }
    }
    async function select(id) {
        await task(t('正在检查这个游戏…'), async () => {
            setAppid(id);
            setInfo(null);
            setManualExe('');
            selected.current = id;
            await load(id);
            setMessage('');
            localStorage.setItem('opti2xmx-selected', String(id));
        });
    }
    SP_REACT.useEffect(() => {
        mounted.current = true;
        let alive = true, polling = false;
        async function poll() {
            if (polling)
                return;
            polling = true;
            try {
                const before = latestOperation.current;
                const next = await readOperation(() => alive && mounted.current);
                if (!alive || !next)
                    return;
                const restarted = before && before.instance_id !== next.instance_id;
                const confirmed = before?.operation_id === next.operation_id && before?.phase === 'awaiting-launch' && next.phase === 'completed';
                if ((restarted || (before?.running && !next.running) || confirmed) && selected.current > 0
                    && (restarted || next.appid === selected.current))
                    refreshNeeded.current = { appid: selected.current, instance: next.instance_id, operation: next.operation_id };
                const refresh = refreshNeeded.current;
                if (refresh && (refresh.appid !== selected.current || refresh.instance !== next.instance_id || refresh.operation !== next.operation_id))
                    refreshNeeded.current = null;
                else if (refresh && !lock.current) {
                    refreshNeeded.current = null;
                    await load(refresh.appid);
                }
            }
            catch { /* Keep the last running snapshot; a failed poll must not unlock it. */ }
            finally {
                polling = false;
            }
        }
        void poll();
        const timer = setInterval(() => { void poll(); }, 500);
        return () => { alive = false; mounted.current = false; clearInterval(timer); };
    }, []);
    SP_REACT.useEffect(() => {
        void task(t('正在读取游戏列表…'), async () => {
            try {
                await readOperation();
            }
            catch { /* Inventory remains usable while snapshot polling reconnects. */ }
            const list = unwrap(await inventory());
            if (!mounted.current)
                return;
            setGames(list);
            const previous = Number(localStorage.getItem('opti2xmx-selected'));
            const attached = latestOperation.current;
            const attach = attached?.running || attached?.phase === 'awaiting-launch';
            const id = (attach ? list.find(g => g.appid === attached?.appid)?.appid : undefined) || list.find(g => g.appid === previous)?.appid || list[0]?.appid;
            if (id) {
                selected.current = id;
                setAppid(id);
                await load(id);
                setMessage('');
            }
            else
                setMessage(t('未找到已安装的 Steam 游戏。'));
        }, true);
    }, []);
    async function finish(id, setup, restoring = false) {
        const before = await readLaunch(id);
        const target = restoring ? setup.old_launch : setup.launch;
        if (before !== setup.old_launch && before !== setup.launch)
            throw new Error(t('启动项已被其他工具修改，请检查后再试。'));
        const actual = before === target ? before : await writeLaunch(id, target, before);
        unwrap(await confirm(id, actual));
    }
    const state = info?.state;
    const active = state?.status === 'active' && actualLaunch === state.launch;
    const managed = !!state && state.status !== 'restored';
    const pending = managed && state?.status !== 'active';
    const executable = manualExe || info?.automatic.executable || '';
    const needsChoice = !!info && !info.automatic.executable && info.automatic.candidates.length > 1;
    const reason = needsChoice && manualExe && info?.automatic.reason === '发现多个游戏程序，请在下面确认一次。'
        ? '' : info?.automatic.reason || '';
    const blocked = !managed && (!!reason || !executable);
    async function toggle(want) {
        if (!info)
            return;
        const id = info.appid;
        await task(want ? t('正在开启 XMX，请稍候…') : t('正在关闭 XMX，恢复原配置…'), async () => {
            try {
                const before = await readLaunch(id);
                if (want) {
                    const setup = managed ? state : unwrap(await enable(id, executable, info.automatic.route, before));
                    if (!['active', 'pending_launch'].includes(setup.status))
                        throw new Error(t('上次设置未完成，请先点击恢复。'));
                    await finish(id, setup);
                }
                else {
                    await finish(id, unwrap(await restore(id, before)), true);
                }
                setMessage(want ? t('已开启。直接从 Steam 启动游戏即可。') : t('已关闭，原文件和启动项已恢复。'));
                toaster.toast({ title: 'Opti2XMX', body: want ? t('XMX 已开启') : t('XMX 已关闭') });
            }
            finally {
                await load(id);
            }
        });
    }
    const opti = info?.opti;
    const optiPending = !!opti?.pending;
    async function toggleOpti(want) {
        await task(want ? t('正在开启 Opti 注入…') : t('正在关闭 Opti 注入，保留 XMX…'), async () => {
            try {
                const before = await readLaunch(appid);
                const next = unwrap(await optiToggle(appid, want, before));
                const actual = before === next.target ? before : await writeLaunch(appid, next.target, before);
                unwrap(await optiConfirm(appid, actual));
                setMessage(want ? t('Opti 注入已开启，下次启动生效。') : t('Opti 注入已关闭；XMX 设置保留，使用游戏原生功能。'));
            }
            finally {
                await load(appid);
            }
        });
    }
    async function optiAction(kind) {
        const id = appid;
        await task(kind === 'install' ? t('正在下载并安装 Opti，请稍候…') : t('正在处理 Opti 配置…'), async () => {
            try {
                const before = await readLaunch(id);
                const next = kind === 'install' ? unwrap(await optiInstall(id, executable, before, version, source))
                    : kind === 'migrate' ? unwrap(await optiMigrate(id, executable, before))
                        : kind === 'rollback' ? unwrap(await optiRollback(id, before))
                            : kind === 'uninstall' ? unwrap(await optiUninstall(id, before)) : opti.pending;
                if (!mounted.current)
                    return;
                if (before !== next.expected && before !== next.target)
                    throw new Error(t('启动项已变化，请检查后重试'));
                const actual = before === next.target ? before : await writeLaunch(id, next.target, before);
                if (!mounted.current)
                    return;
                unwrap(await optiConfirm(id, actual));
                setMessage(t('Opti 操作完成，下次启动游戏生效。'));
                toaster.toast({ title: 'Opti2XMX', body: t('Opti 配置已完成') });
            }
            finally {
                await load(id);
            }
        });
    }
    async function saveSettings(reset = false) {
        await task(reset ? t('正在恢复推荐默认设置…') : t('正在保存设置…'), async () => {
            const desired = reset ? { sr: 'xess', fg: 'native', fg_input: 'upscaler', spoof: 'real' } : settings;
            unwrap(await optiSettings(appid, desired, reset));
            await load(appid);
            setMessage(t('设置已保存，下次启动游戏生效。'));
        });
    }
    const options = (items) => items.map(([data, label]) => ({ data, label }));
    return SP_JSX.jsxs(DFL.PanelSection, { children: [progressDisconnected && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", children: t('进度连接暂不可用，正在重试。') }) }), SP_JSX.jsx(DFL.DropdownItem, { label: t('游戏'), layout: "below", disabled: busy, selectedOption: appid, strDefaultLabel: t('选择游戏'), rgOptions: games.map(g => ({ data: g.appid, label: g.name })), onChange: v => void select(Number(v.data)) }), info ? SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.ToggleField, { label: t('XMX 加速'), checked: active, disabled: busy || blocked || pending || optiPending, description: SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("strong", { children: t('仅支持 Intel 设备。') }), SP_JSX.jsx("br", {}), t('为游戏启用 XMX 加速，使兼容的游戏中的 XeSS 帧生成可以正常使用。'), SP_JSX.jsx("br", {}), t('更改状态前请先关闭游戏！')] }), onChange: want => void toggle(want) }), opti?.managed && SP_JSX.jsx(DFL.ToggleField, { label: t('Opti 注入'), checked: opti.injection_enabled, disabled: busy || pending || optiPending, description: SP_JSX.jsxs(SP_JSX.Fragment, { children: [t('游戏原生支持 XeSS 帧生成时，请关闭此选项。'), SP_JSX.jsx("br", {}), t('使用 '), SP_JSX.jsx("em", { children: "OptiScaler" }), t(' 修改游戏内的超分辨率/帧生成设置')] }), onChange: want => void toggleOpti(want) }), opti?.installed && opti.injection_enabled !== false && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending, onClick: () => task(t('正在打开 Opti 面板…'), async () => {
                            DFL.Navigation.CloseSideMenus();
                            unwrap(await optiPanel(appid));
                            setMessage(t('已发送面板快捷键。'));
                        }), children: t('打开 Opti 面板') }), opti && !opti.managed && !optiPending && SP_JSX.jsxs(SP_JSX.Fragment, { children: [!opti.installed && SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('下载源'), selectedOption: source, disabled: busy, description: t('默认使用官方；备用镜像由第三方提供。已有缓存时直接复用。'), rgOptions: options([['github', t('GitHub 官方')], ['ghfast', t('ghfast.top（第三方备用）')], ['ghproxy', t('gh-proxy.com（第三方备用）')]]), onChange: v => setSource(String(v.data)) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !executable || (!opti.installed && managed), description: opti.installed ? t('保留现有文件，建立统一管理和回退记录。') : t('安装 Opti 0.9.4；有原生 XeSS 的游戏可直接使用 XMX。'), onClick: () => optiAction(opti.installed ? 'migrate' : 'install'), children: opti.installed ? t('迁移现有 Opti') : t('安装 Opti 0.9.4') })] }), optiPending && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || opti?.status === 'recovery_required', onClick: () => optiAction('finish'), children: t('完成 Opti 启动设置') }), needsChoice && !managed && SP_JSX.jsx(DFL.DropdownItem, { label: t('确认游戏程序'), layout: "below", selectedOption: manualExe, description: t('检测到多个版本，只需确认一次。'), disabled: busy, strDefaultLabel: t('请选择要运行的版本'), rgOptions: info.automatic.candidates.map(p => ({ data: p, label: p })), onChange: v => setManualExe(String(v.data)) }), pending && state?.status === 'pending_launch' && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => toggle(true), children: t('继续开启') }), managed && (!active || pending) && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => toggle(false), children: t('恢复原配置') }), (opti?.managed || opti?.rollback) && SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, description: 'Opti ' + opti.version, onClick: () => setAdvanced(!advanced), children: advanced ? t('收起高级设置') : t('高级设置') }), advanced && SP_JSX.jsxs(SP_JSX.Fragment, { children: [opti.managed && opti.version.startsWith('0.9') && SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('超分输出'), disabled: busy || active || optiPending, selectedOption: settings.sr, description: active ? t('XMX 开启时使用 XeSS。') : undefined, rgOptions: options([['xess', 'XeSS'], ['fsr31', 'FSR 3.1'], ['fsr22', 'FSR 2.2'], ['dlss', t('DLSS（需要支持的显卡）')]]), onChange: v => setSettings({ ...settings, sr: String(v.data) }) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('帧生成输出'), disabled: busy || optiPending, selectedOption: settings.fg, description: opti.injection_enabled ? t('这是 Opti 的输出；XeFG 输入尚未实现。原生 XeSS FG 可关闭 Opti 注入测试。') : t('Opti 注入已关闭；这里的设置将在重新开启后生效。'), rgOptions: options([['native', t('游戏原生（不接管）')], ['fsrfg', t('FSR 帧生成')], ['xefg', t('XeSS 帧生成（实验）')]]), onChange: v => setSettings({ ...settings, fg: String(v.data) }) }), settings.fg !== 'native' && SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('游戏 FG 类型'), disabled: busy || optiPending, selectedOption: settings.fg_input, description: t('选择游戏实际支持的类型，并在游戏里开启对应帧生成。无原生 FG 才选超分输入。'), rgOptions: options([['fsrfg30', 'FSR 3.0 FG'], ['fsrfg', 'FSR 3.1 FG'], ['dlssg', 'DLSS FG'], ['upscaler', t('无原生 FG：使用超分输入')]]), onChange: v => setSettings({ ...settings, fg_input: String(v.data) }) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('显卡伪装'), disabled: busy || active || optiPending, selectedOption: settings.spoof, description: active ? t('XMX 开启时保留真实 Intel 身份。') : t('实验兼容选项；改身份不保证解锁功能。'), rgOptions: options([['real', t('真实显卡（推荐）')], ['nvidia', 'NVIDIA'], ['amd', 'AMD'], ['intel', 'Intel Arc']]), onChange: v => setSettings({ ...settings, spoof: String(v.data) }) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending, onClick: () => saveSettings(), children: t('保存设置') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending, description: t('恢复 XeSS、真实显卡、由游戏管理帧生成；先退出游戏。'), onClick: () => saveSettings(true), children: t('恢复默认') })] }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('Opti 版本'), disabled: busy || optiPending, selectedOption: version, rgOptions: options([['0.9.4', t('0.9.4（当前稳定版）')], ['0.7.9', t('0.7.9（兼容旧版）')]]), onChange: v => setVersion(String(v.data)) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('下载源'), disabled: busy || optiPending, selectedOption: source, description: t('默认使用官方；备用镜像由第三方提供。已有缓存时直接复用。'), rgOptions: options([['github', t('GitHub 官方')], ['ghfast', t('ghfast.top（第三方备用）')], ['ghproxy', t('gh-proxy.com（第三方备用）')]]), onChange: v => setSource(String(v.data)) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || optiPending || !opti.injection_enabled, description: managed ? t('先关闭 XMX，再更换 Opti 版本。') : t('开启 Opti 注入后可更换版本；保留回退备份。'), onClick: () => optiAction('install'), children: t('安装所选版本') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || !opti.rollback, description: t('撤销上次安装、迁移或卸载；需先关闭 XMX。'), onClick: () => optiAction('rollback'), children: t('回退上次操作') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || optiPending || !opti.managed, description: t('卸载本插件管理的 Opti 文件并恢复原文件；需先关闭 XMX。'), onClick: () => removeConfirm ? optiAction('uninstall') : setRemoveConfirm(true), children: removeConfirm ? t('确认卸载 Opti') : t('卸载 Opti') })] })] }), message && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: error ? 'alert' : 'status', style: { fontSize: 13, lineHeight: 1.5 }, children: t(message) }) })] }) : SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", style: { fontSize: 13, lineHeight: 1.5 }, children: t(message) }) }), operation?.operation_id && (operation.appid === appid || operation.running) && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { role: operation.phase === 'failed' ? 'alert' : 'status', style: { fontSize: 13, lineHeight: 1.5 }, children: [t({ started: '正在准备 Opti…', downloading: '正在下载 Opti…', 'cache-hit': '正在复用 Opti 缓存…', extracting: '正在解压 Opti…', installing: '正在安装 Opti…', 'awaiting-launch': 'Opti 已准备，等待确认启动设置。', completed: 'Opti 操作已完成。', failed: 'Opti 操作未完成。' }[operation.phase] || '正在处理 Opti 配置…'), operation.downloaded_bytes > 0 && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" \u00B7 ", (operation.downloaded_bytes / 1048576).toFixed(1), " MiB", operation.total_bytes !== null && operation.total_bytes > 0 && operation.downloaded_bytes <= operation.total_bytes
                                    && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" / ", (operation.total_bytes / 1048576).toFixed(1), " MiB \u00B7 ", (operation.downloaded_bytes * 100 / operation.total_bytes).toFixed(0), "%"] })] }), operation.error && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" \u00B7 ", t(operation.error)] })] }) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => task(t('正在刷新…'), async () => {
                    setGames(unwrap(await inventory()));
                    if (appid)
                        await load(appid);
                    setMessage('');
                }), children: t('刷新') })] });
}
var index = definePlugin(() => ({
    name: 'Opti2XMX', titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "Opti2XMX" }),
    content: SP_JSX.jsx(Content, {}), icon: SP_JSX.jsx("span", { style: { fontWeight: 700 }, children: "X" }), onDismount() { },
}));

export { index as default };
//# sourceMappingURL=index.js.map
