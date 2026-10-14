import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, showModal, staticClasses } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useRef, useState } from 'react';

type Status = { ready: boolean; reason: string; target: string | null };
type Reply<T> = { ok: boolean; data?: T; error?: string };
const status = callable<[], Reply<Status>>('status');
const reboot = callable<[string, boolean], Reply<{ reboot_requested: boolean }>>('reboot');
const managerStatus = callable<[], Reply<Status>>('manager_status');
const rebootManager = callable<[string, boolean], Reply<{ reboot_requested: boolean }>>('reboot_manager');
const t = (zh: string, en: string) => /^(zh|schinese|tchinese)/i.test(
  document.documentElement.lang || navigator.language) ? zh : en;
function unwrap<T>(reply: Reply<T>): T {
  if (!reply.ok || reply.data === undefined) throw new Error(reply.error || t('操作失败', 'Operation failed'));
  return reply.data;
}

function Content() {
  const [info, setInfo] = useState<Status | null>(null);
  const [managerInfo, setManagerInfo] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const lock = useRef(false);
  const confirming = useRef(false);
  const requested = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; }; }, []);
  async function task(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage('');
    try { await action(); }
    catch (error) { if (mounted.current) setMessage(error instanceof Error ? error.message : String(error)); }
    finally { lock.current = requested.current; if (mounted.current) setBusy(requested.current); }
  }
  async function refresh() {
    await task(async () => {
      setInfo(null);
      setManagerInfo(null);
      const [windowsReply, managerReply] = await Promise.all([status(), managerStatus()]);
      if (mounted.current) {
        setInfo(windowsReply.ok ? unwrap(windowsReply) : {
          ready: false, target: null, reason: windowsReply.error || t('操作失败', 'Operation failed'),
        });
        setManagerInfo(managerReply.ok ? unwrap(managerReply) : {
          ready: false, target: null, reason: managerReply.error || t('操作失败', 'Operation failed'),
        });
      }
    });
  }
  function confirm(destination: 'windows' | 'manager') {
    const selected = destination === 'windows' ? info : managerInfo;
    if (lock.current || confirming.current || !selected?.ready || !selected.target) return;
    confirming.current = true;
    const target = selected.target;
    showModal(<ConfirmModal
      bDestructiveWarning
      strTitle={destination === 'windows' ? t('重启进入 Windows？', 'Restart into Windows?')
        : t('重启到启动管理器？', 'Restart into boot manager?')}
      strDescription={destination === 'windows'
        ? t('将关闭当前会话。请先保存游戏和文件。仅下一次启动进入 Windows。',
          'Your session will close. Save games and files first. Only the next boot will enter Windows.')
        : t('将关闭当前会话。请先保存游戏和文件。下一次启动进入 SteamOS 启动项对应的启动管理器。',
          'Your session will close. Save games and files first. The next boot will use the boot manager at the SteamOS entry.')}
      strOKButtonText={t('重启', 'Restart')}
      strCancelButtonText={t('取消', 'Cancel')}
      onOK={() => void task(async () => {
        unwrap(await (destination === 'windows' ? reboot(target, true) : rebootManager(target, true)));
        requested.current = true;
        if (mounted.current) setMessage(destination === 'windows'
          ? t('已请求重启，正在进入 Windows…', 'Restart requested. Starting Windows…')
          : t('已请求重启，正在进入启动管理器…', 'Restart requested. Starting boot manager…'));
      })}
    />, undefined, { fnOnClose: () => { confirming.current = false; } });
  }
  return <PanelSection title={t('系统切换', 'Switch system')}>
    <PanelSectionRow><div role="status" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>
      {busy ? t('正在处理…', 'Working…') : info?.ready
        ? t('Windows 启动项已就绪', 'Windows boot entry is ready')
        : info?.reason || t('请刷新启动状态', 'Refresh the boot status')}
    </div></PanelSectionRow>
    <ButtonItem layout="below" disabled={busy || !info?.ready} onClick={() => confirm('windows')}>
      {t('重启进入 Windows', 'Restart into Windows')}
    </ButtonItem>
    <PanelSectionRow><div role="status" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>
      {busy ? t('正在处理…', 'Working…') : managerInfo?.ready
        ? t('SteamOS 启动管理器入口已就绪', 'SteamOS boot-manager entry is ready')
        : managerInfo?.reason || t('请刷新启动状态', 'Refresh the boot status')}
    </div></PanelSectionRow>
    <ButtonItem layout="below" disabled={busy || !managerInfo?.ready} onClick={() => confirm('manager')}>
      {t('重启到启动管理器', 'Restart into boot manager')}
    </ButtonItem>
    <ButtonItem layout="below" disabled={busy} onClick={() => void refresh()}>
      {t('刷新启动状态', 'Refresh boot status')}
    </ButtonItem>
    {message && <PanelSectionRow><div role="status" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>{message}</div></PanelSectionRow>}
    <PanelSectionRow>{t('仅影响下一次启动，之后按原默认顺序启动。', 'Only affects the next boot. Later boots follow your default order.')}</PanelSectionRow>
  </PanelSection>;
}

export default definePlugin(() => ({
  name: 'Restart into Windows',
  titleView: <div className={staticClasses.Title}>{t('重启进入 Windows', 'Restart into Windows')}</div>,
  content: <Content />,
  icon: <svg width="1em" height="1em" style={{ width: '1em', height: '1em', display: 'block' }}
    viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M20 7v5h-5M20 12a8 8 0 1 0-2 6M20 12l-4-4" />
  </svg>,
  onDismount() {},
}));
