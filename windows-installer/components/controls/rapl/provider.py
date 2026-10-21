#!/usr/bin/python3
"""Experimental ONEXPLAYER 3 RAPL remote for SteamOS Manager."""

import fcntl
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading


BUS_NAME = "org.onexplayer.SteamOSManager.PowerControl"
OBJECT_PATH = "/org/onexplayer/SteamOSManager/PowerControl"
TDP_INTERFACE = "com.steampowered.SteamOSManager1.TdpLimit1"
POWER_LIMITS_INTERFACE = "org.onexplayer.SteamOSManager.PowerLimits1"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
PEER_INTERFACE = "org.freedesktop.DBus.Peer"
MIN_WATTS = 10
MAX_WATTS = 40
PL2_MIN_WATTS = MIN_WATTS
PL2_MAX_WATTS = 80
MICROWATTS_PER_WATT = 1_000_000
RAPL_ROOTS = (
    Path("/sys/class/powercap/intel-rapl:0"),
    Path("/sys/class/powercap/intel-rapl-mmio:0"),
)
LIMIT_PATHS = tuple(root / "constraint_0_power_limit_uw" for root in RAPL_ROOTS)
PL2_PATHS = tuple(root / "constraint_1_power_limit_uw" for root in RAPL_ROOTS)
SYNC_UNIT = "oxp3-tdp-sync.service"
LOCK_PATH = Path("/run/lock/oxp3-rapl-controller.lock")
LOG = logging.getLogger("oxp3-rapl")


class ControllerError(RuntimeError):
    """A hardware read, write, device guard, or rollback failed."""


class InvalidLimit(ValueError):
    """The requested value is outside the experimental range."""


def whole_watts(path, value, limit):
    """Validate actual readings, including otherwise unselected higher ones."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControllerError(f"{path}: {limit} cannot be represented as nonnegative uint32 whole watts: {value!r} uW")
    watts, remainder = divmod(value, MICROWATTS_PER_WATT)
    if remainder or watts > 0xFFFFFFFF:
        raise ControllerError(f"{path}: {limit} cannot be represented as uint32 whole watts: {value} uW")
    return watts


def pl1_whole_watts(path, value):
    return whole_watts(path, value, "PL1")


def observed_limit_result(observation):
    """Project one full sample onto getter value or stable failure category.

    Error details remain in raw diagnostics. Changing error text or invalid raw
    values on an already failing path does not repeatedly invalidate a client.
    PL2 is diagnostic only: get_limit does not read its numeric limits.
    """
    guard_error, readings = observation
    if guard_error is not None:
        return ("error", "guard")
    pl1 = readings[:2]
    # The getter reads both PL1 files before validating their numeric values.
    for path, value in pl1:
        if isinstance(value, str) and value.startswith("read failed:"):
            return ("error", "read", path)
    watts = []
    for path, value in pl1:
        try:
            watts.append(pl1_whole_watts(path, value))
        except ControllerError:
            return ("error", "invalid_pl1", path)
    return ("value", min(watts))


def read_number(path):
    text = Path(path).read_text(encoding="ascii").strip()
    if not text.isascii() or not text.isdecimal():
        raise ControllerError(f"{path}: invalid nonnegative integer {text!r}")
    return int(text)


def write_number(path, value):
    # Sysfs files must be opened and written directly, never replaced/renamed.
    with Path(path).open("w", encoding="ascii") as output:
        output.write(f"{value}\n")


def validate_device():
    for root in RAPL_ROOTS:
        for field, wanted in (("name", "package-0"), ("enabled", "1"),
                              ("constraint_0_name", "long_term"),
                              ("constraint_1_name", "short_term")):
            actual = (root / field).read_text(encoding="ascii").strip()
            if actual != wanted:
                raise ControllerError(f"RAPL guard: {root / field} is {actual!r}, expected {wanted!r}")


def refuse_active_sync():
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value", SYNC_UNIT],
        capture_output=True, text=True, timeout=5, check=False,
    )
    state = result.stdout.strip()
    if result.returncode != 0 or state not in ("inactive", "failed"):
        raise ControllerError(
            f"Cannot claim RAPL while {SYNC_UNIT} state is {state!r}; "
            f"systemctl exit={result.returncode}, stderr={result.stderr.strip()!r}"
        )


class RaplController:
    """Serialize writes, always return actual state, and preserve rollback errors."""

    def __init__(self, paths=LIMIT_PATHS, reader=read_number, writer=write_number,
                 validator=validate_device, busy_checker=refuse_active_sync,
                 pl2_paths=PL2_PATHS):
        self.paths = tuple(paths)
        self.pl2_paths = tuple(pl2_paths)
        self.transaction_paths = self.paths + self.pl2_paths
        if len(self.paths) != 2 or len(self.pl2_paths) != 2 or len(set(self.transaction_paths)) != 4:
            raise ValueError("Exactly two distinct PL1 and two distinct PL2 paths are required")
        self.read = reader
        self.write = writer
        self.validate = validator
        self.check_busy = busy_checker
        self.mutex = threading.RLock()

    def observe_state(self):
        """Read all four paths even if one fails, for diagnostic notification."""
        with self.mutex:
            try:
                self.validate()
                guard_error = None
            except Exception as error:
                guard_error = str(error)
            readings = []
            for path in self.transaction_paths:
                try:
                    readings.append((str(path), self.read(path)))
                except Exception as error:
                    readings.append((str(path), f"read failed: {error}"))
            return guard_error, tuple(readings)

    def get_limit(self):
        with self.mutex:
            self.validate()
            values = [self.read(path) for path in self.paths]
            whole_watts = [pl1_whole_watts(path, value) for path, value in zip(self.paths, values)]
            # Baseline values stay visible even if outside our setter range.
            # Bidirectional CPU/GPU/mixed probes support the lower live PL1 on
            # this device. This reports configuration, not measured consumption.
            return min(whole_watts)

    def get_power_limits(self):
        with self.mutex:
            self.validate()
            values = [self.read(path) for path in self.transaction_paths]
            pl1 = [whole_watts(path, value, "PL1")
                   for path, value in zip(self.paths, values[:2])]
            pl2 = [whole_watts(path, value, "PL2")
                   for path, value in zip(self.pl2_paths, values[2:])]
            return {
                "pl1_watts": min(pl1), "pl2_watts": min(pl2),
                "pl1_values": pl1, "pl2_values": pl2,
                "pl1_min_watts": MIN_WATTS, "pl1_max_watts": MAX_WATTS,
                "pl2_min_watts": max(PL2_MIN_WATTS, max(pl1)), "pl2_max_watts": PL2_MAX_WATTS,
            }

    def set_limit(self, watts):
        if isinstance(watts, bool) or not isinstance(watts, int) or not MIN_WATTS <= watts <= MAX_WATTS:
            raise InvalidLimit(f"TdpLimit must be an integer in {MIN_WATTS}..{MAX_WATTS} W")
        with self.mutex:
            self.validate()
            self.check_busy()
            snapshots = {path: self.read(path) for path in self.transaction_paths}
            requested = watts * MICROWATTS_PER_WATT
            targets = {path: requested for path in self.paths}
            targets.update({path: max(requested, snapshots[path]) for path in self.pl2_paths})
            attempted = set()
            try:
                # Raise burst limits first, preserving independently chosen PL2.
                for path in self.pl2_paths + self.paths:
                    if path in self.pl2_paths:
                        current = self.read(path)
                        if current != snapshots[path]:
                            raise ControllerError(f"{path}: PL2 changed during PL1 request")
                    target = targets[path]
                    try:
                        # Sysfs can mutate the value before a write raises.
                        attempted.add(path)
                        self.write(path, target)
                    except Exception as write_error:
                        raise ControllerError(f"{path}: write {target} uW failed: {write_error}") from write_error
                    actual = self.read(path)
                    if actual != target:
                        raise ControllerError(f"{path}: readback {actual} uW != target {target} uW")
                # Verify earlier paths were not changed while writing later ones.
                for path in self.transaction_paths:
                    actual = self.read(path)
                    if actual != targets[path]:
                        raise ControllerError(f"{path}: final readback {actual} uW != target {targets[path]} uW")
            except Exception as error:
                self.rollback("PL1/PL2", snapshots, attempted, error)
            LOG.info("PL1/PL2 request accepted: exact readbacks %s", dict((str(path), value) for path, value in targets.items()))

    def set_pl2(self, watts):
        if isinstance(watts, bool) or not isinstance(watts, int) or not PL2_MIN_WATTS <= watts <= PL2_MAX_WATTS:
            raise InvalidLimit(f"PL2 must be an integer in {PL2_MIN_WATTS}..{PL2_MAX_WATTS} W")
        with self.mutex:
            self.validate()
            self.check_busy()
            snapshots = {path: self.read(path) for path in self.transaction_paths}
            pl1 = [pl1_whole_watts(path, snapshots[path]) for path in self.paths]
            if watts < max(pl1):
                raise InvalidLimit(f"PL2 must be at least the highest live PL1 ({max(pl1)} W)")
            requested = watts * MICROWATTS_PER_WATT
            attempted = set()
            try:
                for path in self.pl2_paths:
                    try:
                        attempted.add(path)
                        self.write(path, requested)
                    except Exception as write_error:
                        raise ControllerError(f"{path}: write {requested} uW failed: {write_error}") from write_error
                    actual = self.read(path)
                    if actual != requested:
                        raise ControllerError(f"{path}: readback {actual} uW != target {requested} uW")
                for path in self.transaction_paths:
                    target = snapshots[path] if path in self.paths else requested
                    actual = self.read(path)
                    if actual != target:
                        raise ControllerError(f"{path}: final readback {actual} uW != target {target} uW")
            except Exception as error:
                # PL1 belongs to Steam or another external writer; never restore
                # its snapshot when this transaction only wrote PL2.
                self.rollback("PL2", snapshots, attempted, error)
            LOG.info("PL2 request accepted: exact readbacks %d uW", requested)

    def rollback(self, label, snapshots, restore_paths, error):
        # Own only attempted writes. An untouched path may now belong to an
        # external writer, even when another path already needs restoration.
        restore_paths = tuple(path for path in snapshots if path in restore_paths)
        rollback_errors = []
        for path in restore_paths:
            try:
                self.write(path, snapshots[path])
            except Exception as rollback_error:
                rollback_errors.append(f"{path}: restore write failed: {rollback_error}")
        observed = {}
        for path, previous in snapshots.items():
            try:
                actual = self.read(path)
                observed[str(path)] = actual
                if actual != previous:
                    operation = "restore" if path in restore_paths else "untouched external conflict"
                    rollback_errors.append(f"{path}: {operation} readback {actual} uW != snapshot {previous} uW")
            except Exception as rollback_error:
                observed[str(path)] = f"read failed: {rollback_error}"
                rollback_errors.append(f"{path}: restore read failed: {rollback_error}")
        message = (
            f"{label} transaction failed: {error}; snapshots={dict((str(path), value) for path, value in snapshots.items())}; "
            f"rollback={'verified' if not rollback_errors else '; '.join(rollback_errors)}; "
            f"observed={observed}"
        )
        LOG.error(message)
        raise ControllerError(message) from error


class DriftObserver:
    """Store observations only to detect changes; getters never use this state."""

    def __init__(self, observe, invalidate):
        self.observe = observe
        self.invalidate = invalidate
        self.previous = observe()
        self.previous_result = observed_limit_result(self.previous)

    def reset(self):
        # An explicit setter is reported separately from an external change.
        self.previous = self.observe()
        self.previous_result = observed_limit_result(self.previous)

    def poll(self):
        current = self.observe()
        result = observed_limit_result(current)
        if current != self.previous:
            LOG.warning("External PL1/PL2/guard change: previous=%s; actual=%s", self.previous, current)
        self.previous = current
        if result != self.previous_result:
            self.previous_result = result
            self.invalidate()
        return True


def acquire_lock():
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        os.close(fd)
        raise
    # Keep the same inode, including after shutdown, so other instances cannot bypass it.
    return fd


def run_service(controller):
    # Lazy imports keep the transaction core testable without a D-Bus daemon.
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    import pwd

    class HardwareError(dbus.DBusException):
        _dbus_error_name = BUS_NAME + ".Error.Hardware"

    class InvalidArgs(dbus.DBusException):
        _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"

    class AccessDenied(dbus.DBusException):
        _dbus_error_name = "org.freedesktop.DBus.Error.AccessDenied"

    class UnknownProperty(dbus.DBusException):
        _dbus_error_name = "org.freedesktop.DBus.Error.UnknownProperty"

    class PropertyReadOnly(dbus.DBusException):
        _dbus_error_name = "org.freedesktop.DBus.Error.PropertyReadOnly"

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    allowed_uids = {0, pwd.getpwnam("deck").pw_uid}

    def authorize(sender):
        if sender is None or bus.get_unix_user(sender) not in allowed_uids:
            raise AccessDenied("Only root and deck may call this experimental provider")

    def hardware_call(method, *args):
        try:
            return method(*args)
        except InvalidLimit as error:
            raise InvalidArgs(str(error)) from error
        except Exception as error:
            LOG.exception("Hardware operation failed")
            raise HardwareError(str(error)) from error

    peer_xml = '<interface name="org.freedesktop.DBus.Peer"><method name="Ping"/></interface>'
    introspect_xml = '<interface name="org.freedesktop.DBus.Introspectable"><method name="Introspect"><arg name="xml" type="s" direction="out"/></method></interface>'
    tdp_xml = f'''<interface name="{TDP_INTERFACE}">
      <property name="TdpLimit" type="u" access="readwrite"><annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="invalidates"/></property>
      <property name="TdpLimitMin" type="u" access="read"><annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="const"/></property>
      <property name="TdpLimitMax" type="u" access="read"><annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="const"/></property>
    </interface>'''
    power_limits_xml = f'''<interface name="{POWER_LIMITS_INTERFACE}">
      <method name="GetLimits"><arg name="limits" type="a{{sv}}" direction="out"/></method>
      <method name="SetPl2"><arg name="watts" type="u" direction="in"/></method>
    </interface>'''
    properties_xml = '''<interface name="org.freedesktop.DBus.Properties">
      <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
      <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
      <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
      <signal name="PropertiesChanged"><arg type="s"/><arg type="a{sv}"/><arg type="as"/></signal>
    </interface>'''

    class Peer(dbus.service.Object):
        @dbus.service.method(PEER_INTERFACE, in_signature="", out_signature="", sender_keyword="sender")
        def Ping(self, sender=None):
            authorize(sender)

        @dbus.service.method("org.freedesktop.DBus.Introspectable", in_signature="", out_signature="s", sender_keyword="sender")
        def Introspect(self, sender=None):
            authorize(sender)
            return f'<node>{peer_xml}{introspect_xml}</node>'

    class PowerControl(Peer):
        @dbus.service.method(POWER_LIMITS_INTERFACE, in_signature="", out_signature="a{sv}", sender_keyword="sender")
        def GetLimits(self, sender=None):
            authorize(sender)
            limits = hardware_call(controller.get_power_limits)
            return {key: dbus.Array([dbus.UInt32(item) for item in value], signature="u", variant_level=1)
                    if isinstance(value, list) else dbus.UInt32(value, variant_level=1)
                    for key, value in limits.items()}

        @dbus.service.method(POWER_LIMITS_INTERFACE, in_signature="u", out_signature="", sender_keyword="sender")
        def SetPl2(self, watts, sender=None):
            authorize(sender)
            try:
                if not isinstance(watts, dbus.UInt32):
                    raise InvalidArgs("PL2 requires a uint32")
                hardware_call(controller.set_pl2, int(watts))
            finally:
                observer.reset()
                self.invalidate_limit()

        def get_property(self, interface, name):
            if interface != TDP_INTERFACE:
                raise InvalidArgs(f"Unknown interface {interface}")
            if name == "TdpLimit":
                return dbus.UInt32(hardware_call(controller.get_limit), variant_level=1)
            if name == "TdpLimitMin":
                return dbus.UInt32(MIN_WATTS, variant_level=1)
            if name == "TdpLimitMax":
                return dbus.UInt32(MAX_WATTS, variant_level=1)
            raise UnknownProperty(f"Unknown property {name}")

        @dbus.service.method(PROPERTIES_INTERFACE, in_signature="ss", out_signature="v", sender_keyword="sender")
        def Get(self, interface, name, sender=None):
            authorize(sender)
            return self.get_property(interface, name)

        @dbus.service.method(PROPERTIES_INTERFACE, in_signature="s", out_signature="a{sv}", sender_keyword="sender")
        def GetAll(self, interface, sender=None):
            authorize(sender)
            return {name: self.get_property(interface, name) for name in ("TdpLimit", "TdpLimitMin", "TdpLimitMax")}

        @dbus.service.method(PROPERTIES_INTERFACE, in_signature="ssv", out_signature="", sender_keyword="sender")
        def Set(self, interface, name, value, sender=None):
            authorize(sender)
            try:
                if interface != TDP_INTERFACE:
                    raise InvalidArgs(f"Unknown interface {interface}")
                if name in ("TdpLimitMin", "TdpLimitMax"):
                    raise PropertyReadOnly(f"{name} is read only")
                if name != "TdpLimit":
                    raise UnknownProperty(f"Unknown property {name}")
                if not isinstance(value, dbus.UInt32):
                    raise InvalidArgs("TdpLimit requires a uint32 variant")
                hardware_call(controller.set_limit, int(value))
            finally:
                observer.reset()
                self.invalidate_limit()

        @dbus.service.signal(PROPERTIES_INTERFACE, signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def invalidate_limit(self):
            # Never publish a requested value as actual state. Preserve a setter
            # failure even if notifying a disconnected bus also fails.
            try:
                self.PropertiesChanged(TDP_INTERFACE, {}, ["TdpLimit"])
            except Exception:
                LOG.exception("Failed to invalidate the TdpLimit client cache")

        @dbus.service.method("org.freedesktop.DBus.Introspectable", in_signature="", out_signature="s", sender_keyword="sender")
        def Introspect(self, sender=None):
            authorize(sender)
            return f'<node>{peer_xml}{introspect_xml}{tdp_xml}{power_limits_xml}{properties_xml}</node>'

    name = dbus.service.BusName(BUS_NAME, bus=bus, allow_replacement=False, do_not_queue=True)
    root_object = Peer(name, "/")
    power_object = PowerControl(name, OBJECT_PATH)
    observer = DriftObserver(controller.observe_state, power_object.invalidate_limit)
    loop = GLib.MainLoop()
    watcher_id = GLib.timeout_add_seconds(1, observer.poll)
    for signum in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, lambda: (loop.quit(), False)[1])
    LOG.info("Serving %s at %s; experimental setter range %d..%d W; no automatic writes", BUS_NAME, OBJECT_PATH, MIN_WATTS, MAX_WATTS)
    try:
        loop.run()
    finally:
        GLib.source_remove(watcher_id)
        power_object.remove_from_connection()
        root_object.remove_from_connection()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.geteuid() != 0:
        raise ControllerError("The provider must run as root")
    lock_fd = acquire_lock()
    try:
        validate_device()
        refuse_active_sync()
        controller = RaplController()
        all_paths = LIMIT_PATHS + PL2_PATHS
        LOG.info("Startup PL1/PL2 snapshot (uW): %s", dict(zip(map(str, all_paths), map(read_number, all_paths))))
        run_service(controller)
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG.exception("Provider stopped")
        raise SystemExit(1)
