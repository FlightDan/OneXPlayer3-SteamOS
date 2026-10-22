# Opti2XMX 0.2.8

Fix the OptiScaler download-source selection resetting to GitHub when Steam's
native dropdown closes and rebuilds Quick Access. Both the normal install/repair
entry and the advanced version-install entry now keep the selected official or
third-party source for the current plugin session. Refresh, reopening the panel
and a failed-download retry preserve that choice. Unrecognized sources are refused.

The frontend regression fixture now discards state updates from unmounted
instances, matching React rather than allowing a stale callback to overwrite a
new component's hook slots. Tests cover all three sources, both install entries,
unmount/callback/remount, late callbacks and the source passed to the install RPC.

OptiScaler versions, XMX runtime and download URLs are unchanged. Existing cached
OptiScaler archives remain shared across sources; changing the source does not
force a new transfer. This fix does not repair a device's DNS or guarantee mirror
availability. Source tests and actual-device acceptance are recorded separately
in the integration release records.
