# OXP3 controls source

`cpu/` and `rapl/` are the maintained CPU plugin and RAPL provider sources.
`prepare-controls.py` includes them in the control resource ZIP; `prepare-integration.py`
uses the same files for the installable CPU and native-TDP components. The remaining
control sources retain their existing research-source locations.

OXP3 CPU 0.2.0 adds two runtime power sliders:

- PL1: 10–40W, using the same `TdpLimit1.TdpLimit` property as Steam's native TDP.
  An explicit plugin edit also uses the native widget's unified settings writer
  for `steamos_tdp_limit` and `steamos_tdp_limit_enabled`, waits for confirmation,
  then applies/readbacks hardware. Steam handles persistence of its settings.
  The plugin polls live limits so changes through Steam are reflected in the plugin.
- PL2: 10–80W, at least the highest live PL1. Its dynamic slider minimum follows PL1.
  Lowering PL1 preserves PL2; raising PL1 above PL2 raises the lower PL2 domain(s).

The existing provider owns all four MSR/MMIO limits and serializes both APIs.
Writes use readback and attempted-path rollback. No power defaults are applied
on plugin mount, unload, provider restart, or installation. Power settings are
runtime hardware state; no additional PL2 per-game/AC/DC policy is saved. Existing CPU frequency
and EPP configuration keeps its previous behavior; its restore button only restores
those settings, not the Steam/package power limits.

Deploy the updated provider and plugin together. An older provider leaves the new
power section unavailable, with a retry action; CPU frequency controls remain usable.
The new D-Bus `org.onexplayer.SteamOSManager.PowerLimits1` interface uses the existing
bus name/object and root/deck authorization. No additional system-bus policy is needed.

Run Linux fixture checks from each source directory:

```sh
cd rapl && python3 -B -m unittest -v test_provider.py
cd ../cpu && python3 -B -m unittest -v test_cpu_control.py test_power_control.py
node test_cpu_power_ui.mjs
```

These cover transactions, rollback, authorization, live readback, native property
routing and UI state transitions. Separately, live-device slider checks confirmed
plugin PL1 20W -> native Steam page 20W, native 30W -> plugin/hardware 30W, and
PL2 slider writes of 52W/80W without changing PL1 or native settings. Values are
bold/right aligned, with PL2 yellow at 52W and above. Tests restored the prior
40W/49W hardware limits. See `docs/CPU_POWER_LIMITS.md` for evidence. This does not
establish 80W load delivery, performance gains, thermal acceptance, or suspend/reboot behavior.
