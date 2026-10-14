import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

let current = '', writes = 0, unregisters = 0, cursor = 0, enableCalls = 0, rejectEnable = false;
const slots = [], effects = [], notifications = [], cleanups = [], timers = new Map();
const progressTimeouts = new Map();
let savedSelection=null, timeoutId=0, inspectCount=0;
let timerId=0;
let operation={schema:1,instance_id:'backend-1',operation_id:null,appid:null,kind:'',version:'',phase:'completed',running:false,downloaded_bytes:0,total_bytes:null,error:null,revision:0};
const info = {appid:42,name:'Demo',executables:['game.exe','Launcher.exe'],libraries:[{path:'libxess.dll'}],optis:[],
  runtime_ready:true,prefix_ready:true,external_managed:false,state:null,
  automatic:{executable:'game.exe',route:'native',reason:'',candidates:['game.exe']}};
const copy = value => JSON.parse(JSON.stringify(value));
const methods = {
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
  }},
  DFL:{staticClasses:{Title:'title'},PanelSection:'section',PanelSectionRow:'row',ButtonItem:'button',DropdownItem:'select',ToggleField:'toggle'},
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
button('刷新').onClick();await settle();
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
assert.match(textOf(englishXmx.props.description),/Intel devices only/);
assert.match(textOf(englishXmx.props.description),/Close the game before changing this setting/);
const englishOpti=englishNodes.find(n=>n.props?.label==='Opti injection');
assert.match(textOf(englishOpti.props.description),/natively supports XeSS Frame Generation, turn this option off/);
assert.ok(button('Open Opti overlay'));assert.ok(button('Uninstall Opti'));
methods.opti_toggle=async()=>({ok:false,error:'游戏仍在运行。请从 Steam 退出游戏，再操作 XMX 开关。'});
englishOpti.props.onChange(false);await settle();
assert.match(notifications.at(-1).body,/game is still running/);
assert.equal(nodes(render()).find(n=>n.props?.label==='Opti injection').props.checked,true);
context.document.documentElement.lang='zh-cn';
assert.equal(textOf(toggle().description),'仅支持 Intel 设备。\n为游戏启用 XMX 加速，使兼容的游戏中的 XeSS 帧生成可以正常使用。\n更改状态前请先关闭游戏！');
assert.equal(textOf(optiToggle().description),'游戏原生支持 XeSS 帧生成时，请关闭此选项。\n使用 OptiScaler 修改游戏内的超分辨率/帧生成设置');
console.log('PASS: Steam language takes precedence; bilingual descriptions, controls and running-game error.');
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
// A stuck read-only RPC times out, retains the last running snapshot, and cannot apply a late reply.
operation={...operation,operation_id:'reconnect',phase:'downloading',running:true,downloaded_bytes:4194304,revision:3};
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
