# OXP3 SteamOS integration version

The current project integration version is **OXP3 SteamOS 0.1.3** on the project's **stable** channel. The version documentation and release notes were updated on 2026-10-15.

`components/release.json` is the version source: machine version `0.1.3`, display version `0.1.3`, channel `stable`. This identifies the ONEXPLAYER 3 integration and its companion installer. SteamOS has its own system version and update branch. The default target remains **SteamOS 3.10 / build 20260924.1000**; the official image's `STEAMOS_DEFAULT_UPDATE_BRANCH` is `stable`. The 0.1.3 new-install image uses the required private local empty update feed and keeps the `atomupd` updater running against that feed, so a healthy updater has no OS update candidate. This affects new images only; it does not modify an installed SteamOS. Manually changing the feed or resuming updates may allow an official update to write another A/B slot and overwrite device fixes. Old prepared images must be rebuilt from the original official download to use the new behavior.

The installer displays the integration version embedded at build time. Development packages use the integration version and a fresh build timestamp, for example `oxp3-development-0.1.3-YYYYMMDD-HHMMSS.zip` or `.tar`; the package root contains `release.json` and `build-info.json` with the build identifier. Each package build receives a new identifier.

Deployment records in `/home/.oxp3-installer/integration/A/result.json` and `B/result.json` store the integration `release`, actual system `system` and per-component results. When selected components and the runtime are deployed, `/usr/local/lib/oxp3-integration/release.json` also records the integration release. The version identifies the deployment source; component results determine which changes were actually enabled and succeeded.

Image preparation creates `/home/deck/OXP3-SteamOS-Version.md` in the user's home folder. It contains the English title `OXP3 SteamOS Version` and integration version `0.1.3`; it is not placed on the desktop. The file is generated from the same release metadata, owned by `deck`, and uses the existing shared-home backup and conflict protections.

The prior **0.1.2 stable**, **0.1.1 stable** and **0.1.0 Beta** (`0.1.0-beta`, channel `beta`) and their ZIPs, prepared images and installed systems remain historical. Updating source or documentation does not change an existing package or installed system.

The `0.1.3 stable` label names this project's integration channel. Available installer assets are listed on GitHub Releases. Mount selection is hidden because mounting remains unavailable. In a physical first-install test, initialization skipped the OS download and stayed black until the user held the power button to shut down and powered on again; the desktop, Wi-Fi and controller worked afterward. The exact SteamOS version, active slot, Steam sign-in and complete OOBE remain unverified. If the black screen occurs during this initialization transition, wait at least five minutes, then hold power to shut down and restart; do not force power off during image writing or real update progress. This known issue is not fixed. Automatic cross-version adaptation is not implemented, and the separate Waydroid dependency issue remains. See the [0.1.3 release notes](RELEASE_0.1.3.md) for the current scope.

## Future version numbers

- A patch release keeps the stable channel and increments the patch number, such as `0.1.4`.
- A feature release increments the minor number, such as `0.2.0`.
- SteamOS, plugins, firmware and kernels retain their own versions; the integration version never replaces compatibility checks.

For each release, update the version metadata and rebuild the installer. Record changes, target system and validation scope in release notes. Component patch updates, online release checks and one-click upgrades are not implemented.
