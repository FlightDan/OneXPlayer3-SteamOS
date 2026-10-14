import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, showModal, staticClasses } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useRef, useState } from 'react';

type Status = { ready: boolean; reason: string; target: string | null };
type Reply<T> = { ok: boolean; data?: T; error?: string };
const status = callable<[], Reply<Status>>('status');
const reboot = callable<[string, boolean], Reply<{ reboot_requested: boolean }>>('reboot');
const t = (zh: string, en: string) => /^(zh|schinese|tchinese)/i.test(
  document.documentElement.lang || navigator.language) ? zh : en;
function unwrap<T>(reply: Reply<T>): T {
  if (!reply.ok || reply.data === undefined) throw new Error(reply.error || t('操作失败', 'Operation failed'));
  return reply.data;
}

function Content() {
  const [info, setInfo] = useState<Status | null>(null);
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
      const result = unwrap(await status());
      if (mounted.current) setInfo(result);
    });
  }
  function confirm() {
    if (lock.current || confirming.current || !info?.ready || !info.target) return;
    confirming.current = true;
    const target = info.target;
    showModal(<ConfirmModal
      bDestructiveWarning
      strTitle={t('重启进入 Windows？', 'Restart into Windows?')}
      strDescription={t('将关闭当前会话。请先保存游戏和文件。仅下一次启动进入 Windows。',
        'Your session will close. Save games and files first. Only the next boot will enter Windows.')}
      strOKButtonText={t('重启', 'Restart')}
      strCancelButtonText={t('取消', 'Cancel')}
      onOK={() => void task(async () => {
        unwrap(await reboot(target, true));
        requested.current = true;
        if (mounted.current) setMessage(t('已请求重启，正在进入 Windows…', 'Restart requested. Starting Windows…'));
      })}
    />, undefined, { fnOnClose: () => { confirming.current = false; } });
  }
  return <PanelSection title={t('系统切换', 'Switch system')}>
    <PanelSectionRow><div role="status" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>
      {busy ? t('正在处理…', 'Working…') : info?.ready
        ? t('Windows 启动项已就绪', 'Windows boot entry is ready')
        : info?.reason || t('请刷新启动状态', 'Refresh the boot status')}
    </div></PanelSectionRow>
    <PanelSectionRow><ButtonItem disabled={busy || !info?.ready} onClick={confirm}>
      {t('重启进入 Windows', 'Restart into Windows')}
    </ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem disabled={busy} onClick={() => void refresh()}>
      {t('刷新启动状态', 'Refresh boot status')}
    </ButtonItem></PanelSectionRow>
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
