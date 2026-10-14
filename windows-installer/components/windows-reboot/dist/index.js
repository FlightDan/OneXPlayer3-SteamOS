const manifest = {"name":"Restart into Windows"};
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
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

const status = callable('status');
const reboot = callable('reboot');
const t = (zh, en) => /^(zh|schinese|tchinese)/i.test(document.documentElement.lang || navigator.language) ? zh : en;
function unwrap(reply) {
    if (!reply.ok || reply.data === undefined)
        throw new Error(reply.error || t('操作失败', 'Operation failed'));
    return reply.data;
}
function Content() {
    const [info, setInfo] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [message, setMessage] = SP_REACT.useState('');
    const lock = SP_REACT.useRef(false);
    const confirming = SP_REACT.useRef(false);
    const requested = SP_REACT.useRef(false);
    const mounted = SP_REACT.useRef(true);
    SP_REACT.useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; }; }, []);
    async function task(action) {
        if (lock.current)
            return;
        lock.current = true;
        setBusy(true);
        setMessage('');
        try {
            await action();
        }
        catch (error) {
            if (mounted.current)
                setMessage(error instanceof Error ? error.message : String(error));
        }
        finally {
            lock.current = requested.current;
            if (mounted.current)
                setBusy(requested.current);
        }
    }
    async function refresh() {
        await task(async () => {
            setInfo(null);
            const result = unwrap(await status());
            if (mounted.current)
                setInfo(result);
        });
    }
    function confirm() {
        if (lock.current || confirming.current || !info?.ready || !info.target)
            return;
        confirming.current = true;
        const target = info.target;
        DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { bDestructiveWarning: true, strTitle: t('重启进入 Windows？', 'Restart into Windows?'), strDescription: t('将关闭当前会话。请先保存游戏和文件。仅下一次启动进入 Windows。', 'Your session will close. Save games and files first. Only the next boot will enter Windows.'), strOKButtonText: t('重启', 'Restart'), strCancelButtonText: t('取消', 'Cancel'), onOK: () => void task(async () => {
                unwrap(await reboot(target, true));
                requested.current = true;
                if (mounted.current)
                    setMessage(t('已请求重启，正在进入 Windows…', 'Restart requested. Starting Windows…'));
            }) }), undefined, { fnOnClose: () => { confirming.current = false; } });
    }
    return SP_JSX.jsxs(DFL.PanelSection, { title: t('系统切换', 'Switch system'), children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", "aria-live": "polite", style: { overflowWrap: 'anywhere' }, children: busy ? t('正在处理…', 'Working…') : info?.ready
                        ? t('Windows 启动项已就绪', 'Windows boot entry is ready')
                        : info?.reason || t('请刷新启动状态', 'Refresh the boot status') }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { disabled: busy || !info?.ready, onClick: confirm, children: t('重启进入 Windows', 'Restart into Windows') }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { disabled: busy, onClick: () => void refresh(), children: t('刷新启动状态', 'Refresh boot status') }) }), message && SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { role: "status", "aria-live": "polite", style: { overflowWrap: 'anywhere' }, children: message }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: t('仅影响下一次启动，之后按原默认顺序启动。', 'Only affects the next boot. Later boots follow your default order.') })] });
}
var index = definePlugin(() => ({
    name: 'Restart into Windows',
    titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: t('重启进入 Windows', 'Restart into Windows') }),
    content: SP_JSX.jsx(Content, {}),
    icon: SP_JSX.jsx("svg", { width: "1em", height: "1em", style: { width: '1em', height: '1em', display: 'block' }, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true", children: SP_JSX.jsx("path", { d: "M20 7v5h-5M20 12a8 8 0 1 0-2 6M20 12l-4-4" }) }),
    onDismount() { },
}));

export { index as default };
