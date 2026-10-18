// OXP3 Light 0.1.0. Native Steam/Decky UI, matching OXP3 CPU/Fan/Battery.
// HueSync/hhd protocol provenance and licenses accompany this distribution.
const R=window.SP_REACT,U=window.DFL,h=R.createElement;
const api=window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(2,"OXP3 Light");
const statusCall=api.callable("get_status"),setZoneCall=api.callable("set_zone");
const tr=(en,zh)=>/^zh(?:[-_]|$)/i.test(globalThis.navigator?.language||"")?zh:en;
const zoneNames={rings:()=>tr("Paired joystick rings","左右摇杆灯环"),xbox:()=>tr("Xbox button","Xbox 按钮灯"),slogan:()=>tr("Rear slogan","背部标语灯")};
const draft=()=>({enabled:true,color:[255,80,0],brightness:60});
const presets=[
  {data:"orange",label:()=>tr("Orange","橙色"),color:[255,80,0]},
  {data:"red",label:()=>tr("Red","红色"),color:[255,0,0]},
  {data:"green",label:()=>tr("Green","绿色"),color:[0,255,0]},
  {data:"blue",label:()=>tr("Blue","蓝色"),color:[0,80,255]},
  {data:"purple",label:()=>tr("Purple","紫色"),color:[160,0,255]},
  {data:"white",label:()=>tr("White","白色"),color:[255,255,255]}
];
function Content(){
  const [data,setData]=R.useState(null),[error,setError]=R.useState(""),[busy,setBusy]=R.useState(false);
  const [values,setValues]=R.useState(()=>Object.fromEntries(Object.keys(zoneNames).map(zone=>[zone,draft()])));
  const [colorModes,setColorModes]=R.useState(()=>Object.fromEntries(Object.keys(zoneNames).map(zone=>[zone,"orange"])));
  const [dirty,setDirty]=R.useState({}),[done,setDone]=R.useState("");
  const alive=R.useRef(false),writing=R.useRef(false),readSequence=R.useRef(0);
  const refresh=async()=>{
    if(writing.current)return;
    const sequence=++readSequence.current;
    try{const result=await statusCall();if(alive.current&&sequence===readSequence.current){setData(result);setError("");}}
    catch(e){if(alive.current&&sequence===readSequence.current)setError(tr("Could not read lighting status. Retry below: ","无法读取灯光状态，请重试：")+String(e));}
  };
  R.useEffect(()=>{alive.current=true;void refresh();return()=>{alive.current=false;readSequence.current++;};},[]);
  const edit=(zone,patch)=>{
    if(writing.current)return;
    setValues(old=>({...old,[zone]:{...old[zone],...patch}}));
    setDirty(old=>({...old,[zone]:true}));setDone("");
  };
  const apply=async zone=>{
    if(writing.current)return;
    writing.current=true;readSequence.current++;setBusy(true);setError("");setDone("");
    const config={...values[zone],color:[...values[zone].color]};
    try{
      const result=await setZoneCall(zone,config);
      if(!alive.current)return;
      setData(result);setDirty(old=>({...old,[zone]:false}));
      setDone(zone);
    }catch(e){if(alive.current){setError(tr("Lighting could not be applied. The zone may be partially changed. Retry: ","灯光应用失败，该区域可能已部分改变，请重试：")+String(e));}}
    finally{writing.current=false;if(alive.current)setBusy(false);}
  };
  const row=(key,child)=>h(U.PanelSectionRow,{key},child);
  const label=(name,value)=>h("span",{style:{display:"flex",justifyContent:"space-between",width:"100%",gap:8}},h("span",null,name),h("span",{style:{fontWeight:700,whiteSpace:"nowrap"}},value));
  return h(R.Fragment,null,
    error||data?.error||data?.available===false?h(U.PanelSection,{title:tr("Lighting","灯光")},
      row("error",h("div",{role:"alert",style:{color:"#ffb4b4"}},error||data.error||tr("Lighting unavailable","灯光不可用"))),
      row("retry",h(U.ButtonItem,{layout:"below",disabled:busy,onClick:refresh},tr("Retry","重试")))):null,
    ...Object.entries(zoneNames).map(([zone,name])=>{
      const value=values[zone],disabled=busy||!data?.available;
      const hex="#"+value.color.map(v=>v.toString(16).padStart(2,"0")).join("").toUpperCase();
      const selected=colorModes[zone];
      return h(U.PanelSection,{key:zone,title:name()},
        row("enabled",h(U.ToggleField,{label:tr("Light enabled","开启灯光"),checked:value.enabled,disabled,onChange:enabled=>edit(zone,{enabled})})),
        row("color",h(U.DropdownItem,{label:label(tr("Color","颜色"),hex),rgOptions:[...presets.map(p=>({data:p.data,label:p.label()})),{data:"custom",label:tr("Custom RGB","自定义 RGB")}],selectedOption:selected,disabled,onChange:option=>{if(writing.current)return;const preset=presets.find(p=>p.data===option.data);if(!preset&&option.data!=="custom")return;setColorModes(old=>({...old,[zone]:option.data}));if(preset)edit(zone,{color:[...preset.color]});}})),
        ...(selected==="custom"?[tr("Red","红色"),tr("Green","绿色"),tr("Blue","蓝色")].map((channel,i)=>row("rgb"+i,h(U.SliderField,{label:channel,min:0,max:255,step:1,value:value.color[i],showValue:true,disabled,onChange:n=>edit(zone,{color:value.color.map((c,j)=>j===i?Math.round(n):c)})}))):[]),
        row("brightness",h(U.SliderField,{label:label(tr("Brightness","亮度"),value.brightness+"%"),min:0,max:100,step:1,value:value.brightness,showValue:false,disabled,onChange:n=>edit(zone,{brightness:Math.round(n)})})),
        row("apply",h(U.ButtonItem,{layout:"below",disabled,onClick:()=>apply(zone)},busy?tr("Applying…","正在应用…"):done===zone?tr("Applied","已应用"):tr("Apply this zone","应用此区域"))),
        dirty[zone]?row("pending",h("div",{style:{fontSize:12}},tr("Pending apply","待应用"))):null);
    }),
    h(U.PanelSection,{title:tr("About OXP3 Light","关于 OXP3 Light")},
      row("limits",h("div",{style:{fontSize:12}},tr("Solid colors only. Settings are not replayed on load or resume. Reapply a zone if firmware resets its lights.","仅支持纯色。加载及唤醒时不自动重放设置；若固件重置灯光，请重新应用相应区域。"))),
      row("authors",h("div",{style:{fontSize:12}},"0.1.0 · HueSync: honjow / HHHHanasak1 · HHD: Antheas Kapenekakis"))));
}
const icon=()=>h("svg",{viewBox:"0 0 24 24",width:20,height:20,fill:"none",stroke:"currentColor",strokeWidth:1.7,"aria-hidden":true},h("path",{d:"M8 17h8M9 20h6M8 14a7 7 0 1 1 8 0v3H8z"}));
export default()=>({title:h("div",null,"OXP3 Light"),content:h(Content),icon:icon(),onDismount(){}});
