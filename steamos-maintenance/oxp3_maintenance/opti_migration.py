"""The bounded ownership transition for the formerly bundled Opti runtime.

These predicates grant no generic ownership-transfer capability. The transaction
store still authenticates live snapshots, original backups, and shared owners.
"""

PLUGIN = 'opti2xmx'
RUNTIME = 'opti2xmx-runtime'
RUNTIME_PREFIX = 'opt/oxp3-opti2xmx/20261005/'
RUNTIME_CONFIG = 'home/deck/.local/share/opti2xmx/runtime.json'


def runtime_path(path):
    return (path == RUNTIME_CONFIG or path.startswith(RUNTIME_PREFIX))


def transfer_allowed(path, previous, target, selected):
    return (runtime_path(path) and previous == PLUGIN and target == RUNTIME
            and RUNTIME in selected)


def retain_legacy_runtime(path, owner, selected):
    return (runtime_path(path) and owner == PLUGIN and PLUGIN in selected
            and RUNTIME not in selected)
