# Opti2XMX 0.3.0

The existing **Upscaling output** control now offers **XeSS** and **FSR 4.1.2 Lite XMX** while XMX is enabled. XeSS remains the default. Selecting FSR prepares the pinned OptiScaler 10 preview, enables the per-game XMX bridge, and saves the selected output for the next Steam launch. GPU identity remains Intel.

FSR requires the user's original `FSR-4.1.2-Lite-XMX-OptiClick-0.6.zip`. The file picker imports and verifies that exact build locally. Its upscaler, weights and NVIDIA DLL are not distributed in this plugin, the Windows installer or maintenance packages. See [FSR XMX](FSR_XMX.md) for the supported archive and limitations.

The public plugin includes the source and licenses of a small LZMS decompression adapter and wimlib. It uses a private import name and does not replace Wine's Cabinet DLL. The per-game compiler adapter corrects the verified FSR PRE kernel's root-table metadata while preserving its machine code. Other kernels retain their original compiler path.

Turning XMX off returns to XeSS rather than leaving the XMX-only FSR model selected. Per-game preparation, injection toggles, settings undo and uninstall keep recoverable originals. Existing mixed manual Opti 0.9.4 installations can be adopted only when the core matches the exact official release; existing companion files are backed up as user originals.

## Validation

- 222 backend tests, frontend behavior checks, TypeScript checking and production build passed.
- The decompression adapter decoded all six real resource packs (136,704,915 output bytes) identically to the reference on Windows and Proton Experimental. Malformed framing, missing dependencies and handle lifecycle checks passed. Repeated builds produced identical DLL hashes.
- SteamOS 3.10 / Intel Arc B390 / the published patched Mesa 26.1.2 runtime / Proton Experimental / Cyberpunk 2077 2.31: FSR completed the 64.20-second benchmark at 30.06 average FPS; switching back to XeSS completed 64.24 seconds at 30.17 FPS. Output was 1920×1200, FSR input 1280×800, frame generation and ray tracing off. Both runs used the managed game setup and showed no device-lost exception.
- Real uninstall restored all 98 original tracked game files byte-for-byte, the original Steam launch options and original game settings. The new installation was then restored with XeSS selected and XMX off.

This is a compatibility feature tested on the configuration above. The two single runs establish that both paths complete; they do not establish a performance advantage. Other GPUs, games, model builds, ray tracing and frame generation combinations remain unverified.

Installer and maintenance delivery retain the separate published XeSS runtime and the two stable Opti archives, and add the pinned `nightly-20261025` Opti 10 archive. FSR model import remains a local user action.
