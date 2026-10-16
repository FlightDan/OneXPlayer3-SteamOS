// Execute the actual patched bundle with only Steam/React host APIs stubbed.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(process.argv[2], 'utf8');
assert.equal(source.split('  return index;').length, 2, 'single bundle export');
const timers = new Map();
let nextTimer = 0;
const React = { createContext: () => ({}), createElement: () => ({}) };
const window = { SP_REACT: React };
const context = vm.createContext({
  window, SP_REACT: React, Event, EventTarget, console,
  DFL: { findModuleChild: () => ({}), definePlugin: fn => fn, staticClasses: {} },
  setInterval(fn, period) {
    assert.equal(period, 1000);
    timers.set(++nextTimer, fn);
    return nextTimer;
  },
  clearInterval(id) { timers.delete(id); },
});
// Expose existing closure values for observation; leave all behavior intact.
const { index: mount, Backend, Settings } = vm.runInContext(source.replace(
  '  return index;', '  return { index, Backend, Settings };'), context);
const routes = [];
const plugin = mount({
  routerHook: { addRoute: route => routes.push(route), removeRoute: route => routes.splice(routes.indexOf(route), 1) },
  // Leave startup pending so unrelated backend work cannot run in this fixture.
  callPluginMethod: () => new Promise(() => {}),
});
const states = [];
Backend.eventBus.addEventListener('BatteryStateEvent', event => states.push(event.batteryState));
const tick = () => [...timers.values()].forEach(fn => fn());
assert.equal(timers.size, 1);
assert.deepEqual(routes, ['/flatpak-manager']);

for (let i = 0; i < 100; i++) tick();
assert.equal(states.length, 0, 'missing store remains quiet');
for (const store of [null, {}, { batteryState: null }, { batteryState: {} },
  { batteryState: { eACState: undefined } }, { batteryState: { eACState: NaN } },
  { batteryState: { eACState: '2' } }]) {
  window.SystemPowerStore = store;
  tick();
}
assert.equal(states.length, 0, 'uninitialized state is not a transition');

const battery = { bHasBattery: true, eACState: 1, eBatteryState: 2, flLevel: 0.6 };
const ac = { bHasBattery: true, eACState: 2, eBatteryState: 3, flLevel: 0.6 };
window.SystemPowerStore = { batteryState: battery };
tick();
tick();
assert.equal(states.length, 1, 'late store initializes once');
assert.equal(states[0], battery, 'forward exact Steam state');
window.SystemPowerStore.batteryState = ac;
tick();
assert.equal(states[1], ac, 'AC transition survives');
delete window.SystemPowerStore;
tick();
assert.equal(states.length, 2, 'store disappearance fabricates no transition');
window.SystemPowerStore = { batteryState: ac };
tick();
assert.equal(states.length, 2, 'restored same object retains upstream comparison');
window.SystemPowerStore.batteryState = battery;
tick();
assert.equal(states[2], battery, 'battery transition survives');
const unknown = { bHasBattery: false, eACState: 0 };
window.SystemPowerStore.batteryState = unknown;
tick();
assert.equal(states[3], unknown, 'preserve valid enum zero and no-battery states');

// Exercise the real interval-update listener after normal initialization.
let checks = 0;
Backend.appState.initialized = true;
Backend.getPackageCount = async () => { checks++; return 0; };
Settings.lastCheckTimestamp = new Date(0);
Settings.saveLastCheckTimestamp = async () => {};
window.SystemPowerStore.batteryState = ac;
tick();
await Promise.resolve();
await Promise.resolve();
assert.equal(checks, 1, 'normal automatic update check still runs');

plugin.onDismount();
assert.equal(timers.size, 0, 'actual plugin unmount clears polling');
assert.deepEqual(routes, []);
const count = states.length;
window.SystemPowerStore.batteryState = battery;
tick();
assert.equal(states.length, count, 'no polling after unmount');
console.log('AutoFlatpaks actual bundle: absent/late state, AC transitions, updates, unmount passed');
