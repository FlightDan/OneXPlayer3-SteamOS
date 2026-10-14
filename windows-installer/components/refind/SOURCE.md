# Bundled rEFInd

Version: upstream 0.14.2, Arch Linux package 0.14.2-3, x86-64 EFI.

Source package: https://archive.archlinux.org/packages/r/refind/refind-0.14.2-3-x86_64.pkg.tar.zst

Upstream: https://www.rodsbooks.com/refind/

The unmodified EFI binary and package license text are bundled here. `manage.py` is this installer's transaction and recovery implementation. `test_refind.py` runs on an independent test ESP only.

The Graphite Quiet theme replaces all eleven original icons. The Steam silhouette source is https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/steam.svg (Simple Icons); Steam and Windows marks identify their respective systems. The Windows panes and functional icons are authored geometric UI assets. Outfit and DM Mono label glyphs use the included SIL Open Font License notices. The original font binaries are build-time inputs from the installed Canvas Design skill, not runtime requirements.

The dark wallpaper was generated with the built-in image generation tool on 2026-10-14 and copied unchanged into `theme/background.png`. The prompt and design direction are in `ASSETS.md` and `DESIGN.md`. Rebuild deterministic UI assets with `scripts/render-refind-steam.cjs` (sharp) and `scripts/build-refind-theme.py` (Pillow plus the named fonts). The deployed payload needs no image/font library.

The new SteamOS ESP retains the official `EFI/steamos/steamcl.efi` A/B loader. Only its removable fallback is replaced, with the original bytes kept in the recovery journal. Existing Windows ESP contents and firmware default are not changed by this component.

The Arch GNU-EFI build exhibits the upstream 0.14.2 ShowTools clearing issue (https://sourceforge.net/p/refind/discussion/general/thread/ed3185fb40/). Configuration explicitly fills all 23 parsed slots: four desired built-ins and 19 excluded gptsync slots. `dont_scan_tools` excludes the gptsync filenames. This avoids duplicate/default tools without patching the executable. Both tool count and focus outlines are checked in the installed firmware menu.

## UEFI controller input

Bundled unmodified release driver: [jlobue10/UsbXbox360Dxe v1.8.0](https://github.com/jlobue10/UsbXbox360Dxe/releases/tag/v1.8.0), release commit `79fca28`, file `drivers_x64/UsbXbox360Dxe.efi` (52,032 bytes). Binary source: https://github.com/jlobue10/UsbXbox360Dxe/releases/download/v1.8.0/UsbXbox360Dxe.efi. License: BSD-2-Clause-Patent, retained verbatim in `GAMEPAD-LICENSE.txt`. This derives from SkorionOS, chenx-dust and the EDK II USB keyboard driver; the fork also contains handheld fixes.

Versioned device table: https://github.com/jlobue10/UsbXbox360Dxe/blob/v1.8.0/Xbox360Device.c. It includes `045e:028e`, matching the OXP3's previously observed physical Xbox 360 interface. This match establishes a candidate driver, not firmware acceptance on OXP3.

`gamepad.ini` is our keyboard navigation preset: D-pad/left stick → arrows, A/Start → Enter, B → Escape; other controls are disabled. `manage.py` deploys it to both its owned payload directory and `EFI/Xbox360/config.ini`, with the driver loaded via rEFInd's `driver_dirs`. Configuration source: https://github.com/jlobue10/UsbXbox360Dxe/blob/v1.8.0/config.ini.example.

The driver searches mounted firmware file systems for `EFI/Xbox360/config.ini`; another ESP with that path can take precedence. It may create diagnostic logs under `EFI/Xbox360`, which are not adopted or deleted by our transaction. No MCU firmware or Linux InputPlumber configuration is changed. Physical boot input, release/repeat behavior and subsequent Windows/SteamOS controller input require device verification.
