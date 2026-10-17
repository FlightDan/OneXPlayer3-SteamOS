import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('./cpu-plugin-index.js',import.meta.url),'utf8')
  .replace('export default()=>({','globalThis.testAPI={Content,createPlugin:()=>({')
  .replace(/\}\);\s*$/,'})};');
const copy=value=>JSON.parse(JSON.stringify(value));
const initialCpu={config:{epp:'balance_performance',p_mhz:4700,e_mhz:3600,lp_mhz:3100},groups:{
  p:{epp:['balance_performance'],limit_mhz:[4700],hardware_max_mhz:4700},
  e:{limit_mhz:[3600],hardware_max_mhz:3600},lp:{limit_mhz:[3100],hardware_max_mhz:3100},
},ibc:{enabled:false}};
const makePower=(pl1=22,pl2=44,pl1Values=[22,22],pl2Values=[44,44])=>({
  pl1_watts:pl1,pl2_watts:pl2,pl1_values:pl1Values,pl2_values:pl2Values,
  pl1_min_watts:10,pl1_max_watts:40,pl2_min_watts:10,pl2_max_watts:80,
});

function harness(methods,language='en-US',throwingCallables=[]){
  const slots=[],effects=[],cleanups=[],intervals=new Map(),timeouts=new Map();
  const native={profileID:'769',settings:{steamos_tdp_limit:15,steamos_tdp_limit_enabled:false},requests:[],update:null};
  const nativeStore={get nActiveProfileGameID(){return native.profileID;}};
  const settingsStore={get clientSettings(){return native.settings;}};
  const settingsModule={rV:settingsStore,qt:async(key,value)=>{
    assert.ok(['steamos_tdp_limit','steamos_tdp_limit_enabled'].includes(key),'only the native TDP widget fields may be written');
    const payload={profileID:native.profileID,fields:{[key]:value}};native.requests.push(payload);
    if(key==='steamos_tdp_limit'&&native.update)return native.update(payload);
    native.settings={...native.settings,...payload.fields};
  }};
  let cursor=0,timerId=0,intervalId=0;
  const hook=init=>{const index=cursor++;if(!(index in slots))slots[index]=init;return [slots[index],value=>{slots[index]=typeof value==='function'?value(slots[index]):value;}];};
  const jsx=(type,props,...children)=>({type,props:{...(props||{}),...(children.length?{children:children.length===1?children[0]:children}:{})}});
  const context=vm.createContext({
    console,navigator:{language},
    setTimeout:(fn,ms)=>{const id=++timerId;timeouts.set(id,{fn,ms});return id;},
    clearTimeout:id=>timeouts.delete(id),
    setInterval:(fn,ms)=>{const id=++intervalId;intervals.set(id,{fn,ms});return id;},
    clearInterval:id=>intervals.delete(id),
    window:{SystemPerfStore:nativeStore,settingsStore,SP_REACT:{Fragment:'fragment',createElement:jsx,useState:hook,useRef:init=>hook({current:init})[0],useEffect:fn=>{
      const index=cursor++;if(!(index in slots)){slots[index]=true;effects.push(fn);}
    }},DFL:{findModule:predicate=>{
      assert.equal(predicate({rV:{},qt:()=>{}}),false,'module discovery requires the current settings store identity');
      assert.equal(predicate({rV:settingsStore}),false,'module discovery requires the unified settings writer');
      return predicate(settingsModule)?settingsModule:undefined;
    },PanelSection:'section',PanelSectionRow:'row',SliderField:'slider',ButtonItem:'button',DropdownItem:'dropdown'},
      __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit:{connect:()=>({callable:name=>{
        if(throwingCallables.includes(name))throw new Error(`Callable ${name} is unavailable`);
        return (...args)=>{
          if(typeof methods[name]!=='function')return Promise.reject(new Error(`Unknown callable ${name}`));
          return methods[name](...args);
        };
      }})}},
  });
  vm.runInContext(source,context);
  const render=()=>{cursor=0;return context.testAPI.Content();};
  const mount=()=>{render();for(const effect of effects){const cleanup=effect();if(cleanup)cleanups.push(cleanup);}};
  const unmount=()=>{for(const cleanup of cleanups.splice(0))cleanup();};
  const nodes=node=>{if(!node||typeof node!=='object')return [];if(Array.isArray(node))return node.flatMap(nodes);return [node,...nodes(node.props?.children)];};
  const textOf=node=>{if(node==null)return '';if(typeof node!=='object')return String(node);if(Array.isArray(node))return node.map(textOf).join('');return textOf(node.props?.children);};
  const hasStyledText=(node,color,text)=>{
    if(!node||typeof node!=='object')return false;
    if(Array.isArray(node))return node.some(child=>hasStyledText(child,color,text));
    return (node.props?.style?.color===color&&textOf(node)===text)||hasStyledText(node.props?.children,color,text);
  };
  const slider=label=>nodes(render()).find(node=>node.type==='slider'&&
    (node.props.label===label||textOf(node.props.label).startsWith(label)))?.props;
  const button=label=>nodes(render()).find(node=>node.type==='button'&&node.props.children===label)?.props;
  const sectionTitle=label=>nodes(render()).find(node=>node.type==='section'&&node.props.title===label)?.props;
  const contentText=()=>textOf(render());
  const flushMicrotasks=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
  const fireTimeout=ms=>{const due=[...timeouts.entries()].filter(([,timer])=>timer.ms===ms);for(const [id,timer] of due){timeouts.delete(id);timer.fn();}};
  const fireInterval=ms=>{for(const timer of [...intervals.values()])if(timer.ms===ms)timer.fn();};
  return {context,native,render,mount,unmount,slider,button,sectionTitle,contentText,hasStyledText,flushMicrotasks,fireTimeout,fireInterval,timeouts,intervals};
}

let live=makePower(22,44,[20,20],[44,44]);
let rejectNextPL2=false,holdNextPL1=false,releasePL1=null,staleNextRead=false,releaseStaleRead=null;
let activeWrites=0,maxActiveWrites=0;
const calls=[];
const methods={
  get_status:async()=>copy(initialCpu),
  get_power_status:async()=>{
    calls.push(['get_power_status']);
    if(staleNextRead){staleNextRead=false;const stale=copy(live);return new Promise(resolve=>{releaseStaleRead=()=>resolve(stale);});}
    return copy(live);
  },
  set_pl1:async value=>{
    calls.push(['set_pl1',value]);activeWrites++;maxActiveWrites=Math.max(maxActiveWrites,activeWrites);
    try{
      if(holdNextPL1){holdNextPL1=false;await new Promise(resolve=>{releasePL1=()=>{live=makePower(value,live.pl2_watts,[value,value],live.pl2_values);resolve();};});}
      else live=makePower(value,live.pl2_watts,[value,value],live.pl2_values);
      return copy(live);
    }finally{activeWrites--;}
  },
  set_pl2:async value=>{
    calls.push(['set_pl2',value]);activeWrites++;maxActiveWrites=Math.max(maxActiveWrites,activeWrites);
    try{if(rejectNextPL2){rejectNextPL2=false;throw new Error('MMIO write denied');}live=makePower(live.pl1_watts,value,live.pl1_values,[value,value]);return copy(live);}
    finally{activeWrites--;}
  },
  configure:async()=>copy(initialCpu),restore:async()=>copy(initialCpu),
};
const ui=harness(methods);
const plugin=ui.context.testAPI.createPlugin();
assert.equal(plugin.title.props.children,'OXP3 CPU','plugin title stays unchanged');
assert.doesNotThrow(()=>ui.render(),'loading power state still renders the existing CPU UI');
assert.deepEqual(calls,[],'render does not invoke CPU or power hardware callables');
ui.mount();await ui.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1'||name==='set_pl2').length,0,'mount reads state without writing power limits');
assert.equal(ui.native.requests.length,0,'mount never enables or writes native TDP');
assert.equal(ui.slider('PL1 sustained power').min,10);assert.equal(ui.slider('PL1 sustained power').max,40);
assert.equal(ui.slider('PL2 burst power').min,20,'PL2 lower bound follows the highest live PL1 value');
assert.equal(ui.slider('PL2 burst power').max,80,'PL2 ceiling remains 80 W');
assert.equal(ui.slider('PL1 sustained power').value,22,'PL1 value starts at hardware readback');
assert.match(ui.contentText(),/PL1 is synced with Steam TDP control/);
assert.ok(ui.sectionTitle('Power limits'));
assert.equal(ui.slider('PL1 sustained power').showValue,false);
assert.equal(ui.slider('PL2 burst power').showValue,false);

ui.slider('PL1 sustained power').onChange(28);
assert.equal(calls.filter(([name])=>name==='set_pl1').length,0,'slider movement is debounced before a write');
assert.match(ui.contentText(),/Pending apply/);
ui.fireTimeout(250);await ui.flushMicrotasks();
assert.deepEqual(calls.filter(([name])=>name==='set_pl1'),[['set_pl1',28]]);
assert.deepEqual(ui.native.requests,[{profileID:'769',fields:{steamos_tdp_limit:28}},{profileID:'769',fields:{steamos_tdp_limit_enabled:true}}],
  'PL1 updates only native TDP value then its enabled flag through the unified settings module');
assert.deepEqual(live.pl1_values,[28,28],'PL1 write reads back both hardware ends');
assert.equal(ui.slider('PL1 sustained power').value,28,'successful write uses returned hardware readback');

assert.equal(ui.slider('PL2 burst power').min,28);
ui.slider('PL2 burst power').onChange(20);ui.fireTimeout(250);await ui.flushMicrotasks();
assert.deepEqual(calls.filter(([name])=>name==='set_pl2'),[['set_pl2',28]],'PL2 writes are clamped to the live PL1 minimum');
ui.slider('PL2 burst power').onChange(100);ui.fireTimeout(250);await ui.flushMicrotasks();
assert.deepEqual(calls.filter(([name])=>name==='set_pl2'),[['set_pl2',28],['set_pl2',80]],'PL2 is clamped to its 80 W ceiling');
assert.deepEqual(calls.filter(([name])=>name==='set_pl1'),[['set_pl1',28]],'PL2 writes never send a PL1 or frequency setting');
assert.equal(ui.native.requests.length,2,'PL2-only edits never write the native profile');

live=makePower(26,51,[26,25],[51,51]);ui.fireInterval(1500);await ui.flushMicrotasks();
assert.equal(ui.slider('PL1 sustained power').value,26,'poll refreshes the live PL1 setting');
assert.equal(ui.slider('PL2 burst power').min,26,'PL2 minimum follows the highest live PL1 end');
assert.equal(ui.slider('PL2 burst power').value,51,'PL2 slider displays live hardware readback');
assert.equal(ui.hasStyledText(ui.slider('PL2 burst power').label,'#f6c85f','51 W'),false,'51 W stays in the normal label color');

live=makePower(40,51,[40,40],[51,51]);ui.fireInterval(1500);await ui.flushMicrotasks();
assert.equal(ui.slider('PL2 burst power').min,40,'a 40 W live PL1 value produces a 40 W PL2 floor');

live=makePower(44,51,[42,44],[51,51]);ui.fireInterval(1500);await ui.flushMicrotasks();
assert.equal(ui.slider('PL2 burst power').min,44,'PL2 minimum follows an external PL1 readback above 40 W');
ui.slider('PL2 burst power').onChange(40);ui.fireTimeout(250);await ui.flushMicrotasks();
assert.deepEqual(calls.filter(([name])=>name==='set_pl2'),[['set_pl2',28],['set_pl2',80],['set_pl2',44]],'write-time clamp follows external PL1 above 40 W');

live=makePower(26,52,[26,25],[52,52]);ui.fireInterval(1500);await ui.flushMicrotasks();
assert.equal(ui.slider('PL2 burst power').min,26);
assert.equal(ui.slider('PL2 burst power').value,52);
assert.equal(ui.hasStyledText(ui.slider('PL2 burst power').label,'#f6c85f','52 W'),true,'52 W and above use the yellow label value');

rejectNextPL2=true;ui.slider('PL2 burst power').onChange(60);ui.fireTimeout(250);await ui.flushMicrotasks();
assert.equal(ui.slider('PL2 burst power').value,52,'failed write returns the control to actual readback');
assert.match(ui.contentText(),/Power limit write failed.*MMIO write denied/,'failed write remains visible after the read refresh');

// A poll already in flight before a write cannot replace the newer write readback.
staleNextRead=true;ui.fireInterval(1500);await ui.flushMicrotasks();assert.equal(typeof releaseStaleRead,'function');
holdNextPL1=true;ui.slider('PL1 sustained power').onChange(34);
assert.match(ui.contentText(),/Pending apply/);
ui.fireTimeout(250);await ui.flushMicrotasks();
assert.match(ui.contentText(),/Writing…/);assert.doesNotMatch(ui.contentText(),/Pending apply/);
assert.equal(ui.slider('PL1 sustained power').disabled,true,'sliders disable during the write');
ui.slider('PL2 burst power').onChange(70);ui.fireTimeout(250);await ui.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl2').length,4,'disabled controls cannot start a parallel or queued second write');
assert.equal(maxActiveWrites,1,'power writes are serialized');
releasePL1();await ui.flushMicrotasks();releaseStaleRead();await ui.flushMicrotasks();
assert.equal(ui.slider('PL1 sustained power').value,34,'late pre-write polling cannot replace the successful readback');

ui.unmount();
// A queued debounce is canceled on unmount and cannot perform a hardware write.
const previousPL2Writes=calls.filter(([name])=>name==='set_pl2').length;
// Create a fresh component lifecycle in the same VM after the previous cleanup.
const fresh=harness(methods);
fresh.mount();await fresh.flushMicrotasks();
const writesBeforeUnmount=calls.filter(([name])=>name==='set_pl1'||name==='set_pl2').length;
fresh.slider('PL2 burst power').onChange(45);
assert.ok([...fresh.timeouts.values()].some(timer=>timer.ms===250));
fresh.unmount();fresh.fireTimeout(250);await fresh.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1'||name==='set_pl2').length,writesBeforeUnmount,'unmount cancels a pending power edit');
assert.equal(calls.filter(([name])=>name==='set_pl2').length,previousPL2Writes,'no delayed PL2 write ran after unmount');

// Native profile writes must complete before the hardware write, including the void bridge API.
const nativeUI=harness(methods);nativeUI.mount();await nativeUI.flushMicrotasks();
let releaseNative;
nativeUI.native.update=payload=>new Promise(resolve=>{releaseNative=()=>{
  nativeUI.native.settings={...nativeUI.native.settings,...payload.fields};resolve();
};});
const beforeNative=calls.filter(([name])=>name==='set_pl1').length;
nativeUI.slider('PL1 sustained power').onChange(31);nativeUI.fireTimeout(250);await nativeUI.flushMicrotasks();
assert.equal(nativeUI.native.requests.length,1);
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative,'hardware waits for the native update acknowledgment');
releaseNative();await nativeUI.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1);
nativeUI.native.update=()=>{throw new Error('native profile update denied');};
nativeUI.slider('PL1 sustained power').onChange(30);nativeUI.fireTimeout(250);await nativeUI.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1,'native rejection cannot fall back to a hardware-only write');
assert.match(nativeUI.contentText(),/Power limit write failed.*native profile update denied/);
nativeUI.unmount();

const changedProfile=harness(methods);changedProfile.mount();await changedProfile.flushMicrotasks();
changedProfile.slider('PL1 sustained power').onChange(29);changedProfile.native.profileID='1234';
changedProfile.fireTimeout(250);await changedProfile.flushMicrotasks();
assert.equal(changedProfile.native.requests.length,0,'a different profile during debounce cancels the native write');
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1);
assert.match(changedProfile.contentText(),/Steam TDP profile changed before apply/);
changedProfile.unmount();

const changedDuringNative=harness(methods);changedDuringNative.mount();await changedDuringNative.flushMicrotasks();
changedDuringNative.native.update=()=>new Promise(resolve=>{releaseNative=resolve;});
changedDuringNative.slider('PL1 sustained power').onChange(29);changedDuringNative.fireTimeout(250);await changedDuringNative.flushMicrotasks();
changedDuringNative.native.profileID='1234';releaseNative();await changedDuringNative.flushMicrotasks();
assert.equal(changedDuringNative.native.requests[0].profileID,'769','in-flight request retains its original target profile');
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1,'profile changes during native apply stop the later hardware write');
assert.match(changedDuringNative.contentText(),/Steam TDP profile changed during apply/);
changedDuringNative.unmount();

const unmountedNative=harness(methods);unmountedNative.mount();await unmountedNative.flushMicrotasks();
unmountedNative.native.update=()=>new Promise(resolve=>{releaseNative=resolve;});
unmountedNative.slider('PL1 sustained power').onChange(29);unmountedNative.fireTimeout(250);await unmountedNative.flushMicrotasks();
unmountedNative.unmount();releaseNative();await unmountedNative.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1,'unmount during native apply prevents the hardware request');

const delayedNative=harness(methods);delayedNative.mount();await delayedNative.flushMicrotasks();
delayedNative.native.update=()=>undefined;
delayedNative.slider('PL1 sustained power').onChange(32);delayedNative.fireTimeout(250);await delayedNative.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+1,'void native return waits for observed profile settings');
delayedNative.native.settings={steamos_tdp_limit:32,steamos_tdp_limit_enabled:true};
delayedNative.fireTimeout(100);await delayedNative.flushMicrotasks();
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+2,'observed native readback permits the hardware request');
delayedNative.slider('PL1 sustained power').onChange(33);delayedNative.fireTimeout(250);await delayedNative.flushMicrotasks();
for(let attempt=0;attempt<15;attempt++){delayedNative.fireTimeout(100);await delayedNative.flushMicrotasks();}
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+2,'unconfirmed native settings never trigger hardware fallback');
assert.match(delayedNative.contentText(),/Steam TDP profile update was not confirmed/);
delayedNative.fireInterval(1500);await delayedNative.flushMicrotasks();
assert.equal(delayedNative.native.requests.length,4,'polls after failure never retry or enable native TDP');
delayedNative.unmount();

const missingNative=harness(methods);missingNative.mount();await missingNative.flushMicrotasks();
delete missingNative.context.window.settingsStore;
missingNative.slider('PL1 sustained power').onChange(29);missingNative.fireTimeout(250);await missingNative.flushMicrotasks();
assert.match(missingNative.contentText(),/Steam TDP update API is unavailable/);
assert.equal(calls.filter(([name])=>name==='set_pl1').length,beforeNative+2,'missing native bridge cannot silently write hardware only');
missingNative.unmount();

const legacy=harness({get_status:async()=>copy(initialCpu),configure:async()=>copy(initialCpu),restore:async()=>copy(initialCpu)});
legacy.mount();await legacy.flushMicrotasks();
assert.equal(legacy.slider('PL1 sustained power').disabled,true,'missing power API disables only the new controls');
assert.equal(legacy.slider('P cores max frequency · 2 cores · GHz').disabled,false,'existing CPU frequency controls still work');
assert.ok(legacy.button('Retry power controls'),'missing API exposes a retry action');
assert.match(legacy.contentText(),/Power controls are unavailable or could not be read: Error: Unknown callable get_power_status/);
legacy.unmount();

const legacyRegistration=harness({get_status:async()=>copy(initialCpu),configure:async()=>copy(initialCpu),restore:async()=>copy(initialCpu)},'en-US',[
  'get_power_status','set_pl1','set_pl2',
]);
assert.doesNotThrow(()=>legacyRegistration.mount(),'missing callable registration does not prevent the CPU panel from rendering');
await legacyRegistration.flushMicrotasks();
assert.equal(legacyRegistration.slider('PL1 sustained power').disabled,true);
assert.ok(legacyRegistration.button('Retry power controls'));
assert.match(legacyRegistration.contentText(),/Callable get_power_status is unavailable/);
legacyRegistration.unmount();

const chinese=harness(methods,'zh-CN');
chinese.mount();await chinese.flushMicrotasks();
assert.ok(chinese.sectionTitle('功耗限制'));
assert.ok(chinese.slider('PL1 持续功耗'));
assert.ok(chinese.slider('PL2 短时功耗'));
assert.match(chinese.contentText(),/PL1 与 Steam TDP 控制同步/);
for(const unwanted of ['MSR','MMIO','等待写入硬件','PL2 是独立的短时功耗限制'])
  assert.equal(chinese.contentText().includes(unwanted),false,`concise Chinese copy excludes ${unwanted}`);
chinese.unmount();

console.log('PASS: power UI readback, native Steam profile PL1 sync and confirmation, profile change guards, native failure handling, debounced PL1/PL2 writes, 80 W cap, live PL2 minimum, failure recovery, stale poll ordering, serialized writes, unmount cancellation, and legacy API fallback.');
