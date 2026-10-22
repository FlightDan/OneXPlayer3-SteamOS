# OXP3 SteamOS 1.0.6+maintenance.12 — Boiler migration bridge

Status: final source and independent review complete; native export acceptance passed. Publication and real-device acceptance are recorded separately below.

The explicit privileged adoption export now streams the existing legacy JSON
index into a private binary snapshot bundle. This removes base64 duplication
from the receipt and supports the large, already-published runtime files found
in real installations. It does not alter old files, keys, component identities
or recovery journals, and does not automatically install or adopt Boiler.

The v2 receipt is published last after validating the complete index, original
and current snapshots, actual managed files, stable PARTUUID/A-B identity,
lifecycle state and existing signing anchor under the old transaction lock.
Binary blobs have explicit size/hash inventories and bounded streaming reads.
The generic runtime separately authenticates the private bundle before recording
ownership. Interrupted adoption retains an explicit resumable barrier.

## Evidence and release gates

- Existing `.10` and `.11` tool-only upgrades succeeded on the test device without
  reinstalling components or changing the formal key or root protection.
- The `.11` exporter correctly refused a 1.5 GB inline index. A read-only bounded
  diagnostic identified 1,957 managed files, about 563 MB of applied data and a
  maximum file of 138 MB; these exceed the first receipt format's limits.
- Complete: native Linux legacy export tests 11/11 and streaming export tests
  11/11, including a 138,485,536-byte file with a receipt under 32 KiB and Python
  peak-RSS increase below 64 MiB, both old state formats, index/link races,
  directory runtime originals, and retained binary snapshots after a late
  publication fsync failure. The private receipt also passed actual generic
  adoption, verification and restore in a disposable Linux filesystem.
- Complete: independent exporter and generic intake review. The generic v1
  adoption and model roundtrip regressions passed 5/5.
- Pending: final rebuild and formal signing, public downloads, `.11` to `.12`
  device upgrade, full live adoption, reboot and recovery acceptance. A separate
  generic-runtime upgrade correction is still being validated.
- Existing versioned assets and the Windows Latest release remain unchanged.

This release does not claim a new disk installation, device boot from a Boiler
image, wireless hardware coverage or generic model-script upgrade support.
