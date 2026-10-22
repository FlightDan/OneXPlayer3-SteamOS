# ONEXPLAYER 3 device package for Boiler

This independent model repository owns OXP3 compatibility policy, system changes,
component choices and the model's legacy integration bridge. Its eventual remote
continues to be `FlightDan/OneXPlayer3-SteamOS`; existing tags and Release assets
must be preserved. `Boiler-oxp3` is only the local candidate directory name.

The current `device:oxp3` package is an **unsigned development snapshot**. Its
`oxp3:legacy-adaptation` component runs only inside Boiler's managed Linux QEMU
guest against a mounted SteamOS 3.10 target. The package freezes explicit
`oxp3:*` choices, binds the slot through the guest's protected A/B marker, invokes the previously public integration
once, and retains its existing per-component recovery journal. The manifest
contains all 28 legacy option descriptions, availability and dependencies.
Its manifest requires Boiler engine 0.1.0 or later and the exact published
`7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9` kernel. Published DMI strings
`ONE-NETBOOK` / `ONEXPLAYER 3` are retained with a pinned source reference as
advisory matching data. Selection remains manual; this development snapshot does
not claim automatic hardware validation.

Build from the locked, already-public installer artifact:

```sh
python scripts/fetch-input.py --output .cache/public-installer.zip
python scripts/build.py --public-installer .cache/public-installer.zip --selection selection.example.json --output dist/device-oxp3 --zip dist/oxp3-device.zip
```

`upstream-lock.json` pins the actual release URL, byte size, SHA-256 and formal
source commit. Preparation executes no target script. It exports only listed
model components, integration resources, Decky assets, model maintenance tool,
Waydroid resources and licenses; it never reads the local workspace or its
research tree. The package inventory covers every exported file, including
scripts. ZIP member order and timestamps are deterministic.

The bridge preserves existing model behavior, including the explicitly
acknowledged OS-image update hold, serial-console policy, selected repairs,
Decky staging, model maintenance application and first-boot service. These are
device policy. Generic Boiler core does not implement or implicitly select them.
The legacy runtime retains exact OS/build/kernel/package gates. Runtime component
failures fail the bridge instead of being reported as successful installation.

Before apply succeeds, the adapter compares actual installed bytes and file
metadata against the protected per-slot and shared legacy journals, requires
coverage of reported files and internal runtime/version-note files, and checks
the runtime enablement link. It saves the resulting file and journal digests in
its private record. Later verification repeats those read-only comparisons and
requires the same proof; successful status labels alone are insufficient.

This package has no `maintenance_entry`. Its apply path is tied to the managed
installer guest and does not upgrade an already applied legacy generation.
Legacy adoption produces granular IDs such as `oxp3:input`, while this package
installs `oxp3:legacy-adaptation`. A live maintenance package still needs an
explicit mapping of those owners, actual upgrade actions, and recovery for old
journal/service side effects. Adding a hook-contract declaration alone cannot
make that lifecycle available.

This migration has not passed fresh-install, first-boot, full rollback, restart,
suspend or device acceptance through the new Boiler stack. Interrupted staging
before creation of the old result journal requires per-component recovery;
automatic bridge rollback refuses that incomplete state. For existing legacy
installations, `adapter.py adopt --slot A --receipt /protected/receipt.json`
reads known installer or maintenance metadata, verifies the installed public key
against the pinned key, and translates verified original/applied snapshots into
a private create-only adoption receipt. It preserves every old journal and key.
From the trusted Boiler installer runtime directory, complete ownership adoption
with `python -m maintenance --root /mounted/steamos adopt /protected/receipt.json`.
The generic engine revalidates the protected receipt, installed public-key
anchor, old metadata and current file snapshots before committing ownership.
Adoption leaves existing runtime bytes, original journals and keys intact;
only an explicit later `restore` uses the translated original snapshots.
Exact-receipt retries reuse already committed component generations. Unknown
formats, edits and pending transactions are refused. This verified file-ownership
migration does not establish live-device or full new-stack lifecycle acceptance.
The registry keeps
the new package experimental, and no production index advertises it. This
candidate must not replace the published OXP3 installer or maintenance release.

For an authenticated-index release candidate, use the clean public repository's
`boiler-device/` subtree at an exact committed HEAD and an explicit model version:

```sh
python scripts/build.py --public-installer /explicit/public-installer.zip --selection selection.example.json --output /explicit/new-package --zip /explicit/oxp3-device.zip --source-commit <public-model-commit> --version 0.1.0
```

The builder checks the existing public repository origin, all 14 reviewed source
paths, their committed bytes, and the frozen selection. It uses those frozen
source bytes for preparation. Package `source.commit` identifies this adapter's
real public commit; `upstream_source` and `upstream-lock.json` separately retain
the old published installer identity. The candidate remains experimental and
requires an authenticated DeviceIndex to anchor the actual manifest and ZIP
hashes; this command neither signs nor publishes or grants hardware acceptance.

Original code is AGPL-3.0-only; public upstream and third-party notices are
retained. The existing upstream public source commit supplies corresponding
source for the unchanged legacy artifact. No signing key is included.
