import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const slots = [], effects = [], dialogs = [], calls = [];
let cursor = 0, ready = true, managerReady = true, rpcError = '', bootError = '';
const hook = init => {
  const index = cursor++;
  if (!(index in slots)) slots[index] = init;
  return [slots[index], value => { slots[index] = value; }];
};
const jsx = (type, props) => ({ type, props });
const context = vm.createContext({
  console, document: { documentElement: { lang: 'zh-CN' } }, navigator: { language: 'en-US' },
  window: { __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
    connect: () => ({ _version: 2, callable: name => async (...args) => {
      calls.push([name, ...args]);
      if (name === 'status') return rpcError ? { ok: false, error: rpcError } : {
        ok: true, data: { ready, target: ready ? '000A' : null, reason: ready ? '' : '未找到 Windows 启动项。' },
      };
      if (name === 'manager_status') return {
        ok: true, data: { ready: managerReady, target: managerReady ? '6000' : null,
          reason: managerReady ? '' : '未找到 SteamOS 启动管理器入口。' },
      };
      return bootError ? { ok: false, error: bootError } : { ok: true, data: { reboot_requested: true } };
    } }),
  } },
  SP_JSX: { jsx, jsxs: jsx },
  SP_REACT: { useState: hook, useRef: init => hook({ current: init })[0], useEffect: fn => {
    const index = cursor++; if (!(index in slots)) { slots[index] = true; effects.push(fn); }
  } },
  DFL: { staticClasses: { Title: 'title' }, PanelSection: 'section', PanelSectionRow: 'row',
    ButtonItem: 'button', ConfirmModal: 'confirm', showModal: (node, _parent, options) => dialogs.push({ node, options }) },
});
const source = fs.readFileSync(new URL('dist/index.js', import.meta.url), 'utf8')
  .replace('export { index as default };', 'globalThis.testAPI={index,Content};');
vm.runInContext(source, context);
assert.ok(context.testAPI, 'Compiled plugin entry was loaded');
const installedPlugin = context.testAPI.index();
assert.equal(installedPlugin.icon.props.width, '1em');
assert.equal(installedPlugin.icon.props.height, '1em');
assert.equal(installedPlugin.icon.props.style.width, '1em');
assert.equal(installedPlugin.icon.props.style.height, '1em');
const render = () => { cursor = 0; return context.testAPI.Content(); };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
const button = label => nodes(render()).find(node => node.type === 'button' && node.props.children === label)?.props;
const content = () => JSON.stringify(render());
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
render(); for (const effect of effects) effect(); await settle();
assert.deepEqual(calls, [['status'], ['manager_status']], 'Mount only reads both statuses');
assert.equal(button('重启进入 Windows').disabled, false, 'Steam page language takes precedence');
button('重启进入 Windows').onClick(); button('重启进入 Windows').onClick();
assert.equal(dialogs.length, 1, 'Double click opens only one confirmation');
assert.equal(calls.length, 2, 'Opening a dialog never reboots');
dialogs[0].options.fnOnClose();
assert.equal(calls.length, 2, 'Cancellation never reboots');
button('重启到启动管理器').onClick();
assert.equal(dialogs.at(-1).node.props.strTitle, '重启到启动管理器？');
dialogs.at(-1).options.fnOnClose();
assert.equal(calls.length, 2, 'Cancelling boot manager never reboots');
managerReady = false; button('刷新启动状态').onClick(); await settle();
assert.equal(button('重启到启动管理器').disabled, true);
assert.equal(button('重启进入 Windows').disabled, false);
assert.match(content(), /未找到 SteamOS 启动管理器/);
managerReady = true;
ready = false; button('刷新启动状态').onClick(); await settle();
assert.equal(button('重启进入 Windows').disabled, true); assert.match(content(), /未找到 Windows/);
assert.equal(button('重启到启动管理器').disabled, false, 'Missing Windows does not disable boot manager');
ready = true; rpcError = 'UEFI read failed'; button('刷新启动状态').onClick(); await settle();
assert.equal(button('重启进入 Windows').disabled, true); assert.match(content(), /UEFI read failed/);
rpcError = ''; button('刷新启动状态').onClick(); await settle();
bootError = 'BootNext write failed'; button('重启进入 Windows').onClick();
dialogs.at(-1).node.props.onOK(); dialogs.at(-1).node.props.onOK(); await settle();
assert.equal(calls.filter(call => call[0] === 'reboot').length, 1);
assert.match(content(), /BootNext write failed/); assert.equal(button('刷新启动状态').disabled, false);
dialogs.at(-1).options.fnOnClose();
bootError = ''; button('重启进入 Windows').onClick(); dialogs.at(-1).node.props.onOK(); await settle();
assert.deepEqual(calls.at(-1), ['reboot', '000A', true]);
assert.match(content(), /已请求重启/); assert.equal(button('重启进入 Windows').disabled, true);
assert.equal(button('刷新启动状态').disabled, true, 'Controls stay disabled after reboot was accepted');
assert.equal(button('重启到启动管理器').disabled, true);
context.document.documentElement.lang = 'en';
assert.ok(button('Restart into Windows'));
assert.ok(button('Restart into boot manager'));
slots.length = effects.length = dialogs.length = calls.length = 0;
context.document.documentElement.lang = 'zh-CN';
render(); for (const effect of effects) effect(); await settle();
button('重启到启动管理器').onClick(); button('重启进入 Windows').onClick();
assert.equal(dialogs.length, 1, 'Only one destination can be confirmed at a time');
dialogs[0].node.props.onOK(); dialogs[0].node.props.onOK(); await settle();
assert.deepEqual(calls.filter(call => call[0].startsWith('reboot')), [['reboot_manager', '6000', true]]);
assert.match(content(), /正在进入启动管理器/);
assert.equal(button('重启进入 Windows').disabled, true);
assert.equal(button('重启到启动管理器').disabled, true);
assert.equal(button('刷新启动状态').disabled, true);
console.log('WINDOWS_REBOOT_UI=passed; both destinations, read-only mount, bilingual controls, confirmation/cancel, independent availability, duplicate requests, accepted reboot state');
