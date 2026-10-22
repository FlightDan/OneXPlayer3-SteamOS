# Static maintenance package

`device:oxp3-maintenance` is a separate, experimental maintenance-only package.
It must be advertised through a maintenance registry, never through the installer
model catalog. It contains one declared modification: the already published
112-byte `etc/modprobe.d/xe-oxp3.conf`, root-owned mode0644, with SHA-256
`1a1e2c951fec8a8a3c10977c78205e30d7052582c36c3e0700ffd03bd748b690`.
It runs no hooks, service operations, legacy updater or shell commands.

The component version remains **1.0.6**, taken from the locked public installer's
`components/release.json`. The independent package version is not a new repair
version. This is an unchanged source-generation baseline, not a claim of a new
display fix, live-device acceptance or DSB re-enablement.

```sh
python scripts/build-maintenance.py --public-installer /explicit/public-installer.zip --output /explicit/new-maintenance-package --zip /explicit/oxp3-maintenance-baseline.zip
```

Preparation uses the same authenticated public archive handle/snapshot as the
install-package builder. `maintenance-static-lock.json` binds the full upstream
lock and exact payload digest, target, mode and baseline version. The public
resource manifest must declare exactly this one destination and no service or
package requirement. Only the payload, project license and original upstream MIT
notice are exported. Source/build identity, duplicate members and special files
are checked before output is created. ZIP bytes are deterministic.

For a release candidate, run in a clean committed public `boiler-device/` subtree
with `--source-commit <exact-HEAD> --version <independent-package-version>`. The
reviewed source whitelist now has18 files. Existing install-package releases and
their original14-file source commits remain unchanged. A new candidate binds
the complete18-file committed subtree; this command neither signs nor publishes.

An already adopted `oxp3:xe-dsb` may also own a machine-specific legacy component
receipt. The signed static manifest declares `retain_owned_paths: true` so the
generic engine may retain only unchanged paths proven by that component's
current protected ownership journal. The reviewed update plan enumerates these
exact paths, snapshots and prior transaction. No dynamic path, wildcard, external
file or unowned file is supplied by this package. Existing historical legacy
receipts retain their original content; they do not claim a new legacy revision.
This flag requires the generic static retention contract and refuses a fresh
installation. It cannot authorize hooks or bypass edited-file checks.

Legacy `component_revisions_by_slot` values are content SHA-256 identities, not
ordered versions. Older adoption receipts use the coarse source-release version.
An installed version newer than1.0.6 therefore correctly blocks this baseline;
identical bytes must not be relabeled with a newer maintenance revision to force
an update. Equal version plus identical declared and retained bytes is reported
as unchanged. A future real reviewed payload change needs its own genuine
component version and signed maintenance registry entry. Until then this package
establishes discoverable baseline identity, not a fictitious functional upgrade.

The generic engine owns transactions, immutable binary backups, verification and
explicit restore. Its tests use a genuinely changed synthetic higher-version
payload to establish upgrade/restore behavior. They do not modify this production
baseline or imply hardware validation. Input calibration, mutable gyro profiles,
merged GRUB repairs, large desktop runtimes and legacy script lifecycle remain
outside this first static package.

A target without an installed `oxp3:xe-dsb` owner is intentionally inapplicable.
This baseline cannot update other adopted owners. No live XE hardware upgrade
acceptance is recorded; source preparation and synthetic lifecycle tests must
not be reported as an actual XE hardware upgrade.
