import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source=fs.readFileSync(new URL("./dist/index.js",import.meta.url),"utf8").replace("export default()=>", "globalThis.pluginFactory=()=>");
const goodStatus=()=>({available:true,backend:"hid-v1",zones:{rings:null,xbox:null,slogan:null},error:null,readback:false});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function harness({language="en-US",status=async()=>goodStatus(),write=async()=>goodStatus()}={}){
  let cursor=0,states=[],refs=[],effects=[],mounted=false,pending=[],tree;
  const calls=[],changed=[];
  const R={
    Fragment:"Fragment",
    createElement:(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity).filter(c=>c!==null&&c!==undefined&&c!==false)}),
    useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==="function"?initial():initial;return[states[i],value=>{states[i]=typeof value==="function"?value(states[i]):value;changed.push(i);}];},
    useRef(initial){const i=cursor++;return refs[i]||=( {current:initial});},
    useEffect(callback){const i=cursor++;if(!mounted)pending.push(()=>effects[i]=callback());}
  };
  const U=Object.fromEntries(["PanelSection","PanelSectionRow","SliderField","ToggleField","DropdownItem","ButtonItem"].map(name=>[name,name]));
  const context={navigator:{language},window:{SP_REACT:R,DFL:U,__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit:{connect(version,name){assert.equal(version,2);assert.equal(name,"OXP3 Light");return{callable(method){if(method==="get_status")return status;if(method==="set_zone")return async(zone,config)=>{calls.push([zone,structuredClone(config)]);return write(zone,config);};throw Error("Unexpected RPC");}};}}}};
  vm.runInNewContext(source,context);
  const plugin=context.pluginFactory();
  const render=()=>{cursor=0;tree=plugin.content.type();for(const run of pending)run();pending=[];mounted=true;return tree;};
  const all=(node=tree)=>node&&typeof node==="object"?[node,...(node.children||[]).flatMap(all)]:[];
  const text=node=>typeof node==="string"?node:(node?.children||[]).map(text).join(" ");
  const section=title=>all().find(n=>n.type==="PanelSection"&&n.props.title===title);
  const controls=(title,type)=>all(section(title)).filter(n=>n.type===type);
  const unmount=()=>{for(const cleanup of effects)if(typeof cleanup==="function")cleanup();mounted=false;states=[];refs=[];effects=[];};
  render();
  return{render,all,text,section,controls,calls,changed,unmount,plugin};
}


const rings="Paired joystick rings",xbox="Xbox button",slogan="Top slogan";
const slider=(ui,title,index=0)=>ui.controls(title,"SliderField")[index].props;
const dropdown=(ui,title)=>ui.controls(title,"DropdownItem")[0].props;

test("native completion applies the latest drag once, without an Apply button",async()=>{
  const ui=harness();await settle();ui.render();
  assert.equal(ui.calls.length,0);
  assert.equal(ui.all().filter(n=>n.type==="ButtonItem").length,0);
  const control=slider(ui,xbox);
  control.onChange(20);control.onChange(39);control.onChange(42);
  assert.equal(ui.calls.length,0);
  await control.onChangeComplete(42);ui.render();
  assert.deepEqual(ui.calls,[["xbox",{enabled:true,color:[255,80,0],brightness:42}]]);
  await slider(ui,xbox).onChangeComplete(42);
  assert.equal(ui.calls.length,1);
  ui.unmount();ui.render();await settle();ui.render();
  assert.equal(slider(ui,xbox).value,42);
  assert.equal(ui.calls.length,1);ui.unmount();
});

test("Custom RGB selection survives Steam unmounting Quick Access for the menu",async()=>{
  const ui=harness();await settle();ui.render();
  const menu=dropdown(ui,xbox);
  ui.unmount();menu.onChange({data:"custom"});ui.render();await settle();ui.render();
  assert.equal(dropdown(ui,xbox).selectedOption,"custom");
  assert.equal(ui.controls(xbox,"SliderField").length,4);
  assert.equal(ui.controls(slogan,"SliderField").length,1);
  assert.equal(ui.calls.length,0);
  const [red,green]=ui.controls(xbox,"SliderField").map(n=>n.props);
  red.onChange(17);green.onChange(0);
  await green.onChangeComplete(0);ui.render();
  assert.deepEqual(ui.calls[0],["xbox",{enabled:true,color:[17,0,0],brightness:60}]);
  await slider(ui,xbox).onChangeComplete(255);ui.render();
  assert.equal(dropdown(ui,xbox).selectedOption,"custom");
  assert.equal(ui.controls(xbox,"SliderField").length,4);ui.unmount();
});

test("presets selected while the panel is unmounted apply and persist; custom only opens controls",async()=>{
  const ui=harness();await settle();ui.render();
  const menu=dropdown(ui,rings);ui.unmount();
  await menu.onChange({data:"blue"});ui.render();await settle();ui.render();
  assert.equal(dropdown(ui,rings).selectedOption,"blue");
  assert.deepEqual(ui.calls,[["rings",{enabled:true,color:[0,80,255],brightness:60}]]);
  dropdown(ui,rings).onChange({data:"custom"});ui.render();
  assert.deepEqual(ui.controls(rings,"SliderField").slice(0,3).map(n=>n.props.value),[0,80,255]);
  assert.equal(ui.calls.length,1);
  await ui.controls(rings,"ToggleField")[0].props.onChange(false);
  assert.equal(ui.calls[1][1].enabled,false);ui.unmount();
});

test("Chinese controls have no explicit apply action",async()=>{
  const ui=harness({language:"zh-CN"});await settle();ui.render();
  for(const title of ["左右摇杆灯环","Xbox 按钮灯","顶部标语灯"]){assert.ok(ui.section(title));assert.equal(ui.controls(title,"ButtonItem").length,0);}
  assert.doesNotMatch(ui.text(ui.render()),/应用此区域|待应用/);
  assert.equal(ui.calls.length,0);ui.unmount();
});

test("unavailable backend disables controls and guards stale edit callbacks",async()=>{
  const ui=harness({status:async()=>({...goodStatus(),available:false,error:"Unexpected controller"})});await settle();ui.render();
  for(const node of ui.all().filter(n=>["SliderField","ToggleField","DropdownItem"].includes(n.type)))assert.equal(node.props.disabled,true);
  await slider(ui,xbox).onChangeComplete(20);
  await dropdown(ui,rings).onChange({data:"red"});
  assert.equal(ui.calls.length,0);
  assert.equal(ui.controls("Lighting","ButtonItem")[0].props.disabled,false);ui.unmount();
});

test("write failure offers scoped retry, persists across panel reopen, and clears on success",async()=>{
  let fail=true;const ui=harness({write:async()=>{if(fail)throw Error("short HID write");return goodStatus();}});
  await settle();ui.render();await slider(ui,slogan).onChangeComplete(21);ui.render();
  assert.match(ui.text(ui.section(slogan)),/partially changed.*short HID write/);
  ui.unmount();ui.render();await settle();ui.render();
  assert.match(ui.text(ui.section(slogan)),/short HID write/);
  assert.equal(ui.calls.length,1);
  fail=false;await ui.controls(slogan,"ButtonItem")[0].props.onClick();ui.render();
  assert.doesNotMatch(ui.text(ui.section(slogan)),/short HID write/);
  assert.equal(ui.controls(slogan,"ButtonItem").length,0);
  assert.deepEqual(ui.calls[1],ui.calls[0]);ui.unmount();
});

test("writes serialize, coalesce completed values, and preserve independent zones",async()=>{
  const releases=[];const ui=harness({write:()=>new Promise(resolve=>releases.push(resolve))});await settle();ui.render();
  const first=slider(ui,rings).onChangeComplete(20);ui.render();
  await slider(ui,rings).onChangeComplete(30);ui.render();
  await slider(ui,rings).onChangeComplete(40);ui.render();
  await slider(ui,xbox).onChangeComplete(50);ui.render();
  assert.equal(ui.calls.length,1);
  assert.equal(slider(ui,xbox).disabled,false);
  // A new drag is not committed just because an older write finishes.
  slider(ui,rings).onChange(75);
  releases.shift()(goodStatus());await settle();
  assert.equal(ui.calls[1][1].brightness,40);
  releases.shift()(goodStatus());await settle();
  assert.deepEqual(ui.calls[2],["xbox",{enabled:true,color:[255,80,0],brightness:50}]);
  releases.shift()(goodStatus());await first;ui.render();
  assert.equal(slider(ui,rings).value,75);
  const last=slider(ui,rings).onChangeComplete(75);
  releases.shift()(goodStatus());await last;assert.equal(ui.calls[3][1].brightness,75);ui.unmount();
});

test("panel unmount suppresses React updates; plugin unload cancels queued work",async()=>{
  let release;const ui=harness({write:()=>new Promise(resolve=>release=resolve)});await settle();ui.render();
  const first=slider(ui,rings).onChangeComplete(20);
  await slider(ui,xbox).onChangeComplete(30);
  const stale=dropdown(ui,slogan);ui.unmount();const count=ui.changed.length;
  ui.plugin.onDismount();release(goodStatus());await first;
  await stale.onChange({data:"red"});
  assert.equal(ui.calls.length,1);assert.equal(ui.changed.length,count);
});

test("status read errors recover without lighting writes",async()=>{
  let fail=true;const ui=harness({status:async()=>{if(fail)throw Error("Decky bridge offline");return goodStatus();}});await settle();ui.render();
  assert.match(ui.text(ui.section("Lighting")),/Retry below.*Decky bridge offline/);
  fail=false;await ui.controls("Lighting","ButtonItem")[0].props.onClick();ui.render();
  assert.equal(ui.section("Lighting"),undefined);assert.equal(slider(ui,xbox).disabled,false);
  assert.equal(ui.calls.length,0);ui.unmount();
});

test("status read started before a write cannot replace the newer result",async()=>{
  let reads=0,release;const ui=harness({status:()=>++reads===1?Promise.resolve({...goodStatus(),error:"Discovery warning"}):new Promise(resolve=>release=resolve)});await settle();ui.render();
  const read=ui.controls("Lighting","ButtonItem")[0].props.onClick();
  await slider(ui,xbox).onChangeComplete(41);ui.render();
  release({...goodStatus(),available:false,error:"stale discovery"});await read;ui.render();
  assert.equal(slider(ui,xbox).disabled,false);assert.equal(ui.section("Lighting"),undefined);ui.unmount();
});
