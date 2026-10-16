# OXP3 Light 0.1.0

Decky lighting controls for ONEXPLAYER 3. Uses native Steam/Decky UI, matching OXP3 CPU, Fan and Battery. Browser Chinese locales select Chinese; other locales use English.

Three independent solid-color zones: **paired joystick rings** (both rings together), **Xbox button**, and **rear slogan**. Each has an on/off switch, RGB color controls and brightness 0–100%. Draft edits never write hardware. **Apply this zone** sends only the selected zone. The color presets are solid RGB conveniences, not firmware animations.

## Installation package

Stage this directory as `OXP3-Light` in Decky's plugins directory. Runtime files are `main.py`, `light_control.py`, `plugin.json`, `package.json`, `dist/index.js`, `LICENSE`, `LICENSE-HueSync`, `LICENSE-HHD`, `THIRD_PARTY_NOTICES.md` and this README. No pip, npm, hidapi, serial, background service, Internet access or root filesystem change is needed. The readable `dist/index.js` is the shipped JavaScript source, with no build step. Root access is required for the selected sysfs LED/hidraw device.

The installer owns staging and updating this package; it must retain the notices. This plugin does not update itself.

## Backend selection and safety

- Exact DMI product name `ONEXPLAYER 3` is required.
- The verified legacy profile is selected **before native LED discovery**: `/proc/sys/kernel/osrelease` must equal `7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9`, and `/etc/os-release` must contain exactly matching `ID=steamos`, `VERSION_ID=3.10`, `BUILD_ID=20260924.1000`. This accepted SteamOS build has an ineffective `joystick_rings` LED placeholder without the other two zones. It always uses the vetted HID transport, even if all three placeholder names appear. A changed/malformed/missing profile does not receive this exception.
- For other profiles, prefer the three exact kernel LED directories together: `/sys/class/leds/oxp:rgb:joystick_rings`, `oxp:rgb:guide_button`, `oxp:rgb:rear_logo`. All three must expose the expected multicolor/effect attributes, RGB channel order, valid `max_brightness`, and the rings enable attribute. Sysfs attributes are fixed, resolved under `/sys/devices`, with leaf symlinks rejected. An incomplete native interface on a new/unknown profile or any native write error fails visibly and never switches to HID.
- HID requires exactly one device with USB vendor/product `1a86:fe00`, interface `02`, usage page `ff00`, usage `0001` and the exact verified 64-byte report descriptor. The node must be a character device matching the sysfs major/minor. The legacy OS/kernel exception does not relax these checks or the DMI model check. Interfaces 00/01, other devices, changed descriptors and ambiguous matches are rejected.
- HID payloads are exclusively 64-byte `B8/FD` enable and `B8/FE` solid color reports on sides 1/2 (rings), 5 (Xbox), 6 (slogan). Linux hidraw writes prepend report number zero, so the syscall receives 65 bytes and USB sends the vetted 64-byte payload. There is no generic frame endpoint. Brightness scales the RGB values with the hardware level held at high. Reports are spaced by 50 ms. Button-table initialization, intercept, vibration, rebind, gamepad mode, driver unbind and arbitrary commands/paths are absent.
- Backend inputs are fully validated before discovery or writes. Transactions and status reads are serialized within the plugin. Do not run another lighting writer concurrently; the plugin cannot lock unrelated processes or the firmware.

## State and limitations

Loading, reading status, closing and unloading the plugin do not change lights. No persistence, automatic boot apply, resume apply, or removal reset is performed. The firmware may retain the last applied color, or reset it on reboot/suspend; manually reapply a zone when needed. Uninstalling preserves the current lighting state.

Hardware settings cannot be queried through this HID protocol. Values in the panel are explicitly **drafts**, including after panel reopen. A successful call means the reports/attributes were written, not that firmware readback confirmed the visible result. A partial failure leaves the zone unknown and shows an error; retry applies the full selected-zone setting. Native writes may take time while the kernel acknowledges an effect change.

Only solid colors are implemented. Native preset animations and hardware animation speeds are intentionally omitted. Other ONEXPLAYER products and changed USB descriptors require a new reviewed implementation. No live lighting writes are part of the automated tests.

## Tests

From the repository root:

```text
python -m unittest discover -s windows-installer/components/light -p test_light_control.py -v
node --test windows-installer/components/light/test_light_ui.mjs
node --check windows-installer/components/light/dist/index.js
```

Python tests cover exact frame bytes, forbidden frame mutations, numeric/schema validation, no writes for invalid requests or discovery, DMI/path/device/descriptor guards, the exact legacy OS/kernel profile and each mismatched field, legacy partial/complete LED placeholders, native capability checks, native-only zone writes, no native write-error fallback, short writes, ambiguous devices and concurrent transactions. UI tests exercise lifecycle, localized zone controls, explicit Apply, errors, duplicate requests and disabled states with native Decky component mocks.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the exact HueSync commit, upstream authors, original HHD port provenance and retained licenses.
