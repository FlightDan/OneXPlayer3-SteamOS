# OneXPlayer3-SteamOS

[简体中文](README.md) | [English](README.en.md)

## 1. Introduction

SteamOS support for the **ONEXPLAYER 3 handheld**, covering Game Mode, the KDE desktop, controller input and hardware controls, with **Intel XeSS XMX acceleration and XeSS frame generation (where supported by the game)**.

The current integration release is **OXP3 SteamOS 0.1.0 Beta**, based on **SteamOS 3.10**.

Report bugs by email at **[dan@devdan.cc](mailto:dan@devdan.cc)** or through [GitHub Issues](https://github.com/FlightDan/OneXPlayer3-SteamOS/issues).

<details>
<summary>How to report a bug</summary>

Check existing issues first. Keep each report focused on one problem and include:

- **Description**: what happened, and what should have happened?
- **Steps to reproduce**: list the actions needed to trigger the problem, starting from boot or opening the feature.
- **Environment and versions**: ONEXPLAYER 3 model, BIOS, SteamOS and installer version; include Decky and plugin versions when relevant.
- **Game details**: game title, Proton version, Game Mode or Desktop Mode, and whether XeSS, XMX and Opti injection are enabled.
- **Frequency**: every time, occasionally, or only after reboot, resume or connecting/disconnecting power?
- **Attachments**: screenshots, exact error messages and logs from the relevant time. Remove passwords, tokens and personal information before sharing.

Copy this template into an email or issue:

```text
Problem:
Device / BIOS:
SteamOS / installer version:
Decky / plugin version, if applicable:
Game / Proton / XeSS settings, if applicable:
Steps to reproduce:
Expected result:
Actual result:
Frequency:
Screenshots / logs:
```

</details>

## 2. Features

| Feature | Support | Status |
| --- | --- | :---: |
| HDR · Game Mode / KDE desktop | Panel-specific **1100 / 472 nit mapping** | ✅ |
| Controller, back buttons and multifunction key | M1 → L4, Home → L5, M2 → R4, multifunction key → R5; customizable through Steam Input | ✅ |
| BMI260 gyroscope | In-game orientation and motion support; calibrate after installation | ✅ |
| Intel XeSS / XMX | Native XeSS XMX acceleration in compatible games | ✅ |
| Refresh rate / VRR | Internal display support from 30 to 144 Hz | ✅ |
| Native TDP | **10–40 W** adjustment through Steam's performance menu | ✅ |
| OXP3 Fan | Firmware automatic control and custom fan curves | ✅ |
| OXP3 CPU | EPP and core-group frequency controls | ✅ |
| Performance overlay | CPU / GPU / APU power, fan and video-memory information are displayed correctly | ✅ |
| Volume keys | Volume keys work normally | ✅ |
| Waydroid | Android apps and a Game Mode launcher; not fully validated | 🧪 |
| Restart into Windows | [Decky button and desktop shortcut](windows-installer/docs/WINDOWS_REBOOT.md), for the next boot only; restart into Windows confirmed on the device | ✅ |
| OXP3 Battery | Verified bypass power and correct charge-limit control | ✅ |
| BE201 Wi-Fi | Wireless firmware support; many users have reported hardware failures under Windows. If the wireless driver drops out, try rebooting | ⚠️ |
| Dual-boot launcher · rEFInd | Windows / SteamOS selection; tested with the D-pad to select, A to confirm and B to go back | ✅ |

✅ indicates an available adaptation; 🧪 indicates ongoing validation; ⚠️ indicates a known issue. HDR uses a Gamma 2.2 mapping path; 1100 / 472 are mapping parameters. See the relevant release notes for installation, update, reboot and suspend support.

<details>
<summary>HDR, native TDP and performance overlay screenshots</summary>

**Game Mode HDR**

![Game Mode HDR and brightness controls](windows-installer/docs/screenshots/hdr-game-mode.png)

**Native TDP · 40 W**

![Steam's native performance menu with 40 W TDP](windows-installer/docs/screenshots/native-tdp-40w.png)

**In-game TDP and performance overlay**

![15 W TDP and the in-game performance overlay](windows-installer/docs/screenshots/native-tdp-15w.png)

![20 W TDP and the in-game performance overlay](windows-installer/docs/screenshots/native-tdp-20w.png)

</details>

<details>
<summary>OXP3 control plugin screenshots</summary>

![OXP3 CPU, Fan, Battery and Opti2XMX in Decky](windows-installer/docs/screenshots/decky-plugins.png)

![OXP3 Fan curve controls](windows-installer/docs/screenshots/oxp3-fan.png)

</details>

<details>
<summary>Waydroid screenshots</summary>

![Waydroid Android desktop](windows-installer/docs/screenshots/waydroid-desktop.png)

![Waydroid launcher in the Steam library](windows-installer/docs/screenshots/waydroid-steam-entry.png)

</details>

<details>
<summary>Dual-boot launcher screenshot</summary>

Tested: use the D-pad to select Windows / SteamOS, A to confirm and B to go back.

![rEFInd dual-boot launcher · Windows / SteamOS selection](windows-installer/docs/screenshots/dual-boot-launcher.png)

</details>

## 3. Featured Plugin · Opti2XMX

**[Opti2XMX](https://github.com/FlightDan/Opti2XMX)** is a Decky plugin developed for this adaptation. It provides native **XeSS XMX acceleration and XeSS frame generation** directly for compatible games, and **OptiScaler with XeSS frame-generation support** for other compatible games.

- Configure XMX directly for native XeSS games, or use OptiScaler in other compatible games.
- Control XMX acceleration and Opti injection independently, with installation, version switching, rollback and uninstall support.
- Configure upscaling, frame-generation output and related settings through a Chinese or English interface.

XMX requires compatible Intel hardware and the matching runtime environment; installing the plugin alone is insufficient. Frame-generation support depends on the game, driver and Proton. Disable Opti injection when testing a game's native XeSS frame generation.

<details>
<summary>Opti2XMX and native XeSS game screenshots</summary>

**Opti2XMX · enable XMX per game**

![Opti2XMX XMX acceleration toggle](windows-installer/docs/screenshots/opti2xmx-xmx.png)

**Black Myth: Wukong · native XeSS and frame-generation settings**

![XeSS and frame-generation options in Black Myth: Wukong](windows-installer/docs/screenshots/native-xess-settings.png)

**Gameplay**

![Black Myth: Wukong gameplay with the related configuration enabled](windows-installer/docs/screenshots/xess-gameplay.png)

</details>

## 4. Installation

The complete Windows x64 installer ZIP is provided through **[Releases](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases)**. The current release is a **0.1.0 Beta prerelease**, with full physical-device acceptance still in progress. Read the matching release notes before use.

1. Download the Windows installer ZIP from Releases, extract it completely and keep its companion files together.
2. Back up existing data. If BitLocker or device encryption is enabled, save and verify the recovery key, suspend protection, then disable Secure Boot in BIOS / UEFI. Resume protection after installation once Windows boots normally.
3. Prepare at least **64 GiB of contiguous unallocated space** on the target GPT disk, plus at least **45 GiB of free space** for the preparation workspace in Windows; **64 GiB** is recommended for the workspace.
4. Run **`SteamOSInstaller.exe`** and follow the wizard to select the installation location, official system image and desired adaptation components. Internal dual-boot installation is supported; installation to an external SD / SSD is in Beta.
5. Review the target disk, partition plan and selected options, optionally enable the rEFInd boot menu, then confirm installation.
6. Follow the application's instructions to boot SteamOS and check Game Mode, the desktop, buttons and plugins.

System images are obtained from Valve's official sources. Calibrate the gyroscope before first use; Waydroid's Android image requires separate initialization. The current adaptation targets SteamOS 3.10, with the gyroscope implementation targeting BIOS 5.09.

System images are not bundled with the installer. Preparing SteamOS 3.10 and initializing some components require an internet connection. See the [installation guide (Chinese)](windows-installer/docs/INSTALLATION_GUIDE.md) for the full steps.

## 5. Roadmap

- [ ] G3E CPU core enable / disable controls
- [x] Touch-friendly installer UI / UX
- [x] Integrated boot manager: Windows / SteamOS selection and default boot entry management
- [ ] Prebuilt 64G system image and companion installer

See the [Roadmap (Chinese)](ROADMAP.md) for further plans.

## 6. License

Copyright © 2026 FlightDan and contributors.

Unless otherwise noted, original code and documentation in this repository are licensed under the **GNU Affero General Public License v3.0 (`AGPL-3.0-only`)**. See [LICENSE](LICENSE) for the full terms.

Third-party code, components, firmware and system images retain their own copyrights and licenses. Opti2XMX also currently uses `AGPL-3.0-only`; its Decky template retains the original BSD-3-Clause notice. See [third-party notices](THIRD_PARTY_NOTICES.md).

This is an unofficial, community-maintained project and is not affiliated with Valve, Intel or ONEXPLAYER. All referenced trademarks belong to their respective owners.

## 7. Acknowledgments

Thanks to the following projects and their contributors:

Special thanks to **HANA** for the original device adaptation project **[onexplayer3-steamos-setup](https://github.com/HHHHanasak1/onexplayer3-steamos-setup)**, and to the testers who provided devices, logs and feedback from real hardware.

- **Device support**: [InputPlumber](https://github.com/ShadowBlip/InputPlumber), [Linux](https://kernel.org/), [KDE / KWin](https://invent.kde.org/plasma/kwin), [Gamescope](https://github.com/ValveSoftware/gamescope), [SteamOS Manager](https://gitlab.steamos.cloud/holo/steamos-manager) and [MangoHud](https://github.com/flightlessmango/MangoHud).
- **XeSS support**: [Intel XeSS](https://github.com/intel/xess), [xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux), [OptiScaler](https://github.com/optiscaler/OptiScaler) and [supporting XeSS runtime components](THIRD_PARTY_NOTICES.md).
- **Plugin framework**: [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
- **Android support**: [Waydroid](https://github.com/waydroid/waydroid) ([SteamOS integration](https://github.com/pjohno/steamos-waydroid-bundle)).
- **Dual boot**: [rEFInd](https://www.rodsbooks.com/refind/), [UsbXbox360Dxe](https://github.com/jlobue10/UsbXbox360Dxe).

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for third-party project sources, roles and license scope.
