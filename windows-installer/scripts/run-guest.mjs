import { spawn } from 'node:child_process';
import { mkdir, open, readFile, writeFile, stat, realpath, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const task = process.argv[2] || 'smoke';
if (!['smoke', 'inspect', 'boot-tools', 'verify', 'partition-test', 'deployment-test', 'component-tests', 'partition-mount-tests'].includes(task)) throw Error('Unknown guest task');
const id = `${new Date().toISOString().replace(/[:.]/g, '-')}-${task}`;
const work = path.join(root, 'work', id);
await mkdir(work, { recursive: true });
const qemu = path.join(root, 'runtime/qemu-min/qemu-system-x86_64.exe');
const iso = path.join(root, 'cache/alpine-virt-3.23.6-x86_64.iso');
const payload = path.join(work, 'payload'); await mkdir(path.join(payload, 'apks'), { recursive: true }); await mkdir(path.join(payload, 'tasks'), { recursive: true });
const packages = JSON.parse(await readFile(path.join(root, 'runtime/payload/packages.json'), 'utf8'));
for (const packageInfo of packages) {
  const filename = `${packageInfo.name}-${packageInfo.version}.apk`;
  if (path.basename(filename) !== filename) throw Error('Unsafe package path');
  await copyFile(path.join(root, 'runtime/payload/apks', filename), path.join(payload, 'apks', filename));
}
const { readdir } = await import('node:fs/promises');
for (const filename of (await readdir(path.join(root, 'guest'))).filter(name => name.endsWith('.sh'))) await copyFile(path.join(root, 'guest', filename), path.join(payload, 'tasks', filename));
if (task === 'partition-mount-tests') {
  const { cp } = await import('node:fs/promises');
  if (process.argv[3] && process.argv[3] !== '--export-ntfs-fixture') {
    const installer = await realpath(process.argv[3]);
    if (!installer.endsWith('.sh') || !(await stat(installer)).isFile()) throw Error('Expected a local test installer .sh');
    await copyFile(installer, path.join(payload, 'partition-mount-test.sh'));
  }
  if (process.argv.includes('--export-ntfs-fixture')) await writeFile(path.join(payload, 'export-ntfs-fixture'), 'private blank image only\n');
  await mkdir(path.join(payload, 'components'), { recursive: true });
  for (const filename of ['test_partition_mount.py', 'test_partition_mount_integration.py', 'test_ntfs_preflight.py', 'partition_mount.py', 'slot_switch.py']) {
    await copyFile(path.join(root, 'components', filename), path.join(payload, 'components', filename));
  }
  await cp(path.join(root, 'components/partition-mount'), path.join(payload, 'components/partition-mount'), { recursive: true });
  await cp(path.join(root, '../steamos-maintenance/oxp3_maintenance'), path.join(payload, 'maintenance/oxp3_maintenance'), {
    recursive: true, filter: source => !source.includes('__pycache__') && !source.endsWith('.pyc')
  });
  await mkdir(path.join(payload, 'maintenance/tests'), { recursive: true });
  await copyFile(path.join(root, '../steamos-maintenance/tests/test_components.py'), path.join(payload, 'maintenance/tests/test_components.py'));
  await copyFile(path.join(root, '../steamos-maintenance/tests/test_partition_mount_entry.py'), path.join(payload, 'maintenance/tests/test_partition_mount_entry.py'));
}
if (task === 'component-tests') {
  const { cp } = await import('node:fs/promises');
  await cp(path.join(root, 'components'), path.join(payload, 'components'), { recursive: true });
  await cp(path.join(root, 'cache/components/oxp3-controls'), path.join(payload, 'control-resources'), { recursive: true });
}
const boot = path.join(root, 'runtime/alpine/boot');
const scratch = path.join(work, 'scratch.raw');
const handle = await open(scratch, 'wx'); await handle.truncate(256 * 1024 ** 2); await handle.close();
const option = p => p.replaceAll('\\', '/').replaceAll(',', ',,');
let source = null;
if (task === 'inspect' || task === 'boot-tools' || task === 'verify' || task === 'deployment-test') {
  source = await realpath(process.argv[3]);
  if (!(await stat(source)).isFile() || path.extname(source).toLowerCase() !== '.img') throw Error('Only regular .img files may be attached');
}
const args = ['-accel', 'tcg', '-m', '1024', '-smp', '2', '-display', 'none', '-monitor', 'none',
  '-serial', 'stdio', '-no-reboot', '-nic', 'none', '-kernel', path.join(boot, 'vmlinuz-virt'),
  '-initrd', path.join(boot, 'initramfs-virt'), '-append', 'console=ttyS0,115200 modules=loop,squashfs,sd-mod,virtio_pci,virtio_blk,vfat alpine_dev=cdrom:iso9660',
  '-drive', `file=${option(iso)},format=raw,media=cdrom,readonly=on`,
  '-drive', `file=${option(scratch)},format=raw,if=virtio`,
  '-drive', `file=fat:ro:${option(payload)},format=raw,if=virtio,readonly=on`];
if (source) args.push('-drive', `file=${option(source)},format=raw,if=virtio,readonly=on`);
let target = null;
if (task === 'deployment-test') {
  target = await realpath(process.argv[4]);
  if (!target.startsWith(path.join(root, 'work') + path.sep) || path.extname(target) !== '.qcow2' || !(await stat(target)).isFile()) throw Error('Only a workspace test fixture may be deployed');
  args.push('-drive', `file=${option(target)},format=qcow2,if=virtio`);
}
if (task === 'partition-test') {
  // Fill vdc with a separate scratch file, so the test target has the fixed vdd name.
  const reserved = path.join(work, 'reserved.raw'); const fd = await open(reserved, 'wx'); await fd.truncate(1024 ** 2); await fd.close();
  args.push('-drive', `file=${option(reserved)},format=raw,if=virtio`);
  const target = path.join(work, 'partition-fixture.qcow2');
  const { spawnSync } = await import('node:child_process');
  const create = spawnSync(path.join(root, 'runtime/qemu-min/qemu-img.exe'), ['create', '-f', 'qcow2', target, '80G'], { windowsHide: true, encoding: 'utf8' });
  if (create.status !== 0) throw Error(create.stderr);
  args.push('-drive', `file=${option(target)},format=qcow2,if=virtio`);
}
const logBase = path.join(root, 'logs', id); await mkdir(path.dirname(logBase), { recursive: true });
const child = spawn(qemu, args, { cwd: path.dirname(qemu), windowsHide: true, stdio: 'pipe' });
child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8'); child.stdin.on('error', () => {});
const started = Date.now(); let phase = 'login', transcript = '', readySeconds, timedOut = false, cancelled = false, error = null;
async function send(command) {
  for (let p = 0; p < command.length && child.exitCode === null; p += 8) {
    child.stdin.write(command.slice(p, p + 8)); await new Promise(r => setTimeout(r, 25));
  }
}
function receive(chunk) {
  transcript += chunk;
  // Keep a usable log even when the host is interrupted.
  void writeFile(`${logBase}.txt`, transcript).catch(() => {});
  if (phase === 'task') process.stdout.write(chunk);
  const terminal = transcript.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
  if (phase === 'login' && /login:\s*$/.test(terminal)) { phase = 'shell'; child.stdin.write('root\n'); }
  else if (phase === 'shell' && /~\s*#\s*$/.test(terminal)) {
    readySeconds = (Date.now() - started) / 1000; phase = 'task';
    console.log(`Offline Linux ready after ${readySeconds}s`);
    void send(`( mkdir -p /mnt/payload && mount -t vfat -o ro /dev/vdb1 /mnt/payload && sh /mnt/payload/tasks/${task}.sh ); poweroff\n`);
  }
}
child.stdout.on('data', receive); child.stderr.on('data', receive);
child.once('error', e => { error = e.message; });
const timeout = setTimeout(() => { timedOut = true; child.kill(); }, task === 'deployment-test' ? 1_200_000 : 300_000);
const cancel = () => { cancelled = true; child.kill(); };
process.once('SIGINT', cancel); process.once('SIGTERM', cancel);
const exitCode = await new Promise(r => child.once('close', r)); clearTimeout(timeout);
process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel);
const passed = !timedOut && !cancelled && !error && exitCode === 0 && /(?:^|[\r\n])OXP_TASK_RESULT=passed[\r\n]/.test(transcript);
const report = { task, passed, exitCode, timedOut, cancelled, error, readySeconds, totalSeconds: (Date.now() - started) / 1000, network: 'disabled', scratch, source, target };
await writeFile(`${logBase}.txt`, transcript); await writeFile(`${logBase}.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2)); process.exitCode = passed ? 0 : 1;
