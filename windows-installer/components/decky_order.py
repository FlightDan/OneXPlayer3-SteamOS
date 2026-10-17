"""Seed native Decky ordering and insert newly introduced OXP3 Light safely."""
import base64
import json
from pathlib import Path
import stat
from file_transaction import snapshot

SETTINGS = 'var/lib/oxp3-installer/decky/runtime/settings/loader.json'
PLUGINS = 'var/lib/oxp3-installer/decky/runtime/plugins'
PRIORITY = ('OXP3 CPU', 'OXP3 Fan', 'OXP3 Battery', 'OXP3 Light', 'Opti2XMX', 'Restart into Windows')


def ordered_settings(settings, names):
    """Return changed settings or None; existing relative order always survives."""
    if 'pluginOrder' in settings:
        order = settings['pluginOrder']
        if (settings.get('sortPlugins') is True or not isinstance(order, list) or not order
                or any(not isinstance(name, str) for name in order)
                or 'OXP3 Light' not in names or 'OXP3 Light' in order):
            return None
        order = list(order)
        anchor = next((name for name in reversed(PRIORITY[:3]) if name in order), None)
        order.insert(order.index(anchor) + 1 if anchor else len(order), 'OXP3 Light')
        return dict(settings, pluginOrder=order)
    if 'sortPlugins' in settings or not any(name in names for name in PRIORITY):
        return None
    return dict(settings, pluginOrder=[name for name in PRIORITY if name in names]
                + [name for name in names if name not in PRIORITY], sortPlugins=False)


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
    settings = ordered_settings(settings, names)
    if settings is None:
        return {}
    return {SETTINGS: {'data': (json.dumps(settings, ensure_ascii=False, indent=2)+'\n').encode('utf-8')}}
