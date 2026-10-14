"""Explicit firstboot choices, independent from passive resource carriage."""
import copy
from uuid import UUID
HDR_SOURCE = {'version': '3.10', 'build': '20260924.1000'}
def selected(selection):
    choices = selection.get('components', [])
    if not isinstance(choices, list) or any(type(item) is not str or item != 'hdr' for item in choices) or len(set(choices)) != len(choices):
        raise ValueError('Unknown/duplicate firstboot component')
    if selection.get('plugins', []): raise ValueError('Plugin activation adapter is not available')
    if choices:
        if selection.get('source') != HDR_SOURCE: raise ValueError('HDR requires the accepted SteamOS 3.10 build; this media is incompatible')
        if 'hdr' not in selection.get('resources', []): raise ValueError('Selected HDR component requires its carried resource')
    return copy.deepcopy(choices)
def request(selection, operation_id):
    choices = selected(selection)
    if str(UUID(operation_id)) != operation_id: raise ValueError('Canonical installation operation ID required')
    source = selection.get('source')
    if not isinstance(source, dict) or set(source) != {'version', 'build'} or any(type(value) is not str or not value for value in source.values()):
        raise ValueError('Component request source metadata missing')
    return {'schema': 1, 'id': operation_id, 'components': choices, 'source': copy.deepcopy(source), 'user': 'deck'}
