const fs=require('fs');
const path=require('path');
const [before,after,out]=process.argv.slice(2);
const rows=[];
function walk(p){return fs.readdirSync(p,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(path.join(p,x.name)):path.join(p,x.name));}
function normalize(text,relative){
  text=text.replace(/\r\n/g,'\n');
  if(relative.replaceAll('\\','/')==='app/App.xaml.cs')text=text.replace(/^        if \(e\.Args\.Length == 3 && e\.Args\[0\] == "--capacity-mock"\).*\n/gm,'');
  if(relative.replaceAll('\\','/')==='app/Backend.cs')text=text.replace('task is not ("capacity-usage" or "resize-prepared"','task is not ("resize-prepared"');
  return text;
}
for(const dir of ['app','guest','components']){
  for(const file of walk(path.join(after,dir))){
    const relative=path.relative(after,file);
    if(relative.replaceAll('\\','/')==='app/CapacityMock.cs')continue;
    if(relative.split(path.sep).some(x=>['bin','obj','__pycache__'].includes(x))||! /\.(cs|xaml|csproj|config|manifest|sh|py|json|txt)$/i.test(file))continue;
    const old=path.join(before,relative);
    rows.push({file:relative,matching:fs.existsSync(old)&&normalize(fs.readFileSync(old,'utf8'),relative)===normalize(fs.readFileSync(file,'utf8'),relative)});
  }
}
const changed=rows.filter(x=>!x.matching);
const value={before,after,method:'Plain source text comparison, normalized line endings; measurement entry point and extra readonly usage task stripped. No hashes.',compared:rows.length,changed,
  preparation_and_components_unchanged:changed.every(x=>['app/NativeVolumes.cs','app/NativeVolumeChecks.cs'].includes(x.file.replaceAll('\\','/')))};
fs.writeFileSync(out,JSON.stringify(value,null,2));
console.log(JSON.stringify(value,null,2));
