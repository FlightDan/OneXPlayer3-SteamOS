# Source and license notices

OXP3 Light 0.1.0 is a narrowly scoped lighting adaptation. Preserve this file and all accompanying LICENSE files when distributing it, including in installer archives.

## HueSync

Source: [HHHHanasak1/HueSync, oxp3 branch](https://github.com/HHHHanasak1/HueSync/tree/e05aa394f8e3a339b0f6e0c54e0ed23b955e7e84), pinned on 2026-10-16 to commit `e05aa394f8e3a339b0f6e0c54e0ed23b955e7e84`. This fork credits [honjow/HueSync](https://github.com/honjow/HueSync) and is based on upstream 3.9.0. The fork account was previously PPPPatrick0 and is now HHHHanasak1.

Copyright (c) 2024, honjow

Original Copyright (c) 2022-2024, Steam Deck Homebrew

All rights reserved. Full BSD 3-Clause terms, conditions, and disclaimer are reproduced without omissions in `LICENSE-HueSync` and `LICENSE`.

Files inspected at that exact revision:

- `py_modules/devices/onexplayer.py`: ONEXPLAYER 3 backend selection and three-zone routing.
- `py_modules/devices/oxp3_native_leds.py`: exact native LED names, attributes, and monocolor handling.
- `py_modules/devices/onexplayer_configs.py`: exact `ONEXPLAYER 3` model and X2-class zone layout.
- `py_modules/led/onex_led_device_hid.py`: VID/PID, usage, ring mirroring, 50 ms command interval, and zone sides 1, 2, 5, 6.
- `py_modules/led/hhd/oxp_hid_v1.py`: HID v1 64-byte envelope, solid-color payload, and enable/brightness payload.

OXP3 Light supplies independent fixed-path Linux hidraw discovery and a small lighting-only transport. It does not import HueSync's device classes, generic command helpers, button-table initialization, intercept commands, controller modes, software effects, serial transport, bundled hid/serial libraries, or updater. The upstream device class initializes the controller; it is deliberately excluded. All outgoing frames are checked again against the two lighting subcommand layouts before writing.

## Handheld Daemon (HHD) port provenance

HueSync's `py_modules/led/hhd/oxp_hid_v1.py` explicitly states that it is ported from `hhd/device/oxp/hid_v1.py`. HHD project author: Antheas Kapenekakis (project metadata also writes the name as Kapenekakis Antheas), and HHD contributors. Actual original module: [`hhd-dev/hhd/src/hhd/device/oxp/hid_v1.py`](https://github.com/hhd-dev/hhd/blob/52423445aa1b183697b98156ccb38c352b0d6949/src/hhd/device/oxp/hid_v1.py). Its current module revision inspected was commit `52423445aa1b183697b98156ccb38c352b0d6949` (2026-09-10, “restore zones 5 and 6 after windows verification”). This is the source of the port's HID v1 framing conventions, rather than an invented attribution to a standalone lighting library.

HHD's project metadata declares `LGPL-2.1-or-later`. Its full distributed LGPL 2.1 text is retained as `LICENSE-HHD`. The derived framing helpers in `light_control.py` retain that provenance and LGPL-2.1-or-later licensing in addition to the HueSync BSD notice. Their complete editable source is included; there is no compiled HHD library to relink. The remainder of this plugin is offered under the accompanying BSD 3-Clause license. This distribution makes no claim to relicense HHD under BSD alone.

## Local verification

The USB vendor interface and report descriptor were checked read-only on the target ONEXPLAYER 3 (SteamOS 3.10 build 20260924.1000, kernel 7.2.4, BIOS 5.09): `1a86:fe00`, USB interface `02`, top-level usage `ff00:0001`, one 64-byte input/output report. The exact descriptor is pinned in `light_control.py`; interface 00 is a keyboard and interface 01 is a mouse. A different descriptor or interface is rejected. This hardware observation is distinct from the upstream source provenance above.

The same accepted baseline was also checked read-only for native LEDs: its old/custom `hid-oxp` exposes only `oxp:rgb:joystick_rings` (including effect/color attributes), with no `guide_button` or `rear_logo`. This placeholder is not proof of working OXP3 native lighting. The exact legacy profile (`7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9`, SteamOS `3.10`, build `20260924.1000`) therefore selects the vetted HID backend before inspecting LED names. Other/new profiles retain fail-closed handling for partial native interfaces, and no native write error triggers HID fallback.

Linux transport was checked against the primary implementations: [HIDAPI Linux `hid_write`](https://github.com/libusb/hidapi/blob/master/linux/hid.c) calls `write` directly, while [Linux USB HID `usbhid_output_report` / `usbhid_set_raw_report`](https://github.com/torvalds/linux/blob/master/drivers/hid/usbhid/hid-core.c) strip an explicit report-number zero before sending an unnumbered USB payload and include that byte in the return count. OXP3 Light therefore writes `0x00` plus the 64-byte payload, checking a 65-byte return; the MCU receives the same 64-byte lighting payload. This also selects report number zero for control-transfer fallback. These implementations were inspected, not copied into the distribution.
