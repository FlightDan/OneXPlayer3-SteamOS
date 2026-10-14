#!/bin/sh
set -eu
. /mnt/payload/tasks/common.sh
python3 -B /mnt/payload/tasks/test_fs_metadata.py
test "$(cat /sys/block/vdc/ro)" = 1
python3 - <<'PY'
import sys
from uuid import UUID
sys.path.insert(0, '/mnt/payload/tasks')
from fs_metadata import probe
if probe('/dev/vdc3') != 'btrfs' or UUID(probe('/dev/vdc3', 'UUID')).int == 0:
    raise RuntimeError('Recovery root filesystem metadata is invalid')
print('OXP_FS_METADATA=actual-btrfs-uuid-field-not-device-description')
PY
mkdir -p /mnt/root /mnt/efi /mnt/home
mount -t btrfs -o ro,rescue=nologreplay /dev/vdc3 /mnt/root || { dmesg | tail -40; exit 1; }
test "$(btrfs property get -ts /mnt/root ro)" = 'ro=true'
test -s /mnt/root/usr/local/lib/oxp3-installer/preview.py
test -s /mnt/root/usr/local/lib/oxp3-installer/installer_ui.py
chroot /mnt/root /usr/bin/python3 -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/oxp3-installer"); import installer_ui, ui_backend, ui_model, install_session, intent_store, deployment, fs_metadata'
if test -f /mnt/root/usr/local/share/oxp3-installer/media-layer.json; then
    python3 -B /mnt/payload/tasks/media_layer.py inspect /mnt/root
    printf '\nOXP_MEDIA_SOURCE=owned-detachable-layer\n'
else
    printf '\nOXP_MEDIA_SOURCE=legacy-preview-not-deployable\n'
fi
if test -f /mnt/root/usr/local/lib/oxp3-installer/console/oxp3-owned; then
    test -x /mnt/root/usr/local/lib/oxp3-installer/console/kmscon
    test -s /mnt/root/usr/local/lib/oxp3-installer/console/libtsm.so.4
    test -s /mnt/root/usr/lib/x86_64-linux-gnu/kmscon/mod-bbulk.so
    grep -q 'ExecStart=/usr/bin/python3 /usr/local/lib/oxp3-installer/preview-launcher.py' /mnt/root/etc/systemd/system/oxp3-preview.service
    chroot /mnt/root /usr/bin/env LD_LIBRARY_PATH=/usr/local/lib/oxp3-installer/console \
        /usr/local/lib/oxp3-installer/console/kmscon --help >/tmp/oxp3-console-help.txt 2>&1
    grep -q 'font-engine' /tmp/oxp3-console-help.txt
    printf '\nOXP_PREVIEW_CONSOLE=drm-runtime-compatible-visible-boot-separate\n'
fi
grep -q 'preview_only' /mnt/root/usr/local/share/oxp3-installer/selection.json
mount -o ro /dev/vdc5 /mnt/home
python3 - <<'PY'
import io, json, re, subprocess, tarfile
from pathlib import Path
selection = json.loads(Path('/mnt/root/usr/local/share/oxp3-installer/selection.json').read_text())
if 'hdr' in selection.get('resources', []):
    import ast, zipfile
    directory = Path('/mnt/home/oxp3-resources/hdr')
    profile = json.loads((directory / 'profile.json').read_text(encoding='utf-8-sig'))
    if profile['version'] not in ('20261013-hdr-r2', '20261013-hdr-r3') or profile['deployment'] != 'configuration_files_only' or profile['default'] is not False:
        raise RuntimeError('Unexpected HDR resource capability/version')
    with zipfile.ZipFile(directory / profile['archive']) as package:
        if set(package.namelist()) != set(profile['source_files']): raise RuntimeError('Unexpected HDR resource file set')
        if profile['version'] == '20261013-hdr-r3' and 'shared_state.py' not in package.namelist(): raise RuntimeError('Missing shared HDR state implementation')
        for name in package.namelist():
            if name.endswith('.py'): ast.parse(package.read(name).decode())
        lua = package.read('hdr/upstream.lua').decode()
        if 'max_frame_average_luminance = 472,' not in lua or 'max_content_light_level = 1100,' not in lua or lua.count('gamescope.hook("OnPostPaint"') != 1:
            raise RuntimeError('HDR source mapping/composition regressed')
        if 'string.match(display.model, "^%s*(.-)%s*$") == "AMS881KB01-0"' not in lua: raise RuntimeError('HDR panel guard missing')
    if (Path('/mnt/home') / 'deck/.config/gamescope/scripts/98-oxp3-oled-hdr.lua').exists(): raise RuntimeError('HDR resources unexpectedly activated in preview')
    print('OXP_HDR_RESOURCE=accepted-template-logical-file-recovery-not-activated')
if 'oxp3-controls' in selection.get('resources', []):
    import zipfile
    directory = Path('/mnt/home/oxp3-resources/oxp3-controls')
    profile = json.loads((directory / 'profile.json').read_text())
    if profile['version'] not in ('20261013', '20261013-r2') or profile['deployment'] != 'resources_only': raise RuntimeError('Wrong control source bundle')
    with zipfile.ZipFile(directory / profile['archive']) as package:
        if set(package.namelist()) != set(profile['source_files']): raise RuntimeError('Unexpected control source files')
        if 'MAX_WATTS = 40' not in package.read('rapl/provider.py').decode(): raise RuntimeError('Old TDP range')
        if profile['version'] == '20261013-r2':
            if profile['battery']['default_policy_change'] is not False: raise RuntimeError('Unexpected battery policy capability')
            if profile['plugin_languages']['other_languages_and_missing_locale'] != 'en': raise RuntimeError('Missing language fallback')
            for frontend in ('overlay/cpu-plugin-index.js', 'overlay/fan-plugin-index.js', 'charging/battery-plugin-index.js'):
                if 'navigator?.language' not in package.read(frontend).decode(): raise RuntimeError('Missing embedded bilingual frontend')
            for file in ('charging/check-battery-ui.mjs', 'check-plugin-i18n.mjs', 'PLUGIN_LANGUAGES.md'):
                if file not in package.namelist(): raise RuntimeError('Missing control language/interaction source')
    print('OXP_CONTROL_RESOURCE=40w-overlay-fan-cpu-sources-not-installed')
if 'waydroid' in selection.get('resources', []):
    directory = Path('/mnt/home/oxp3-resources/waydroid')
    profile = json.loads((directory / 'profile.json').read_text())
    version = 'steamos-3.10-b20260924.1000-wlroots0.20.2-oxp3-r2'
    if profile['bundle_version'] != version: raise RuntimeError('Wrong Waydroid resource version')
    for filename in (profile['archive'], profile['source_archive'], 'intel-ibt-kernel-calls.patch'):
        if Path(filename).name != filename or not (directory / filename).is_file(): raise RuntimeError('Incomplete Waydroid resource')
    with tarfile.open(directory / profile['archive'], 'r:gz') as bundle:
        binder = bundle.extractfile(version + '/packages/steamos-waydroid-binder-1-2-x86_64.pkg.tar.zst').read()
    uncompressed = subprocess.check_output(['zstd', '-d', '-c'], input=binder)
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:') as package:
        information = package.extractfile('.PKGINFO').read().decode()
        if 'pkgver = 1-2\n' not in information: raise RuntimeError('Old Binder r1 was included')
        module = package.extractfile('usr/lib/modules/' + profile['system']['kernel'] + '/updates/steamos-waydroid/binder_linux.ko').read()
        if ('vermagic=' + profile['system']['kernel'] + ' ').encode() not in module: raise RuntimeError('Wrong Binder kernel metadata')
    print('OXP_WAYDROID_RESOURCE=accepted-r2-cached-not-installed')
PY
umount /mnt/home
test -L /mnt/root/etc/systemd/system/oxp3-preview.target.wants/oxp3-preview.service
mount -o ro /dev/vdc2 /mnt/efi
grep -q 'systemd.unit=oxp3-preview.target' /mnt/efi/EFI/steamos/grub.cfg
if grep -q 'fsck.mode=auto' /mnt/efi/EFI/steamos/grub.cfg; then exit 1; fi
umount /mnt/efi
umount /mnt/root
printf '\nOXP_TASK_RESULT=passed\n'
