# Opti2XMX

[English](README.md) | [简体中文](README.zh-CN.md)

**A Decky plugin for per-game OptiScaler management and Intel XeSS XMX setup on SteamOS.**

Version **0.2.6** · AGPL-3.0-only license

This release adds experimental XeSS FG 2x/3x/4x requests, independent settings undo, and a Proton-safe XMX shim path. Short Cyberpunk 2077 benchmarks and rollback were tested on one Intel handheld; the FG controls retain their experimental label. See [FG testing and recovery](docs/FRAME_GENERATION.md).

## Features

- Install OptiScaler 0.9.4 or 0.7.9, migrate recognized existing installations, and roll back changes.
- A separate **Download and configure XMX runtime** action shows the download size, stages, progress and result. The plugin ZIP stays small; OptiScaler works without this runtime.
- Enable or restore a per-game XMX setup for compatible Intel hardware.
- Toggle Opti injection separately, retaining XMX settings and backups.
- Configure upscaling, frame-generation output and GPU identity; open the Opti overlay.
- Request experimental Opti XeSS FG 2x/3x/4x output, with independent settings undo and interrupted-write recovery.
- Chinese and English interface, following Steam's language.
- Download progress reports actual bytes, known totals and extraction/installation stages. Unknown totals do not display a percentage. Busy and error messages remain visible.

Closing the panel does not cancel the backend installation. Reopening attaches to the active operation; pending launch setup remains available for confirmation or recovery. Progress reconnects use a five-second read-only timeout and retain the last snapshot with a retry notice. Installation commands are never automatically retried.

This is an independent, unofficial project. It is not affiliated with Intel, Valve, Decky or OptiScaler.

## Screenshots

Main controls (English interface):

![Opti2XMX main controls showing XMX acceleration and Opti injection](assets/screenshots/main-en.png)

Advanced settings (English interface):

![Opti2XMX advanced settings showing upscaling, frame generation and GPU identity](assets/screenshots/advanced-en.png)

Cyberpunk 2077 2.31 built-in benchmark, requested XeSS FG 4x, ray tracing off, with OptiScaler's English performance OSD:

![Cyberpunk 2077 benchmark with the English OptiScaler performance OSD, scene 1](assets/screenshots/cyberpunk-xess-4x-en-01.png)

![Cyberpunk 2077 benchmark with the English OptiScaler performance OSD, scene 2](assets/screenshots/cyberpunk-xess-4x-en-02.png)

![Cyberpunk 2077 benchmark with the English OptiScaler performance OSD, scene 3](assets/screenshots/cyberpunk-xess-4x-en-03.png)

These are actual game captures. The OSD alone does not establish the effective multiplier or physical display scanout; see the separate [validation evidence and limits](docs/FRAME_GENERATION.md).

## Requirements

- Native Steam on Linux/SteamOS, Decky Loader, and a Proton game launched at least once.
- For XMX: compatible Intel hardware and a separate XMX runtime, patched ANV and compiler stack. Use the runtime button to download the pinned 186.5 MiB runtime from GitHub, or use an already prepared runtime. See [runtime setup](docs/RUNTIME.md).
- System `7z` for OptiScaler extraction; `xdotool` for the overlay shortcut. XMX checks also use `bash`, `ldd` and `vulkaninfo`.

The XMX route has been developed on an Intel ONEXPLAYER 3. AMD Steam Deck hardware cannot provide Intel XMX acceleration. Broad hardware/game compatibility and Decky Store acceptance are not established.

## Install

Download `opti2xmx-0.2.6.zip` from the [Releases page](https://github.com/FlightDan/Opti2XMX/releases/tag/v0.2.6), or build the ZIP using the commands below.
In Decky settings, enable developer mode and use **Install Plugin from ZIP File** (wording may vary by Loader version). Choose the built ZIP, then open Opti2XMX.

The plugin runs as the Steam user and does not modify games just by loading. No upstream DLLs, private runtime binaries, game files or generated compiler caches are bundled.

## Use

1. Exit the game and select it in Opti2XMX.
2. For a game without native XeSS, install OptiScaler or migrate a recognized existing Opti installation. Native XeSS games can use the XMX route directly.
3. For XMX, use **Download and configure XMX runtime** (195.6 MB download), or prepare it separately. Then enable **XMX acceleration**. The plugin writes and reads back Steam launch options.
4. Use **Opti injection** to enable or disable the managed injector. For native XeSS Frame Generation, turn Opti injection off before testing.
5. Restart the game after changing settings. Advanced settings include SR/FG output, GPU identity, version selection, rollback and uninstall.

Turn XMX off before installing, changing versions, rolling back or removing Opti. Version changes require Opti injection to be enabled. Do not run another injector manager over an active managed setup.

## Limits and recovery

XMX requires a compatible XeSS path; this is not a global Gamescope upscaler. FSR1 and arbitrary custom upscalers are not automatically supported. Frame generation depends on the game, runtime, driver and Proton. OptiScaler 0.9.4 supports XeFG output, but its XeFG input path is not implemented. A successful installation does not prove XMX execution, image quality or a performance gain.

Per-game journals live in `~/.local/share/opti2xmx/games/<appid>/`; Opti backups in `~/.local/share/opti2xmx/opti/<appid>/`. Pending operations offer completion or rollback. Unexpected DLL modifications block restoration instead of overwriting them. Uninstalling the Decky plugin does **not** restore games or delete backups: restore games through the plugin first, with games stopped.

Settings undo preserves each managed file's original contents. Pure INI formatting changes made by OptiScaler are archived and accepted only when strict option names, values and DEFAULT placement match; ambiguous syntax, changed values and modified backup mirrors still stop recovery. New XMX setups use a dedicated prefix shim path to avoid Proton replacing the DriverStore copy; existing setups must be restored and enabled again to adopt it.

Downloads use official GitHub releases by default. Optional third-party mirrors (`ghfast.top`, `gh-proxy.com`) receive the public asset URL; no account credentials are sent. Their availability and contents are outside this project's control.

## Build and test

Use Node.js 20+, pnpm 9 and Python 3.10+. Backend tests require Linux and an ordinary, non-root user.

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
node test_frontend.mjs
python3 -B -m unittest discover -v
python3 package_plugin.py
```

The archive is written to `opti2xmx-0.2.6.zip`. It contains the Python backend, built frontend, pinned runtime descriptor, documentation and licenses, without runtime DLLs or drivers. Repository screenshots are omitted from the install ZIP to keep it small. Fixture tests cover restoration, interrupted operations, runtime hash/extraction failures and conflicting files; they do not replace real game and hardware testing. The plugin screenshots above show the prior 0.2.2 interface.

## Development and credits

This project was developed with AI assistance. Contributions should be reviewed and tested on the target system. When reporting a bug, include plugin/Decky/SteamOS versions, GPU, game, Proton version and reproduction steps; remove personal paths and account details from logs.

Built with [Decky](https://github.com/SteamDeckHomebrew/decky-loader), using [OptiScaler](https://github.com/optiscaler/OptiScaler) and the separately provisioned [xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux) runtime. See [third-party notices](THIRD_PARTY_NOTICES.md).
