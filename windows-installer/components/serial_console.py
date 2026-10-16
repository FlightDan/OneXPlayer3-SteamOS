"""Gate the unusable OXP3 ttyS0 login console without changing kernel output."""

DROPIN = 'etc/systemd/system/serial-getty@ttyS0.service.d/90-oxp3-console.conf'
DATA = b'''# OXP3: the default ttyS0 cannot provide an interactive login terminal.
# Keep kernel console output and all other gettys unchanged.
# An intentional serial login setup can opt in through the kernel command line.
[Unit]
ConditionKernelCommandLine=oxp3.serial-console=1
'''


def files():
    # A regular drop-in uses the existing conflict-aware file transaction.
    # Unlike a /dev/null mask, it also retains a deliberate diagnostic opt-in.
    return {DROPIN: {'data': DATA}}
