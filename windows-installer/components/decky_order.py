"""Seed Decky 3.2.10's native ordering once, preserving existing preferences."""
import base64
import json
from pathlib import Path
import stat
from file_transaction import snapshot

SETTINGS = 'var/lib/oxp3-installer/decky/runtime/settings/loader.json'
PLUGINS = 'var/lib/oxp3-installer/decky/runtime/plugins'
PRIORITY = ('OXP3 CPU', 'OXP3 Fan', 'OXP3 Battery', 'Opti2XMX', 'Restart into Windows')


def files(root):
    root = Path(root)
    # Decky migrates this legacy file on startup. Leave it entirely in charge.
    for legacy in ('home/deck/homebrew/loader.json', 'home/deck/homebrew/settings/loader.json'):
        if snapshot(root/legacy)['exists']:
            return {}
    saved = snapshot(root/SETTINGS)
    settings = {}
    if saved['exists']:
        try:
            settings = json.loads(base64.b64decode(saved['data']))
        except (ValueError, UnicodeError):
            return {}  # Never repair or overwrite unfamiliar user settings.
        if not isinstance(settings, dict):
            return {}
        if 'pluginOrder' in settings or 'sortPlugins' in settings:
            return {}
    names = []
    directory = root/PLUGINS
    if not directory.exists():
        return {}
    # Include every deployed plugin: Decky's indexOf sort puts omitted names first.
    for plugin in sorted(directory.iterdir(), key=lambda path: path.name):
        mode = plugin.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise RuntimeError('Symlinked Decky plugin directory refused')
        if not stat.S_ISDIR(mode):
            continue
        metadata = snapshot(plugin/'plugin.json')
        if not metadata['exists']:
            continue
        name = json.loads(base64.b64decode(metadata['data'])).get('name')
        if not isinstance(name, str) or not name or name in names:
            raise RuntimeError('Invalid or duplicate Decky plugin display name')
        names.append(name)
    if not any(name in names for name in PRIORITY):
        return {}
    settings['pluginOrder'] = [name for name in PRIORITY if name in names] + [name for name in names if name not in PRIORITY]
    settings['sortPlugins'] = False
    return {SETTINGS: {'data': (json.dumps(settings, ensure_ascii=False, indent=2)+'\n').encode('utf-8')}}
