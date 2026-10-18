import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

let current = '', writes = 0, unregisters = 0, cursor = 0, enableCalls = 0, rejectEnable = false;
const slots = [], effects = [], notifications = [], cleanups = [], timers = new Map();
const progressTimeouts = new Map();
let savedSelection=null, timeoutId=0, inspectCount=0;
let timerId=0;
let operation={schema:1,instance_id:'backend-1',operation_id:null,appid:null,kind:'',version:'',phase:'completed',running:false,downloaded_bytes:0,total_bytes:null,error:null,revision:0};
let runtime={ready:false,available:true,version:'fixture',size_bytes:195433378,host_issue:'',error:'',availability_message:''};
const info = {appid:42,name:'Demo',executables:['game.exe','Launcher.exe'],libraries:[{path:'libxess.dll'}],optis:[],
  runtime_ready:true,prefix_ready:true,external_managed:false,state:null,
  automatic:{executable:'game.exe',route:'native',reason:'',candidates:['game.exe']}};
const copy = value => JSON.parse(JSON.stringify(value));
const methods = {
  runtime_status: async () => ({ok:true,data:copy(runtime)}),
  operation_progress: async () => ({ok:true,data:copy(operation)}),
  inventory: async () => ({ok:true,data:[{appid:42,name:'Demo'}]}),
  inspect_game: async id => {inspectCount++;return {ok:true,data:{...copy(info),appid:id}};},
  enable: async (_id,exe,route,before) => {
    enableCalls++; assert.equal(exe,'game.exe'); assert.equal(route,'native');
    if(rejectEnable)return {ok:false,error:'游戏仍在运行，请退出后重试。'};
    info.state={status:'pending_launch',launch:'/test/launch %command%',old_launch:before};
    return {ok:true,data:copy(info.state)};
  },
  confirm_launch: async () => {
    info.state.status=info.state.status==='pending_restore_launch'?'restored':'active';
    return {ok:true,data:copy(info.state)};
  },
  restore: async () => {info.state.status='pending_restore_launch';return {ok:true,data:copy(info.state)};},
};
const hook = init => {
  const n=cursor++;if(!(n in slots))slots[n]=init;
  return [slots[n],value=>{slots[n]=value;}];
};
const jsx = (type,props) => ({type,props});
const context = vm.createContext({
  console,queueMicrotask,
  setTimeout:(fn,ms,...args)=>{if(ms===5000){const id='progress-'+(++timeoutId);progressTimeouts.set(id,fn);return id;}return setTimeout(fn,ms,...args);},
  clearTimeout:id=>{if(progressTimeouts.has(id))progressTimeouts.delete(id);else clearTimeout(id);},
  setInterval:fn=>{timers.set(++timerId,fn);return timerId;},clearInterval:id=>timers.delete(id),
  localStorage:{getItem:()=>savedSelection,setItem:(_key,value)=>{savedSelection=value;}},
  window:{__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit:{connect:()=>({
    _version:2,callable:name=>(...args)=>methods[name](...args),toaster:{toast:value=>notifications.push(value)},
  })}},
  SP_JSX:{jsx,jsxs:jsx,Fragment:'Fragment'},
  SP_REACT:{useState:hook,useRef:init=>hook({current:init})[0],useEffect:fn=>{
    const n=cursor++;if(!(n in slots)){slots[n]=true;effects.push(fn);}
  },useSyncExternalStore:(subscribe,getSnapshot)=>{
    const [value,setValue]=hook(getSnapshot());
    const n=cursor++;if(!(n in slots)){slots[n]=true;effects.push(()=>{
      setValue(getSnapshot());return subscribe(()=>setValue(getSnapshot()));
    });}
    return value;
  }},
  DFL:{staticClasses:{Title:'title'},PanelSection:'section',PanelSectionRow:'row',ButtonItem:'button',DropdownItem:'select',SliderField:'slider',ToggleField:'toggle'},
  SteamClient:{Apps:{
    RegisterForAppDetails:(id,callback)=>{queueMicrotask(()=>callback(id,{strLaunchOptions:current}));return {unregister:()=>unregisters++};},
    SetAppLaunchOptions:(_id,value)=>{current=value;writes++;},
  }},
});
const source=fs.readFileSync(new URL('dist/index.js',import.meta.url),'utf8')
  .replace('export { index as default };','globalThis.testAPI={index,readLaunch,writeLaunch,Content};');
vm.runInContext(source,context);
const api=context.testAPI;
function render(){cursor=0;return api.Content();}
function nodes(node){if(!node||typeof node!=='object')return [];if(Array.isArray(node))return node.flatMap(nodes);return [node,...nodes(node.props?.children)];}
function toggle(){return nodes(render()).find(n=>n.type==='toggle').props;}
function textOf(node){if(node==null)return '';if(typeof node!=='object')return String(node);if(Array.isArray(node))return node.map(textOf).join('');return node.type==='br'?'\n':textOf(node.props?.children);}
async function settle(){for(let n=0;n<50;n++){await new Promise(r=>setTimeout(r,20));if(!slots[5])return;}throw new Error('UI stayed busy');}
assert.equal(api.index().name,'Opti2XMX');
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.equal(toggle().disabled,false);assert.equal(toggle().checked,false);
assert.equal(nodes(render()).filter(n=>n.type==='select').length,1,'normal flow only asks for game');
toggle().onChange(true);
assert.equal(toggle().disabled,true);
assert.ok(nodes(render()).some(n=>n.props?.role==='status'&&textOf(n).includes('正在开启 XMX')),'busy status must remain visible with loaded game info');
// Double activation is blocked before React can repaint.
toggle().onChange(true);await settle();
assert.equal(enableCalls,1);assert.equal(toggle().checked,true);assert.equal(writes,1);
assert.equal(current,'/test/launch %command%');
toggle().onChange(false);assert.equal(toggle().disabled,true);await settle();
assert.equal(toggle().checked,false);assert.equal(current,'');assert.equal(writes,2);
rejectEnable=true;toggle().onChange(true);await settle();
assert.equal(toggle().checked,false);assert.match(notifications.at(-1).body,/游戏仍在运行/);
assert.ok(nodes(render()).some(n=>n.props?.role==='alert'&&textOf(n).includes('游戏仍在运行')),'error must remain visible beyond its toast');
assert.ok(notifications.some(n=>n.title.includes('未完成')));
current='external %command%';
await assert.rejects(()=>api.writeLaunch(42,'overwrite','stale'),/刚被其他工具修改/);
assert.equal(writes,2);assert.ok(unregisters>=8);
console.log('PASS: automatic selection; toggle on/off; immediate progress; double-click guard; visible errors/toasts; Steam readback and conflict protection.');

current='';rejectEnable=false;
info.opti={managed:false,installed:false,version:'',status:'',rollback:false,settings:{sr:'xess',fg:'native',fg_input:'upscaler',spoof:'real'}};
let installCount=0;
let releaseDownload;
methods.opti_install=async(id,exe,before,version,source)=>{
  assert.equal(id,42);assert.equal(exe,'game.exe');assert.equal(version,'0.9.4');assert.equal(source,'github');installCount++;
  operation={...operation,operation_id:'download-1',appid:42,kind:'opti_install',version,phase:'downloading',running:true,downloaded_bytes:1048576,total_bytes:2097152,revision:1};
  await new Promise(resolve=>{releaseDownload=resolve;});
  operation={...operation,phase:'awaiting-launch',running:false,revision:2};
  info.opti={...info.opti,managed:true,installed:true,version:'0.9.4',status:'pending_launch',rollback:true,
    pending:{expected:before,target:'/opti/launch %command%',kind:'install'}};
  return {ok:true,data:copy(info.opti.pending)};
};
methods.opti_confirm=async(_id,actual)=>{
  assert.equal(actual,info.opti.pending.target);info.opti.status='active';info.opti.pending=null;
  return {ok:true,data:true};
};
function button(label){return nodes(render()).find(n=>n.type==='button'&&n.props.children===label)?.props;}
info.runtime_ready=false;info.automatic.reason='XMX 运行组件未就绪。';
button('刷新').onClick();await settle();
assert.equal(toggle().disabled,true);assert.equal(button('安装 Opti 0.9.4').disabled,false,'Opti install stays available without the XMX runtime');
const mainNodes=nodes(render());
assert.ok(mainNodes.findIndex(n=>n.type==='select'&&n.props.label==='游戏') < mainNodes.findIndex(n=>n.type==='button'&&n.props.children==='下载并配置 XMX 运行环境'));
assert.ok(mainNodes.findIndex(n=>n.type==='button'&&n.props.children==='下载并配置 XMX 运行环境') < mainNodes.findIndex(n=>n.type==='button'&&n.props.children==='安装 Opti 0.9.4'));
button('安装 Opti 0.9.4').onClick();await new Promise(resolve=>setTimeout(resolve,20));
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.match(textOf(render()),/正在下载 Opti/);assert.match(textOf(render()),/1\.0 MiB.*2\.0 MiB.*50%/);
assert.equal(button('安装 Opti 0.9.4').disabled,true);
operation={...operation,total_bytes:null,revision:2};
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.doesNotMatch(textOf(render()),/50%/,'unknown total must not invent a percentage');
releaseDownload();await settle();
operation={...operation,running:false,phase:'completed',revision:3};for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(installCount,1);assert.equal(current,'/opti/launch %command%');assert.ok(button('打开 Opti 面板'));
info.runtime_ready=true;info.automatic.reason='';
button('高级设置').onClick();
assert.ok(button('卸载 Opti'));assert.ok(button('回退上次操作'));
const version=nodes(render()).find(n=>n.type==='select'&&n.props.label==='Opti 版本');
assert.equal(version.props.selectedOption,'0.9.4');
console.log('PASS: official 0.9.4 install action, Steam confirmation, panel button, advanced lifecycle controls.');

info.opti.injection_enabled=true;
methods.opti_toggle=async(id,want,before)=>{
  assert.equal(id,42);assert.equal(before,current);
  info.opti.injection_enabled=want;
  info.opti.pending={expected:before,target:before,kind:'toggle'};
  return {ok:true,data:copy(info.opti.pending)};
};
button('刷新').onClick();await settle();
const optiToggle=()=>nodes(render()).find(n=>n.type==='toggle'&&n.props.label==='Opti 注入').props;
optiToggle().onChange(false);await settle();
assert.equal(optiToggle().checked,false);assert.equal(button('打开 Opti 面板'),undefined);
assert.equal(current,'/opti/launch %command%');
optiToggle().onChange(true);await settle();
assert.equal(optiToggle().checked,true);assert.ok(button('打开 Opti 面板'));
console.log('PASS: independent Opti injection toggle and hidden panel when disabled.');

context.document={documentElement:{lang:'en'}};
context.navigator={language:'zh-CN'};
const englishNodes=nodes(render());
const englishXmx=englishNodes.find(n=>n.props?.label==='XMX acceleration');
assert.ok(englishXmx);
assert.equal(textOf(englishXmx.props.description),'Intel only. Exit the game before changing.');
const englishOpti=englishNodes.find(n=>n.props?.label==='Opti injection');
assert.equal(textOf(englishOpti.props.description),'Turn off for native XeSS Frame Generation.');
assert.ok(button('Open Opti overlay'));assert.ok(button('Uninstall Opti'));
methods.opti_toggle=async()=>({ok:false,error:'游戏仍在运行。请从 Steam 退出游戏，再操作 XMX 开关。'});
englishOpti.props.onChange(false);await settle();
assert.match(notifications.at(-1).body,/game is still running/);
assert.equal(nodes(render()).find(n=>n.props?.label==='Opti injection').props.checked,true);
context.document.documentElement.lang='zh-cn';
assert.equal(textOf(toggle().description),'仅限 Intel；更改前请退出游戏。');
assert.equal(textOf(optiToggle().description),'原生 XeSS 帧生成请关闭。');
console.log('PASS: Steam language takes precedence; bilingual descriptions, controls and running-game error.');
// The slider switches between native game control and XeFG override.
const multiplier=()=>nodes(render()).find(n=>n.type==='slider'&&n.props.label.startsWith('插帧倍率'))?.props;
assert.equal(multiplier().value,0);
nodes(render()).find(n=>n.type==='select'&&n.props.label==='帧生成输出').props.onChange({data:'xefg'});
assert.equal(multiplier().value,1);
assert.equal(multiplier().min,0);assert.equal(multiplier().max,3);assert.equal(multiplier().step,1);
assert.equal(multiplier().notchLabels.map(x=>x.label).join(','),'原生,2×,3×,4×');
multiplier().onChange(3);
let settingsCalls=0,restoreSettingsCalls=0;
const launchBeforeSettings=current;
methods.opti_settings=async(id,value,reset)=>{
  settingsCalls++;assert.equal(id,42);assert.equal(reset,false);assert.equal(value.fg,settingsCalls===1?'xefg':'native');
  assert.equal(value.fg_multiplier,settingsCalls===1?'4':'native');
  info.opti.settings=copy(value);info.opti.settings_rollback=true;return {ok:true,data:true};
};
methods.opti_restore_settings=async(id)=>{
  restoreSettingsCalls++;assert.equal(id,42);info.opti.settings={sr:'xess',fg:'native',fg_input:'upscaler',spoof:'real',fg_multiplier:'2'};
  info.opti.settings_rollback=false;info.opti.settings_recovery=false;return {ok:true,data:true};
};
button('保存设置').onClick();await settle();
assert.equal(settingsCalls,1);assert.equal(multiplier().value,3);assert.ok(button('撤销上次设置'));
multiplier().onChange(0);button('保存设置').onClick();await settle();
assert.equal(settingsCalls,2);assert.equal(multiplier().value,0,'native control persists after saving and reloading');
context.document.documentElement.lang='en';
assert.ok(nodes(render()).some(n=>n.props?.label==='FG multiplier · Game controlled'));
assert.equal(nodes(render()).find(n=>n.type==='slider').props.notchLabels[0].label,'Native');
assert.ok(button('Undo last settings change'));
context.document.documentElement.lang='zh-cn';
button('撤销上次设置').onClick();await settle();assert.equal(restoreSettingsCalls,1);assert.equal(multiplier().value,0);
assert.equal(current,launchBeforeSettings);
info.opti.settings_recovery=true;button('刷新').onClick();await settle();
assert.equal(multiplier().disabled,true);
assert.equal(button('保存设置').disabled,true);assert.equal(button('恢复默认').disabled,true);assert.ok(button('恢复中断的设置'));
assert.equal(toggle().disabled,true);assert.equal(optiToggle().disabled,true);assert.equal(button('安装所选版本').disabled,true);
assert.equal(button('恢复中断的设置').disabled,false);
button('恢复中断的设置').onClick();await settle();assert.equal(restoreSettingsCalls,2);
runtime.ready=true;button('刷新').onClick();await settle();
assert.equal(button('XMX 运行环境已就绪'),undefined,'ready state is not a separate button');
assert.equal(button('收起高级设置').description,'Opti 0.9.4 · XMX 运行环境已就绪');
runtime.ready=false;
console.log('PASS: game-controlled/2x/3x/4x slider, bilingual copy, persistence, independent undo/recovery and unchanged launch options.');
// Reopening attaches to a backend operation without starting a second install.
for(const cleanup of cleanups)cleanup();cleanups.length=0;slots.length=0;effects.length=0;
operation={...operation,operation_id:'download-2',phase:'downloading',running:true,downloaded_bytes:3145728,total_bytes:null,revision:10};
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.match(textOf(render()),/3\.0 MiB/);assert.equal(optiToggle().disabled,true);assert.equal(installCount,1);
// Older responses cannot replace the active operation or attach another game's progress.
methods.operation_progress=async()=>({ok:true,data:{...operation,operation_id:'old',appid:99,downloaded_bytes:99*1048576,revision:9}});
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.doesNotMatch(textOf(render()),/99\.0 MiB/);assert.match(textOf(render()),/3\.0 MiB/);
methods.operation_progress=async()=>({ok:true,data:{...operation,running:false,phase:'failed',error:'fixture download failed',revision:11}});
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.ok(nodes(render()).some(n=>n.props?.role==='alert'&&textOf(n).includes('fixture download failed')));
assert.equal(optiToggle().disabled,false);
// A backend-only restart can return revision zero and still refresh persisted state.
const beforeRestart=inspectCount;
operation={...operation,instance_id:'backend-2',operation_id:null,appid:null,running:false,phase:'completed',revision:0};
methods.operation_progress=async()=>({ok:true,data:copy(operation)});
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.ok(inspectCount>beforeRestart,'backend epoch change must reload journal-backed game info');
// A terminal transition arriving during an existing load must be refreshed after that load releases its lock.
operation={...operation,operation_id:'pending-confirm',appid:42,phase:'awaiting-launch',revision:1};
info.opti.pending={expected:current,target:current,kind:'install'};info.opti.status='pending_launch';
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
const inspectOriginal=methods.inspect_game;
let releaseInspect;
methods.inspect_game=async id=>{const stale=await inspectOriginal(id);await new Promise(resolve=>{releaseInspect=resolve;});return stale;};
button('刷新').onClick();await new Promise(resolve=>setTimeout(resolve,20));
info.opti.pending=null;info.opti.status='active';
operation={...operation,phase:'completed',revision:2};
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
methods.inspect_game=inspectOriginal;releaseInspect();await settle();
assert.ok(button('完成 Opti 启动设置'),'fixture loads stale pending info before deferred refresh');
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(button('完成 Opti 启动设置'),undefined,'completed confirmation must refresh after local lock releases');
// A failed terminal refresh is retried on the next snapshot without repeating a mutation.
operation={...operation,phase:'awaiting-launch',revision:3};
info.opti.pending={expected:current,target:current,kind:'install'};info.opti.status='pending_launch';
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
button('刷新').onClick();await settle();
assert.ok(button('完成 Opti 启动设置'));
info.opti.pending=null;info.opti.status='active';
let refreshFailures=1;
methods.inspect_game=async id=>{if(refreshFailures-- > 0)throw new Error('temporary inspect failure');return inspectOriginal(id);};
operation={...operation,phase:'completed',revision:4};
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.ok(button('完成 Opti 启动设置'),'failed read retains pending UI until a successful refresh');
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(button('完成 Opti 启动设置'),undefined,'terminal refresh retries after a transient read failure');
methods.inspect_game=inspectOriginal;
// A stuck read-only RPC times out, retains the last running snapshot, and cannot apply a late reply.
operation={...operation,operation_id:'reconnect',phase:'downloading',running:true,downloaded_bytes:4194304,revision:5};
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
let lateReply;
methods.operation_progress=()=>new Promise(resolve=>{lateReply=resolve;});
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(progressTimeouts.size,1);
for(const timeout of [...progressTimeouts.values()])timeout();await new Promise(resolve=>setTimeout(resolve,20));
assert.match(textOf(render()),/进度连接暂不可用/);assert.match(textOf(render()),/4\.0 MiB/);assert.equal(optiToggle().disabled,true);
operation={...operation,instance_id:'backend-3',operation_id:null,appid:null,running:false,phase:'completed',revision:0};
methods.operation_progress=async()=>({ok:true,data:copy(operation)});
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.doesNotMatch(textOf(render()),/进度连接暂不可用/);assert.equal(optiToggle().disabled,false);
lateReply({ok:true,data:{...operation,instance_id:'backend-2',operation_id:'late',appid:42,running:true,phase:'downloading',downloaded_bytes:99*1048576,revision:99}});
await new Promise(resolve=>setTimeout(resolve,20));assert.doesNotMatch(textOf(render()),/99\.0 MiB/);assert.equal(optiToggle().disabled,false);
for(const cleanup of cleanups)cleanup();
console.log('PASS: byte/known-total progress, unknown-total fallback, visible busy/error, remount attachment, stale-poll refusal and failure unlock.');
// Completed historical operations do not override the user's saved game selection.
cleanups.length=0;slots.length=0;effects.length=0;savedSelection='43';
methods.inventory=async()=>({ok:true,data:[{appid:42,name:'Demo'},{appid:43,name:'Saved'}]});
operation={...operation,operation_id:'completed-old-game',appid:42,phase:'completed',revision:1};
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.equal(nodes(render()).find(n=>n.type==='select'&&n.props.label==='游戏').props.selectedOption,43);
for(const cleanup of cleanups)cleanup();
assert.equal(progressTimeouts.size,0);
console.log('PASS: backend epoch reconnect, deferred confirmation refresh, hung snapshot timeout/late-reply refusal and saved-game selection.');

// The global runtime button works without a game and never starts on mount.
cleanups.length=0;slots.length=0;effects.length=0;let runtimeCalls=0, finishRuntime;
methods.inventory=async()=>({ok:true,data:[]});
methods.runtime_install=async()=>{
  runtimeCalls++;
  operation={...operation,kind:'runtime_install',operation_id:'runtime-1',appid:null,phase:'downloading',running:true,downloaded_bytes:1048576,total_bytes:195433378,revision:2};
  await new Promise(resolve=>{finishRuntime=resolve;});
  runtime.ready=true;operation={...operation,running:false,phase:'completed',revision:3};
  return {ok:true,data:copy(runtime)};
};
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.equal(runtimeCalls,0);assert.match(textOf(button('下载并配置 XMX 运行环境').description),/下载后校验/);
button('下载并配置 XMX 运行环境').onClick();
button('下载并配置 XMX 运行环境').onClick();await new Promise(resolve=>setTimeout(resolve,20));
for(const timer of timers.values())timer();await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(runtimeCalls,1);assert.match(textOf(render()),/正在下载 XMX 运行环境/);assert.match(textOf(render()),/1\.0 MiB/);
finishRuntime();await settle();assert.equal(button('XMX 运行环境已就绪'),undefined);
assert.equal(button('下载并配置 XMX 运行环境'),undefined);
assert.ok(nodes(render()).some(n=>n.props?.role==='status'&&textOf(n)==='XMX 运行环境已就绪'));
assert.match(textOf(render()),/XMX 运行环境已配置/);
for(const cleanup of cleanups)cleanup();cleanups.length=0;slots.length=0;effects.length=0;
runtime={...runtime,ready:false,available:false,availability_message:'Pinned runtime release not published'};
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.equal(button('下载并配置 XMX 运行环境').disabled,true);assert.match(textOf(button('下载并配置 XMX 运行环境').description),/not published/);
for(const cleanup of cleanups)cleanup();
console.log('PASS: global explicit runtime action, no automatic download, size/progress/outcome, duplicate guard and unpublished-release state.');

// Real 0.2.5 reports: Control without a prefix; Death Stranding with leftover INI.
cleanups.length=0;slots.length=0;effects.length=0;savedSelection='42';
methods.inventory=async()=>({ok:true,data:[{appid:42,name:'Control'}]});
info.state=null;info.prefix_ready=false;
info.opti={managed:false,installed:false,incomplete:false,injection_enabled:false,version:'',status:'',rollback:false,settings:{sr:'xess',fg:'native',fg_input:'upscaler',spoof:'real'}};
info.automatic={executable:'',route:'native',reason:'请先从 Steam 用 Proton 启动游戏一次，退出后点击刷新。',candidates:['Control.exe','Control_DX11.exe','Control_DX12.exe']};
info.executables=[...info.automatic.candidates];
render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();
assert.match(textOf(toggle().description),/Proton/);
assert.equal(button('安装 Opti 0.9.4').disabled,true);
assert.match(textOf(button('安装 Opti 0.9.4').description),/Proton/);
let choice=nodes(render()).find(n=>n.props?.label==='确认游戏程序');
assert.ok(nodes(render()).indexOf(choice)<nodes(render()).findIndex(n=>n.props?.label==='XMX 加速'));
choice.props.onChange({data:'Control_DX12.exe'});
assert.equal(button('安装 Opti 0.9.4').disabled,true,'manual EXE cannot bypass missing prefix');
info.prefix_ready=true;info.automatic.reason='尚未发现 XeSS。请先为此游戏安装 OptiScaler 并运行一次，再刷新。';
button('刷新').onClick();await settle();
nodes(render()).find(n=>n.props?.label==='确认游戏程序').props.onChange({data:'Control_DX12.exe'});
assert.equal(button('安装 Opti 0.9.4').disabled,false,'Opti install does not require XeSS');
assert.equal(toggle().disabled,true);assert.match(textOf(toggle().description),/尚未发现 XeSS/);
info.automatic={executable:'ds.exe',route:'opti',reason:'OptiScaler 文件不完整，需要同目录的 dxgi.dll 和 libxess.dll。',candidates:['ds.exe']};
info.executables=['ds.exe'];
info.opti={...info.opti,installed:true,incomplete:true};
button('刷新').onClick();await settle();
assert.equal(button('迁移现有 Opti'),undefined);assert.equal(button('打开 Opti 面板'),undefined);
assert.equal(button('修复安装 Opti 0.9.4').disabled,false);
assert.match(textOf(button('修复安装 Opti 0.9.4').description),/备份现有文件/);
let repairCalls=0;
methods.opti_install=async(id,exe)=>{assert.equal(id,42);assert.equal(exe,'ds.exe');repairCalls++;return {ok:false,error:'fixture repair rejected before mutation'};};
button('修复安装 Opti 0.9.4').onClick();await settle();assert.equal(repairCalls,1);
info.state={status:'failed',old_launch:''};info.automatic.reason='';
button('刷新').onClick();await settle();
assert.equal(button('修复安装 Opti 0.9.4').disabled,false,'failed XMX journal cannot block installation');
assert.equal(toggle().disabled,false);
context.document.documentElement.lang='en';
assert.equal(button('Repair Opti 0.9.4 installation').disabled,false);
assert.match(textOf(button('Repair Opti 0.9.4 installation').description),/Back up existing files/);
for(const cleanup of cleanups)cleanup();
console.log('PASS: Control prerequisites and executable selection, visible XMX reasons, incomplete Death Stranding repair, failed journal and English copy.');

// Native Steam dropdowns unmount Quick Access before invoking their callback.
function clearUI(){for(const cleanup of cleanups)cleanup();cleanups.length=0;slots.length=0;effects.length=0;}
async function mountUI(){render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}await settle();}
const exeChoice=()=>nodes(render()).find(n=>n.props?.label==='确认游戏程序')?.props;
const gameChoice=()=>nodes(render()).find(n=>n.props?.label==='游戏')?.props;
clearUI();context.document.documentElement.lang='zh-cn';savedSelection='42';
methods.inventory=async()=>({ok:true,data:[{appid:42,name:'Control'},{appid:43,name:'Another game'}]});
info.state=null;info.prefix_ready=true;info.executables=['Control.exe','Control_DX11.exe','Control_DX12.exe'];
info.automatic={executable:'',route:'native',reason:'尚未发现 XeSS。请先为此游戏安装 OptiScaler 并运行一次，再刷新。',candidates:[...info.executables]};
info.opti={...info.opti,installed:false,incomplete:false,managed:false,pending:null};
await mountUI();const originalExeMenu=exeChoice();
clearUI();originalExeMenu.onChange({data:'Control_DX12.exe'});await mountUI();
assert.equal(exeChoice().selectedOption,'Control_DX12.exe','native callback after unmount survives remount');
assert.equal(button('安装 Opti 0.9.4').disabled,false);
button('刷新').onClick();await settle();assert.equal(exeChoice().selectedOption,'Control_DX12.exe');
clearUI();await mountUI();originalExeMenu.onChange({data:'Control_DX11.exe'});
assert.equal(exeChoice().selectedOption,'Control_DX11.exe','late old-instance callback notifies the already-mounted instance');
for(const invalid of ['/tmp/evil.exe','../evil.exe','unknown.exe'])originalExeMenu.onChange({data:invalid});
assert.equal(exeChoice().selectedOption,'Control_DX11.exe','arbitrary paths cannot enter selection');
info.executables=['Control.exe','Control_DX12.exe'];info.automatic.candidates=[...info.executables];
button('刷新').onClick();await settle();
assert.equal(exeChoice().selectedOption,'','removed candidate is invalidated');assert.equal(button('安装 Opti 0.9.4').disabled,true);
exeChoice().onChange({data:'Control_DX12.exe'});
let nativeInstallCalls=0;
methods.opti_install=async(id,exe)=>{assert.equal(id,42);assert.equal(exe,'Control_DX12.exe');nativeInstallCalls++;return {ok:false,error:'fixture stopped before mutation'};};
button('安装 Opti 0.9.4').onClick();await settle();assert.equal(nativeInstallCalls,1);
const oldGameMenu=gameChoice();clearUI();oldGameMenu.onChange({data:43});
assert.equal(savedSelection,'43','game selection is saved synchronously before async inspection');
await mountUI();assert.equal(gameChoice().selectedOption,43);assert.equal(exeChoice().selectedOption,'','EXE never leaks across appids');
originalExeMenu.onChange({data:'Control_DX12.exe'});assert.equal(exeChoice().selectedOption,'','late previous-game callback cannot change this game');
clearUI();
console.log('PASS: native-menu unmount/callback/remount, late callback subscription, refresh/invalidation, appid isolation and real selected-EXE RPC.');
