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
  const unmount=()=>{for(const cleanup of effects)if(typeof cleanup==="function")cleanup();};
  render();
  return{render,all,text,section,controls,calls,changed,unmount,plugin};
}

test("mount and draft edits never write; apply affects only the selected zone",async()=>{
  const ui=harness();await settle();ui.render();
  assert.equal(ui.calls.length,0);
  assert.equal(ui.section("Lighting"),undefined);
  assert.doesNotMatch(ui.text(ui.render()),/Refresh status|drafts, not hardware readback/);
  for(const title of ["Paired joystick rings","Xbox button","Rear slogan"]){
    assert.equal(ui.controls(title,"SliderField").length,1);
    assert.equal(ui.controls(title,"ToggleField").length,1);
  }
  ui.controls("Xbox button","DropdownItem")[0].props.onChange({data:"custom"});ui.render();
  ui.controls("Xbox button","SliderField")[0].props.onChange(17);ui.render();
  ui.controls("Xbox button","SliderField")[3].props.onChange(42);ui.render();
  assert.equal(ui.calls.length,0);
  await ui.controls("Xbox button","ButtonItem")[0].props.onClick();ui.render();
  assert.equal(ui.calls.length,1);
  assert.equal(ui.calls[0][0],"xbox");
  assert.deepEqual(ui.calls[0][1],{enabled:true,color:[17,80,0],brightness:42});
  assert.equal(ui.text(ui.controls("Xbox button","ButtonItem")[0]),"Applied");
  ui.unmount();assert.equal(ui.calls.length,1);
});

test("custom RGB expands per zone and stays expanded when its values match a preset",async()=>{
  const ui=harness();await settle();ui.render();
  const title="Xbox button";
  ui.controls(title,"DropdownItem")[0].props.onChange({data:"custom"});ui.render();
  assert.equal(ui.controls(title,"SliderField").length,4);
  assert.equal(ui.controls("Rear slogan","SliderField").length,1);
  assert.equal(ui.controls(title,"DropdownItem")[0].props.selectedOption,"custom");
  ui.controls(title,"SliderField")[1].props.onChange(0);ui.render();
  assert.equal(ui.controls(title,"DropdownItem")[0].props.selectedOption,"custom");
  assert.equal(ui.controls(title,"SliderField").length,4);
  ui.controls(title,"DropdownItem")[0].props.onChange({data:"blue"});ui.render();
  assert.equal(ui.controls(title,"SliderField").length,1);
  assert.equal(ui.controls(title,"DropdownItem")[0].props.selectedOption,"blue");
  ui.controls(title,"DropdownItem")[0].props.onChange({data:"custom"});ui.render();
  assert.deepEqual(ui.controls(title,"SliderField").slice(0,3).map(n=>n.props.value),[0,80,255]);
  assert.equal(ui.calls.length,0);
  await ui.controls(title,"ButtonItem")[0].props.onClick();ui.render();
  assert.deepEqual(ui.calls[0],["xbox",{enabled:true,color:[0,80,255],brightness:60}]);
  ui.unmount();
});

test("Chinese locale exposes all three clear zone names and apply actions",async()=>{
  const ui=harness({language:"zh-CN"});await settle();ui.render();
  for(const title of ["左右摇杆灯环","Xbox 按钮灯","背部标语灯"]){
    assert.ok(ui.section(title));
    assert.match(ui.text(ui.controls(title,"ButtonItem")[0]),/应用此区域/);
  }
  assert.equal(ui.section("灯光"),undefined);
  assert.equal(ui.calls.length,0);ui.unmount();
});

test("unavailable backend disables zone edits and apply, leaving status retry usable",async()=>{
  const ui=harness({status:async()=>({...goodStatus(),available:false,error:"Unexpected controller"})});
  await settle();ui.render();
  for(const node of ui.all().filter(n=>["SliderField","ToggleField","DropdownItem"].includes(n.type)))assert.equal(node.props.disabled,true);
  for(const title of ["Paired joystick rings","Xbox button","Rear slogan"])assert.equal(ui.controls(title,"ButtonItem")[0].props.disabled,true);
  assert.equal(ui.controls("Lighting","ButtonItem")[0].props.disabled,false);
  assert.match(ui.text(ui.section("Lighting")),/Unexpected controller/);
  ui.unmount();
});

test("write failure displays unknown-state recovery and allows retry",async()=>{
  let fail=true;
  const ui=harness({write:async()=>{if(fail)throw Error("short HID write");return goodStatus();}});
  await settle();ui.render();
  await ui.controls("Rear slogan","ButtonItem")[0].props.onClick();ui.render();
  assert.match(ui.text(ui.section("Lighting")),/partially changed.*short HID write/);
  assert.equal(ui.controls("Rear slogan","ButtonItem")[0].props.disabled,false);
  fail=false;await ui.controls("Rear slogan","ButtonItem")[0].props.onClick();ui.render();
  assert.doesNotMatch(ui.text(ui.section("Lighting")),/short HID write/);
  assert.equal(ui.calls.length,2);ui.unmount();
});

test("rapid apply clicks serialize in UI and unmount suppresses stale updates",async()=>{
  let release;
  const ui=harness({write:()=>new Promise(resolve=>release=resolve)});await settle();ui.render();
  const click=ui.controls("Paired joystick rings","ButtonItem")[0].props.onClick;
  const first=click();await click();ui.render();
  assert.equal(ui.calls.length,1);
  assert.equal(ui.controls("Xbox button","SliderField")[0].props.disabled,true);
  ui.unmount();const changes=ui.changed.length;release(goodStatus());await first;
  assert.equal(ui.changed.length,changes);
});

test("status read failure is recoverable without writing lights",async()=>{
  let fail=true;
  const ui=harness({status:async()=>{if(fail)throw Error("Decky bridge offline");return goodStatus();}});
  await settle();ui.render();assert.match(ui.text(ui.section("Lighting")),/Retry below.*Decky bridge offline/);
  fail=false;await ui.controls("Lighting","ButtonItem")[0].props.onClick();ui.render();
  assert.doesNotMatch(ui.text(ui.section("Lighting")),/Decky bridge offline/);
  assert.equal(ui.controls("Xbox button","ButtonItem")[0].props.disabled,false);
  assert.equal(ui.calls.length,0);ui.unmount();
});

test("status started before apply cannot replace the newer write result",async()=>{
  let reads=0,release;
  const ui=harness({status:()=>++reads===1?Promise.resolve({...goodStatus(),error:"Discovery warning"}):new Promise(resolve=>release=resolve)});
  await settle();ui.render();
  const refresh=ui.controls("Lighting","ButtonItem")[0].props.onClick();
  await ui.controls("Xbox button","ButtonItem")[0].props.onClick();ui.render();
  release({...goodStatus(),available:false,error:"stale discovery"});await refresh;ui.render();
  assert.equal(ui.controls("Xbox button","ButtonItem")[0].props.disabled,false);
  assert.doesNotMatch(ui.text(ui.section("Lighting")),/stale discovery/);
  assert.equal(ui.section("Lighting"),undefined);
  assert.equal(ui.text(ui.controls("Xbox button","ButtonItem")[0]),"Applied");ui.unmount();
});
