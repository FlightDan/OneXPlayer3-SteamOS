// Record artifact paths, byte sizes and supplied notices. No digest is calculated.
import { readFile, writeFile, mkdir, readdir, stat, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, 'licenses'); await mkdir(output, { recursive: true });
const files = [];
async function inventory(directory) {
  for (const entry of await readdir(path.join(root, directory), { withFileTypes: true })) {
    const name = path.join(directory, entry.name);
    if (entry.isDirectory()) await inventory(name);
    else if (entry.isFile()) files.push({ file: name.replaceAll('\\', '/'), bytes: (await stat(path.join(root, name))).size });
  }
}
await inventory('runtime/qemu-min'); await inventory('runtime/archive'); await inventory('runtime/console');
const packages = JSON.parse(await readFile(path.join(root, 'runtime/payload/packages.json'), 'utf8'));
await copyFile('C:/Program Files/7-Zip/License.txt', path.join(output, '7-Zip-License.txt'));
await copyFile(path.join(root, '../onexplayer3-steamos-setup/LICENSE'), path.join(output, 'upstream-fixes-MIT.txt'));
const inventoryResult = {
  schema: 1, scope: 'private development package; public redistribution source/notice closure still pending',
  runtime: [
    { name: 'QEMU Windows', version: '11.1.0 / 20260811', source: 'https://qemu.weilnetz.de/w64/', notices: ['runtime/qemu-min/COPYING', 'runtime/qemu-min/COPYING.LIB', 'runtime/qemu-min/share/edk2-licenses.txt'], pending: 'Exact Windows build inputs and source/notices for all DLL dependencies' },
    { name: 'Alpine Linux virt', version: '3.23.6', source: 'https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/x86_64/', pending: 'Corresponding kernel, initramfs and ISO package sources/notices' },
    { name: '.NET Core and Windows Desktop', version: '10.0.12', source: 'https://github.com/dotnet/runtime', notices: ['runtime/dotnet/LICENSE.txt', 'runtime/dotnet/ThirdPartyNotices.txt'], pending: 'Review notices for the exact Windows Desktop runtime build' },
    { name: '7-Zip', source: 'https://www.7-zip.org/', notices: ['licenses/7-Zip-License.txt'], pending: 'Pin installed binary version and preserve corresponding source for public release' },
    { name: 'kmscon + libtsm', version: 'Debian 9.0.0-4 / 4.0.2-0.4', source: 'https://deb.debian.org/debian/pool/main/', notices: ['runtime/console/licenses/kmscon-copyright', 'runtime/console/licenses/libtsm-copyright'], sources: 'runtime/console/sources/', pending: 'Review combined notices with the exact target SteamOS libraries before public release' },
    { name: 'Decky Loader', version: '3.2.10', source: 'https://github.com/SteamDeckHomebrew/decky-loader', pending: 'Release binary source and bundled dependency notices; include source cache for a public release' },
    { name: 'Waydroid OXP3 r2', version: 'steamos-3.10-b20260924.1000-wlroots0.20.2-oxp3-r2', source: 'https://github.com/pjohno/steamos-waydroid-bundle', notices: ['cache/components/waydroid/waydroid-source-ibt-r2.tar', 'cache/components/waydroid/intel-ibt-kernel-calls.patch'], pending: 'Review complete nested package sources/licenses before public redistribution' }
  ], files, alpinePackages: packages
};
await writeFile(path.join(output, 'runtime-inventory.json'), JSON.stringify(inventoryResult, null, 2) + '\n');
console.log(JSON.stringify({ nativeFiles: files.length, alpinePackages: packages.length, publicReleaseReady: false }));
