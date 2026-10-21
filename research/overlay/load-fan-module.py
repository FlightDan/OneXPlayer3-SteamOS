from pathlib import Path
import platform
import subprocess

assert platform.release() == '7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9'
if not Path('/sys/module/oxpec').exists():
    subprocess.run(['insmod','/var/lib/oxp3-fan/oxpec.ko'],check=True)
