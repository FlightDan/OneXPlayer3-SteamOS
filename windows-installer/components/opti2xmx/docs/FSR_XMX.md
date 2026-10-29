# FSR 4.1.2 Lite XMX

Opti2XMX 0.3.0 adds FSR 4.1.2 Lite XMX to the existing **Upscaling output**
selector. XeSS remains the default. Exit the game before saving either choice.

Import the original `FSR-4.1.2-Lite-XMX-OptiClick-0.6.zip` with the local file
picker. The plugin accepts only the exact archive described in `fsr-source.json`.
The model DLLs remain in the user's private cache; they are not included in the
plugin, maintenance update or Windows installer. A matching file already imported
on the device is retained during updates.

Saving FSR prepares the pinned OptiScaler 10 build and the model for that game,
then enables XMX before applying FSR. The action preserves the existing Opti
rollback journal and confirms each Steam launch-option change. Selecting XeSS
uses the same managed installation. Disabling XMX restores a XeSS-safe INI;
an undo from the previous FSR session cannot enable FSR on the stock driver.

The public package contains the `fsrxdec` decompression adapter and the LGPL
Windows build of wimlib, with their licenses and corresponding source. Import
adapts only the model DLL's Cabinet import name to the dedicated adapter. No
Microsoft Cabinet DLL is copied or redistributed, and the game's system Cabinet
imports are not replaced.

The CM compiler wrapper corrects the verified PRE kernel's descriptor-table
offset, including its trailing sampler table. It changes only CMK resource
metadata; XeSS and other kernels pass through. Each new XMX setup keeps its own
wrapper copy, so replacing the plugin does not change an existing launcher.

The validated profile is the exact model/Opti build with the 20261005 XMX runtime
on SteamOS and Intel Arc B390. Other games, GPUs, ray tracing and frame-generation
combinations retain their experimental compatibility status. FSR support does
not imply support for FSR frame generation or a particular performance gain.

See `docs/RELEASE-0.3.0.md` for final source, installer, maintenance and device
verification results. If a file has been edited by another tool, preserve it and
use the displayed recovery action instead of overwriting the conflict.
