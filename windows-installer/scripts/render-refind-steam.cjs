// Rasterize the sourced vector at 4x the UI size. Pass the installed sharp path.
const fs=require('fs'), path=require('path'), sharp=require(process.argv[2]);
const root=path.resolve(__dirname,'../components/refind');
const svg=fs.readFileSync(path.join(root,'steam-source.svg'),'utf8').replace('<path ','<path fill="#7D8792" ');
sharp(Buffer.from(svg)).resize(448,448).png().toFile(path.join(root,'steam-silhouette.png'));
