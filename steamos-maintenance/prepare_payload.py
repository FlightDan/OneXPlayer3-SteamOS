#!/usr/bin/env python3
"""Stage explicit installer Linux resources without running their generators.

The workspace is a local source input, not an authenticity claim. This command
does not download, sign, install, or inspect a device. Its report describes
resource coverage, never runtime compatibility or hardware acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile

from build_bundle import _metadata
from oxp3_maintenance.bundle import BundleError
from desktop_hdr_policy import DesktopHdrPolicyError, validate_desktop_hdr_runtime
from oxp3_maintenance.payload_policy import (
    distributable_path, json_bytes, sanitize_metadata,
    sanitize_options,
)


EXCLUDED = {
    'refind': 'Separate EFI boot-manager operation; maintenance does not deploy it.',
    'shared-storage': 'Separate shared-storage and mount-layout operation.',
}
SPECIAL = {'hdr', 'keyboard', 'multifunction', 'flathub-ustc', 'decky', 'split-lock', 'slot-switch', 'partition-mount',
           'windows-reboot', 'waydroid', 'serial-console-policy', 'autoflatpaks-compat', 'animation-changer-compat'}
MANIFEST_ADAPTERS = {'opti2xmx', 'oxp3-fan', 'oxp3-cpu', 'charging', 'oxp3-light', 'fan-driver',
                     'native-tdp', 'overlay', 'wifi', 'xe-dsb', 'gm7-resume',
                     'gamescope-env', 'input', 'gyro', 'legacy-runtime', 'manager',
                     'desktop-hdr'}
SOURCE_SUFFIXES = {'.py', '.json', '.lua', '.yaml', '.yml', '.sh', '.js', '.patch',
                   '.desktop', '.rules', '.policy', '.conf', '.toml', '.md', '.txt',
                   '.flatpakrepo', '.service'}
FORBIDDEN_NAMES = {'credentials', 'credentials.json', 'secrets', 'token', 'tokens',
                   'node_modules', '__pycache__', '.git'}
FORBIDDEN_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.exe', '.dll', '.img', '.iso',
                      '.vhd', '.vhdx', '.pyc', '.pyo'}
OLD_GUARD = b'ExecCondition=/usr/bin/python3 -I -B /usr/local/lib/oxp3-integration/integration_runtime.py guard'


class PreparationError(ValueError):
    pass


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(ord(c) < 32 for c in value) or value.startswith('/')
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise PreparationError('Unsafe resource path: ' + repr(value))
    return value


def _source(root, relative):
    path = Path(root)
    for part in PurePosixPath(_relative(relative)).parts:
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PreparationError('Linked resource refused: ' + str(path))
    if not path.is_file() or path.stat().st_nlink != 1:
        raise PreparationError('Expected a single regular resource file: ' + str(path))
    return path


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PreparationError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def _allowed(relative):
    path = PurePosixPath(relative)
    return (not any(p.startswith('.') or p.lower() in FORBIDDEN_NAMES for p in path.parts)
            and path.suffix.lower() not in FORBIDDEN_SUFFIXES)


def _current_source(component, target):
    """Only public component source mappings; never infer research locations."""
    if component == 'desktop-hdr' and target.startswith('home/deck/.local/lib/oxp3-desktop-hdr-runtime/'):
        name = target.rsplit('/', 1)[1]
        if name in ('hdr_trial.py', 'x2mini_device.py', 'install-x2mini-hdr.sh', 'launch.sh'):
            return 'components/desktop-hdr/' + name
    if component == 'oxp3-cpu':
        cpu_files = {
            'var/lib/oxp3-cpu/cpu_control.py': 'cpu_control.py',
            'var/lib/oxp3-cpu/power_control.py': 'power_control.py',
            'var/lib/oxp3-cpu/test_cpu_control.py': 'test_cpu_control.py',
            'var/lib/oxp3-cpu/test_power_control.py': 'test_power_control.py',
            'var/lib/oxp3-cpu/gpu_priority.py': 'gpu_priority.py',
            'var/lib/oxp3-cpu/gpu-priority-profile.json': 'gpu-priority-profile.json',
            'var/lib/oxp3-cpu/test_gpu_priority.py': 'test_gpu_priority.py',
            'var/lib/oxp3-cpu/test_cpu_gpu_ui.mjs': 'test_cpu_gpu_ui.mjs',
            'etc/systemd/system/oxp3-gpu-priority.service': 'gpu_priority.service',
        }
        if target in cpu_files:
            return 'components/controls/cpu/' + cpu_files[target]
        for prefix in ('home/deck/homebrew/plugins/OXP3-CPU/',
                       'var/lib/oxp3-installer/decky/runtime/plugins/OXP3-CPU/'):
            if target.startswith(prefix) and target[len(prefix):] in ('main.py', 'dist/index.js'):
                source = 'cpu-plugin-main.py' if target.endswith('/main.py') else 'cpu-plugin-index.js'
                return 'components/controls/cpu/' + source
    if component == 'overlay' and target in (
            'var/lib/oxp3-overlay-telemetry/telemetry.py',
            'var/lib/oxp3-overlay-telemetry/allow-read.py'):
        return 'components/controls/overlay/' + target.rsplit('/', 1)[1]
    prefix = 'home/deck/homebrew/plugins/opti2xmx/'
    if component == 'opti2xmx' and target.startswith(prefix):
        return 'components/opti2xmx/' + target[len(prefix):]
    for prefix in ('home/deck/homebrew/plugins/OXP3-Light/',
                   'var/lib/oxp3-installer/decky/runtime/plugins/OXP3-Light/'):
        if component == 'oxp3-light' and target.startswith(prefix):
            return 'components/light/' + target[len(prefix):]
    gyro = {'load.sh', 'unload.sh', 'launch.sh'}
    if component == 'gyro' and target.startswith('var/lib/oxp3-gyro-v1/') and target.rsplit('/', 1)[1] in gyro:
        return 'components/gyro/' + target.rsplit('/', 1)[1]
    if component == 'gyro' and target == 'etc/systemd/system/oxp3-gyro.service':
        return 'components/gyro/oxp3-gyro.service'
    if component == 'gyro' and target == 'etc/systemd/system/inputplumber.service.d/oxp3-gyro-v1.conf':
        return 'components/gyro/inputplumber.conf'
    if component == 'input' and target == 'usr/local/lib/oxp3-input/input_profile.py':
        return 'components/input_profile.py'
    if component == 'input' and target == 'etc/systemd/system/inputplumber.service.d/oxp3-input-profile.conf':
        return 'components/input-profile.conf'
    if component == 'input' and target == 'etc/inputplumber/devices.d/50-onexplayer_3.yaml':
        return 'components/input-profile.yaml'
    return None


def _maintenance_options(options, additions):
    result = json.loads(json.dumps(options))
    if additions is None:
        return result
    if (additions.get('schema') != 1 or set(additions) != {'schema', 'repairs', 'plugins'}
            or any(not isinstance(additions[group], list) for group in ('repairs', 'plugins'))):
        raise PreparationError('Invalid maintenance-only options')
    existing = {item['id'] for group in ('repairs', 'plugins') for item in result[group]}
    for group in ('repairs', 'plugins'):
        expected = {'serial-console-policy'} if group == 'repairs' else {'autoflatpaks-compat', 'animation-changer-compat'}
        for item in additions[group]:
            if not isinstance(item, dict) or item.get('id') in existing:
                raise PreparationError('Duplicate maintenance-only option')
            if item.get('id') not in expected:
                raise PreparationError('Unreviewed maintenance-only adapter/category')
            if item.get('default') is not (group == 'repairs') or item.get('dependencies') != []:
                raise PreparationError('Invalid maintenance-only defaults/dependencies')
            if any(not isinstance(item.get(key), str) or not item[key] for key in ('zh', 'en')):
                raise PreparationError('Missing maintenance option labels')
            existing.add(item['id'])
            result[group].append(item)
    return result


def prepare_payload(workspace, output, maintenance_options=None):
    workspace, output = Path(workspace).resolve(), Path(output).absolute()
    installer = workspace / 'windows-installer'
    if output.exists() or output.is_symlink():
        raise PreparationError('Output must be a new isolated directory')
    # Output may be under the maintenance worktree, never in an input tree.
    for tree in ('components', 'cache', 'licenses'):
        if output.resolve().is_relative_to((installer / tree).resolve()):
            raise PreparationError('Output overlaps installer input: ' + tree)
    if not output.parent.is_dir():
        raise PreparationError('Output parent must exist')
    for ancestor in (output.parent, *output.parent.parents):
        info = ancestor.lstat()
        if ancestor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PreparationError('Output parent contains a symlink or junction')
    output = output.resolve()
    try:
        original_options = sanitize_options(_json(_source(installer, 'components/options.json')))
        additions = _json(Path(maintenance_options)) if maintenance_options is not None else None
        options = _maintenance_options(original_options, additions)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    if options.get('schema') != 1:
        raise PreparationError('Unsupported options schema')
    items = {}
    for category in ('repairs', 'plugins'):
        if not isinstance(options.get(category), list):
            raise PreparationError('Missing component option category: ' + category)
        for item in options[category]:
            name = item.get('id')
            if not isinstance(name, str) or not re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', name) or name in items:
                raise PreparationError('Invalid or duplicate option ID')
            if not isinstance(item.get('dependencies'), list):
                raise PreparationError('Missing dependencies for ' + name)
            items[name] = item
    for name, item in items.items():
        if any(d not in items for d in item['dependencies']):
            raise PreparationError('Unknown option dependency: ' + name)
    complete, visiting = set(), set()
    def visit(name):
        if name in visiting:
            raise PreparationError('Cyclic option dependency: ' + name)
        if name in complete:
            return
        visiting.add(name)
        for dependency in items[name]['dependencies']:
            visit(dependency)
        visiting.remove(name)
        complete.add(name)
    for name in items:
        visit(name)
    manifest = sanitize_metadata('integration/manifest.json',
                                _json(_source(installer, 'cache/integration/manifest.json')))
    if not isinstance(manifest, dict) or set(manifest) - set(items):
        raise PreparationError('Integration manifest IDs disagree with current options')
    release = _metadata(installer)
    for cached in ('cache/components/release.json', 'cache/integration/release.json'):
        path = installer / cached
        if path.exists() and _json(_source(installer, cached)) != release:
            raise PreparationError('Cached release disagrees with current release metadata')
    desktop = manifest.get('desktop-hdr')
    if isinstance(desktop, dict) and desktop.get('runtime_archive'):
        runtime_relative = 'cache/integration/' + _relative(desktop['runtime_archive'])
        try:
            runtime = _source(installer, runtime_relative)
        except FileNotFoundError:
            runtime = None
        if runtime is not None:
            try:
                validate_desktop_hdr_runtime(runtime)
            except DesktopHdrPolicyError as exc:
                raise PreparationError('Rebuild the fixed KWin and mapped-HDR frontend with the EDID-only policy before preparing maintenance payloads; rejected cache: ' + str(exc)) from exc
    report = {'schema': 1, 'release': release, 'source_inventory': {},
              'refreshed_integration': [], 'coverage': {},
              'separate_operations': EXCLUDED,
              'scope': 'Prepared resource presence only; compatibility and activation require maintenance preflight.',
              'warnings': ['Existing native binaries retain their exact SteamOS/kernel/package restrictions.',
                           'Freshness checks cover explicit public component source mappings; prepared native/research-derived binaries are retained without claims of rebuilding or latest-source parity.',
                           'Research directories, device snapshots, Windows runtimes and OS images are never scanned.']}
    stage = Path(tempfile.mkdtemp(prefix='oxp3-payload-', dir=output.parent))
    missing = {name: [] for name in items}
    copied = set()

    def copy(relative, destination=None, *, optional_for=None, data=None):
        destination = _relative(destination or relative)
        if not distributable_path(destination):
            return
        if not _allowed(destination):
            raise PreparationError('Forbidden output resource: ' + destination)
        try:
            source = _source(installer, relative)
        except FileNotFoundError:
            if optional_for is None:
                raise PreparationError('Missing required resource: ' + relative)
            missing[optional_for].append(relative)
            return
        raw = source.read_bytes()
        if any(marker in raw for marker in (b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN OPENSSH PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----')):
            raise PreparationError('Private key material in resource: ' + relative)
        value = raw if data is None else data
        if destination in ('components/options.json', 'components/fulloptions.json'):
            value = json_bytes(_maintenance_options(sanitize_options(json.loads(value.decode('utf-8-sig'))), additions))
        if destination.endswith('.json'):
            value = json_bytes(sanitize_metadata(destination, json.loads(value.decode('utf-8-sig'))))
        if destination in copied:
            if (stage / destination).read_bytes() != value:
                raise PreparationError('Conflicting staged resource: ' + destination)
            return
        target = stage / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
        copied.add(destination)
        report['source_inventory'][destination] = {
            'source': 'windows-installer/' + relative,
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'sha256': hashlib.sha256(value).hexdigest(), 'size': len(value)}

    try:
        # Public source is data in the signed bundle, never imported here.
        for parent, directories, files in os.walk(installer / 'components', followlinks=False):
            for directory in directories:
                candidate = Path(parent) / directory
                if candidate.is_symlink() or getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise PreparationError('Linked component directory refused')
            directories[:] = sorted(d for d in directories if _allowed(d) and distributable_path(
                (Path(parent) / d).relative_to(installer).as_posix()))
            for filename in sorted(files):
                relative = (Path(parent) / filename).relative_to(installer).as_posix()
                if not _allowed(relative) or filename.startswith('test_'):
                    continue
                if Path(filename).suffix.lower() in SOURCE_SUFFIXES or 'license' in filename.lower() or filename.startswith('oxp3-'):
                    copy(relative)
        for name, metadata in manifest.items():
            if not isinstance(metadata, dict) or not isinstance(metadata.get('files'), list):
                raise PreparationError('Invalid integration record: ' + name)
            for entry in metadata['files']:
                source = _relative(entry['source'])
                target = _relative(entry['target'])
                destination = 'integration/' + source
                if name == 'gyro' and target == 'var/lib/oxp3-gyro-v1/binding.py':
                    helper = _source(workspace, 'steamos-maintenance/oxp3_maintenance/gyro_binding.py').read_bytes()
                    if _source(installer, 'cache/integration/' + source).read_bytes() != helper:
                        raise PreparationError('Rebuild gyro integration payload from the current binding helper')
                if name == 'gyro' and target == 'var/lib/oxp3-gyro-v1/oxp3_bmi260.ko':
                    module = _source(installer, 'cache/integration/' + source).read_bytes()
                    if b'oxp3_model_policy=hardware-interface-v2\x00' not in module:
                        raise PreparationError('Rebuild the model-independent BMI260 module before preparing maintenance payloads')
                current = _current_source(name, target)
                if current:
                    raw = _source(installer, current).read_bytes()
                    cached = _source(installer, 'cache/integration/' + source).read_bytes()
                    # Preserve the installer activation guard when refreshing units.
                    if target.endswith('.service') and OLD_GUARD in cached and OLD_GUARD not in raw:
                        raw = raw.replace(b'[Service]\n', b'[Service]\n' + OLD_GUARD + b'\n', 1)
                    if raw != cached:
                        report['refreshed_integration'].append({'component': name, 'target': target,
                            'source': current, 'cached_sha256': hashlib.sha256(cached).hexdigest(),
                            'sha256': hashlib.sha256(raw).hexdigest()})
                    copy(current, destination, data=raw)
                else:
                    copy('cache/integration/' + source, destination, optional_for=name)
            if metadata.get('runtime_archive'):
                value = _relative(metadata['runtime_archive'])
                copy('cache/integration/' + value, 'integration/' + value, optional_for=name)
            missing[name].extend(str(x) for x in metadata.get('missing', []))
        copy('cache/integration/manifest.json', 'integration/manifest.json')
        # Third-party archives/profiles (including stale source caches) are no
        # longer distribution inputs. Existing device plugins are unaffected.
        if 'decky' in items:
            copy('cache/plugins/decky/PluginLoader', 'plugins/decky/PluginLoader', optional_for='decky')
        for source_name, destination, owner in (('hdr', 'hdr', 'hdr'), ('oxp3-controls', 'controls', 'native-tdp'), ('waydroid', 'waydroid', 'waydroid')):
            if owner not in items:
                continue
            relative = 'cache/components/' + source_name + '/profile.json'
            if not (installer / relative).exists():
                if owner in missing:
                    missing[owner].append(relative)
                continue
            profile = _json(_source(installer, relative))
            if profile.get('schema') != 1 or profile.get('id') != source_name:
                raise PreparationError('Resource profile identity mismatch: ' + relative)
            names = ['profile.json', profile['archive']]
            if source_name == 'waydroid':
                names += [profile['source_archive'], 'intel-ibt-kernel-calls.patch']
            for value in names:
                if '/' in _relative(value):
                    raise PreparationError('Resource profile archive must be a leaf filename')
                copy('cache/components/' + source_name + '/' + value,
                     destination + '/' + value, optional_for=owner)
        license_root = installer / 'licenses'
        if license_root.is_dir():
            for parent, directories, files in os.walk(license_root, followlinks=False):
                for directory in directories:
                    if (Path(parent) / directory).is_symlink():
                        raise PreparationError('Linked license directory refused')
                directories[:] = sorted(d for d in directories if _allowed(d))
                for filename in sorted(files):
                    relative = (Path(parent) / filename).relative_to(installer).as_posix()
                    if _allowed(relative):
                        copy(relative)
        project_license = _source(workspace, 'LICENSE')
        target = stage / 'licenses/PROJECT-LICENSE'
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = project_license.read_bytes()
        target.write_bytes(raw)
        report['source_inventory']['licenses/PROJECT-LICENSE'] = {'source': 'LICENSE',
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        requirements = {
            'slot-switch': ['components/slot-switch/' + name for name in (
                'boot.py', 'desktop.py', 'oxp3-switch-slot',
                '49-oxp3-slot-switch.rules', 'oxp3-slot-switch.desktop')],
            'partition-mount': ['components/partition_mount.py'] + [
                'components/partition-mount/' + name for name in (
                    'mounts.py', 'desktop.py', 'oxp3-partition-mount', 'oxp3-partition-mount.desktop')],
            'serial-console-policy': ['components/serial_console.py'],
            'split-lock': ['components/split-lock/UPSTREAM_LICENSE'],
            'oxp3-light': ['components/light/' + name for name in (
                'main.py', 'light_control.py', 'plugin.json', 'package.json',
                'dist/index.js', 'LICENSE', 'LICENSE-HHD', 'LICENSE-HueSync',
                'THIRD_PARTY_NOTICES.md', 'README.md')],
            'hdr': ['components/hdr/upstream.lua'],
            'desktop-hdr': ['components/desktop-hdr/' + name for name in (
                'hdr_trial.py', 'x2mini_device.py', 'install-x2mini-hdr.sh', 'launch.sh')],
            'flathub-ustc': ['components/flathub.flatpakrepo'],
            'input': ['components/input-profile.yaml'],
            'windows-reboot': ['components/windows-reboot/' + name for name in (
                'main.py', 'plugin.json', 'package.json', 'dist/index.js', 'boot.py',
                'desktop.py', 'oxp3-reboot-windows', 'oxp3-reboot-windows.desktop',
                'org.oxp3.restart-windows.policy', '49-oxp3-restart-windows.rules')],
        }
        for name, paths in requirements.items():
            if name in items:
                missing[name].extend(path for path in paths if path not in copied)
        # Refuse a concurrently changed source identity instead of publishing a
        # report for one release/options set alongside another set of bytes.
        if (_json(stage / 'components/options.json') != options or _metadata(stage) != release
                or sanitize_options(_json(_source(installer, 'components/options.json'))) != original_options
                or maintenance_options is not None and _json(Path(maintenance_options)) != additions):
            raise PreparationError('Release/options changed during payload preparation')
        for name, item in items.items():
            if name in EXCLUDED:
                status, reason = 'excluded', EXCLUDED[name]
            elif name not in SPECIAL | MANIFEST_ADAPTERS:
                status, reason = 'unsupported', 'No maintenance adapter is registered for this current option.'
            else:
                if name in MANIFEST_ADAPTERS and name not in manifest:
                    missing[name].append('integration/manifest.json entry: ' + name)
                status = 'missing' if missing[name] else 'adapter_supported'
                reason = 'Missing prepared resources.' if missing[name] else 'Resources staged; runtime compatibility still requires preflight.'
            report['coverage'][name] = {'status': status, 'reason': reason,
                'dependencies': item['dependencies'], 'missing': sorted(set(missing[name]))}
        # A missing dependency is visible even when the leaf has its own resources.
        for _ in items:
            for name, item in report['coverage'].items():
                blocked = [d for d in item['dependencies'] if report['coverage'][d]['status'] != 'adapter_supported']
                if item['status'] == 'adapter_supported' and blocked:
                    item.update(status='dependency_unavailable', reason='Unavailable dependencies: ' + ', '.join(blocked))
        report['resource_complete'] = all(v['status'] in ('adapter_supported', 'excluded') for v in report['coverage'].values())
        (stage / 'components/preparation-report.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        stage.rename(output)
        return report
    except BaseException:
        # Only this function's fresh temporary directory is removed.
        shutil.rmtree(stage)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--maintenance-options', type=Path,
                        default=Path(__file__).resolve().parent / 'release/maintenance-options.json')
    args = parser.parse_args(argv)
    try:
        report = prepare_payload(args.workspace, args.output, maintenance_options=args.maintenance_options)
    except (OSError, ValueError, KeyError, TypeError, BundleError) as exc:
        parser.exit(1, 'Payload preparation failed: %s\n' % exc)
    print(json.dumps({'release': report['release']['version'], 'resource_complete': report['resource_complete'],
                      'coverage': report['coverage'], 'report': str(args.output / 'components/preparation-report.json')}, ensure_ascii=False, indent=2))
    return 0 if report['resource_complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
