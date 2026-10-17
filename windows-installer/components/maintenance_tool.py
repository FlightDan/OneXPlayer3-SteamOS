"""Offline integration of the same GTK application shipped by maintenance releases."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def files(root, payload, release):
    app = Path(payload) / 'maintenance/app'
    manifest = json.loads((app.parent / 'manifest.json').read_text())
    if manifest.get('schema') != 1 or not isinstance(manifest.get('files'), dict):
        raise RuntimeError('Invalid maintenance application manifest')
    actual = {p.relative_to(app).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in app.rglob('*') if p.is_file()}
    if actual != manifest['files']:
        raise RuntimeError('Maintenance application differs from its staged manifest')
    # Load the package under its own name; runtime_files only generates bytes.
    # In particular, never call the live installer/probe/service entry points.
    spec = importlib.util.spec_from_file_location('oxp3_maintenance', app / 'oxp3_maintenance/__init__.py',
                                                submodule_search_locations=[str(app / 'oxp3_maintenance')])
    if 'oxp3_maintenance' in sys.modules:
        raise RuntimeError('Maintenance package already loaded before offline preparation')
    module = importlib.util.module_from_spec(spec)
    sys.modules['oxp3_maintenance'] = module
    try:
        spec.loader.exec_module(module)
        from oxp3_maintenance.operations import runtime_files
        result = runtime_files(app, release, {'components': {}},
                               installed_runtime=Path(root) / 'usr/local/lib/oxp3-maintenance')
    finally:
        for name in list(sys.modules):
            if name == 'oxp3_maintenance' or name.startswith('oxp3_maintenance.'):
                del sys.modules[name]
    return result
