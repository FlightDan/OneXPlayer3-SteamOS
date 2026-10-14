const fs = require('fs');
const path = require('path');
const root=process.argv[2];
const rows=fs.readFileSync(path.join(root,'evidence/events.jsonl'),'utf8').split(/\r?\n/).filter(Boolean).flatMap(x=>{try{return [JSON.parse(x)]}catch{return []}});
const text=rows.filter(x=>x.type==='log').map(x=>x.text).join('');
const components=[...text.matchAll(/OXP_COMPONENT_RESULT=(\{[^\r\n]+\})/g)].flatMap(x=>{try{return [JSON.parse(x[1])]}catch{return []}});
const counts={};
for(const x of components){const key=x.slot+':'+x.status;counts[key]=(counts[key]||0)+1;}
const samples=rows.filter(x=>x.allocated_bytes!==undefined);
console.log(JSON.stringify({stage:rows.at(-1)?.stage,seconds:rows.at(-1)?.seconds,counts,refused:components.filter(x=>x.status!=='files_installed').map(x=>({slot:x.slot,id:x.id,reason:x.reason})),allocated_gib:samples.at(-1)?.allocated_bytes/1024**3,last_log:rows.filter(x=>x.type==='log').at(-1)?.text.slice(-200)},null,2));
