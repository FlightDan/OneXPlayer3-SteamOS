"""Trusted native Decky order policy; never execute bundled plugin code."""
import json

SETTINGS = 'var/lib/oxp3-installer/decky/runtime/settings/loader.json'
PRIORITY = ('OXP3 CPU', 'OXP3 Fan', 'OXP3 Battery', 'OXP3 Light', 'Opti2XMX', 'Restart into Windows')


def ordered_settings(settings, names):
    """Seed a fresh order or insert Light, preserving existing relative order."""
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


def insertion_bytes(current):
    """Only the single Light insertion, with every other setting retained."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate Decky setting')
            value[key] = item
        return value
    def constant(value):
        raise ValueError('Invalid JSON Decky setting: ' + value)
    try:
        settings = json.loads(current, object_pairs_hook=unique, parse_constant=constant)
        if not isinstance(settings, dict) or 'pluginOrder' not in settings:
            return None
        changed = ordered_settings(settings, ['OXP3 Light'])
        return None if changed is None else (json.dumps(changed, ensure_ascii=False, indent=2) + '\n').encode()
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return None
