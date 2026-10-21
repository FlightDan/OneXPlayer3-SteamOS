# SPDX-License-Identifier: GPL-2.0-or-later
# Startup compatibility fallback: retain other display settings.
from pathlib import Path
import json, os, stat, tempfile
p=Path("/home/deck/.config/kwinoutputconfig.json")
if not p.exists(): raise SystemExit(0)
if p.is_symlink(): raise RuntimeError("Output configuration is a symlink")
original=p.stat()
value=json.loads(p.read_text())
changed=False
for group in value:
    if group.get("name")!="outputs": continue
    for output in group.get("data",[]):
        if output.get("connectorName")!="eDP-1": continue
        for key in ("highDynamicRange","wideColorGamut"):
            if output.get(key): output[key]=False; changed=True
if changed:
    fd,name=tempfile.mkstemp(prefix=".oxp3-hdr-safe-",dir=p.parent)
    try:
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),stat.S_IMODE(original.st_mode))
            json.dump(value,f,indent=4); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(name,p)
        d=os.open(p.parent,os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(name): os.unlink(name)
