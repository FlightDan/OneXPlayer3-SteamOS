// Development probe only. No physical disk arguments or user-supplied disk paths.
import { spawn } from 'node:child_process';
import { mkdir, open, writeFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const qemu = path.join(root, 'runtime/qemu-min/qemu-system-x86_64.exe');
const iso = path.join(root, 'cache/alpine-virt-3.23.6-x86_64.iso');
const boot = path.join(root, 'runtime/alpine/boot');
for (const file of [qemu, iso, path.join(boot, 'vmlinuz-virt'), path.join(boot, 'initramfs-virt')]) await stat(file);
const id = new Date().toISOString().replace(/[:.]/g, '-');
const work = path.join(root, 'work', id);
await mkdir(work, { recursive: true });
await mkdir(path.join(root, 'logs'), { recursive: true });
const scratch = path.join(work, 'scratch.raw');
const disk = await open(scratch, 'wx');
await disk.truncate(256 * 1024 * 1024);
await disk.close();
const optionPath = value => value.replaceAll('\\', '/').replaceAll(',', ',,');
const args = [
  '-accel', 'tcg', '-m', '768', '-smp', '2', '-display', 'none',
  '-monitor', 'none', '-serial', 'stdio', '-no-reboot', '-nic', 'none',
  '-kernel', path.join(boot, 'vmlinuz-virt'), '-initrd', path.join(boot, 'initramfs-virt'),
  '-append', 'console=ttyS0,115200 modules=loop,squashfs,sd-mod,virtio_pci,virtio_blk alpine_dev=cdrom:iso9660',
  '-drive', `file=${optionPath(iso)},format=raw,media=cdrom,readonly=on`,
  '-drive', `file=${optionPath(scratch)},format=raw,if=virtio`,
  '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0,romfile=',
];
const started = Date.now();
let transcript = '', phase = 'login', readySeconds = null, timedOut = false, spawnError = null;
const child = spawn(qemu, args, { cwd: path.dirname(qemu), windowsHide: true, stdio: 'pipe' });
child.stdin.on('error', () => {});
async function sendSerial(line) {
  // UART input has a small FIFO; a single large write can lose bytes under TCG.
  for (let p = 0; p < line.length && child.exitCode === null; p += 8) {
    child.stdin.write(line.slice(p, p + 8));
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}
// Only /dev/vda, the new scratch.raw above, is writable in this guest.
const commands = [
  'set -e',
  'ip link set eth0 up',
  'udhcpc -i eth0 -q -n -t 5',
  "printf '%s\\n' https://dl-cdn.alpinelinux.org/alpine/v3.23/main > /etc/apk/repositories",
  'apk add btrfs-progs e2fsprogs',
  'modprobe btrfs', 'modprobe ext4', 'mkdir -p /mnt/probe',
  'test "$(blockdev --getsize64 /dev/vda 2>/dev/null || cat /sys/block/vda/size)" != 0',
  'mkfs.btrfs -f /dev/vda', 'mount /dev/vda /mnt/probe',
  'echo oxp-btrfs > /mnt/probe/probe.txt', 'sync', 'umount /mnt/probe',
  'mount /dev/vda /mnt/probe', 'test "$(cat /mnt/probe/probe.txt)" = oxp-btrfs', 'umount /mnt/probe',
  'mkfs.ext4 -F /dev/vda', 'mount /dev/vda /mnt/probe',
  'echo oxp-ext4 > /mnt/probe/probe.txt', 'sync', 'umount /mnt/probe',
  'mount /dev/vda /mnt/probe', 'test "$(cat /mnt/probe/probe.txt)" = oxp-ext4', 'umount /mnt/probe',
  "printf '\\nOXP_SMOKE_%s=passed\\n' RESULT",
].join(' && ');
const receive = data => {
  const chunk = data.toString(); transcript += chunk;
  if (phase === 'probe') process.stdout.write(chunk);
  const terminal = transcript.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
  if (phase === 'login' && /login:\s*$/.test(terminal)) {
    phase = 'shell'; child.stdin.write('root\n');
  } else if (phase === 'shell' && /(?:~|\/root)\s*#\s*$/.test(terminal)) {
    readySeconds = (Date.now() - started) / 1000;
    phase = 'probe';
    console.log(`Linux ready after ${readySeconds}s; probing scratch disk.`);
    // A failed probe powers off too, but never emits the passed marker.
    void sendSerial(`( ${commands} ); poweroff\n`);
  }
};
child.stdout.on('data', receive); child.stderr.on('data', receive);
const timeout = setTimeout(() => { timedOut = true; child.kill(); }, 240_000);
const cancel = () => child.kill();
process.once('SIGINT', cancel); process.once('SIGTERM', cancel);
child.once('error', error => { spawnError = error.message; });
const code = await new Promise(resolve => child.once('close', resolve));
clearTimeout(timeout);
process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel);
const passed = !timedOut && !spawnError && code === 0 && /(?:^|[\r\n])OXP_SMOKE_RESULT=passed[\r\n]/.test(transcript);
const result = { passed, phase, timedOut, spawnError, exitCode: code, accelerator: 'tcg', readySeconds,
  totalSeconds: (Date.now() - started) / 1000, scratch, scope: 'scratch Btrfs/ext4 write and remount; not SteamOS build or boot acceptance' };
await writeFile(path.join(root, 'logs', `${id}.txt`), transcript);
await writeFile(path.join(root, 'logs', `${id}.json`), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
process.exitCode = passed ? 0 : 1;
