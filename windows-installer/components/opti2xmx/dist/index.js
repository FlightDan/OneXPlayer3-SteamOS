// Follow the Steam page language, with its browser locale as a fallback.
function language() {
    const locale = (typeof document !== 'undefined' && document.documentElement.lang)
        || (typeof navigator !== 'undefined' && navigator.language) || 'zh-CN';
    return /^(zh|schinese|tchinese)/i.test(locale) ? 'zh' : 'en';
}
const english = {
    '仅限 Intel；更改前请退出游戏。': 'Intel only. Exit the game before changing.',
    '原生 XeSS 帧生成请关闭。': 'Turn off for native XeSS Frame Generation.',
    '默认官方源；镜像由第三方提供。': 'Official source by default; third-party mirrors available.',
    '保留文件并建立回退备份。': 'Keep files and create rollback backups.',
    '开启 Opti 注入后生效。': 'Applies when Opti injection is enabled.',
    '插帧倍率': 'FG multiplier', '游戏原生控制': 'Game controlled', '原生': 'Native',
    '选择游戏支持的帧生成类型。': 'Select the frame generation type supported by the game.',
    '启用 Intel XMX 执行路径；帧生成仍需游戏、运行时和 Proton 支持。': 'Enable the Intel XMX path. Frame generation still requires game, runtime and Proton support.',
    'XeSS FG 倍率（实验）': 'XeSS FG multiplier (experimental)',
    '仅用于 Opti XeSS FG 输出。实际倍率取决于运行时支持；原生 XeSS FG 请在游戏内设置。': 'For Opti XeSS FG output. The runtime determines the effective multiplier. Configure native XeSS FG in the game.',
    '2x（生成 1 帧）': '2x (1 generated frame)', '3x（生成 2 帧）': '3x (2 generated frames)', '4x（生成 3 帧）': '4x (3 generated frames)',
    '恢复上次保存前的配置；保留安装回退记录。先退出游戏。': 'Restore the settings before the last save, retaining install rollback. Exit the game first.',
    '正在撤销上次设置…': 'Undoing the last settings change…', '已恢复上次保存前的设置，下次启动生效。': 'Previous settings restored for the next launch.',
    '恢复中断的设置': 'Recover interrupted settings', '撤销上次设置': 'Undo last settings change',
    '设置保存或恢复未完成，请先恢复上次设置': 'A settings change is incomplete. Recover the previous settings first.',
    '设置保存未完成，已保留恢复记录；请先恢复上次设置：': 'Settings were not fully saved. Recovery records were retained. Recover the previous settings: ',
    '设置恢复未完成，已保留恢复记录；请重试恢复上次设置：': 'Settings recovery is incomplete. Records were retained. Retry recovery: ',
    '设置文件已被外部修改，保留现场：': 'A settings file changed externally. It was left untouched: ',
    '没有可恢复的设置': 'No settings change is available to undo.',
    '设置恢复目标已变化，保留现场': 'Settings recovery targets changed. Files were left untouched.',
    '设置恢复记录与当前安装不一致': 'Settings recovery does not match the current installation.',
    '无效设置备份路径': 'Invalid settings backup path.',
    '设置文件必须是当前用户的普通文件：': 'The settings file must be a regular file owned by the current user: ',
    '游戏程序已经变化，请刷新': 'The game executable changed. Refresh before continuing.',
    '没有已管理的 Opti 设置文件': 'No managed Opti settings file was found.',
    'XMX 操作待完成，请先完成或恢复': 'An XMX operation is pending. Complete or restore it first.',
    '游戏 Proton 环境已变化，请刷新': 'The game Proton prefix changed. Refresh before continuing.',
    '固定版本的 XMX 运行环境尚未发布。发布后请更新插件。': 'The pinned XMX runtime release is not published yet. Update the plugin when it becomes available.',
    '独立的 XMX 组件，不含 OptiScaler。': 'Separate XMX components; OptiScaler is managed separately.',
    'XMX 运行环境已就绪。': 'XMX runtime is ready.', 'XMX 运行环境已就绪': 'XMX runtime ready',
    '下载后校验并配置到当前用户目录。': 'Download, verify and configure in your user data directory.',
    '正在检查 XMX 运行环境…': 'Checking the XMX runtime…',
    '正在下载并配置 XMX 运行环境…': 'Downloading and configuring the XMX runtime…',
    '下载并配置 XMX 运行环境': 'Download and configure XMX runtime',
    'XMX 运行环境已配置。选择游戏后开启 XMX。': 'XMX runtime configured. Select a game to enable XMX.',
    '正在准备 XMX 运行环境…': 'Preparing the XMX runtime…', '正在下载 XMX 运行环境…': 'Downloading the XMX runtime…',
    '正在解压 XMX 运行环境…': 'Extracting the XMX runtime…', '正在验证并配置 XMX 运行环境…': 'Validating and configuring the XMX runtime…',
    'XMX 运行环境配置完成。': 'XMX runtime setup completed.', 'XMX 运行环境配置未完成。': 'XMX runtime setup did not complete.',
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
    '打开 / 关闭 Opti 面板': 'Toggle Opti overlay', '高级设置': 'Advanced settings', '收起高级设置': 'Hide advanced settings',
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
    '正在切换 Opti 面板…': 'Toggling the Opti overlay…', '已发送面板快捷键。': 'Overlay shortcut sent.', '正在刷新…': 'Refreshing…',
    '游戏仍在运行。请从 Steam 退出游戏，再操作 XMX 开关。': 'The game is still running. Exit it from Steam before changing the switches.',
    '游戏仍在运行，请退出后重试。': 'The game is still running. Exit it and try again.',
    'Opti 注入已关闭，当前使用游戏原生功能': 'Opti injection is off; native game features are in use.',
    '请先启动选中的游戏，再打开面板': 'Start the selected game before opening the overlay.',
    '未找到该游戏的可见窗口，请回到游戏后重试': 'No visible window found for this game. Return to the game and try again.',
    '此游戏已有其他 XMX 配置，需要先迁移后才能用此开关。': 'This game has another XMX setup. Migrate it before using this switch.',
    'XMX 运行组件未就绪。': 'XMX runtime components are not ready.',
    '请先选择要运行的游戏程序。': 'Select the game executable first.',
    '选择与 Steam 启动选项一致的版本。': 'Choose the version used by your Steam launch option.',
    '修复安装 Opti 0.9.4': 'Repair Opti 0.9.4 installation',
    '缺少注入文件；备份现有文件后重新安装，可回退。': 'Injector missing. Back up existing files and reinstall; rollback is available.',
    '游戏已有注入文件，请先迁移或处理冲突：': 'An injector already exists. Migrate it or resolve the conflict first: ',
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

let selection = { appid: 0, executables: {}, source: 'github' };
const selectionListeners = new Set();
const selectionSnapshot = () => selection;
function subscribeSelection(listener) {
    selectionListeners.add(listener);
    return () => { selectionListeners.delete(listener); };
}
function updateSelection(next) {
    selection = next;
    for (const listener of selectionListeners)
        listener();
}
function setSource(value) {
    if (value === 'github' || value === 'ghfast' || value === 'ghproxy')
        updateSelection({ ...selection, source: value });
}
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
const optiRestoreSettings = callable('opti_restore_settings');
const optiPanel = callable('opti_panel');
const operationProgress = callable('operation_progress');
const runtimeStatus = callable('runtime_status');
const runtimeInstall = callable('runtime_install');
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
    const [settings, setSettings] = SP_REACT.useState({ sr: 'xess', fg: 'native', fg_input: 'upscaler', spoof: 'real', fg_multiplier: 'native' });
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
    const [runtime, setRuntime] = SP_REACT.useState(null);
    const session = SP_REACT.useSyncExternalStore(subscribeSelection, selectionSnapshot);
    const source = session.source;
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
        const remembered = selection.executables[id] || '';
        const valid = data.automatic.candidates.includes(remembered) && data.executables.includes(remembered);
        if (remembered && !valid) {
            const executables = { ...selection.executables };
            delete executables[id];
            updateSelection({ ...selection, executables });
        }
        setInfo(data);
        setActualLaunch(launch);
        setManualExe(valid ? remembered : '');
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
        if (!games.some(game => game.appid === id))
            return;
        localStorage.setItem('opti2xmx-selected', String(id));
        if (selection.appid !== id)
            updateSelection({ ...selection, appid: id });
        if (!mounted.current)
            return;
        await task(t('正在检查这个游戏…'), async () => {
            setAppid(id);
            setInfo(null);
            setManualExe('');
            selected.current = id;
            await load(id);
            setMessage('');
        });
    }
    SP_REACT.useEffect(() => {
        if (!busy && session.appid && selected.current !== session.appid && games.some(g => g.appid === session.appid))
            void select(session.appid);
    }, [session.appid, games, busy]);
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
                if (before?.running && !next.running && next.kind === 'runtime_install')
                    setRuntime(unwrap(await runtimeStatus()));
                if ((restarted || (before?.running && !next.running) || confirmed) && selected.current > 0
                    && (restarted || next.appid === selected.current || next.kind === 'runtime_install'))
                    refreshNeeded.current = { appid: selected.current, instance: next.instance_id, operation: next.operation_id };
                const refresh = refreshNeeded.current;
                if (refresh && (refresh.appid !== selected.current || refresh.instance !== next.instance_id || refresh.operation !== next.operation_id))
                    refreshNeeded.current = null;
                else if (refresh && !lock.current) {
                    await load(refresh.appid);
                    if (refreshNeeded.current === refresh)
                        refreshNeeded.current = null;
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
            setRuntime(unwrap(await runtimeStatus()));
            const list = unwrap(await inventory());
            if (!mounted.current)
                return;
            setGames(list);
            const previous = Number(localStorage.getItem('opti2xmx-selected')) || selection.appid;
            const attached = latestOperation.current;
            const attach = attached?.running || attached?.phase === 'awaiting-launch';
            const id = (attach ? list.find(g => g.appid === attached?.appid)?.appid : undefined) || list.find(g => g.appid === previous)?.appid || list[0]?.appid;
            if (id) {
                selected.current = id;
                setAppid(id);
                updateSelection({ ...selection, appid: id });
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
    const managed = !!state && !['restored', 'failed'].includes(state.status);
    const pending = managed && state?.status !== 'active';
    const rememberedExe = session.executables[appid] || manualExe;
    const validManualExe = info?.executables.includes(rememberedExe) && info.automatic.candidates.includes(rememberedExe) ? rememberedExe : '';
    const executable = info?.automatic.executable || validManualExe;
    const needsChoice = !!info && !info.automatic.executable && info.automatic.candidates.length > 1;
    const reason = needsChoice && validManualExe && info?.automatic.reason === '发现多个游戏程序，请在下面确认一次。'
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
    const migrateOpti = !!opti?.installed && !opti.incomplete;
    const installReason = !info?.prefix_ready ? '请先从 Steam 用 Proton 启动游戏一次，退出后点击刷新。'
        : !executable ? '请先选择要运行的游戏程序。'
            : !migrateOpti && managed ? '请先关闭 XMX，再安装、回退或卸载 Opti' : '';
    const optiPending = !!opti?.pending;
    const configBlocked = optiPending || !!opti?.settings_recovery;
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
            const desired = reset ? { sr: 'xess', fg: 'native', fg_input: 'upscaler', spoof: 'real', fg_multiplier: 'native' } : settings;
            unwrap(await optiSettings(appid, desired, reset));
            await load(appid);
            setMessage(t('设置已保存，下次启动游戏生效。'));
        });
    }
    const options = (items) => items.map(([data, label]) => ({ data, label }));
    const multipliers = ['native', '2', '3', '4'];
    const runtimeReady = runtime?.ready ? t('XMX 运行环境已就绪') : '';
    const runtimeControl = !runtime?.ready && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !runtime || !runtime.available || !!runtime.host_issue, description: runtime
            ? t(runtime.error || runtime.availability_message || runtime.host_issue || '下载后校验并配置到当前用户目录。')
            : t('正在检查 XMX 运行环境…'), onClick: () => task(t('正在下载并配置 XMX 运行环境…'), async () => {
            try {
                setRuntime(unwrap(await runtimeInstall()));
                setMessage(t('XMX 运行环境已配置。选择游戏后开启 XMX。'));
            }
            finally {
                setRuntime(unwrap(await runtimeStatus()));
                if (appid)
                    await load(appid);
            }
        }), children: t('下载并配置 XMX 运行环境') });
    return SP_JSX.jsxs(DFL.PanelSection, { children: [progressDisconnected && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", children: t('进度连接暂不可用，正在重试。') }) }), SP_JSX.jsx(DFL.DropdownItem, { label: t('游戏'), layout: "below", disabled: busy, selectedOption: appid, strDefaultLabel: t('选择游戏'), rgOptions: games.map(g => ({ data: g.appid, label: g.name })), onChange: v => void select(Number(v.data)) }), info ? SP_JSX.jsxs(SP_JSX.Fragment, { children: [needsChoice && !managed && SP_JSX.jsx(DFL.DropdownItem, { label: t('确认游戏程序'), layout: "below", selectedOption: validManualExe, description: t('选择与 Steam 启动选项一致的版本。'), disabled: busy, strDefaultLabel: t('请选择要运行的版本'), rgOptions: info.automatic.candidates.map(p => ({ data: p, label: p })), onChange: v => {
                            const value = String(v.data), id = info.appid;
                            if (selection.appid !== id || !info.executables.includes(value) || !info.automatic.candidates.includes(value))
                                return;
                            updateSelection({ ...selection, executables: { ...selection.executables, [id]: value } });
                            if (mounted.current)
                                setManualExe(value);
                        } }), SP_JSX.jsx(DFL.ToggleField, { label: t('XMX 加速'), checked: active, disabled: busy || blocked || pending || configBlocked, description: t(blocked ? reason || '请先选择要运行的游戏程序。' : '仅限 Intel；更改前请退出游戏。'), onChange: want => void toggle(want) }), opti?.managed && SP_JSX.jsx(DFL.ToggleField, { label: t('Opti 注入'), checked: opti.injection_enabled, disabled: busy || pending || configBlocked, description: t('原生 XeSS 帧生成请关闭。'), onChange: want => void toggleOpti(want) }), opti?.installed && !opti.incomplete && opti.injection_enabled !== false && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || configBlocked, onClick: () => task(t('正在切换 Opti 面板…'), async () => {
                            DFL.Navigation.CloseSideMenus();
                            unwrap(await optiPanel(appid));
                            setMessage(t('已发送面板快捷键。'));
                        }), children: t('打开 / 关闭 Opti 面板') }), runtimeControl, opti && !opti.managed && !optiPending && SP_JSX.jsxs(SP_JSX.Fragment, { children: [!migrateOpti && SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('下载源'), selectedOption: source, disabled: busy, description: t('默认官方源；镜像由第三方提供。'), rgOptions: options([['github', t('GitHub 官方')], ['ghfast', t('ghfast.top（第三方备用）')], ['ghproxy', t('gh-proxy.com（第三方备用）')]]), onChange: v => setSource(String(v.data)) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !!installReason, description: installReason ? t(installReason) : opti.incomplete ? t('缺少注入文件；备份现有文件后重新安装，可回退。') : migrateOpti ? t('保留文件并建立回退备份。') : undefined, onClick: () => optiAction(migrateOpti ? 'migrate' : 'install'), children: opti.incomplete ? t('修复安装 Opti 0.9.4') : migrateOpti ? t('迁移现有 Opti') : t('安装 Opti 0.9.4') })] }), optiPending && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || opti?.status === 'recovery_required', onClick: () => optiAction('finish'), children: t('完成 Opti 启动设置') }), pending && state?.status === 'pending_launch' && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => toggle(true), children: t('继续开启') }), managed && (!active || pending) && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => toggle(false), children: t('恢复原配置') }), (opti?.managed || opti?.rollback) && SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, description: [opti.version ? 'Opti ' + opti.version : '', runtimeReady].filter(Boolean).join(' · '), onClick: () => setAdvanced(!advanced), children: advanced ? t('收起高级设置') : t('高级设置') }), advanced && SP_JSX.jsxs(SP_JSX.Fragment, { children: [opti.managed && opti.version.startsWith('0.9') && SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('超分输出'), disabled: busy || active || configBlocked, selectedOption: settings.sr, description: active ? t('XMX 开启时使用 XeSS。') : undefined, rgOptions: options([['xess', 'XeSS'], ['fsr31', 'FSR 3.1'], ['fsr22', 'FSR 2.2'], ['dlss', t('DLSS（需要支持的显卡）')]]), onChange: v => setSettings({ ...settings, sr: String(v.data) }) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('帧生成输出'), disabled: busy || configBlocked, selectedOption: settings.fg, description: opti.injection_enabled ? undefined : t('开启 Opti 注入后生效。'), rgOptions: options([['native', t('游戏原生（不接管）')], ['fsrfg', t('FSR 帧生成')], ['xefg', t('XeSS 帧生成（实验）')]]), onChange: v => setSettings({ ...settings, fg: String(v.data), fg_multiplier: v.data === 'native' ? 'native' : settings.fg_multiplier === 'native' ? '2' : settings.fg_multiplier || '2' }) }), settings.fg !== 'fsrfg' && SP_JSX.jsx(DFL.SliderField, { label: t('插帧倍率') + (settings.fg === 'native' ? ' · ' + t('游戏原生控制') : ''), disabled: busy || configBlocked, value: settings.fg === 'native' ? 0 : Math.max(1, multipliers.indexOf(settings.fg_multiplier || '2')), min: 0, max: 3, step: 1, validValues: "steps", notchCount: 4, notchTicksVisible: true, showValue: false, notchLabels: [t('原生'), '2×', '3×', '4×'].map((label, notchIndex) => ({ label, notchIndex })), onChange: value => setSettings({ ...settings, fg: value === 0 ? 'native' : 'xefg', fg_multiplier: multipliers[value] }) }), settings.fg !== 'native' && SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('游戏 FG 类型'), disabled: busy || configBlocked, selectedOption: settings.fg_input, description: t('选择游戏支持的帧生成类型。'), rgOptions: options([['fsrfg30', 'FSR 3.0 FG'], ['fsrfg', 'FSR 3.1 FG'], ['dlssg', 'DLSS FG'], ['upscaler', t('无原生 FG：使用超分输入')]]), onChange: v => setSettings({ ...settings, fg_input: String(v.data) }) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('显卡伪装'), disabled: busy || active || configBlocked, selectedOption: settings.spoof, description: active ? t('XMX 开启时保留真实 Intel 身份。') : t('实验兼容选项；改身份不保证解锁功能。'), rgOptions: options([['real', t('真实显卡（推荐）')], ['nvidia', 'NVIDIA'], ['amd', 'AMD'], ['intel', 'Intel Arc']]), onChange: v => setSettings({ ...settings, spoof: String(v.data) }) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending || !!opti.settings_recovery, onClick: () => saveSettings(), children: t('保存设置') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending || !!opti.settings_recovery, description: t('恢复 XeSS、真实显卡、由游戏管理帧生成；先退出游戏。'), onClick: () => saveSettings(true), children: t('恢复默认') }), (opti.settings_rollback || opti.settings_recovery) && SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || optiPending, description: t('恢复上次保存前的配置；保留安装回退记录。先退出游戏。'), onClick: () => task(t('正在撤销上次设置…'), async () => { unwrap(await optiRestoreSettings(appid)); await load(appid); setMessage(t('已恢复上次保存前的设置，下次启动生效。')); }), children: opti.settings_recovery ? t('恢复中断的设置') : t('撤销上次设置') })] }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('Opti 版本'), disabled: busy || configBlocked, selectedOption: version, rgOptions: options([['0.9.4', t('0.9.4（当前稳定版）')], ['0.7.9', t('0.7.9（兼容旧版）')]]), onChange: v => setVersion(String(v.data)) }), SP_JSX.jsx(DFL.DropdownItem, { layout: "below", label: t('下载源'), disabled: busy || configBlocked, selectedOption: source, description: t('默认官方源；镜像由第三方提供。'), rgOptions: options([['github', t('GitHub 官方')], ['ghfast', t('ghfast.top（第三方备用）')], ['ghproxy', t('gh-proxy.com（第三方备用）')]]), onChange: v => setSource(String(v.data)) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || configBlocked || !opti.injection_enabled, description: managed ? t('先关闭 XMX，再更换 Opti 版本。') : t('开启 Opti 注入后可更换版本；保留回退备份。'), onClick: () => optiAction('install'), children: t('安装所选版本') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || configBlocked || !opti.rollback, description: t('撤销上次安装、迁移或卸载；需先关闭 XMX。'), onClick: () => optiAction('rollback'), children: t('回退上次操作') }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || managed || configBlocked || !opti.managed, description: t('卸载本插件管理的 Opti 文件并恢复原文件；需先关闭 XMX。'), onClick: () => removeConfirm ? optiAction('uninstall') : setRemoveConfirm(true), children: removeConfirm ? t('确认卸载 Opti') : t('卸载 Opti') })] })] }), message && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: error ? 'alert' : 'status', style: { fontSize: 13, lineHeight: 1.5 }, children: t(message) }) })] }) : SP_JSX.jsxs(SP_JSX.Fragment, { children: [runtimeControl, SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", style: { fontSize: 13, lineHeight: 1.5 }, children: t(message) }) })] }), operation?.operation_id && (operation.appid === appid || operation.running || operation.kind === 'runtime_install') && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { role: operation.phase === 'failed' ? 'alert' : 'status', style: { fontSize: 13, lineHeight: 1.5 }, children: [t((operation.kind === 'runtime_install' ? { started: '正在准备 XMX 运行环境…', downloading: '正在下载 XMX 运行环境…', extracting: '正在解压 XMX 运行环境…', installing: '正在验证并配置 XMX 运行环境…', completed: 'XMX 运行环境配置完成。', failed: 'XMX 运行环境配置未完成。' } : { started: '正在准备 Opti…', downloading: '正在下载 Opti…', 'cache-hit': '正在复用 Opti 缓存…', extracting: '正在解压 Opti…', installing: '正在安装 Opti…', 'awaiting-launch': 'Opti 已准备，等待确认启动设置。', completed: 'Opti 操作已完成。', failed: 'Opti 操作未完成。' })[operation.phase] || '正在处理 Opti 配置…'), operation.downloaded_bytes > 0 && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" \u00B7 ", (operation.downloaded_bytes / 1048576).toFixed(1), " MiB", operation.total_bytes !== null && operation.total_bytes > 0 && operation.downloaded_bytes <= operation.total_bytes
                                    && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" / ", (operation.total_bytes / 1048576).toFixed(1), " MiB \u00B7 ", (operation.downloaded_bytes * 100 / operation.total_bytes).toFixed(0), "%"] })] }), operation.error && SP_JSX.jsxs(SP_JSX.Fragment, { children: [" \u00B7 ", t(operation.error)] })] }) }), runtimeReady && !(opti?.managed || opti?.rollback) && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", children: runtimeReady }) }), SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => task(t('正在刷新…'), async () => {
                    setRuntime(unwrap(await runtimeStatus()));
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
