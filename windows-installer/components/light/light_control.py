"""ONEXPLAYER 3 lighting only. No controller initialization or input interception.

Protocol/zone routing adapted from HueSync oxp3; see THIRD_PARTY_NOTICES.md,
LICENSE-HueSync (honjow, Steam Deck Homebrew) and LICENSE-HHD (HHD port).
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import shlex
import stat
import threading
import time

ZONES = {"rings": (1, 2), "xbox": (5,), "slogan": (6,)}
LEDS = {"rings": "oxp:rgb:joystick_rings", "xbox": "oxp:rgb:guide_button", "slogan": "oxp:rgb:rear_logo"}
VID, PID, INTERFACE, USAGE_PAGE, USAGE = 0x1A86, 0xFE00, 2, 0xFF00, 1
# Read-only verified OXP3 MCU vendor interface; the adjacent interfaces are keyboard/mouse.
REPORT_DESCRIPTOR = bytes.fromhex("0600ff0901a101090215002600ff750895408106090215002600ff750895409106c0")
LEGACY_KERNEL = "7.2.4-valve1-1-neptune-72-g5ab4af5e2eb9"
LEGACY_OS = {"ID": "steamos", "VERSION_ID": "3.10", "BUILD_ID": "20260924.1000"}


def validate(zone, config):
    if not isinstance(zone, str) or zone not in ZONES:
        raise ValueError("Unknown lighting zone")
    if not isinstance(config, dict) or set(config) != {"enabled", "color", "brightness"}:
        raise ValueError("Expected enabled, color and brightness only")
    if type(config["enabled"]) is not bool:
        raise ValueError("enabled must be boolean")
    color = config["color"]
    if not isinstance(color, list) or len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
        raise ValueError("RGB must contain three integers from 0 to 255")
    if type(config["brightness"]) is not int or not 0 <= config["brightness"] <= 100:
        raise ValueError("brightness must be an integer from 0 to 100")
    return copy.deepcopy(config)


def lighting_frames(zone, config):
    """HueSync/HHD-derived framing (LGPL-2.1-or-later, BSD notice retained).

    Only B8/FD (enable) and B8/FE (solid) are implemented, no generic RPC.
    """
    config = validate(zone, config)
    rgb = [(v * config["brightness"] + 50) // 100 for v in config["color"]]
    enabled = config["enabled"] and config["brightness"] > 0
    frames = []
    for side in ZONES[zone]:
        # HueSync/HHD HID v1: 64 bytes, B8 3F 01 payload padding 3F B8.
        payload = bytes((0xFD, side, 2, int(enabled), 5, 4))
        frames.append(bytes((0xB8, 0x3F, 1)) + payload + bytes(53) + bytes((0x3F, 0xB8)))
        if enabled:
            payload = bytes((0xFE, side, 2)) + bytes(rgb) * 18 + bytes(rgb[:2])
            frames.append(bytes((0xB8, 0x3F, 1)) + payload + bytes((0x3F, 0xB8)))
    return tuple(frames)


def vetted_frame(frame):
    """Defence at the write boundary: reject every non-lighting frame."""
    if not isinstance(frame, bytes) or len(frame) != 64 or frame[:3] != b"\xb8\x3f\x01" or frame[-2:] != b"\x3f\xb8":
        return False
    if frame[4] not in (1, 2, 5, 6) or frame[5] != 2:
        return False
    if frame[3] == 0xFD:
        return frame[6] in (0, 1) and frame[7:9] == b"\x05\x04" and frame[9:62] == bytes(53)
    if frame[3] == 0xFE:
        return frame[6:62] == frame[6:9] * 18 + frame[6:8]
    return False


def application_usages(descriptor):
    """Parse top-level HID Application usages; malformed/ambiguous reports fail closed."""
    page, usages, local_usage, depth, stack = 0, [], None, 0, []
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]; i += 1
        if prefix == 0xFE:
            raise ValueError("HID long items are unsupported")
        size = (0, 1, 2, 4)[prefix & 3]
        if i + size > len(descriptor):
            raise ValueError("Truncated HID descriptor")
        value = int.from_bytes(descriptor[i:i + size], "little"); i += size
        tag, kind = prefix >> 4, (prefix >> 2) & 3
        if kind == 1 and tag == 0: page = value
        elif kind == 1 and tag == 10: stack.append(page)
        elif kind == 1 and tag == 11:
            if not stack: raise ValueError("Invalid HID globals")
            page = stack.pop()
        elif kind == 2 and tag == 0: local_usage = value
        elif kind == 0:
            if tag == 10:
                if depth == 0 and value == 1:
                    if local_usage is None: raise ValueError("Missing application usage")
                    usages.append((local_usage >> 16, local_usage & 65535) if local_usage > 65535 else (page, local_usage))
                depth += 1
            elif tag == 12:
                depth -= 1
                if depth < 0: raise ValueError("Invalid HID collection")
            local_usage = None
    if depth or stack: raise ValueError("Unclosed HID collection")
    return usages


class LinuxHardware:
    """Fixed local paths. None of these paths are accepted from Decky RPC."""
    dmi = Path("/sys/devices/virtual/dmi/id/product_name")
    led_base = Path("/sys/class/leds")
    hid_base = Path("/sys/class/hidraw")
    devices = Path("/sys/devices")
    dev_base = Path("/dev")
    kernel_release = Path("/proc/sys/kernel/osrelease")
    os_release = Path("/etc/os-release")

    def check_model(self):
        if self.dmi.read_text().strip() != "ONEXPLAYER 3":
            raise RuntimeError("Lighting is supported only on ONEXPLAYER 3")

    def legacy_hid_profile(self):
        """The verified legacy hid-oxp exposes ineffective LED placeholders.

        This exact OS/kernel profile must use the vetted HID transport even when
        placeholder LED names exist. An unknown/malformed profile grants no exception.
        """
        try:
            if self.kernel_release.read_text().strip() != LEGACY_KERNEL: return False
            values = {}
            for line in self.os_release.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator and key in LEGACY_OS:
                    if key in values: return False
                    parsed = shlex.split(value, comments=True, posix=True)
                    if len(parsed) != 1: return False
                    values[key] = parsed[0]
            return values == LEGACY_OS
        except (OSError, ValueError):
            return False

    def native_present(self):
        if self.legacy_hid_profile(): return False
        present = [(self.led_base / name).is_dir() for name in LEDS.values()]
        if any(present) and not all(present):
            raise RuntimeError("Incomplete native OXP3 LED interface; refusing HID fallback")
        if all(present):
            for zone in LEDS: self._native_format(zone)
            return True
        return False

    def _attribute(self, zone, attr):
        if zone not in LEDS or attr not in ("brightness", "max_brightness", "multi_index", "multi_intensity", "effect", "enabled"):
            raise ValueError("LED path is not allowed")
        directory = (self.led_base / LEDS[zone]).resolve(strict=True)
        if not directory.is_relative_to(self.devices.resolve()):
            raise RuntimeError("LED directory is outside sysfs devices")
        path = directory / attr
        if path.is_symlink(): raise RuntimeError("Unexpected LED attribute symlink")
        return path

    def _read(self, zone, attr):
        return self._attribute(zone, attr).read_text().strip()

    def _write(self, zone, attr, value):
        path = self._attribute(zone, attr)
        fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            data = str(value).encode("ascii")
            if os.write(fd, data) != len(data): raise OSError("Short LED attribute write")
        finally: os.close(fd)

    def _native_format(self, zone):
        """Require real multicolor/effect capabilities, not directory names alone."""
        maximum = int(self._read(zone, "max_brightness"))
        order = self._read(zone, "multi_index").split()
        if maximum <= 0 or maximum > 65535 or sorted(order) != ["blue", "green", "red"]:
            raise RuntimeError("Unexpected native multicolor LED format")
        for attr in ("multi_intensity", "effect", "brightness"):
            self._attribute(zone, attr).stat()
        if zone == "rings": self._attribute(zone, "enabled").stat()
        return maximum, order

    def native_apply(self, zone, config):
        # Preflight all attributes before the first write. Never fall back on error.
        maximum, order = self._native_format(zone)
        brightness = (maximum * config["brightness"] + 50) // 100 if config["enabled"] else 0
        if brightness:
            if zone == "rings": self._write(zone, "enabled", "true")
            channels = dict(zip(("red", "green", "blue"), config["color"]))
            self._write(zone, "multi_intensity", " ".join(str(channels[c]) for c in order))
            self._write(zone, "effect", "monocolor")
        self._write(zone, "brightness", brightness)

    def _hid_identity(self, entry):
        if not re.fullmatch(r"hidraw[0-9]+", entry.name): raise RuntimeError("Unexpected HID path")
        device = (entry / "device").resolve(strict=True)
        if not device.is_relative_to(self.devices.resolve()): raise RuntimeError("HID path outside sysfs")
        fields = dict(line.split("=", 1) for line in (device / "uevent").read_text().splitlines() if "=" in line)
        if fields.get("HID_ID", "").upper() != "0003:00001A86:0000FE00": return False
        interface = next((p for p in (device, *device.parents) if (p / "bInterfaceNumber").is_file()), None)
        if interface is None or int((interface / "bInterfaceNumber").read_text().strip(), 16) != INTERFACE: return False
        descriptor = (device / "report_descriptor").read_bytes()
        if descriptor != REPORT_DESCRIPTOR or application_usages(descriptor) != [(USAGE_PAGE, USAGE)]: return False
        return True

    def hid_target(self):
        matches = []
        for entry in self.hid_base.glob("hidraw*"):
            try:
                if self._hid_identity(entry): matches.append(entry)
            except (OSError, ValueError): continue
        if len(matches) != 1: raise RuntimeError("Exactly one matching OXP3 lighting HID interface is required")
        return matches[0]

    def hid_apply(self, zone, config):
        frames = lighting_frames(zone, config)
        if not all(vetted_frame(frame) for frame in frames): raise RuntimeError("Rejected non-lighting HID frame")
        entry = self.hid_target()
        node = self.dev_base / entry.name
        fd = os.open(node, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            major, minor = map(int, (entry / "dev").read_text().strip().split(":"))
            if not stat.S_ISCHR(info.st_mode) or info.st_rdev != os.makedev(major, minor) or not self._hid_identity(entry):
                raise RuntimeError("HID device identity changed")
            for frame in frames:
                # Linux hidraw ABI: report number 0 precedes an unnumbered report.
                # usbhid removes this byte on USB; the MCU receives the vetted 64-byte frame.
                report = b"\x00" + frame
                if os.write(fd, report) != len(report): raise OSError("Short HID lighting write")
                time.sleep(0.05)
        finally: os.close(fd)


class LightController:
    def __init__(self, hardware=None):
        self.hardware = hardware if hardware is not None else LinuxHardware()
        self._lock = threading.Lock()
        self._applied = {zone: None for zone in ZONES}
        self._error = None

    def _backend(self):
        self.hardware.check_model()
        if self.hardware.native_present(): return "native"
        self.hardware.hid_target()  # Read-only discovery; never initialize a controller.
        return "hid-v1"

    def _status(self):
        try:
            backend = self._backend()
            available, error = True, self._error
        except (OSError, RuntimeError, ValueError) as exc:
            backend, available, error = None, False, str(exc)
        return {"available": available, "backend": backend, "zones": copy.deepcopy(self._applied),
                "error": error, "readback": False, "version": "0.1.0"}

    def status(self):
        with self._lock: return self._status()

    def set_zone(self, zone, config):
        config = validate(zone, config)  # Reject invalid requests before discovery or writes.
        with self._lock:
            backend = self._backend()
            try:
                if backend == "native": self.hardware.native_apply(zone, config)
                else: self.hardware.hid_apply(zone, config)
            except Exception as exc:
                self._applied[zone] = None  # Partial hardware state cannot be claimed as applied.
                self._error = "Lighting write failed; zone state is unknown: " + str(exc)
                raise RuntimeError(self._error) from exc
            self._applied[zone] = config
            self._error = None
            return self._status()
