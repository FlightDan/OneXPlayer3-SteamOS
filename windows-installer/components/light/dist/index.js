// OXP3 Light 0.1.1. Native Steam/Decky UI, matching OXP3 CPU/Fan/Battery.
// HueSync/hhd protocol provenance and licenses accompany this distribution.
const R=window.SP_REACT,U=window.DFL,h=R.createElement;
const api=window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(2,"OXP3 Light");
const statusCall=api.callable("get_status"),setZoneCall=api.callable("set_zone");
const tr=(en,zh)=>/^zh(?:[-_]|$)/i.test(globalThis.navigator?.language||"")?zh:en;
const zoneNames={rings:()=>tr("Paired joystick rings","左右摇杆灯环"),xbox:()=>tr("Xbox button","Xbox 按钮灯"),slogan:()=>tr("Top slogan","顶部标语灯")};
const draft=()=>({enabled:true,color:[255,80,0],brightness:60});
const presets=[
  {data:"orange",label:()=>tr("Orange","橙色"),color:[255,80,0]},
  {data:"red",label:()=>tr("Red","红色"),color:[255,0,0]},
  {data:"green",label:()=>tr("Green","绿色"),color:[0,255,0]},
  {data:"blue",label:()=>tr("Blue","蓝色"),color:[0,80,255]},
  {data:"purple",label:()=>tr("Purple","紫色"),color:[160,0,255]},
  {data:"white",label:()=>tr("White","白色"),color:[255,255,255]}
];
// Steam moves dropdowns into a modal and unmounts Quick Access. Keep the
// user's session outside Content so its menu callback survives that transition.
// Nothing is replayed on mount/resume; only explicit edit completion queues RPCs.
let state={data:null,error:"",values:Object.fromEntries(Object.keys(zoneNames).map(zone=>[zone,draft()])),
  colorModes:Object.fromEntries(Object.keys(zoneNames).map(zone=>[zone,"orange"])),dirty:{},failed:{},active:null};
const listeners=new Set(),queue=new Map();
let disposed=false,writing=false,readSequence=0;
const update=patch=>{if(disposed)return;state={...state,...patch};for(const listener of listeners)listener(state);};
const refresh=async()=>{
  if(disposed||writing)return;
  const sequence=++readSequence;
  try{const data=await statusCall();if(!disposed&&sequence===readSequence)update({data,error:""});}
  catch(e){if(!disposed&&sequence===readSequence)update({error:tr("Could not read lighting status. Retry below: ","无法读取灯光状态，请重试：")+String(e)});}
};
const edit=(zone,patch)=>{
  if(disposed||!state.data?.available)return;
  const value={...state.values[zone],...patch};
  if(JSON.stringify(value)===JSON.stringify(state.values[zone]))return;
  update({values:{...state.values,[zone]:value},dirty:{...state.dirty,[zone]:true}});
};
const drain=async()=>{
  if(disposed||writing)return;
  writing=true;readSequence++;
  try{
    while(!disposed&&queue.size){
      const [zone,config]=queue.entries().next().value;queue.delete(zone);
      update({active:zone,error:""});
      try{
        const data=await setZoneCall(zone,config);
        update({data,failed:{...state.failed,[zone]:""}});
      }catch(e){update({failed:{...state.failed,[zone]:tr("Lighting could not be applied. The zone may be partially changed: ","灯光应用失败，该区域可能已部分改变：")+String(e)}});}
    }
  }finally{writing=false;update({active:null});}
};
const apply=zone=>{
  if(disposed||!state.data?.available)return;
  const value=state.values[zone];
  // Snapshot at completion, then serialize writes. Later completed edits replace
  // queued edits for that zone without dropping changes made during an RPC.
  queue.set(zone,{...value,color:[...value.color]});
  update({dirty:{...state.dirty,[zone]:false}});
  return drain();
};
const complete=(zone,patch)=>{edit(zone,patch);if(state.dirty[zone])return apply(zone);};
function Content(){
  const [view,setView]=R.useState(state);
  R.useEffect(()=>{listeners.add(setView);setView(state);void refresh();return()=>listeners.delete(setView);},[]);
  const {data,error,values,colorModes,failed,active}=view;
  const row=(key,child)=>h(U.PanelSectionRow,{key},child);
  const label=(name,value)=>h("span",{style:{display:"flex",justifyContent:"space-between",width:"100%",gap:8}},h("span",null,name),h("span",{style:{fontWeight:700,whiteSpace:"nowrap"}},value));
  const colorPatch=(zone,i,n)=>({color:state.values[zone].color.map((c,j)=>j===i?Math.round(n):c)});
  return h(R.Fragment,null,
    error||data?.error||data?.available===false?h(U.PanelSection,{title:tr("Lighting","灯光")},
      row("error",h("div",{role:"alert",style:{color:"#ffb4b4"}},error||data.error||tr("Lighting unavailable","灯光不可用"))),
      row("retry",h(U.ButtonItem,{layout:"below",disabled:!!active,onClick:refresh},tr("Retry","重试")))):null,
    ...Object.entries(zoneNames).map(([zone,name])=>{
      const value=values[zone],disabled=!data?.available;
      const hex="#"+value.color.map(v=>v.toString(16).padStart(2,"0")).join("").toUpperCase();
      const selected=colorModes[zone];
      return h(U.PanelSection,{key:zone,title:name()},
        row("enabled",h(U.ToggleField,{label:tr("Light enabled","开启灯光"),checked:value.enabled,disabled,onChange:enabled=>{edit(zone,{enabled});return apply(zone);}})),
        row("color",h(U.DropdownItem,{label:label(tr("Color","颜色"),hex),rgOptions:[...presets.map(p=>({data:p.data,label:p.label()})),{data:"custom",label:tr("Custom RGB","自定义 RGB")}],selectedOption:selected,disabled,onChange:option=>{
          if(disposed||!state.data?.available)return;
          const preset=presets.find(p=>p.data===option.data);
          if(!preset&&option.data!=="custom")return;
          update({colorModes:{...state.colorModes,[zone]:option.data}});
          if(preset){edit(zone,{color:[...preset.color]});return apply(zone);}
        }})),
        ...(selected==="custom"?[tr("Red","红色"),tr("Green","绿色"),tr("Blue","蓝色")].map((channel,i)=>row("rgb"+i,h(U.SliderField,{
          label:channel,min:0,max:255,step:1,value:value.color[i],showValue:true,disabled,
          onChange:n=>edit(zone,colorPatch(zone,i,n)),onChangeComplete:n=>complete(zone,colorPatch(zone,i,n))
        }))):[]),
        row("brightness",h(U.SliderField,{label:label(tr("Brightness","亮度"),value.brightness+"%"),min:0,max:100,step:1,value:value.brightness,showValue:false,disabled,
          onChange:n=>edit(zone,{brightness:Math.round(n)}),onChangeComplete:n=>complete(zone,{brightness:Math.round(n)})})),
        active===zone?row("applying",h("div",{role:"status",style:{fontSize:12}},tr("Applying…","正在应用…"))):null,
        failed[zone]?row("failure",h("div",{role:"alert",style:{color:"#ffb4b4"}},failed[zone])):null,
        failed[zone]?row("retry-zone",h(U.ButtonItem,{layout:"below",disabled:!!active||disabled,onClick:()=>apply(zone)},tr("Retry lighting","重试灯光设置"))):null);
    }),
    h(U.PanelSection,{title:tr("About OXP3 Light","关于 OXP3 Light")},
      row("limits",h("div",{style:{fontSize:12}},tr("Solid colors only. Slider changes apply when adjustment ends; presets and switches apply immediately. Settings are not replayed on load or resume.","仅支持纯色。滑块调整结束后自动应用，预设颜色和开关立即生效。加载及唤醒时不自动重放设置。"))),
      row("authors",h("div",{style:{fontSize:12}},"0.1.1 · HueSync: honjow / HHHHanasak1 · HHD: Antheas Kapenekakis"))));
}
const icon=()=>h("svg",{viewBox:"0 0 24 24",width:20,height:20,fill:"none",stroke:"currentColor",strokeWidth:1.7,"aria-hidden":true},h("path",{d:"M8 17h8M9 20h6M8 14a7 7 0 1 1 8 0v3H8z"}));
export default()=>({title:h("div",null,"OXP3 Light"),content:h(Content),icon:icon(),onDismount(){disposed=true;readSequence++;queue.clear();listeners.clear();}});
