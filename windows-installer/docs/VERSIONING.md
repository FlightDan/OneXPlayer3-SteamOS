# OXP3 SteamOS integration version

The current project integration release is **OXP3 SteamOS 0.1.1**, on the **stable** project channel, dated 2026-10-14.

`components/release.json` is the version source: machine version `0.1.1`, display version `0.1.1`, channel `stable`. This identifies the ONEXPLAYER 3 integration and its companion installer. SteamOS has its own system version and update branch. The default target remains **SteamOS 3.10 / build 20260924.1000**; the official image's `STEAMOS_DEFAULT_UPDATE_BRANCH` is `stable`. When an installation includes device fixes, plugins or account configuration, the installer pauses SteamOS system updates in both A/B slots while leaving Steam client and game updates available.

The installer displays the integration version embedded at build time. Development packages use the integration version and a fresh build timestamp, for example `oxp3-development-0.1.1-YYYYMMDD-HHMMSS.zip` or `.tar`; the package root contains `release.json` and `build-info.json` with the build identifier. Each package build receives a new identifier.

Deployment records in `/home/.oxp3-installer/integration/A/result.json` and `B/result.json` store the integration `release`, actual system `system` and per-component results. When selected components and the runtime are deployed, `/usr/local/lib/oxp3-integration/release.json` also records the integration release. The version identifies the deployment source; component results determine which changes were actually enabled and succeeded.

Image preparation creates `/home/deck/OXP3-SteamOS-Version.md` in the user's home folder. It contains the English title `OXP3 SteamOS Version` and integration version `0.1.1`; it is not placed on the desktop. The file is generated from the same release metadata, owned by `deck`, and uses the existing shared-home backup and conflict protections.

The prior **0.1.0 Beta** (`0.1.0-beta`, channel `beta`) and its ZIPs, prepared images and installed systems remain historical. Updating source or documentation does not change an existing package or installed system.

The `0.1.1 stable` label names this project's integration channel. It does not claim that every device feature is validated: a complete fresh installation through first-boot setup has not been tested, automatic cross-version adaptation is not implemented, and the independent Waydroid dependency issue remains. See the [0.1.1 release notes](RELEASE_0.1.1.md) for the current scope.

## Future version numbers

- A patch release keeps the stable channel and increments the patch number, such as `0.1.2`.
- A feature release increments the minor number, such as `0.2.0`.
- SteamOS, plugins, firmware and kernels retain their own versions; the integration version never replaces compatibility checks.

For each release, update the version metadata and rebuild the installer. Record changes, target system and validation scope in release notes. Component patch updates, online release checks and one-click upgrades are not implemented.
