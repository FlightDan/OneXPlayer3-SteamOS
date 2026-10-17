# Performance overlay telemetry

The maintained runtime sources and sensor fixtures are in
`components/controls/overlay`. Both preparation scripts use these files for the
control ZIP and installable overlay component.

FAN reads the unique `oxp_ec` hwmon `fan1_input` directly. Stopping the OXP3 Fan
curve controller no longer removes RPM telemetry. The driver must still be
available. No PWM or fan mode is written by telemetry.

CPU and APU power use RAPL energy counters. GPU power prefers the RAPL `uncore`
counter, with a fallback to Intel Panther Lake PMT `VCCGT_ENERGY`. This fixes
boots where RAPL does not register `uncore` even though the GPU counter works.
The exact boot-time reason for a missing domain has not been proven.

The fallback accepts only GUID `0x03086000`, size `3352`, and reads the 64-bit
little-endian energy counter at byte offset `1640`. Joules are `raw / 16384`;
watts are the energy change divided by elapsed seconds. This is the reported GT
energy, rather than package power minus CPU power. Intel defines the field and
conversion in the [PTL layout](https://github.com/intel/Intel-PMT/blob/main/xml/PTL/0/ptl_aggregator.xml)
and [interface](https://github.com/intel/Intel-PMT/blob/main/xml/PTL/0/ptl_aggregator_interface.xml).

The root permission helper grants only group read access to the matching PMT
region after checking its device path and owner. Raw MSR permissions and all
power controls are unchanged. Duplicate, missing, unreadable, stale or invalid
data displays N/A. The PMT sampler rebaselines on source changes, counter
decreases, suspend and long sampling gaps.

The installed-device comparison matched PMT and raw PP1 counters for twelve
seconds (approximately 18.1–18.5W). All three overlay presets returned live GPU
power, CPU/APU power and RPM after deployment. The user subsequently confirmed
testing and requested publication. This does not establish complete new-install,
reboot or suspend/resume acceptance. The existing permission oneshot runs after
udev triggering; late PMT enumeration or device recreation may require restarting
`oxp3-overlay-read.service`.

Run the Linux fixtures from `components/controls/overlay`:

```sh
python3 -B -m unittest -v test_telemetry_fan.py test_telemetry_gpu.py
```
