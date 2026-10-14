import { spawn, spawnSync } from 'node:child_process';
import { mkdir, copyFile, writeFile, readFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const image = path.resolve(process.argv[2]);
const format = path.extname(image) === '.qcow2' ? 'qcow2' : 'raw';
if (!['.img', '.qcow2'].includes(path.extname(image)) || !(await stat(image)).isFile()) throw Error('Only image files are accepted');
const installed = process.argv[3] === '--installed';
const directory = path.join(root, 'work', `boot-${Date.now()}`); await mkdir(directory, { recursive: true });
const qemu = path.join(root, 'runtime/qemu-min');
const overlay = path.join(directory, 'boot.qcow2');
const create = spawnSync(path.join(qemu, 'qemu-img.exe'), ['create', '-f', 'qcow2', '-F', format, '-b', image, overlay], { windowsHide: true, encoding: 'utf8' });
if (create.status !== 0) throw Error(create.stderr);
const vars = path.join(directory, 'vars.fd'); await copyFile(path.join(qemu, 'share/edk2-i386-vars.fd'), vars);
const serialFile = path.join(directory, 'serial.txt');
const p = value => value.replaceAll('\\', '/').replaceAll(',', ',,');
const args = ['-accel', 'tcg', '-machine', 'q35', '-m', '2048', '-smp', '2', '-display', 'none', '-serial', `file:${serialFile}`, '-monitor', 'none', '-nic', 'none', '-no-reboot',
  '-drive', `if=pflash,format=raw,readonly=on,file=${p(path.join(qemu, 'share/edk2-x86_64-code.fd'))}`,
  '-drive', `if=pflash,format=raw,file=${p(vars)}`, '-drive', `file=${p(overlay)},format=qcow2,if=none,id=bootdisk`,
  '-device', 'nvme,drive=bootdisk,serial=OXP3-TEST-BOOT',
  '-qmp', 'stdio'];
const processHandle = spawn(path.join(qemu, 'qemu-system-x86_64.exe'), args, { cwd: qemu, windowsHide: true, stdio: 'pipe' });
processHandle.stdin.on('error', () => {});
let transcript = '', found = false, timedOut = false, qmpReady = false;
processHandle.stdout.setEncoding('utf8'); processHandle.stderr.setEncoding('utf8');
const receive = chunk => {
  transcript += chunk;
  if (!qmpReady && transcript.includes('"QMP"')) {
    qmpReady = true;
    processHandle.stdin.write(JSON.stringify({ execute: 'qmp_capabilities' }) + '\n');
  }
};
processHandle.stdout.on('data', receive); processHandle.stderr.on('data', receive);
processHandle.on('error', error => { transcript += error.toString(); });
async function capture() {
  if (qmpReady && processHandle.exitCode === null) processHandle.stdin.write(JSON.stringify({ execute: 'screendump', arguments: { filename: path.join(directory, 'screen.png'), format: 'png' } }) + '\n');
  try {
    const serial = await readFile(serialFile, 'utf8');
    if (installed ? /SteamOS.*\(ttyS0\)/.test(serial) : serial.includes('OXP_PREVIEW_READY')) { found = true; processHandle.kill(); }
  } catch { }
}
const screenshotTimer = setInterval(capture, 15_000);
const timeout = setTimeout(() => { timedOut = true; clearInterval(screenshotTimer); processHandle.kill(); }, 180_000);
const cancel = () => processHandle.kill(); process.once('SIGINT', cancel);
const code = await new Promise(resolve => processHandle.once('close', resolve));
clearInterval(screenshotTimer); clearTimeout(timeout); process.removeListener('SIGINT', cancel);
await writeFile(path.join(directory, 'qmp.txt'), transcript);
await writeFile(path.join(directory, 'result.json'), JSON.stringify({ found, timedOut, code, scope: installed ? 'UEFI SteamOS fixture boot to serial login; no Windows OS or Steam frontend acceptance' : 'UEFI boot preview with writable overlay; base image unchanged' }, null, 2));
console.log(JSON.stringify({ found, timedOut, code, directory }, null, 2)); process.exitCode = found ? 0 : 1;
