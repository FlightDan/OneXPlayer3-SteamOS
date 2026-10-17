OXP3 AutoFlatpaks compatibility patch 1.6.8+oxp3.1

Base: unmodified AutoFlatpaks 1.6.8 from the official Decky plugin store.
Upstream: https://github.com/jurassicplayer/decky-autoflatpaks
Original BSD-3-Clause LICENSE, authorship, backend, plugin metadata, and README
are preserved. Only package version/provenance and the battery polling block
in dist/index.js are modified. Upstream supplies no source map in this archive.

The one-second callback used to dereference window.SystemPowerStore without
checking whether Steam had exposed the store in that UI context. Keep polling
so late initialization recovers automatically. Skip absent/null state and
state without a finite numeric eACState, without inventing an AC/battery value
or dispatching a false transition. Read Steam's existing batteryState object
again on every tick, retaining upstream object comparison and event handling.
The polling interval and onDismount cleanup remain unchanged.

The modified block and exact unified bundle diff are included in oxp3-compat/.
Rebuild with scripts/patch-autoflatpaks.py using the pinned upstream archive;
the builder checks package identity, version, and the exact original polling
block, and emits deterministic archive metadata.
