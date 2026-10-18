# OneXPlayer3-SteamOS

[简体中文](README.md) | [English](README.en.md) | [Installation](#3-installation)

## 1. Introduction

SteamOS support for the ONEXPLAYER 3 handheld, covering Game Mode, the KDE desktop, controller input and hardware controls, with Intel XeSS XMX acceleration and XeSS frame generation (where supported by the game).

The current main-branch integration release is OXP3 SteamOS 1.0.6, targeting SteamOS 3.10; check GitHub [Releases](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases) for available installer assets. Script-based maintenance tools are also available for handhelds running other SteamOS versions.

Report bugs by email at **[dan@devdan.cc](mailto:dan@devdan.cc)** or through [GitHub Issues](https://github.com/FlightDan/OneXPlayer3-SteamOS/issues).

<details>
<summary>View installer screenshots</summary>

**Installation location · Disk and partition selection**

![Installer disk and unallocated space selection](windows-installer/docs/screenshots/installer-location.png)

**Installation content · Device support and plugins**

![Installer device support and preinstalled plugin selection](windows-installer/docs/screenshots/installer-components.png)

**Boot settings · rEFInd dual-boot menu**

![Installer default boot system and menu timeout settings](windows-installer/docs/screenshots/installer-boot-options.png)

**Installation progress · Writing, readback verification and detailed logs**

![Installer progress and detailed log interface preview](windows-installer/docs/screenshots/installer-progress-preview.png)

These screenshots show the actual installer interface in Chinese. The disk layout, installation progress and logs are preview examples; no installation was performed.

</details>

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
| BMI260 gyroscope | In-game orientation and motion support; requires BIOS 5.09 and calibration after installation | ✅ |
| Intel XeSS / XMX | Native XeSS XMX acceleration in compatible games | ✅ |
| Refresh rate / VRR | Internal display support from 30 to 144 Hz | ✅ |
| Native TDP | **10–40 W** adjustment through Steam's performance menu | ✅ |
| OXP3 Fan | Firmware automatic control and custom fan curves | ✅ |
| OXP3 CPU | EPP, core-group frequency limits, PL1 at 10–40 W and independent PL2 up to 80 W; PL1 syncs with Steam's native TDP control | ✅ |
| [OXP3 Light](windows-installer/components/light/README.md) | On/off, solid colors and brightness for the stick rings, Xbox button and rear slogan light; settings are not automatically reapplied after boot or resume | ✅ |
| Split-lock workaround | Reduces split-lock report flooding; takes effect after reboot and does not automatically clear historical reports | ✅ |
| Performance overlay | CPU / GPU / APU power, fan and video-memory information are displayed correctly | ✅ |
| Volume keys | Volume keys work normally | ✅ |
| Waydroid | Android apps and a Game Mode launcher; not fully validated | 🧪 |
| Restart into Windows | [Decky button and desktop shortcut](windows-installer/docs/WINDOWS_REBOOT.md), for the next boot only; restart into Windows confirmed on the device | ✅ |
| OXP3 Battery | Verified bypass power and correct charge-limit control | ✅ |
| BE201 Wi-Fi | Wireless firmware support; many users have reported hardware failures under Windows. If the wireless driver drops out, try rebooting | ⚠️ |
| Dual-boot launcher · rEFInd | Windows / SteamOS boot menu; D-pad and A/B are now working during boot | ✅ |

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

Windows / SteamOS boot menu screenshot. D-pad and A/B are now working during boot.

![rEFInd dual-boot launcher · Windows / SteamOS selection](windows-installer/docs/screenshots/dual-boot-launcher.png)

</details>

## 3. Installation

### Install a dual-boot system from Windows

Download the complete Windows x64 installer ZIP from [Releases](https://github.com/FlightDan/OneXPlayer3-SteamOS/releases). The current main-branch integration release is **1.0.6 stable**; read the [1.0.6 release notes](windows-installer/docs/RELEASE_1.0.6.md) before use.

1. Download the Windows installer ZIP from Releases, extract it completely and keep the accompanying files together.
2. Back up your data. If BitLocker or device encryption is enabled, save and verify the recovery key, suspend protection, then disable Secure Boot in BIOS / UEFI. Restore protection after confirming Windows starts normally.
3. Prepare at least **64 GiB of contiguous unallocated space** on the target GPT disk, plus at least **45 GiB** of free Windows workspace; **64 GiB** is recommended.
4. Run **`SteamOSInstaller.exe`** and choose the installation location, official system image and desired components. Continue directly to Review plan. Shared-partition mounting remains hidden for new installations. Internal dual-boot installation is supported; see the implementation status for external SD / SSD validation.
5. Review the target disk, partition plan and selected components. Enable the optional rEFInd boot menu if desired, then start installation.
6. Follow the installer instructions to boot SteamOS, then check Game Mode, the desktop, controls and plugins.

System images are not included. Preparing SteamOS 3.10 and initializing some components requires an internet connection. See the [installation guide](windows-installer/docs/INSTALLATION_GUIDE.md) for full instructions.

Version 1.0.6 provides the project's OXP3 control plugins and Opti2XMX; install third-party Decky plugins separately. New images include desktop and application-menu shortcuts for OXP3 Repairs and Project Updates.

### Update this project or install repairs from SteamOS

[OXP3 Repairs and Project Updates](steamos-maintenance/README.md) lets existing SteamOS users select project repairs, plugins and subsequent project updates. Its native GTK touch interface maintains the current slot and supports signature verification, rollback and interrupted-operation recovery.

Open a terminal in SteamOS KDE Desktop Mode and run the following as the regular desktop user (do not add `sudo`). On first use, verify the release public-key fingerprint using the [maintenance instructions](steamos-maintenance/README.md):

```bash
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output install-oxp3-maintenance.sh \
  https://github.com/FlightDan/OneXPlayer3-SteamOS/releases/download/maintenance-v1.0.6%2Bmaintenance.2/install-oxp3-maintenance.sh \
  && bash install-oxp3-maintenance.sh
```

Select the repairs or plugins you need; components download on demand. Version 1.0.6 provides signed maintenance packages and a Bash installer. See the [maintenance instructions](steamos-maintenance/README.md) and [validation record](steamos-maintenance/VALIDATION.md) for tested coverage and remaining checks.

The maintenance tool targets ONEXPLAYER 3 and checks compatibility per component. Native drivers, HDR, Decky and plugin runtimes still require SteamOS 3.10 / build 20260924.1000 / kernel 7.2.4. Other SteamOS versions currently have adapters for settings such as the on-screen keyboard and Flathub; incompatible items show the reason.

This updates the OXP3 project only; it does not upgrade SteamOS or change the official OS update settings.

## 4. Featured Plugin · Opti2XMX

**[Opti2XMX](https://github.com/FlightDan/Opti2XMX)** is a Decky plugin developed for this adaptation. It provides native **XeSS XMX acceleration and XeSS frame generation** directly for compatible games, and **OptiScaler with XeSS frame-generation support** for other compatible games.

OXP3 SteamOS 1.0.6 integrates Opti2XMX **0.2.4**. Its XeSS FG 2x / 3x / 4x controls remain experimental; see the [frame-generation notes](windows-installer/components/opti2xmx/docs/FRAME_GENERATION.md) for compatibility and test coverage.

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
