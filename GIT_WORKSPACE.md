# Workspace Git repository

This repository tracks Windows installer source, component deployment logic, tests,
scripts, current documentation, and workspace roadmaps. The current integration
release is **OXP3 SteamOS 0.1.1 (stable channel)**; Valve's SteamOS version and update
branch are recorded separately.

## Active source and local resources

- `windows-installer/app`: WPF interface, installation controller and native helpers.
- `windows-installer/components`: installation options, integration code, release metadata and rEFInd resources.
- `windows-installer/guest` and `scripts`: offline preparation, deployment and validation.
- `windows-installer/docs`: current user and technical guides; start at [the index](windows-installer/docs/README.md).
- `windows-installer/IMPLEMENTATION_STATUS.md`: current capability and verification summary.
- `runtime`, `cache`, `work`, `output`, `logs` and `dist`: local dependencies and generated artifacts, excluded from Git.

The installer can select a local workspace outside its default `work` folder.
The setting is stored in the portable installer's `workspace.json`; changing it
does not move old downloads, images or task records.

A fresh clone is source, not a ready-to-run installer. Rebuilding and packaging
require the excluded .NET runtime/SDK, QEMU, offline packages, archives and component
payloads. Users of a complete prepared package do not need WSL2, an SDK, Node.js or
installed virtual-machine software.

## Current branch and packages

`main` includes the completed touchscreen / rEFInd / guarded deletion branch.
The development working tree also contains workspace, capacity, release-metadata,
log-export and native-volume changes. The GitHub source destination is
[FlightDan/OneXPlayer3-SteamOS](https://github.com/FlightDan/OneXPlayer3-SteamOS).
Upload uses a separate checkout and an allowlisted source snapshot; the local
development repository and its internal history are not pushed.

Local ZIP files are historical builds. They are not updated when the source or
documentation changes. The previously released 0.1.0 Beta package remains a historical
build; the 0.1.1 stable package and its exact source commit are identified in the
corresponding GitHub Release and build-info.json. The current two-image subpages and
deferred RAUC reconstruction must be checked against each package's build-info.json.
Full fresh-install/OOBE validation remains pending; automatic cross-version adaptation
is not implemented. See the [0.1.1 release notes](windows-installer/docs/RELEASE_0.1.1.md).
See [the installer README](windows-installer/README.md) for delivery differences.

Future package names include the integration version and a fresh build timestamp;
`release.json` and `build-info.json` identify the resulting build.

## GitHub source candidate

Use `windows-installer/scripts/prepare-github-source.ps1` to create a fresh source
candidate under the ignored `windows-installer/dist` directory. It exports an
explicit allowlist of source, maintained documentation and license materials,
without copying Git history, research records, runtime payloads, credentials,
workspace settings or generated installers. Do not upload the workspace root as
a folder. See [publication preparation](windows-installer/docs/GITHUB_PREPARATION.md).

This prepares files only; it does not initialize a remote, commit, push or publish.
Export a fresh candidate for each upload so later code fixes are included.
Original project content uses AGPL-3.0-only unless otherwise noted; third-party
terms remain applicable. The 0.1.1 stable integration label does not claim complete
workflow or device acceptance; full fresh-install/OOBE validation and third-party
redistribution review remain documented limitations. The 0.1.0 Beta release remains
historical.

## Local history archive

Old installer development records were moved out of `windows-installer` to
`archive/windows-installer-history/2026-10-14/`, retaining their original relative
paths. The root `.gitignore` excludes that archive from future commits and packages.
The active implementation summary replaces the old cumulative log; some technical
guides also have an unchanged pre-edit snapshot in the archive.

Existing repositories `OneXPlayer3-SteamOS`, `onexplayer3-steamos-setup` and
`Opti2XMX` remain independent, not submodules. Research/device captures, tools,
credentials, caches, generated images and release archives remain local.
