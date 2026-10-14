import { mkdir, writeFile, rename } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const storeResponse = await fetch('https://plugins.deckbrew.xyz/plugins');
if (!storeResponse.ok) throw Error(`Official store failed: ${storeResponse.status}`);
const store = await storeResponse.json();
const selected = [
  { id: 'steamgriddb', name: 'SteamGridDB', version: '1.8.1', source: 'official-store' },
  {
    id: 'protondb', name: 'ProtonDB Badges', version: '1.3.4',
    url: 'https://github.com/bschelst/protondb-decky/releases/download/v1.3.4/protondb-decky.zip',
    archive: 'protondb-1.3.4.zip', source: 'upstream-prebuilt-release',
  },
];
const manifest = [];
for (const item of selected) {
  const { name, version, id } = item;
  let url = item.url;
  if (!url) {
    const plugin = store.find(p => p.name === name);
    const release = plugin?.versions.find(v => v.name === version);
    if (!release) throw Error(`Official store no longer provides ${name} ${version}`);
    // The store identifier is part of its download address; no digest is computed or compared.
    url = release.artifact || `https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/${release.hash}.zip`;
  }
  if (new URL(url).protocol !== 'https:') throw Error('Plugin archive is not HTTPS');
  const directory = path.join(root, 'cache/plugins', id); await mkdir(directory, { recursive: true });
  const response = await fetch(url);
  if (!response.ok) throw Error(`Archive download failed: ${name} ${response.status}`);
  const target = path.join(directory, item.archive || `${id}-${version}.zip`);
  await writeFile(`${target}.part`, Buffer.from(await response.arrayBuffer())); await rename(`${target}.part`, target);
  manifest.push({ id, name, version, url, source: item.source, dependency: 'decky', archive: path.basename(target) });
  console.log(`Cached ${name} ${version}`);
}
await writeFile(path.join(root, 'cache/plugins/plugins.json'), JSON.stringify(manifest, null, 2));
