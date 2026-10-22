# OXP3 SteamOS 1.0.6 — maintenance.10

Release preparation revision `1.0.6+maintenance.10`; display version remains
`1.0.6`. This record describes the candidate source and completed fixture tests.
Formal signing and local signature verification are complete. Publication and live-device migration acceptance remain separate gates.

## Change

Add the explicit privileged `export-adoption --output <private-receipt>` command.
It translates verified original and applied snapshots from maintenance format 1
or the known installer logical-file/runtime journals. It probes the active live
slot, holds the existing maintenance transaction lock, preserves the formal
public key, refuses incomplete or modified state, and rechecks evidence and live
bytes before publishing a complete create-only mode-0600 receipt. Private
snapshot contents are not printed in the summary.

Export does not modify managed files, original backups, old journals, services,
update discovery, or recovery behavior. The usual maintenance lock file may be
created when no old maintenance state exists. The new action is not exposed by
the existing window-session authorization protocol. A separate explicit trusted
Boiler runtime operation is required to adopt the receipt; export alone leaves
`migration_complete` false.

Preparation reports now identify their input directory by its name, avoiding
publication of an absolute local workspace path in release payload metadata.

The OXP3 model package source is in `boiler-device/`. Its Boiler version and
experimental registry status remain independent of this maintenance revision.
This release does not certify new-stack installation, suspend, reboot, update,
or complete rollback behavior. Do not use old and new tools as concurrent repair
writers. Unknown formats, incomplete originals, modified files and inconsistent
keys are refused instead of silently adopted or replaced.

## Validation completed before signing

- Independent review found no blocking issue in the bounded bridge change.
- Linux root: all 8 focused bridge tests passed, including both old state
  formats, protected readers, private directory traversal, create-only atomic
  publication, and explicit export → actual new Engine adoption → verification
  → original-byte restoration. These used isolated fixtures, not a live device.
- Windows: 6 focused tests passed; the 2 real POSIX ownership/descriptor tests
  skipped explicitly. Existing release discovery tests passed 17/17; existing
  authorization tests passed 14 with 4 POSIX-only skips.
- The copied model source passed its 7 independent tests. The canonical formal
  public key and old release assets remain unchanged.

## Signed candidate verification

The existing formal publisher produced a complete report. The signed core and
32-component catalog both passed signature verification; the bridge source
matched the unpacked archive and the canonical public key was unchanged.

## Remaining release gates

 Reuse verified `maintenance.9` catalog references
for unchanged published packages instead of republishing them. Preserve every
old referenced asset. Re-download and verify the final published script,
catalog, core, hashes, version discovery and revision ordering. Verify the actual
`.9` → `.10` upgrade, receipt export, adoption, reboot and old/new recovery and
restoration behavior on the supported SteamOS 3.10 baseline before claiming
live migration acceptance. Windows installer publication remains a separate
gate. Publication and live-device upgrade are not yet claimed by this record.

Operational boundaries and command examples are in
[BOILER-ADOPTION-BRIDGE-PREVIEW.md](BOILER-ADOPTION-BRIDGE-PREVIEW.md).
