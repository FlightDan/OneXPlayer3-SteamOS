"""Focused transaction failure tests; these do not prove device acceptance."""

import unittest
from unittest.mock import Mock, patch
import sys
import types
import xml.etree.ElementTree as ET

from provider import (ControllerError, DriftObserver, InvalidLimit, RaplController,
                      BUS_NAME, OBJECT_PATH, POWER_LIMITS_INTERFACE, TDP_INTERFACE,
                      run_service)


class TransactionTests(unittest.TestCase):
    def controller(self, state, writer):
        state.setdefault("msr_pl2", 52_000_000)
        state.setdefault("mmio_pl2", 51_000_000)
        return RaplController(paths=("msr", "mmio"), reader=state.__getitem__,
                              writer=writer, validator=lambda: None, busy_checker=lambda: None,
                              pl2_paths=("msr_pl2", "mmio_pl2"))

    def test_second_write_failure_restores_both_distinct_snapshots(self):
        state = {"msr": 35_000_000, "mmio": 34_500_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            # Simulate a kernel write that mutates before reporting failure.
            state[path] = value
            if path == "mmio" and value == 20_000_000:
                raise OSError("injected second-write failure")

        with self.assertRaisesRegex(ControllerError, "rollback=verified"):
            self.controller(state, write).set_limit(20)
        self.assertEqual(state, {"msr": 35_000_000, "mmio": 34_500_000,
                                 "msr_pl2": 52_000_000, "mmio_pl2": 51_000_000})
        self.assertEqual(writes[-4:], list(state.items()))

    def test_rollback_failure_does_not_skip_other_restore_or_hide_state(self):
        state = {"msr": 35_000_000, "mmio": 35_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            if path == "mmio" and value == 20_000_000:
                raise OSError("request failure")
            if path == "msr" and value == 35_000_000:
                raise OSError("restore failure")
            state[path] = value

        controller = self.controller(state, write)
        with self.assertRaises(ControllerError) as context:
            controller.set_limit(20)
        message = str(context.exception)
        self.assertIn("request failure", message)
        self.assertIn("restore failure", message)
        self.assertIn("restore readback 20000000 uW != snapshot 35000000 uW", message)
        self.assertEqual(writes[-3:], [("mmio", 35_000_000), ("msr_pl2", 52_000_000),
                                      ("mmio_pl2", 51_000_000)])
        self.assertEqual(state["msr"], 20_000_000)
        self.assertEqual(state["mmio"], 35_000_000)
        # A truthful getter remains available; it cannot erase setter failure.
        self.assertEqual(controller.get_limit(), 20)

    def test_final_readback_detects_first_path_reset_and_restores(self):
        state = {"msr": 35_000_000, "mmio": 35_000_000}

        def write(path, value):
            state[path] = value
            if path == "mmio" and value == 20_000_000:
                state["msr"] = 35_000_000

        with self.assertRaisesRegex(ControllerError, "final readback"):
            self.controller(state, write).set_limit(20)
        self.assertEqual(state, {"msr": 35_000_000, "mmio": 35_000_000,
                                 "msr_pl2": 52_000_000, "mmio_pl2": 51_000_000})

    def test_partial_pl2_write_failure_restores_only_attempted_snapshots(self):
        state = {"msr": 25_000_000, "mmio": 24_500_000,
                 "msr_pl2": 24_000_000, "mmio_pl2": 23_000_000}
        original = state.copy()
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value
            if path == "mmio_pl2" and value == 35_000_000:
                raise OSError("partial PL2 write failed")

        with self.assertRaisesRegex(ControllerError, "rollback=verified"):
            self.controller(state, write).set_limit(35)
        self.assertEqual(state, original)
        self.assertEqual(writes[-2:], list(original.items())[2:])
        self.assertTrue(all(path.endswith("_pl2") for path, _ in writes))

    def test_failed_pl2_rollback_reports_incomplete_restoration_and_continues(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000,
                 "msr_pl2": 24_000_000, "mmio_pl2": 23_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            if path == "mmio_pl2" and value == 35_000_000:
                raise OSError("request failure")
            if path == "msr_pl2" and value == 24_000_000:
                raise OSError("PL2 restore failure")
            state[path] = value

        with self.assertRaises(ControllerError) as context:
            self.controller(state, write).set_limit(35)
        self.assertIn("PL2 restore failure", str(context.exception))
        self.assertIn("restore readback 35000000 uW != snapshot 24000000 uW", str(context.exception))
        self.assertEqual(writes[-1], ("mmio_pl2", 23_000_000))

    def test_35w_request_raises_lower_pl2_and_preserves_higher_one_first(self):
        state = {"msr": 20_000_000, "mmio": 20_000_000,
                 "msr_pl2": 22_500_000, "mmio_pl2": 52_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value

        controller = self.controller(state, write)
        controller.set_limit(35)
        self.assertEqual(state, {"msr": 35_000_000, "mmio": 35_000_000,
                                 "msr_pl2": 35_000_000, "mmio_pl2": 52_000_000})
        self.assertEqual(writes[:2], [("msr_pl2", 35_000_000), ("mmio_pl2", 52_000_000)])
        self.assertEqual(controller.get_limit(), 35)

    def test_invalid_requests_do_not_mutate_any_limit(self):
        state = {"msr": 35_000_000, "mmio": 35_000_000}
        writes = []
        controller = self.controller(state, lambda path, value: writes.append((path, value)))
        original = state.copy()
        for value in (9, 41, True, 35.0, "35"):
            with self.subTest(value=value), self.assertRaises(InvalidLimit):
                controller.set_limit(value)
        self.assertEqual(state, original)
        self.assertEqual(writes, [])

    def test_independent_pl2_survives_steam_pl1_changes(self):
        for burst in (52, 80):
            with self.subTest(pl2=burst):
                state = {"msr": 35_000_000, "mmio": 35_000_000}
                controller = self.controller(state, state.__setitem__)
                controller.set_pl2(burst)
                for sustained in (10, 40, 22):
                    controller.set_limit(sustained)
                    self.assertEqual(controller.get_power_limits()["pl1_values"], [sustained] * 2)
                    self.assertEqual(controller.get_power_limits()["pl2_values"], [burst] * 2)

    def test_40w_pl1_raises_both_lower_pl2_to_40(self):
        state = {"msr": 22_000_000, "mmio": 22_000_000,
                 "msr_pl2": 22_000_000, "mmio_pl2": 35_000_000}
        controller = self.controller(state, state.__setitem__)
        controller.set_limit(40)
        self.assertEqual(list(state.values()), [40_000_000] * 4)
        controller.set_pl2(40)
        self.assertEqual(list(state.values()), [40_000_000] * 4)

    def test_pl2_rejects_invalid_or_below_highest_live_pl1_without_writes(self):
        state = {"msr": 20_000_000, "mmio": 40_000_000}
        writes = []
        controller = self.controller(state, lambda *args: writes.append(args))
        original = state.copy()
        for watts in (9, 10, 39, 81, True, False, 52.0, "52"):
            with self.subTest(watts=watts), self.assertRaises(InvalidLimit):
                controller.set_pl2(watts)
        self.assertEqual(writes, [])
        self.assertEqual(state, original)
        # An out-of-range live baseline remains authoritative for the PL1 floor.
        state["mmio"] = 50_000_000
        with self.assertRaisesRegex(InvalidLimit, "highest live PL1"):
            controller.set_pl2(40)
        self.assertEqual(writes, [])

    def test_pl2_only_writes_burst_paths_and_allows_range_endpoints(self):
        for watts in (10, 80):
            with self.subTest(watts=watts):
                state = {"msr": 10_000_000, "mmio": 10_000_000}
                writes = []

                def write(path, value):
                    writes.append((path, value))
                    state[path] = value

                controller = self.controller(state, write)
                controller.set_pl2(watts)
                self.assertEqual(writes, [("msr_pl2", watts * 1_000_000),
                                          ("mmio_pl2", watts * 1_000_000)])
                self.assertEqual(controller.get_limit(), 10)

    def test_pl2_partial_failure_restores_only_distinct_burst_snapshots(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value
            if path == "mmio_pl2" and value == 80_000_000:
                raise OSError("PL2 partial failure")

        controller = self.controller(state, write)
        original = state.copy()
        with self.assertRaisesRegex(ControllerError, "rollback=verified"):
            controller.set_pl2(80)
        self.assertEqual(state, original)
        self.assertEqual(writes[-2:], [("msr_pl2", 52_000_000), ("mmio_pl2", 51_000_000)])
        self.assertTrue(all(path.endswith("_pl2") for path, _ in writes))

    def test_pl2_first_write_failure_restores_mutated_path_and_preserves_untouched_changes(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value
            if path == "msr_pl2" and value == 80_000_000:
                state["mmio_pl2"] = 70_000_000
                state["msr"] = 40_000_000
                raise OSError("mutated before first-write failure")

        controller = self.controller(state, write)
        with self.assertRaisesRegex(ControllerError, "untouched external conflict"):
            controller.set_pl2(80)
        self.assertEqual(writes, [("msr_pl2", 80_000_000), ("msr_pl2", 52_000_000)])
        self.assertEqual(state["mmio_pl2"], 70_000_000)
        self.assertEqual(state["msr"], 40_000_000)

    def test_pl1_conflict_after_first_burst_write_restores_only_owned_path(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value
            if path == "msr_pl2" and value == 40_000_000:
                state["mmio_pl2"] = 80_000_000
                state["msr"] = 30_000_000

        controller = self.controller(state, write)
        with self.assertRaisesRegex(ControllerError, "untouched external conflict"):
            controller.set_limit(40)
        self.assertEqual(writes, [("msr_pl2", 40_000_000), ("msr_pl2", 35_000_000)])
        self.assertEqual(state["mmio_pl2"], 80_000_000)
        self.assertEqual(state["msr"], 30_000_000)
        self.assertEqual(state["mmio"], 25_000_000)

    def test_pl2_failed_restore_reports_both_readback_and_original_error(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            if path == "mmio_pl2" and value == 80_000_000:
                raise OSError("request failed")
            if path == "msr_pl2" and value == 52_000_000:
                raise OSError("restore failed")
            state[path] = value

        controller = self.controller(state, write)
        with self.assertRaises(ControllerError) as context:
            controller.set_pl2(80)
        message = str(context.exception)
        self.assertIn("request failed", message)
        self.assertIn("restore failed", message)
        self.assertIn("restore readback 80000000 uW != snapshot 52000000 uW", message)
        self.assertEqual(writes[-1], ("mmio_pl2", 51_000_000))

    def test_pl2_final_readback_detects_reset_of_first_burst_path(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000}

        def write(path, value):
            state[path] = value
            if path == "mmio_pl2" and value == 80_000_000:
                state["msr_pl2"] = 52_000_000

        controller = self.controller(state, write)
        with self.assertRaisesRegex(ControllerError, "msr_pl2: final readback"):
            controller.set_pl2(80)
        self.assertEqual(state["msr_pl2"], 52_000_000)
        self.assertEqual(state["mmio_pl2"], 51_000_000)

    def test_pl2_external_pl1_change_is_detected_and_never_overwritten(self):
        state = {"msr": 25_000_000, "mmio": 25_000_000}
        writes = []

        def write(path, value):
            writes.append((path, value))
            state[path] = value
            if path == "mmio_pl2" and value == 52_000_000:
                state["msr"] = 40_000_000

        controller = self.controller(state, write)
        with self.assertRaisesRegex(ControllerError, "untouched external conflict readback"):
            controller.set_pl2(52)
        self.assertEqual(state["msr"], 40_000_000)
        self.assertEqual(state["mmio"], 25_000_000)
        self.assertEqual(state["msr_pl2"], 52_000_000)
        self.assertEqual(state["mmio_pl2"], 51_000_000)
        self.assertTrue(all(path.endswith("_pl2") for path, _ in writes))

    def test_power_limits_getter_reports_actual_arrays_and_dynamic_pl2_minimum_without_writes(self):
        state = {"msr": 15_000_000, "mmio": 40_000_000,
                 "msr_pl2": 80_000_000, "mmio_pl2": 52_000_000}
        controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
        self.assertEqual(controller.get_power_limits(), {
            "pl1_watts": 15, "pl2_watts": 52,
            "pl1_values": [15, 40], "pl2_values": [80, 52],
            "pl1_min_watts": 10, "pl1_max_watts": 40,
            "pl2_min_watts": 40, "pl2_max_watts": 80,
        })
        state["msr_pl2"] = 22_000_000
        self.assertEqual(controller.get_power_limits()["pl2_watts"], 22)
        state["msr"] = state["mmio"] = 20_000_000
        self.assertEqual(controller.get_power_limits()["pl2_min_watts"], 20)
        state["msr"] = state["mmio"] = 0
        self.assertEqual(controller.get_power_limits()["pl2_min_watts"], 10)

    def test_power_limits_getter_validates_all_four_paths(self):
        invalid_values = (-1, True, 52_000_000.0, 52_500_000,
                          (0xFFFFFFFF + 1) * 1_000_000)
        for path in ("msr", "mmio", "msr_pl2", "mmio_pl2"):
            for value in invalid_values:
                with self.subTest(path=path, value=value):
                    state = {"msr": 20_000_000, "mmio": 40_000_000}
                    controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
                    state[path] = value
                    with self.assertRaisesRegex(ControllerError, path + ": PL[12] cannot be represented"):
                        controller.get_power_limits()

    def test_extended_range_raises_lower_pl2_and_lowering_pl1_preserves_it(self):
        for watts in (36, 40):
            state = {"msr": 22_000_000, "mmio": 22_000_000,
                     "msr_pl2": 35_000_000, "mmio_pl2": 52_000_000}
            controller = self.controller(state, state.__setitem__)
            controller.set_limit(watts)
            self.assertEqual(list(state.values()), [watts * 1_000_000] * 3 + [52_000_000])
            controller.set_limit(22)
            self.assertEqual(list(state.values()), [22_000_000, 22_000_000, watts * 1_000_000, 52_000_000])

    def test_extended_range_external_pl2_change_is_preserved_without_writes(self):
        state = {"msr": 22_000_000, "mmio": 22_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        before = state.copy()
        reads = 0
        writes = []
        def read(path):
            nonlocal reads
            if path == "msr_pl2":
                reads += 1
                if reads == 2:
                    state[path] = 18_000_000
            return state[path]
        controller = RaplController(paths=("msr", "mmio"), pl2_paths=("msr_pl2", "mmio_pl2"),
                                    reader=read, writer=lambda *args: writes.append(args), validator=lambda: None,
                                    busy_checker=lambda: None)
        with self.assertRaisesRegex(ControllerError, 'PL2 changed'):
            controller.set_limit(40)
        before["msr_pl2"] = 18_000_000
        self.assertEqual(state, before)
        self.assertEqual(writes, [])

    def test_pl2_changed_after_snapshot_is_preserved_without_writes(self):
        state = {"msr": 20_000_000, "mmio": 20_000_000,
                 "msr_pl2": 52_000_000, "mmio_pl2": 52_000_000}
        reads = 0
        writes = []

        def read(path):
            nonlocal reads
            if path == "msr_pl2":
                reads += 1
                if reads == 2:
                    state[path] = 18_000_000
            return state[path]

        controller = RaplController(paths=("msr", "mmio"), pl2_paths=("msr_pl2", "mmio_pl2"),
                                    reader=read, writer=lambda *args: writes.append(args), validator=lambda: None,
                                    busy_checker=lambda: None)
        with self.assertRaisesRegex(ControllerError, "PL2 changed"):
            controller.set_limit(35)
        self.assertEqual(state["msr_pl2"], 18_000_000)
        self.assertEqual(state["mmio_pl2"], 52_000_000)
        self.assertEqual(writes, [])

    def test_read_only_watcher_invalidates_drift_and_error_transitions(self):
        state = {"msr": 20_000_000, "mmio": 20_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        invalidations = []

        def read(path):
            value = state[path]
            if isinstance(value, Exception):
                raise value
            return value

        def forbidden_write(path, value):
            self.fail("The read-only observer must never write")

        controller = RaplController(paths=("msr", "mmio"), reader=read,
                                    writer=forbidden_write, validator=lambda: None,
                                    busy_checker=lambda: None, pl2_paths=("msr_pl2", "mmio_pl2"))
        observer = DriftObserver(controller.observe_state, lambda: invalidations.append(True))
        observer.poll()
        self.assertEqual(invalidations, [])
        state["mmio"] = 35_000_000
        observer.poll()
        self.assertEqual(controller.get_limit(), 20)
        self.assertEqual(invalidations, [])
        state["msr"] = OSError("unavailable")
        observer.poll()
        observer.poll()
        state["msr"] = 35_000_000
        observer.poll()
        self.assertEqual(controller.get_limit(), 35)
        self.assertEqual(len(invalidations), 2)
        state["msr_pl2"] = 52_000_000
        observer.poll()
        self.assertEqual(len(invalidations), 2)

    def watcher(self, state, guard=None):
        def read(path):
            value = state[path]
            if isinstance(value, Exception):
                raise value
            return value

        def validate():
            if guard and guard[0] is not None:
                raise guard[0]

        controller = RaplController(paths=("msr", "mmio"), reader=read,
                                    writer=lambda *_: self.fail("Observer wrote a limit"),
                                    validator=validate, busy_checker=lambda: None,
                                    pl2_paths=("msr_pl2", "mmio_pl2"))
        invalidations = []
        observer = DriftObserver(controller.observe_state, lambda: invalidations.append(True))
        return controller, observer, invalidations

    def test_watcher_pl2_drift_and_read_errors_only_log_without_notification(self):
        state = {"msr": 35_000_000, "mmio": 35_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        controller, observer, invalidations = self.watcher(state)
        with self.assertLogs("oxp3-rapl", level="WARNING") as logs:
            for value in (52_000_000, OSError("unavailable 1"), OSError("unavailable 2"), 35_000_000):
                state["mmio_pl2"] = value
                observer.poll()
                self.assertEqual(controller.get_limit(), 35)
        self.assertEqual(len(logs.records), 4)
        self.assertEqual(invalidations, [])

    def test_watcher_higher_pl1_drift_logs_but_effective_minimum_change_notifies(self):
        state = {"msr": 15_000_000, "mmio": 25_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        controller, observer, invalidations = self.watcher(state)
        with self.assertLogs("oxp3-rapl", level="WARNING") as logs:
            state["mmio"] = 35_000_000
            observer.poll()
            self.assertEqual(invalidations, [])
            state["msr"] = 20_000_000
            observer.poll()
            self.assertEqual(controller.get_limit(), 20)
            self.assertEqual(len(invalidations), 1)
            state["mmio"] = 10_000_000
            observer.poll()
            self.assertEqual(controller.get_limit(), 10)
        self.assertEqual(len(logs.records), 3)
        self.assertEqual(len(invalidations), 2)

    def test_watcher_invalid_higher_pl1_and_read_failure_notify_stable_categories(self):
        state = {"msr": 15_000_000, "mmio": 35_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        controller, observer, invalidations = self.watcher(state)
        with self.assertLogs("oxp3-rapl", level="WARNING"):
            for value in (35_500_000, 36_500_000, (0xFFFFFFFF + 1) * 1_000_000):
                state["mmio"] = value
                observer.poll()
                with self.assertRaises(ControllerError):
                    controller.get_limit()
            self.assertEqual(len(invalidations), 1)
            state["mmio"] = OSError("unavailable at time 1")
            observer.poll()
            self.assertEqual(len(invalidations), 2)
            state["mmio"] = OSError("unavailable at time 2")
            observer.poll()
            self.assertEqual(len(invalidations), 2)
            state["mmio"] = 35_000_000
            observer.poll()
        self.assertEqual(controller.get_limit(), 15)
        self.assertEqual(len(invalidations), 3)

    def test_watcher_guard_failure_and_recovery_ignore_changing_error_details(self):
        state = {"msr": 15_000_000, "mmio": 35_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        guard = [None]
        controller, observer, invalidations = self.watcher(state, guard)
        with self.assertLogs("oxp3-rapl", level="WARNING") as logs:
            guard[0] = ControllerError("guard failed at time 1")
            observer.poll()
            with self.assertRaises(ControllerError):
                controller.get_limit()
            guard[0] = ControllerError("guard failed at time 2")
            observer.poll()
            self.assertEqual(len(invalidations), 1)
            guard[0] = None
            observer.poll()
        self.assertEqual(len(logs.records), 3)
        self.assertEqual(controller.get_limit(), 15)
        self.assertEqual(len(invalidations), 2)

    def test_watcher_reset_adopts_setter_outcome_before_next_poll(self):
        state = {"msr": 35_000_000, "mmio": 35_000_000,
                 "msr_pl2": 35_000_000, "mmio_pl2": 35_000_000}
        _, observer, invalidations = self.watcher(state)
        state["msr"] = state["mmio"] = 20_000_000
        observer.reset()
        observer.poll()
        self.assertEqual(invalidations, [])
        state["mmio"] = 10_000_000
        with self.assertLogs("oxp3-rapl", level="WARNING"):
            observer.poll()
        self.assertEqual(len(invalidations), 1)

    def test_getter_equal_limits_including_baseline_outside_setter_range(self):
        for watts in (0, 10, 35, 36, 0xFFFFFFFF):
            with self.subTest(watts=watts):
                state = {"msr": watts * 1_000_000, "mmio": watts * 1_000_000}
                controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
                self.assertEqual(controller.get_limit(), watts)

    def test_getter_upward_mmio_drift_returns_current_msr_without_writes(self):
        state = {"msr": 15_000_000, "mmio": 35_000_000}
        controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
        self.assertEqual(controller.get_limit(), 15)
        state["msr"] = 20_000_000
        self.assertEqual(controller.get_limit(), 20)
        self.assertEqual(state["mmio"], 35_000_000)

    def test_getter_lower_mmio_returns_live_minimum_in_either_direction(self):
        state = {"msr": 25_000_000, "mmio": 15_000_000}
        controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
        self.assertEqual(controller.get_limit(), 15)
        state["mmio"] = 30_000_000
        self.assertEqual(controller.get_limit(), 25)
        self.assertEqual(state["msr"], 25_000_000)

    def test_getter_validates_both_paths_before_comparing_limits(self):
        invalid_values = (-1, True, 20_000_000.0, 35_500_000,
                          (0xFFFFFFFF + 1) * 1_000_000,
                          0xFFFFFFFF * 1_000_000 + 1)
        for path in ("msr", "mmio"):
            for value in invalid_values:
                with self.subTest(path=path, value=value):
                    state = {"msr": 20_000_000, "mmio": 35_000_000}
                    state[path] = value
                    controller = self.controller(state, lambda *_: self.fail("Getter wrote a limit"))
                    with self.assertRaisesRegex(ControllerError, path + ": PL1 cannot be represented"):
                        controller.get_limit()

    def test_getter_does_not_hide_read_failure_on_either_path(self):
        for failed_path in ("msr", "mmio"):
            with self.subTest(path=failed_path):
                def read(path):
                    if path == failed_path:
                        raise OSError(f"{path}: unavailable")
                    return 20_000_000 if path == "msr" else 35_000_000

                controller = RaplController(paths=("msr", "mmio"), reader=read,
                                            writer=lambda *_: self.fail("Getter wrote a limit"),
                                            validator=lambda: None, busy_checker=lambda: None,
                                            pl2_paths=("msr_pl2", "mmio_pl2"))
                with self.assertRaisesRegex(OSError, failed_path + ": unavailable"):
                    controller.get_limit()


class ServiceTests(unittest.TestCase):
    def test_custom_interface_auth_signatures_and_shared_controller(self):
        """Exercise the service without a real bus, GLib, users, or hardware."""
        objects = {}

        class UInt32(int):
            def __new__(cls, value, variant_level=0):
                result = super().__new__(cls, value)
                result.variant_level = variant_level
                return result

        class Array(list):
            def __init__(self, value, signature, variant_level=0):
                super().__init__(value)
                self.signature = signature
                self.variant_level = variant_level

        class Object:
            def __init__(self, name, path):
                objects[path] = self

            def remove_from_connection(self):
                pass

        def method(interface, **signatures):
            def decorate(function):
                function.dbus_metadata = (interface, signatures)
                return function
            return decorate

        def signal(*args, **kwargs):
            return lambda function: function

        dbus = types.ModuleType("dbus")
        dbus.DBusException = type("DBusException", (Exception,), {})
        dbus.UInt32, dbus.Array = UInt32, Array
        dbus.SystemBus = lambda: types.SimpleNamespace(
            get_unix_user=lambda sender: {"root": 0, "deck": 1000, "other": 1001}[sender])
        service = types.ModuleType("dbus.service")
        service.Object, service.method, service.signal = Object, method, signal
        service.BusName = lambda *args, **kwargs: BUS_NAME
        dbus.service = service
        glib_mainloop = types.ModuleType("dbus.mainloop.glib")
        glib_mainloop.DBusGMainLoop = lambda **kwargs: None
        pwd = types.ModuleType("pwd")
        pwd.getpwnam = lambda name: types.SimpleNamespace(pw_uid=1000)
        state = {"msr": 20_000_000, "mmio": 20_000_000,
                 "msr_pl2": 52_000_000, "mmio_pl2": 51_000_000}
        controller = RaplController(paths=("msr", "mmio"), reader=state.__getitem__,
                                    writer=state.__setitem__, validator=lambda: None,
                                    busy_checker=lambda: None,
                                    pl2_paths=("msr_pl2", "mmio_pl2"))

        def exercise():
            obj = objects[OBJECT_PATH]
            obj.PropertiesChanged = Mock()
            xml = ET.fromstring(obj.Introspect(sender="deck"))
            interface = xml.find(f"interface[@name='{POWER_LIMITS_INTERFACE}']")
            self.assertIsNotNone(interface)
            self.assertEqual(interface.find("method[@name='GetLimits']/arg").attrib["type"], "a{sv}")
            self.assertEqual(interface.find("method[@name='SetPl2']/arg").attrib["type"], "u")
            self.assertEqual(obj.GetLimits.dbus_metadata[1]["out_signature"], "a{sv}")
            self.assertEqual(obj.SetPl2.dbus_metadata[1]["in_signature"], "u")
            limits = obj.GetLimits(sender="deck")
            self.assertEqual(limits["pl2_values"], [52, 51])
            self.assertEqual(limits["pl2_values"].signature, "u")
            self.assertEqual(limits["pl2_values"].variant_level, 1)
            self.assertEqual(limits["pl1_watts"].variant_level, 1)
            for sender in (None, "other"):
                for method_call in (lambda: obj.GetLimits(sender=sender),
                                    lambda: obj.SetPl2(UInt32(80), sender=sender),
                                    lambda: obj.Introspect(sender=sender)):
                    with self.assertRaises(dbus.DBusException) as context:
                        method_call()
                    self.assertEqual(context.exception._dbus_error_name,
                                     "org.freedesktop.DBus.Error.AccessDenied")
            obj.SetPl2(UInt32(80), sender="root")
            obj.Set(TDP_INTERFACE, "TdpLimit", UInt32(40), sender="deck")
            self.assertEqual(controller.get_power_limits()["pl2_values"], [80, 80])
            self.assertEqual(controller.get_limit(), 40)
            for watts in (UInt32(39), True):
                with self.assertRaises(dbus.DBusException) as context:
                    obj.SetPl2(watts, sender="deck")
                self.assertEqual(context.exception._dbus_error_name,
                                 "org.freedesktop.DBus.Error.InvalidArgs")
            self.assertEqual(obj.PropertiesChanged.call_count, 4)

        glib = types.SimpleNamespace(MainLoop=lambda: types.SimpleNamespace(run=exercise, quit=lambda: None),
                                    timeout_add_seconds=lambda *args: 1, source_remove=lambda *args: None,
                                    unix_signal_add=lambda *args: None, PRIORITY_DEFAULT=0)
        repository = types.ModuleType("gi.repository")
        repository.GLib = glib
        modules = {"dbus": dbus, "dbus.service": service,
                   "dbus.mainloop": types.ModuleType("dbus.mainloop"),
                   "dbus.mainloop.glib": glib_mainloop, "gi": types.ModuleType("gi"),
                   "gi.repository": repository, "pwd": pwd}
        with patch.dict(sys.modules, modules):
            run_service(controller)


if __name__ == "__main__":
    unittest.main()
