# SPDX-License-Identifier: GPL-2.0-or-later
# Apply only to Valve kwin 6.7.3-1.6 after all five PKGBUILD patches.
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
base = Path(__file__).resolve().parent
pairs = [("drm_output.candidate.cpp", "src/backends/drm/drm_output.cpp"),
         ("drm_output.candidate.h", "src/backends/drm/drm_output.h"),
         ("workspace.candidate.cpp", "src/workspace.cpp")]
for local, dest in pairs:
    assert (root / dest).is_file(), dest
assert "usesOxp3Gamma22" not in (root / pairs[0][1]).read_text()
for local, dest in pairs:
    (root / dest).write_bytes((base / local).read_bytes())
(root / "src/backends/drm/oxp3_gamma22_policy.h").write_bytes((base / "oxp3_gamma22_policy.h").read_bytes())
print("Exact-version candidate source applied; no runtime activation.")
