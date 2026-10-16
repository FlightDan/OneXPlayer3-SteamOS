"""Plan the OXP3 serial-login policy without changing kernel console output.

The caller reads the one destination through the planner's safe-path checks.
The ordinary current-slot file transaction owns backups, apply and restore.
No service is started or enabled here: the condition takes effect on next boot.
"""

DROPIN = 'etc/systemd/system/serial-getty@ttyS0.service.d/90-oxp3-console.conf'
DATA = b'''# OXP3: the default ttyS0 cannot provide an interactive login terminal.
# Keep kernel console output and all other gettys unchanged.
# An intentional serial login setup can opt in through the kernel command line.
[Unit]
ConditionKernelCommandLine=oxp3.serial-console=1
'''


def files(existing=None):
    """Return a fixed drop-in; preserve a different administrator policy.

    ``existing`` is the safely read destination's bytes, or None when absent.
    A pre-existing identical hotfix is valid; its original state remains the
    transaction layer's responsibility. This never clears failed-unit state or
    changes a getty mask, another drop-in, GRUB, or /proc/cmdline.
    """
    if existing is not None and not isinstance(existing, bytes):
        raise ValueError('Invalid existing serial-console policy')
    if existing is not None and existing != DATA:
        raise ValueError('Existing serial-console drop-in differs; preserve it for review')
    return {DROPIN: {'data': DATA, 'mode': 0o644, 'user': False, 'mutable': False}}
