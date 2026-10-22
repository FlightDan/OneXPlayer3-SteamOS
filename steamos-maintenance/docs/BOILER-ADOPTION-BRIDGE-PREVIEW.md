# Explicit legacy adoption receipt bridge — local preview

This branch adds one explicit `export-adoption` command. It does not publish a
release, change the canonical public key, replace the old updater, or activate
Boiler automatically. Existing discovery, repair, rollback, restore, recovery,
and window authorization behavior remain available. The new action is excluded
from the window-session action allowlist and requires separate root invocation.

After an independently reviewed and signed bridge core is installed, an
administrator can export a receipt to an existing root-private directory:

```sh
sudo /usr/bin/python3 -I -B /usr/local/lib/oxp3-maintenance/entry.py export-adoption --output /root/oxp3-adoption-A.json
```

The command detects the active slot from the existing live probe, requires the
supported OXP3 baseline, and holds the existing maintenance transaction lock.
It refuses pending or incoherent operations, unknown journal formats, changed
live bytes, incomplete originals, and public-key mismatch. It reads the active
`current-release.json` generation rather than assuming that every installed
runtime directory is active. The verified translator supports maintenance
format 1 and the installer's logical-file journals, including the existing
protected runtime-directory decoder. Unknown or edited states require recovery
or manual review; they are never guessed into ownership.

The only output is a complete create-only mode-0600 receipt and a small summary
with its hash. The existing parent directory must be root-owned, private, and
reachable through protected directories without symlinks. The receipt contains
private original file snapshots. Do not upload it, add it to release assets, or
put it in a desktop-user cache. Old keys, journals, original backups and live
runtime files remain untouched; acquiring the old lock can create its usual
private lock directory/file when no old maintenance state exists yet.

Adoption is a separate explicit operation performed by the trusted new runtime:

```sh
sudo /usr/local/bin/boiler-maintenance --root / adopt /root/oxp3-adoption-A.json
```

The new engine must revalidate the protected receipt, formal public key,
evidence hashes and live snapshots before committing its own ownership records.
Export alone leaves `migration_complete` false. Adoption alone does not upgrade
the device or establish new-stack lifecycle acceptance. Old-tool writes after
export or adoption must cause a stale-evidence or modified-file refusal, and
old/new restoration coexistence still needs explicit device acceptance. Never
use both tools as concurrent repair writers. A future combined action must
retain one lock order: old maintenance lock before new engine lock.

## Proposed release metadata, pending acceptance

Keep project/display version `1.0.6` and use the next unoccupied positive
maintenance revision after the published `1.0.6+maintenance.9` (for example
`1.0.6+maintenance.10`, only after checking that tag is unused). Add its new
`release/<revision>.json`, `docs/RELEASE-<revision>.md`, and generated signed
catalog/core artifacts through the existing publisher. Suggested note:

> Add an explicit root-only export of verified legacy adoption receipts for
> separate Boiler runtime review. Preserve the existing formal public key,
> update discovery, repair, recovery and all historical release assets. No
> automatic migration, base-OS upgrade or new device acceptance is claimed.

The signed core must contain `oxp3_maintenance/adoption_export.py`. Existing
complete component catalogs and all unchanged referenced assets remain covered;
do not reduce the catalog to this command or replace already published assets.
The model's Boiler version remains independent and its registry status remains
experimental. A signed old-format bridge does not make an unsigned development
DevicePackage into an official package.

Before any release: independent review, Linux descriptor/ownership tests,
public download/signature verification, old `.9` to the new core upgrade,
receipt export on both slot/state formats as applicable, no-byte-change
verification, explicit new-engine adoption, reboot, and old/new recovery and
restoration acceptance remain gates. The Windows installer remains a separate
release gate. This document does not report any of those device tests as passed.

## Focused tests

```sh
PYTHONPATH=. python -B -m unittest discover -s tests -p test_adoption_export.py -v
BOILER_INSTALLER_SOURCE=/explicit/Boiler-installer PYTHONPATH=. python -B -m unittest discover -s tests -p test_adoption_export.py -v
```

Linux root runs the actual protected reader, private descriptor traversal and
atomic no-replace publication tests. On Windows only metadata tests substitute
a fixture reader; POSIX ownership tests skip explicitly. The separate new
runtime integration runs only when its source is explicitly supplied.
