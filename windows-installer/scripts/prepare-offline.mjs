import { gunzipSync } from 'node:zlib';
import { readFile, mkdir, writeFile, rename, stat } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const tar = gunzipSync(await readFile(path.join(root, 'cache/APKINDEX.tar.gz')));
let index = '';
for (let offset = 0; offset + 512 <= tar.length;) {
  const name = tar.toString('utf8', offset, offset + 100).split('\0')[0];
  const size = parseInt(tar.toString('ascii', offset + 124, offset + 136).replace(/\0/g, '').trim(), 8) || 0;
  if (name === 'APKINDEX') index = tar.toString('utf8', offset + 512, offset + 512 + size);
  offset += 512 + Math.ceil(size / 512) * 512;
}
if (!index) throw Error('Alpine package index is missing');
const packages = index.trim().split('\n\n').map(block => Object.fromEntries(block.split('\n').map(line => [line[0], line.slice(2)])));
const named = new Map(packages.map(p => [p.P, p]));
const provided = new Map();
for (const p of packages) for (const token of (p.p || '').split(' ')) {
  if (token) { const name = token.split('=')[0]; if (!provided.has(name)) provided.set(name, p); }
}
const selected = new Map(), queue = ['btrfs-progs', 'btrfs-progs-extra', 'e2fsprogs', 'e2fsprogs-extra', 'dosfstools', 'parted', 'sfdisk', 'python3', 'tar', 'zstd', 'openssl', 'ntfs-3g-progs', 'ntfs-3g'];
while (queue.length) {
  const dep = queue.shift();
  if (dep.startsWith('!')) continue;
  const name = dep.split(/[<>=~]/)[0], p = named.get(name) || provided.get(name);
  if (!p) throw Error(`Unresolved Alpine dependency: ${dep}`);
  if (selected.has(p.P)) continue;
  selected.set(p.P, p);
  queue.push(...(p.D || '').split(' ').filter(Boolean));
}
const directory = path.join(root, 'runtime/payload/apks');
await mkdir(directory, { recursive: true });
const manifest = [];
for (const p of selected.values()) {
  const filename = `${p.P}-${p.V}.apk`, target = path.join(directory, filename);
  const url = `https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/${filename}`;
  try { await stat(target); } catch {
    console.log(`Fetching ${filename}`);
    const result = spawnSync('curl.exe', ['-fsSL', '--retry', '2', '--connect-timeout', '20', '--max-time', '120', '-o', `${target}.part`, url], { windowsHide: true, stdio: 'inherit' });
    if (result.status !== 0) throw Error(`Download failed: ${filename}`);
    await rename(`${target}.part`, target);
  }
  manifest.push({ name: p.P, version: p.V, license: p.L, source: p.U, download: url, bytes: (await stat(target)).size });
}
await writeFile(path.join(root, 'runtime/payload/packages.json'), JSON.stringify(manifest, null, 2));
console.log(`Cached ${manifest.length} packages, ${(manifest.reduce((n, p) => n + p.bytes, 0) / 1024 ** 2).toFixed(2)} MiB`);
