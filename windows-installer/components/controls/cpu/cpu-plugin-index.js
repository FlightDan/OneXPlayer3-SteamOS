const R=window.SP_REACT, U=window.DFL, h=R.createElement;
const api=window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(2,"OXP3 CPU");
const getStatus=api.callable("get_status"), configure=api.callable("configure"), restore=api.callable("restore");
const optionalCallable=name=>{try{return api.callable(name);}catch(error){return()=>Promise.reject(error);}};
const getPowerStatus=optionalCallable("get_power_status"), setPL1=optionalCallable("set_pl1"), setPL2=optionalCallable("set_pl2");
// Use the same browser locale as Decky Loader; every non-Chinese locale falls back to English.
const tr=(en,zh)=>/^zh(?:[-_]|$)/i.test(globalThis.navigator?.language||"")?(zh||en):en;
const finiteNumber=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value));
const maxLivePL1=power=>{
  const values=Array.isArray(power?.pl1_values)?power.pl1_values:[];
  const numeric=values.filter(finiteNumber).map(Number);
  return numeric.length?Math.max(...numeric):Number(power?.pl1_watts)||10;
};
const minimumPL2=power=>Math.max(10,Number(power?.pl2_min_watts??10),maxLivePL1(power));
const nativeProfileID=()=>{
  const id=window.SystemPerfStore?.nActiveProfileGameID;
  if(id===undefined||id===null)throw new Error("Steam TDP profile is unavailable");
  return String(id);
};
const updateNativeTDP=async(watts,profileID,isCurrent)=>{
  const store=window.settingsStore;
  const settingsModule=store&&typeof U.findModule==="function"?U.findModule(m=>m?.rV===store&&typeof m.qt==="function"):null;
  if(!settingsModule)
    throw new Error("Steam TDP update API is unavailable");
  if(nativeProfileID()!==profileID)throw new Error("Steam TDP profile changed before apply");
  // Use the same unified settings writer and fields as Steam's native TDP widget.
  await settingsModule.qt("steamos_tdp_limit",watts);
  if(!isCurrent())return;
  if(nativeProfileID()!==profileID)throw new Error("Steam TDP profile changed during apply");
  await settingsModule.qt("steamos_tdp_limit_enabled",true);
  // Steam's bridge can return void; confirm the native widget's observed settings.
  for(let attempt=0;attempt<=15;attempt++){
    if(!isCurrent())return;
    if(nativeProfileID()!==profileID)throw new Error("Steam TDP profile changed during apply");
    const current=store.clientSettings;
    if(current?.steamos_tdp_limit===watts&&current?.steamos_tdp_limit_enabled===true)return;
    if(attempt===15)throw new Error("Steam TDP profile update was not confirmed");
    await new Promise(resolve=>setTimeout(resolve,100));
  }
};
function Content(){
  const names={performance:tr("Performance","性能优先"),balance_performance:tr("Balanced performance","均衡性能"),balance_power:tr("Balanced power saving","均衡节能"),power:tr("Power saving","节能优先")};
  const [data,setData]=R.useState(null),[error,setError]=R.useState(""),[busy,setBusy]=R.useState(false);
  const [epp,setEpp]=R.useState("balance_performance");
  const [caps,setCaps]=R.useState({p:4.7,e:3.6,lp:3.1});
  const initialized=R.useRef(false);
  const [power,setPower]=R.useState(null),[powerError,setPowerError]=R.useState(""),[powerWriteError,setPowerWriteError]=R.useState("");
  const [powerDraft,setPowerDraft]=R.useState({}),[powerWriting,setPowerWriting]=R.useState(false);
  const powerAlive=R.useRef(false),powerWritingRef=R.useRef(false),powerTimer=R.useRef(null);
  const powerQueue=R.useRef({}),powerDraftRef=R.useRef({}),powerReadSequence=R.useRef(0),powerWriteSequence=R.useRef(0),powerPollRef=R.useRef(null);

  R.useEffect(()=>{let live=true;const poll=async()=>{try{const d=await getStatus();if(!live)return;setData(d);if(!initialized.current){initialized.current=true;setEpp(d.config.epp||d.groups.p.epp[0]);setCaps(Object.fromEntries(["p","e","lp"].map(k=>[k,(d.config[k+"_mhz"]??d.groups[k].limit_mhz[0])/1000])));}}catch(e){if(live)setError(String(e));}};poll();const id=setInterval(poll,3000);return()=>{live=false;clearInterval(id);};},[]);

  const pollPowerRef=powerPollRef;
  R.useEffect(()=>{
    let live=true;powerAlive.current=true;
    const poll=async()=>{
      if(!live||powerWritingRef.current)return;
      const sequence=++powerReadSequence.current;
      try{
        if(typeof getPowerStatus!=="function")throw new Error("power status API unavailable");
        const result=await getPowerStatus();
        if(!live||sequence!==powerReadSequence.current)return;
        if(!result||typeof result!=="object")throw new Error("power status response is invalid");
        setPower(result);setPowerError("");
      }catch(e){if(live&&sequence===powerReadSequence.current)setPowerError(`${tr("Power controls are unavailable or could not be read","功率控制不可用或读取失败")}: ${String(e)}`);}
    };
    pollPowerRef.current=poll;void poll();
    const id=setInterval(poll,1500);
    return()=>{
      live=false;powerAlive.current=false;powerWriteSequence.current++;
      if(powerTimer.current!==null){clearTimeout(powerTimer.current);powerTimer.current=null;}
      powerQueue.current={};powerDraftRef.current={};powerPollRef.current=null;
      clearInterval(id);
    };
  },[]);

  const flushPowerEdits=async()=>{
    if(!powerAlive.current||powerWritingRef.current)return;
    const edits=Object.entries(powerQueue.current);
    if(!edits.length)return;
    powerQueue.current={};powerWritingRef.current=true;setPowerWriting(true);
    const sequence=++powerWriteSequence.current;
    // Any read started before this write must not replace its newer readback.
    powerReadSequence.current++;
    let latest=null,failed=false;
    setPowerWriteError("");
    try{
      for(const [key,edit] of edits){
        const {value,profileID}=edit;
        const setter=key==="pl1"?setPL1:setPL2;
        if(typeof setter!=="function")throw new Error(`${key.toUpperCase()} write API unavailable`);
        if(key==="pl1"){
          await updateNativeTDP(value,profileID,()=>powerAlive.current&&sequence===powerWriteSequence.current);
          if(!powerAlive.current||sequence!==powerWriteSequence.current)return;
          if(nativeProfileID()!==profileID)throw new Error("Steam TDP profile changed during apply");
        }
        latest=await setter(value);
        if(!powerAlive.current||sequence!==powerWriteSequence.current)return;
        if(key==="pl1"&&nativeProfileID()!==profileID)throw new Error("Steam TDP profile changed during apply");
        if(!latest||typeof latest!=="object")throw new Error("power write response is invalid");
      }
      if(powerAlive.current&&sequence===powerWriteSequence.current){
        setPower(latest);powerDraftRef.current={};setPowerDraft({});
      }
    }catch(e){
      failed=true;
      if(powerAlive.current&&sequence===powerWriteSequence.current){
        const attempted=edits.map(([key,{value}])=>`${key.toUpperCase()} ${value} W`).join(", ");
        setPowerWriteError(`${tr("Power limit write failed","功率限制写入失败")} (${attempted}): ${String(e)}`);
        powerQueue.current={};powerDraftRef.current={};setPowerDraft({});
      }
    }finally{
      if(powerAlive.current&&sequence===powerWriteSequence.current){
        powerWritingRef.current=false;setPowerWriting(false);
        if(failed&&powerPollRef.current)void powerPollRef.current();
      }
    }
  };
  const queuePowerEdit=(key,rawValue)=>{
    if(!powerAlive.current||powerWritingRef.current)return;
    const low=key==="pl1"?10:minimumPL2(power);
    const high=key==="pl1"?40:80;
    const value=Math.max(low,Math.min(high,Math.round(Number(rawValue))));
    let profileID;
    try{if(key==="pl1")profileID=nativeProfileID();}
    catch(e){setPowerWriteError(`${tr("Power limit write failed","功率限制写入失败")}: ${String(e)}`);return;}
    powerQueue.current={...powerQueue.current,[key]:{value,profileID}};
    powerDraftRef.current={...powerDraftRef.current,[key]:value};
    setPowerDraft(powerDraftRef.current);setPowerWriteError("");
    if(powerTimer.current!==null)clearTimeout(powerTimer.current);
    powerTimer.current=setTimeout(()=>{powerTimer.current=null;void flushPowerEdits();},250);
  };

  const perform=async(reset)=>{setBusy(true);setError("");try{setData(reset?await restore():await configure({enabled:true,epp,...Object.fromEntries(Object.entries(caps).map(([k,v])=>[k+"_mhz",Math.round(v*1000)]))}));}catch(e){setError(String(e));}finally{setBusy(false);}};
  const row=(child,key)=>h(U.PanelSectionRow,{key},child);
  const pl1Min=Number(power?.pl1_min_watts??10),pl1Max=Number(power?.pl1_max_watts??40);
  const pl2Min=minimumPL2(power),pl2Max=Number(power?.pl2_max_watts??80);
  const pl1Value=powerDraft.pl1??Number(power?.pl1_watts??pl1Min);
  const pl2Value=powerDraft.pl2??Number(power?.pl2_watts??pl2Min);
  const powerLabel=(label,value,yellow=false)=>h("span",{style:{display:"flex",alignItems:"center",justifyContent:"space-between",width:"100%",gap:8}},
    h("span",null,label),h("span",{style:{fontWeight:700,whiteSpace:"nowrap",color:yellow?"#f6c85f":"inherit"}},`${value} W`));
  const pl1Label=powerLabel(tr("PL1 sustained power","PL1 持续功耗"),pl1Value);
  const pl2Label=powerLabel(tr("PL2 burst power","PL2 短时功耗"),pl2Value,pl2Value>=52);
  const queued=Object.keys(powerDraft).length>0&&!powerWriting;
  return h(R.Fragment,null,
    h(U.PanelSection,{title:tr("Power limits","功耗限制")},
      row(h(U.SliderField,{label:pl1Label,min:pl1Min,max:pl1Max,step:1,value:pl1Value,showValue:false,disabled:!power||powerWriting,onChange:v=>queuePowerEdit("pl1",v)}),"pl1"),
      row(h(U.SliderField,{label:pl2Label,min:pl2Min,max:pl2Max,step:1,value:pl2Value,showValue:false,disabled:!power||powerWriting,onChange:v=>queuePowerEdit("pl2",v)}),"pl2"),
      row(h("div",{style:{fontSize:12}},tr("PL1 is synced with Steam TDP control","PL1 与 Steam TDP 控制同步")),"pl1-note"),
      queued?row(h("div",{style:{fontSize:12}},tr("Pending apply","待应用")),"power-pending"):null,
      powerWriting?row(h("div",{style:{fontSize:12}},tr("Writing…","正在写入…")),"power-writing"):null,
      powerError?row(h("div",{style:{color:"#ffb4b4"}},powerError),"power-error"):null,
      powerWriteError?row(h("div",{style:{color:"#ffb4b4"}},powerWriteError),"power-write-error"):null,
      powerError?row(h(U.ButtonItem,{layout:"below",disabled:powerWriting,onClick:()=>{if(powerPollRef.current)void powerPollRef.current();}},tr("Retry power controls","重试功率控制")),"power-retry"):null),
    h(U.PanelSection,{title:tr("CPU efficiency and frequency","CPU 能效与频率")},
      row(h(U.DropdownItem,{label:tr("EPP preference","EPP 能效偏好"),rgOptions:Object.entries(names).map(([data,label])=>({data,label})),selectedOption:epp,disabled:busy||!data,onChange:o=>setEpp(o.data)}),"epp"),
      ...[["p","P cores","P 核",2],["e","E cores","E 核",8],["lp","LP E cores","低功耗 E 核",4]].map(([k,en,zh,count])=>row(h(U.SliderField,{label:tr(`${en} max frequency · ${count} cores · GHz`,`${zh}最高频率 · ${count}核 · GHz`),min:0.8,max:(data?.groups[k].hardware_max_mhz??Math.round(caps[k]*1000))/1000,step:0.1,value:caps[k],showValue:true,disabled:busy||!data,onChange:v=>setCaps(old=>({...old,[k]:Math.round(v*10)/10}))}),k)),
      row(h(U.ButtonItem,{layout:"below",disabled:busy||!data,onClick:()=>perform(false)},tr("Apply CPU settings","应用 CPU 设置")),"apply"),
      row(h(U.ButtonItem,{layout:"below",disabled:busy||!data,onClick:()=>perform(true)},tr("Restore original settings","恢复原始设置")),"restore"),
      data?row(h("div",{style:{fontSize:12}},["p","e","lp"].map(k=>`${k.toUpperCase()}: ${[...new Set(data.groups[k].limit_mhz)].join("/")} MHz`).join(" · ")),"readback"):null,
      error?row(h("div",{style:{color:"#ffb4b4"}},error),"error"):null),
    h(U.PanelSection,{title:tr("Intel IBC automatic power allocation","Intel IBC 自动功率分配")},
      row(h("div",null,data?.ibc.enabled===true?tr("IBC enabled","IBC 已启用"):data?.ibc.enabled===false?tr("IBC disabled","IBC 未启用"):tr("Reading IBC status…","IBC 状态读取中")),"ibc")));
}
export default()=>({title:h("div",null,"OXP3 CPU"),content:h(Content),icon:h("span",null,"▦"),onDismount(){}});
