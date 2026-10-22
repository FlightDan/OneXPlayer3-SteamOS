# OXP3 SteamOS 1.0.6 — maintenance.11

Correct the explicit Boiler adoption export on real A/B installations. The live
probe identifies a root by PARTUUID and separately reports its verified A/B
label. Maintenance index/original/lifecycle records are now addressed using the
stable identity; installer journals and the receipt retain the A/B label. Both
identities are required and the full live probe is rechecked under the old lock.
No guessed fallback or key replacement is introduced.

The previous `.10` signed release successfully upgraded the test device from
`.9` in tool-only mode. Component revisions, formal public key, previous runtime
and original root protection remained unchanged. Its receipt export safely
refused the PARTUUID form; this revision addresses that observed failure.

Validation before publication: independent review passed; 11 focused tests ran
with 9 passing and 2 POSIX-root-only skips on Windows. Tests exercise realistic
PARTUUID/B addressing, installer B journals, changed/missing identities, and
actual Boiler adoption/verification/restoration through isolated fixtures.
Prior Linux private-file and bridge lifecycle tests remain recorded in `.10`.
Native regression and actual `.10` to `.11` upgrade/export results are separate
release gates and will be recorded only after execution. New Boiler ownership
adoption, reboot and recovery acceptance are not implied by source tests.

Keep all historical assets, the full signed component catalog and existing
Windows Latest. This release changes only the maintenance bridge and does not
upgrade SteamOS or automatically migrate any component.
