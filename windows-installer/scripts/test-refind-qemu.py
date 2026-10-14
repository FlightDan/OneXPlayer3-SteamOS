"""Test real rEFInd settings in private, offline UEFI VMs; never attach host disks.

The two destinations are EFI probe menus, not Windows/SteamOS installations.
Requires an extracted rEFInd package and the installer's bundled QEMU/OVMF.
"""
import argparse
import json
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def configuration(default, timeout, graphical=False):
    return ('' if graphical else 'textonly\n') + f'''timeout {timeout}
default_selection "{default}"
scanfor manual
showtools shutdown
big_icon_size 256
small_icon_size 96
menuentry "SteamOS" {{
    icon /EFI/BOOT/icons/os_linux.png
    loader /EFI/probes/steamos/refind_x64.efi
}}
menuentry "Windows" {{
    icon /EFI/BOOT/icons/os_win.png
    loader /EFI/probes/windows/refind_x64.efi
}}
'''


def prepare(directory, source, default, timeout, graphical):
    esp = directory / 'esp'
    boot = esp / 'EFI/BOOT'
    boot.mkdir(parents=True)
    shutil.copyfile(source / 'refind_x64.efi', boot / 'BOOTX64.EFI')
    shutil.copytree(source / 'icons', boot / 'icons')
    (boot / 'refind.conf').write_text(configuration(default, timeout, graphical), encoding='ascii')
    for name in ('steamos', 'windows'):
        probe = esp / 'EFI/probes' / name
        probe.mkdir(parents=True)
        shutil.copyfile(source / 'refind_x64.efi', probe / 'refind_x64.efi')
        # A separate rEFInd invocation provides an unambiguous console marker.
        (probe / 'refind.conf').write_text(f'''textonly
timeout 0
scanfor manual
showtools shutdown
menuentry "PROBE_{name.upper()}" {{
    loader /EFI/probes/{name}/refind_x64.efi
}}
''', encoding='ascii')
    return esp


def run_case(base, source, name, default, timeout, graphical=False):
    directory = base / name
    directory.mkdir()
    esp = prepare(directory, source, default, timeout, graphical)
    runtime = ROOT / 'runtime/qemu-min'
    variables = directory / 'vars.fd'
    shutil.copyfile(runtime / 'share/edk2-i386-vars.fd', variables)
    option = lambda path: str(path).replace('\\', '/').replace(',', ',,')
    serial = directory / 'serial.txt'
    arguments = [str(runtime / 'qemu-system-x86_64.exe'), '-accel', 'tcg', '-machine', 'q35',
                 '-m', '512', '-smp', '1', '-display', 'none', '-monitor', 'none',
                 '-nic', 'none', '-no-reboot', '-vga', 'std', '-qmp', 'stdio',
                 '-serial', 'file:' + option(serial),
                 '-drive', 'if=pflash,format=raw,readonly=on,file=' + option(runtime / 'share/edk2-x86_64-code.fd'),
                 '-drive', 'if=pflash,format=raw,file=' + option(variables),
                 '-drive', 'file=fat:ro:' + option(esp) + ',format=raw,if=virtio,readonly=on']
    (directory / 'arguments.json').write_text(json.dumps(arguments, indent=2), encoding='utf-8')
    process = subprocess.Popen(arguments, cwd=runtime, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    output, errors, responses = [], [], queue.Queue()

    def protocol_reader():
        for line in process.stdout:
            output.append(line)
            try:
                value = json.loads(line)
                if 'QMP' in value or 'id' in value:
                    responses.put(value)
            except ValueError:
                pass

    def error_reader():
        errors.extend(process.stderr.readlines())

    threading.Thread(target=protocol_reader, daemon=True).start()
    threading.Thread(target=error_reader, daemon=True).start()
    identifier = 0

    def command(execute, arguments=None):
        nonlocal identifier
        identifier += 1
        request = {'execute': execute, 'id': identifier}
        if arguments is not None:
            request['arguments'] = arguments
        process.stdin.write(json.dumps(request) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = responses.get(timeout=max(.1, deadline - time.monotonic()))
            if response.get('id') == identifier:
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response
        raise RuntimeError('QMP response timeout')

    def capture(label):
        filename = directory / (label + '.ppm')
        command('screendump', {'filename': str(filename)})
        from PIL import Image
        with Image.open(filename) as picture:
            picture.save(directory / (label + '.png'))

    def text():
        return serial.read_text(encoding='utf-8', errors='replace') if serial.exists() else ''

    started = time.monotonic()
    evidence = {'case': name, 'default_selection': default, 'timeout': timeout, 'graphical': graphical,
                'destination_kind': 'EFI probe menu, not an installed OS', 'passed': False}
    try:
        greeting = responses.get(timeout=10)
        if 'QMP' not in greeting:
            raise RuntimeError('Missing QMP greeting')
        command('qmp_capabilities')
        menu_at, arrived_at = None, None
        while time.monotonic() - started < 40:
            log = text()
            if menu_at is None and ('Boot SteamOS' in log or 'Boot Windows' in log):
                menu_at = time.monotonic()
                capture('menu')
            if 'PROBE_STEAMOS' in log or 'PROBE_WINDOWS' in log:
                arrived_at = time.monotonic()
                break
            if timeout == 0:
                # Graphical menus do not print their labels to the serial console.
                if graphical and menu_at is None and time.monotonic() - started >= 8:
                    menu_at = time.monotonic()
                    capture('menu')
                if menu_at is not None and time.monotonic() - menu_at >= 12:
                    capture('still-waiting')
                    evidence['waited_without_autoboot_seconds'] = round(time.monotonic() - menu_at, 2)
                    command('human-monitor-command', {'command-line': 'sendkey ret'})
                    evidence['manual_enter_sent'] = True
                    # Only send Enter once; continue waiting for the probe marker.
                    timeout = -2
            if process.poll() is not None:
                raise RuntimeError('QEMU exited before its destination marker')
            time.sleep(.1)
        if arrived_at is None:
            capture('failure')
            raise RuntimeError('No EFI destination marker within 40 seconds')
        expected = 'PROBE_' + default.upper()
        if expected not in text():
            raise RuntimeError('Wrong default destination: expected ' + expected)
        evidence['destination_marker'] = expected
        evidence['elapsed_since_process_start_seconds'] = round(arrived_at - started, 2)
        if menu_at is not None:
            evidence['elapsed_since_menu_detected_seconds'] = round(arrived_at - menu_at, 2)
        if evidence['timeout'] > 0:
            if menu_at is None or arrived_at - menu_at < evidence['timeout'] - 1:
                raise RuntimeError('Destination launched before the configured countdown')
        capture('destination')
        evidence['passed'] = True
    except Exception as error:
        evidence['error'] = str(error)
    finally:
        if process.poll() is None:
            try:
                command('quit')
            except Exception:
                process.kill()
        process.wait(timeout=10)
        (directory / 'qmp.jsonl').write_text(''.join(output), encoding='utf-8')
        (directory / 'stderr.txt').write_text(''.join(errors), encoding='utf-8')
        (directory / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence), flush=True)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refind-directory', type=Path, required=True)
    args = parser.parse_args()
    source = args.refind_directory.resolve(strict=True)
    binary = (source / 'refind_x64.efi').read_bytes()
    pe = struct.unpack_from('<I', binary, 0x3c)[0]
    if binary[:2] != b'MZ' or binary[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', binary, pe+4)[0] != 0x8664:
        raise RuntimeError('Expected an x86-64 EFI binary')
    base = ROOT / 'work' / ('refind-qemu-' + uuid.uuid4().hex)
    base.mkdir()
    print('REFIND_TEST_DIRECTORY=' + str(base), flush=True)
    results = [run_case(base, source, *values) for values in (
        ('steamos-default-3s', 'SteamOS', 3),
        ('windows-default-6s', 'Windows', 6),
        ('graphical-wait-for-enter', 'Windows', 0, True),
        ('steamos-immediate', 'SteamOS', -1))]
    report = {'passed': all(item['passed'] for item in results), 'source_directory': str(source),
              'scope': 'Real rEFInd/OVMF menu settings and EFI probe chaining; no OS, firmware touch or host boot acceptance',
              'cases': results, 'directory': str(base)}
    destination = ROOT / 'logs/refind-qemu-settings.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('REFIND_TEST_REPORT=' + str(destination), flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
