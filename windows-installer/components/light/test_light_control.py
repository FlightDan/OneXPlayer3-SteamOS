"""No hardware required; every write is mocked or confined to temporary fixtures."""
import concurrent.futures
import copy
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

import light_control as light

CONFIG = {"enabled": True, "color": [255, 128, 0], "brightness": 60}


class FakeHardware:
    def __init__(self, native=False):
        self.native = native
        self.calls = []
        self.active = 0
        self.maximum_active = 0
        self.fail = False
        self.supported = True
    def check_model(self):
        if not self.supported: raise RuntimeError("Wrong DMI")
    def native_present(self): return self.native
    def hid_target(self): return "read-only-target"
    def _apply(self, backend, zone, config):
        self.active += 1
        self.maximum_active = max(self.active, self.maximum_active)
        try:
            time.sleep(.002)
            self.calls.append((backend, zone, copy.deepcopy(config)))
            if self.fail: raise OSError("simulated write failure")
        finally: self.active -= 1
    def native_apply(self, zone, config): self._apply("native", zone, config)
    def hid_apply(self, zone, config): self._apply("hid", zone, config)


class ProtocolTests(unittest.TestCase):
    def test_exact_solid_and_enable_bytes(self):
        frames = light.lighting_frames("rings", CONFIG)
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0], bytes.fromhex("b83f01fd0102010504") + bytes(53) + bytes.fromhex("3fb8"))
        self.assertEqual(frames[1], bytes.fromhex("b83f01fe0102") + bytes([153, 77, 0]) * 18 + bytes([153, 77]) + bytes.fromhex("3fb8"))
        self.assertEqual([f[4] for f in frames], [1, 1, 2, 2])
        self.assertTrue(all(map(light.vetted_frame, frames)))

    def test_all_zones_off_and_zero_brightness(self):
        for zone, sides in light.ZONES.items():
            for config in ({**CONFIG, "enabled": False}, {**CONFIG, "brightness": 0}):
                frames = light.lighting_frames(zone, config)
                self.assertEqual(tuple(f[4] for f in frames), sides)
                self.assertTrue(all(f[3] == 0xFD and f[6] == 0 and light.vetted_frame(f) for f in frames))

    def test_no_other_zone_or_forbidden_command(self):
        for zone, sides in light.ZONES.items():
            for brightness in (0, 1, 25, 60, 99, 100):
                for enabled in (True, False):
                    for frame in light.lighting_frames(zone, {**CONFIG, "brightness": brightness, "enabled": enabled}):
                        self.assertEqual(frame[0], 0xB8)
                        self.assertIn(frame[3], (0xFD, 0xFE))
                        self.assertIn(frame[4], sides)
                        self.assertNotIn(frame[0], (0xB2, 0xB3, 0xB4))
        valid = light.lighting_frames("xbox", CONFIG)[0]
        for index, invalid in ((0, 0xB4), (0, 0xB2), (0, 0xB3), (3, 0x01), (4, 0), (4, 3), (4, 4), (4, 7), (6, 2), (8, 3), (10, 1), (62, 0)):
            frame = bytearray(valid); frame[index] = invalid
            self.assertFalse(light.vetted_frame(bytes(frame)), (index, invalid))
        self.assertFalse(light.vetted_frame(valid[:-1]))

    def test_descriptor_parser(self):
        self.assertEqual(light.application_usages(light.REPORT_DESCRIPTOR), [(0xFF00, 1)])
        self.assertNotEqual(light.application_usages(bytes.fromhex("05010906a101c0")), [(0xFF00, 1)])
        for invalid in (b"\xfe", b"\x06\x00", b"\xc0", bytes.fromhex("05010906a101")):
            with self.assertRaises(ValueError): light.application_usages(invalid)


class ControllerTests(unittest.TestCase):
    def test_load_status_are_read_only_and_unknown(self):
        hardware = FakeHardware()
        controller = light.LightController(hardware)
        self.assertTrue(controller.status()["available"])
        self.assertEqual(controller.status()["zones"], dict.fromkeys(light.ZONES))
        self.assertEqual(hardware.calls, [])

    def test_invalid_requests_do_not_discover_or_write(self):
        hardware = mock.Mock()
        controller = light.LightController(hardware)
        requests = [("../xbox", CONFIG), ([], CONFIG), ("xbox", None), ("xbox", []),
                    ("xbox", {**CONFIG, "path": "/etc/passwd"}), ("xbox", {**CONFIG, "enabled": 1}),
                    ("xbox", {**CONFIG, "brightness": True}), ("xbox", {**CONFIG, "brightness": 1.1}),
                    ("xbox", {**CONFIG, "brightness": -1}), ("xbox", {**CONFIG, "brightness": 101}),
                    ("xbox", {**CONFIG, "color": [256, 0, 0]}), ("xbox", {**CONFIG, "color": [True, 0, 0]}),
                    ("xbox", {**CONFIG, "color": [0, 0]}), ("xbox", {**CONFIG, "color": "ff0000"})]
        for zone, config in requests:
            with self.assertRaises(ValueError): controller.set_zone(zone, config)
        self.assertEqual(hardware.mock_calls, [])

    def test_native_selection_and_only_selected_zone(self):
        hardware = FakeHardware(native=True)
        controller = light.LightController(hardware)
        state = controller.set_zone("xbox", CONFIG)
        self.assertEqual(hardware.calls, [("native", "xbox", CONFIG)])
        self.assertEqual(state["zones"], {"rings": None, "xbox": CONFIG, "slogan": None})
        state["zones"]["xbox"]["color"][0] = 0
        self.assertEqual(controller.status()["zones"]["xbox"]["color"][0], 255)

    def test_model_guard_before_writes(self):
        hardware = FakeHardware(); hardware.supported = False
        controller = light.LightController(hardware)
        self.assertFalse(controller.status()["available"])
        with self.assertRaises(RuntimeError): controller.set_zone("rings", CONFIG)
        self.assertEqual(hardware.calls, [])

    def test_native_failure_never_falls_back_and_state_unknown(self):
        hardware = FakeHardware(native=True)
        controller = light.LightController(hardware)
        controller.set_zone("rings", CONFIG)
        hardware.fail = True
        with self.assertRaises(RuntimeError): controller.set_zone("rings", CONFIG)
        self.assertTrue(all(call[0] == "native" for call in hardware.calls))
        self.assertIsNone(controller.status()["zones"]["rings"])
        self.assertIn("unknown", controller.status()["error"])

    def test_concurrent_transactions_are_serial(self):
        hardware = FakeHardware()
        controller = light.LightController(hardware)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(controller.set_zone, list(light.ZONES)[i % 3], {**CONFIG, "brightness": i}) for i in range(24)]
            for future in futures: future.result()
        self.assertEqual(len(hardware.calls), 24)
        self.assertEqual(hardware.maximum_active, 1)


class LinuxPathTests(unittest.TestCase):
    def setUp(self):
        # NTFS reserves ':'; fixture aliases exercise identical path guards on Windows.
        if os.name == "nt":
            patcher = mock.patch.dict(light.LEDS, {key: value.replace(":", "_") for key, value in light.LEDS.items()})
            patcher.start(); self.addCleanup(patcher.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hardware = light.LinuxHardware()
        self.hardware.devices = self.root / "devices"
        self.hardware.devices.mkdir()
        self.hardware.led_base = self.hardware.devices / "leds"
        self.hardware.led_base.mkdir()
        self.hardware.hid_base = self.hardware.devices / "hidraw"
        self.hardware.hid_base.mkdir()
        self.hardware.dev_base = self.root / "dev"
        self.hardware.dmi = self.root / "product_name"
        self.hardware.dmi.write_text("ONEXPLAYER 3\n")
        self.hardware.kernel_release = self.root / "kernel_release"
        self.hardware.kernel_release.write_text("unknown-kernel\n")
        self.hardware.os_release = self.root / "os-release"
        self.hardware.os_release.write_text('ID=steamos\nVERSION_ID="3.10"\nBUILD_ID=20260924.1000\n')

    def leds(self):
        for name in light.LEDS.values():
            directory = self.hardware.led_base / name; directory.mkdir(exist_ok=True)
            for attr, value in {"max_brightness": "100", "brightness": "30", "multi_index": "green blue red", "multi_intensity": "1 2 3", "enabled": "true", "effect": "aurora"}.items():
                (directory / attr).write_text(value)

    def hid(self):
        entry = self.hardware.hid_base / "hidraw2"; entry.mkdir()
        device = entry / "device"; device.mkdir()
        (device / "uevent").write_text("HID_ID=0003:00001A86:0000FE00\n")
        (device / "bInterfaceNumber").write_text("02\n")
        (device / "report_descriptor").write_bytes(light.REPORT_DESCRIPTOR)
        (entry / "dev").write_text("240:2")
        return entry, device

    def test_exact_dmi_and_native_partial_guard(self):
        self.hardware.check_model()
        self.hardware.dmi.write_text("ONEXPLAYER X1 mini")
        with self.assertRaises(RuntimeError): self.hardware.check_model()
        self.assertFalse(self.hardware.native_present())
        (self.hardware.led_base / light.LEDS["rings"]).mkdir()
        with self.assertRaises(RuntimeError): self.hardware.native_present()

    def test_verified_legacy_profile_bypasses_partial_or_complete_native_placeholders(self):
        self.hardware.kernel_release.write_text(light.LEGACY_KERNEL + "\n")
        self.assertTrue(self.hardware.legacy_hid_profile())
        self.assertFalse(self.hardware.native_present())
        (self.hardware.led_base / light.LEDS["rings"]).mkdir()
        self.assertFalse(self.hardware.native_present())
        self.leds()
        # The accepted baseline always uses HID, including with three placeholders.
        with mock.patch.object(self.hardware, "_native_format") as native_format:
            self.assertFalse(self.hardware.native_present())
            native_format.assert_not_called()
        entry, _ = self.hid()
        controller = light.LightController(self.hardware)
        with mock.patch.object(self.hardware, "native_apply") as native, mock.patch.object(self.hardware, "hid_apply") as hid:
            self.assertEqual(controller.status()["backend"], "hid-v1")
            controller.set_zone("slogan", CONFIG)
            native.assert_not_called(); hid.assert_called_once_with("slogan", CONFIG)

    def test_legacy_profile_exception_requires_every_exact_field(self):
        self.hardware.kernel_release.write_text(light.LEGACY_KERNEL)
        (self.hardware.led_base / light.LEDS["rings"]).mkdir()
        valid_os = self.hardware.os_release.read_text()
        valid_kernel = light.LEGACY_KERNEL
        for kernel, os_release in (
            (valid_kernel.replace("7.2.4", "7.2.7"), valid_os),
            (valid_kernel + "-custom", valid_os),
            (valid_kernel, valid_os.replace("ID=steamos", "ID=arch")),
            (valid_kernel, valid_os.replace("3.10", "3.11")),
            (valid_kernel, valid_os.replace("20260924.1000", "20260925.1000")),
            (valid_kernel, valid_os.replace("BUILD_ID=20260924.1000\n", "")),
            (valid_kernel, valid_os + "BUILD_ID=20260924.1000\n"),
            (valid_kernel, valid_os.replace('VERSION_ID="3.10"', 'VERSION_ID="3.10')),
        ):
            self.hardware.kernel_release.write_text(kernel)
            self.hardware.os_release.write_text(os_release)
            self.assertFalse(self.hardware.legacy_hid_profile(), (kernel, os_release))
            with self.assertRaises(RuntimeError): self.hardware.native_present()
        self.hardware.os_release.unlink()
        self.assertFalse(self.hardware.legacy_hid_profile())
        with self.assertRaises(RuntimeError): self.hardware.native_present()

    def test_legacy_profile_still_requires_model_and_exact_hid(self):
        self.hardware.kernel_release.write_text(light.LEGACY_KERNEL)
        (self.hardware.led_base / light.LEDS["rings"]).mkdir()
        controller = light.LightController(self.hardware)
        with mock.patch.object(self.hardware, "hid_apply") as write:
            self.assertFalse(controller.status()["available"])
            with self.assertRaises(RuntimeError): controller.set_zone("rings", CONFIG)
            write.assert_not_called()
        self.hid()
        self.hardware.dmi.write_text("ONEXPLAYER X1 mini")
        self.assertFalse(controller.status()["available"])

    def test_unknown_native_profile_requires_capabilities_without_fallback(self):
        self.leds()
        (self.hardware.led_base / light.LEDS["slogan"] / "effect").unlink()
        controller = light.LightController(self.hardware)
        with mock.patch.object(self.hardware, "hid_target") as hid:
            self.assertFalse(controller.status()["available"])
            with self.assertRaises(OSError): controller.set_zone("slogan", CONFIG)
            hid.assert_not_called()

    def test_sysfs_native_channel_order_and_selected_zone(self):
        self.leds(); self.assertTrue(self.hardware.native_present())
        with mock.patch.object(self.hardware, "_write") as write:
            self.hardware.native_apply("xbox", CONFIG)
        self.assertEqual(write.call_args_list, [mock.call("xbox", "multi_intensity", "128 0 255"), mock.call("xbox", "effect", "monocolor"), mock.call("xbox", "brightness", 60)])
        with mock.patch.object(self.hardware, "_write") as write:
            self.hardware.native_apply("rings", {**CONFIG, "enabled": False})
        write.assert_called_once_with("rings", "brightness", 0)
        with mock.patch.object(self.hardware, "_write") as write:
            self.hardware.native_apply("slogan", {**CONFIG, "brightness": 0})
        write.assert_called_once_with("slogan", "brightness", 0)
        with mock.patch.object(self.hardware, "_write") as write:
            self.hardware.native_apply("rings", CONFIG)
        self.assertEqual(write.call_args_list[0], mock.call("rings", "enabled", "true"))

    def test_native_preflight_and_path_rejection_no_writes(self):
        self.leds()
        with self.assertRaises(ValueError): self.hardware._attribute("../rings", "brightness")
        with self.assertRaises(ValueError): self.hardware._attribute("rings", "../../passwd")
        self.hardware.devices = self.root / "wrong-root"
        with self.assertRaises(RuntimeError): self.hardware._attribute("rings", "brightness")
        self.hardware.devices = self.root / "devices"
        (self.hardware.led_base / light.LEDS["rings"] / "multi_index").write_text("red blue")
        with mock.patch.object(self.hardware, "_write") as write:
            with self.assertRaises(RuntimeError): self.hardware.native_apply("rings", CONFIG)
        write.assert_not_called()

    def test_hid_exact_vendor_product_interface_and_descriptor(self):
        entry, device = self.hid()
        self.assertEqual(self.hardware.hid_target(), entry)
        for field, invalid in (("uevent", b"HID_ID=0003:00001A86:0000FE01\n"), ("bInterfaceNumber", b"00"), ("bInterfaceNumber", b"01"), ("report_descriptor", light.REPORT_DESCRIPTOR[:-1]), ("report_descriptor", light.REPORT_DESCRIPTOR.replace(b"\x95\x40", b"\x95\x20"))):
            original = (device / field).read_bytes(); (device / field).write_bytes(invalid)
            with self.assertRaises(RuntimeError): self.hardware.hid_target()
            (device / field).write_bytes(original)

    def test_ambiguous_hid_fails_closed(self):
        entry, device = self.hid()
        import shutil
        shutil.copytree(entry, self.hardware.hid_base / "hidraw3")
        with self.assertRaises(RuntimeError): self.hardware.hid_target()

    def test_hid_write_boundary_device_type_and_short_write(self):
        entry, device = self.hid()
        # O_NOFOLLOW/O_CLOEXEC are Linux-only; simulate syscall flags in Windows tests.
        with mock.patch.object(os, "O_NOFOLLOW", 0, create=True), mock.patch.object(os, "O_CLOEXEC", 0, create=True), mock.patch.object(os, "O_NONBLOCK", 0, create=True), mock.patch.object(os, "open", return_value=42), mock.patch.object(os, "close") as close, mock.patch.object(os, "makedev", return_value=1234, create=True), mock.patch.object(os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFREG, st_rdev=1234)), mock.patch.object(os, "write") as write:
            with self.assertRaises(RuntimeError): self.hardware.hid_apply("xbox", CONFIG)
            write.assert_not_called(); close.assert_called_once_with(42)
        with mock.patch.object(os, "O_NOFOLLOW", 0, create=True), mock.patch.object(os, "O_CLOEXEC", 0, create=True), mock.patch.object(os, "O_NONBLOCK", 0, create=True), mock.patch.object(os, "open", return_value=42), mock.patch.object(os, "close") as close, mock.patch.object(os, "makedev", return_value=1234, create=True), mock.patch.object(os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFCHR, st_rdev=1234)), mock.patch.object(os, "write", return_value=63) as write:
            with self.assertRaises(OSError): self.hardware.hid_apply("xbox", CONFIG)
            self.assertEqual(write.call_count, 1); close.assert_called_once_with(42)

    def test_hid_success_sequence_zero_report_prefix_and_spacing(self):
        self.hid()
        with mock.patch.object(os, "O_NOFOLLOW", 0, create=True), mock.patch.object(os, "O_CLOEXEC", 0, create=True), mock.patch.object(os, "O_NONBLOCK", 0, create=True), mock.patch.object(os, "open", return_value=42), mock.patch.object(os, "close") as close, mock.patch.object(os, "makedev", return_value=1234, create=True), mock.patch.object(os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFCHR, st_rdev=1234)), mock.patch.object(os, "write", return_value=65) as write, mock.patch.object(light.time, "sleep") as sleep:
            self.hardware.hid_apply("rings", CONFIG)
            self.assertEqual(write.call_args_list, [mock.call(42, b"\x00" + frame) for frame in light.lighting_frames("rings", CONFIG)])
            self.assertEqual(sleep.call_args_list, [mock.call(.05)] * 4)
            close.assert_called_once_with(42)

    def test_hid_rdev_and_revalidation_guards(self):
        self.hid()
        for rdev, identities in ((9999, [True]), (1234, [True, False])):
            with mock.patch.object(os, "O_NOFOLLOW", 0, create=True), mock.patch.object(os, "O_CLOEXEC", 0, create=True), mock.patch.object(os, "O_NONBLOCK", 0, create=True), mock.patch.object(os, "open", return_value=42), mock.patch.object(os, "close") as close, mock.patch.object(os, "makedev", return_value=1234, create=True), mock.patch.object(os, "fstat", return_value=mock.Mock(st_mode=stat.S_IFCHR, st_rdev=rdev)), mock.patch.object(os, "write") as write, mock.patch.object(self.hardware, "_hid_identity", side_effect=identities):
                with self.assertRaises(RuntimeError): self.hardware.hid_apply("xbox", CONFIG)
                write.assert_not_called(); close.assert_called_once_with(42)


if __name__ == "__main__": unittest.main()
