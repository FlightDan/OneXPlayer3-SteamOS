// Copy the transitive PE imports for the two tools we use. Never remove the source.
import { readFile, readdir, mkdir, copyFile, writeFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'runtime/qemu-full');
const output = path.join(root, 'runtime/qemu-min');
await mkdir(output, { recursive: true });
const names = new Map((await readdir(source)).map(name => [name.toLowerCase(), name]));
function imports(buffer) {
  const pe = buffer.readUInt32LE(0x3c);
  if (buffer.toString('ascii', pe, pe + 4) !== 'PE\0\0') throw Error('Not a PE image');
  const optional = pe + 24;
  const dirs = optional + (buffer.readUInt16LE(optional) === 0x20b ? 112 : 96);
  const sections = optional + buffer.readUInt16LE(pe + 20);
  const rvaToOffset = rva => {
    for (let i = 0; i < buffer.readUInt16LE(pe + 6); i++) {
      const s = sections + i * 40, start = buffer.readUInt32LE(s + 12);
      const size = Math.max(buffer.readUInt32LE(s + 8), buffer.readUInt32LE(s + 16));
      if (rva >= start && rva < start + size) return rva - start + buffer.readUInt32LE(s + 20);
    }
    throw Error(`Unmapped RVA ${rva}`);
  };
  const result = [];
  const table = buffer.readUInt32LE(dirs + 8);
  if (!table) return result;
  for (let p = rvaToOffset(table); buffer.readUInt32LE(p + 12); p += 20) {
    const start = rvaToOffset(buffer.readUInt32LE(p + 12));
    result.push(buffer.toString('ascii', start, buffer.indexOf(0, start)));
  }
  // Some DLLs load additional libraries at runtime: the smoke probe must verify this closure.
  return result;
}
const queue = ['qemu-system-x86_64.exe', 'qemu-img.exe'], copied = new Set(), hostImports = new Set();
while (queue.length) {
  const name = queue.shift();
  if (copied.has(name)) continue;
  const file = path.join(source, name), buffer = await readFile(file);
  await copyFile(file, path.join(output, name)); copied.add(name);
  for (const dependency of imports(buffer)) {
    const actual = names.get(dependency.toLowerCase());
    if (actual) queue.push(actual); else hostImports.add(dependency);
  }
}
await mkdir(path.join(output, 'share'), { recursive: true });
for (const name of ['bios-256k.bin', 'vgabios-stdvga.bin', 'kvmvapic.bin', 'linuxboot_dma.bin', 'edk2-x86_64-code.fd', 'edk2-i386-vars.fd', 'edk2-licenses.txt']) {
  await copyFile(path.join(source, 'share', name), path.join(output, 'share', name));
  copied.add(`share/${name}`);
}
for (const name of ['COPYING', 'COPYING.LIB']) {
  await copyFile(path.join(source, name), path.join(output, name)); copied.add(name);
}
let bytes = 0;
for (const name of copied) bytes += (await stat(path.join(output, name))).size;
const report = { files: [...copied].sort(), bytes, mib: bytes / 1024 ** 2,
  hostImports: [...hostImports].sort(), scope: 'TCG BIOS direct-kernel and UEFI/NVMe runtime files; see IMPLEMENTATION_STATUS.md for actual validation. WHPX and public redistribution pending.' };
await writeFile(path.join(output, 'bundle-report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ fileCount: copied.size, mib: report.mib }, null, 2));
