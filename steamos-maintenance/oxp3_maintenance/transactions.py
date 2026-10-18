"""Durable file generations for the maintenance CLI (Python standard library).

All public methods acquire the same reentrant, cross-process lock.  Callers may
hold ``with store.lock():`` across planning and an operation as well.  Only one
Store instance per state directory should be used in a thread.  A pending
transaction is rolled forward, never guessed at: every target must still equal
its recorded before or after image.  Recovery requires the same mounted root,
or an explicit authoritative slot ID verified by the privileged caller.

``adopt`` is a trusted installer-journal translation keyed by relative path:
{path: {"original": snapshot, "applied": snapshot, "component": component}}.
Trusted adoption may additionally use preserve=True and baseline=<legacy applied
snapshot> for explicitly mutable settings edited after the old installation.
A snapshot is {exists: bool, data: base64 ASCII, mode: int, uid: int, gid: int};
absent snapshots only require exists=False.  Adoption verifies applied against
the live target before accepting original.  Blobs never appear in public views.
An adopting generation privately records adoption_before so rollback can return
to the legacy installation while explicit restore still uses its true original.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import uuid

from .opti_migration import (PLUGIN as OPTI_PLUGIN, RUNTIME as OPTI_RUNTIME,
                             RUNTIME_CONFIG as OPTI_RUNTIME_CONFIG, runtime_path,
                             retain_legacy_runtime, transfer_allowed)


class TransactionError(RuntimeError):
    pass


_ABSENT = {"exists": False}
_MAX_ADOPTION_FILE = 256 * 1024 * 1024
_MAX_ADOPTION_TOTAL = 1024 * 1024 * 1024
_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
_PREFIXES = (
    "etc/", "usr/bin/", "usr/local/bin/", "usr/local/sbin/", "usr/local/lib/",
    "usr/lib/modules/", "usr/lib/firmware/", "usr/lib/udev/rules.d/",
    "usr/lib/systemd/system/", "usr/share/", "opt/", "home/",
    "var/lib/", "var/cache/",
)


def _snapshot(value: dict) -> dict:
    if not isinstance(value, dict) or type(value.get("exists")) is not bool:
        raise TransactionError("Invalid file snapshot")
    if not value["exists"]:
        return dict(_ABSENT)
    try:
        blob = value["data"]
        if not isinstance(blob, str):
            raise ValueError()
        data = base64.b64decode(blob, validate=True)
        result = {"exists": True, "data": base64.b64encode(data).decode("ascii")}
        for key in ("mode", "uid", "gid"):
            number = value[key]
            if type(number) is not int or number < 0:
                raise ValueError()
            result[key] = number
        if result["mode"] > 0o7777:
            raise ValueError()
        return result
    except (KeyError, ValueError, TypeError) as exc:
        raise TransactionError("Invalid file snapshot") from exc


def _public_entry(entry: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in entry.items() if k != "snapshot"}


def _operation_order(operation):
    """The trusted runtime switch is the last durable target write."""
    relative = operation["path"]
    if relative == "usr/local/lib/oxp3-maintenance/entry.py":
        rank = 3
    elif relative == "usr/local/lib/oxp3-maintenance/activation.json":
        rank = 2
    elif relative.endswith(".service"):
        rank = 1
    else:
        rank = 0
    return rank, relative


class Store:
    def __init__(self, root: Path, state: Path, *, uid=0, gid=0, enforce_owner=True):
        self.root = Path(os.path.abspath(root))
        self.state = Path(os.path.abspath(state))
        self.uid, self.gid = int(uid), int(gid)
        self.enforce_owner = enforce_owner
        self._depth = 0
        self._lock_fd = None
        with _LOCAL_LOCKS_GUARD:
            self._mutex = _LOCAL_LOCKS.setdefault(str(self.state), threading.RLock())
        if self.enforce_owner and os.name != "posix":
            raise TransactionError("Ownership enforcement requires Linux/POSIX")
        self._check_root()

    def _check_root(self):
        # Do not resolve symlinks: inspect every supplied ancestor instead.
        for path in reversed((self.root, *self.root.parents)):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
                raise TransactionError(f"Unsafe root ancestor: {path}")
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o022):
                raise TransactionError(f"Root ancestor must be root-owned and protected: {path}")

    def _identity(self):
        info = self.root.stat()
        return {"path": str(self.root), "dev": info.st_dev, "ino": info.st_ino}

    def _prepare_state(self):
        for path in reversed((self.state, *self.state.parents)):
            try:
                info = path.lstat()
            except FileNotFoundError:
                path.mkdir(mode=0o700)
                info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
                raise TransactionError(f"Unsafe state ancestor: {path}")
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o022):
                raise TransactionError(f"Untrusted state ancestor: {path}")
        if self.enforce_owner:
            info = self.state.stat()
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise TransactionError("State directory must have mode 0700")

    @contextlib.contextmanager
    def lock(self):
        with self._mutex:
            if self._depth:
                self._depth += 1
                try:
                    yield self
                finally:
                    self._depth -= 1
                return
            self._prepare_state()
            if os.name != "posix" and (self.state / "lock").exists():
                info = (self.state / "lock").lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise TransactionError("Unsafe state lock link")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.state / "lock", flags, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise TransactionError("Unsafe state lock")
                if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o077):
                    raise TransactionError("Untrusted state lock")
                if os.name == "posix":
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                else:  # Test fixtures only. Production requires POSIX above.
                    import msvcrt
                    if info.st_size == 0:
                        os.write(fd, b"\0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                self._lock_fd, self._depth = fd, 1
                try:
                    yield self
                finally:
                    self._depth, self._lock_fd = 0, None
                    if os.name == "posix":
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    else:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)

    def _state_read(self, name, default=None):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            info = (self.state / name).lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise TransactionError(f"Unsafe state file link: {name}")
            fd = os.open(self.state / name, flags)
        except FileNotFoundError:
            return copy.deepcopy(default)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise TransactionError(f"Unsafe state file: {name}")
            if self.enforce_owner and (info.st_uid != 0 or info.st_mode & 0o077):
                raise TransactionError(f"Untrusted state file: {name}")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                fd = None
                return json.load(stream)
        except (ValueError, UnicodeError) as exc:
            raise TransactionError(f"Corrupt state file: {name}") from exc
        finally:
            if fd is not None:
                os.close(fd)

    def _sync_state(self):
        if os.name == "posix":
            fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _state_write(self, name, value):
        temporary = self.state / (".tmp-" + uuid.uuid4().hex)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state / name)
            self._sync_state()
        finally:
            temporary.unlink(missing_ok=True)

    def _index(self):
        value = self._state_read("index.json", {"format": 1, "next_generation": 1,
                                                 "slots": {}, "originals": {}})
        if not isinstance(value, dict) or value.get("format") != 1:
            raise TransactionError("Unsupported transaction index")
        self._validate_generation_metadata(value)
        return value

    def _validate_generation_metadata(self, index):
        for record in index.get('slots', {}).values():
            for key in ('current', 'previous'):
                generation = record.get(key)
                if generation is not None:
                    if 'aborted_apply' in generation:
                        aborted = generation['aborted_apply']
                        if (not isinstance(aborted, dict) or set(aborted) != {'generation', 'source_generation'}
                                or type(aborted['generation']) is not int or aborted['generation'] < 1
                                or aborted['source_generation'] is not None and (
                                    type(aborted['source_generation']) is not int or aborted['source_generation'] < 1)):
                            raise TransactionError('Invalid apply abort provenance')
                    for field in ('legacy_selected', 'legacy_adopted'):
                        if field in generation:
                            self._legacy_choices(generation[field])
                    if 'adoption_before' in generation:
                        self._adoption_snapshots(generation['adoption_before'])
                    if 'decky_order_edit' in generation:
                        from .decky_order import SETTINGS
                        order_edit = self._order_edit(generation['decky_order_edit'])
                        entry = generation.get('paths', {}).get(SETTINGS, {})
                        if (entry.get('component') != 'decky' or not entry.get('mutable')
                                or entry.get('user') or entry.get('snapshot') != order_edit['after']):
                            raise TransactionError('Invalid managed Decky insertion record')
                    if 'adoption_preserved' in generation:
                        preserved = generation['adoption_preserved']
                        if (not isinstance(preserved, list) or len(preserved) > 20000
                                or any(not isinstance(path, str) for path in preserved)
                                or len(set(preserved)) != len(preserved)):
                            raise TransactionError('Invalid preserved adoption paths')
                        for path in preserved:
                            self._path(path)
                            if path not in generation.get('adoption_before', {}):
                                raise TransactionError('Preserved adoption path has no before-image')

    def _adoption_snapshots(self, value):
        """Validate private rollback before-images without exposing their bytes."""
        if not isinstance(value, dict) or len(value) > 20000:
            raise TransactionError('Invalid adoption rollback snapshots')
        result, total = {}, 0
        for relative, snapshot in value.items():
            self._path(relative)
            if isinstance(snapshot, dict) and snapshot == _ABSENT and snapshot.get('exists') is False:
                result[relative] = dict(_ABSENT)
                continue
            if (not isinstance(snapshot, dict)
                    or set(snapshot) != {'exists', 'data', 'mode', 'uid', 'gid'}
                    or snapshot['exists'] is not True
                    or not isinstance(snapshot['data'], str)
                    or len(snapshot['data']) > ((_MAX_ADOPTION_FILE + 2) // 3) * 4):
                raise TransactionError('Invalid adoption rollback snapshot: ' + relative)
            normalized = _snapshot(snapshot)
            if normalized != snapshot:
                raise TransactionError('Noncanonical adoption rollback snapshot: ' + relative)
            size = len(base64.b64decode(normalized['data'], validate=True))
            total += size
            if size > _MAX_ADOPTION_FILE or total > _MAX_ADOPTION_TOTAL:
                raise TransactionError('Oversized adoption rollback snapshots')
            result[relative] = normalized
        return result

    def _order_edit(self, value):
        """Validate the one permitted edited-settings operation and its preimage."""
        from .decky_order import SETTINGS, insertion_bytes
        if not isinstance(value, dict) or set(value) != {'before', 'after'}:
            raise TransactionError('Invalid Decky insertion rollback record')
        before = self._adoption_snapshots({SETTINGS: value['before']})[SETTINGS]
        after = self._adoption_snapshots({SETTINGS: value['after']})[SETTINGS]
        if (not before['exists'] or not after['exists']
                or any(before[key] != after[key] for key in ('mode', 'uid', 'gid'))
                or insertion_bytes(base64.b64decode(before['data'])) != base64.b64decode(after['data'])):
            raise TransactionError('Invalid Decky insertion rollback record')
        return {'before': before, 'after': after}

    @staticmethod
    def _legacy_choices(value):
        if (not isinstance(value, list) or len(value) > 256
                or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}', name) for name in value)
                or len(set(value)) != len(value)):
            raise TransactionError('Invalid legacy component selection')
        return sorted(value)

    @staticmethod
    def _slot(slot):
        if not isinstance(slot, str) or not slot or len(slot) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in slot):
            raise TransactionError("Invalid slot identifier")
        return slot

    @staticmethod
    def _path(relative):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative or "\x00" in relative:
            raise TransactionError("Invalid target path")
        path = PurePosixPath(relative)
        if path.is_absolute() or not path.parts or any(p in (".", "..") for p in relative.split("/")) or str(path) != relative:
            raise TransactionError(f"Invalid target path: {relative}")
        if not relative.startswith(_PREFIXES) and relative != "efi/EFI/steamos/grub.cfg":
            raise TransactionError(f"Target outside allowed installation prefixes: {relative}")
        # Never allow maintenance packages to change OS identity/authentication or
        # disable the platform update pipeline, including via unit drop-ins.
        forbidden = {"etc/passwd", "etc/shadow", "etc/group", "etc/gshadow", "etc/sudoers"}
        lowered = relative.lower()
        if relative in forbidden or lowered.startswith("etc/sudoers.d/") or "atomupd" in lowered or "rauc" in lowered:
            raise TransactionError(f"Protected system target: {relative}")
        if relative.startswith("etc/default/grub") and relative not in {
                "etc/default/grub.d/oxp3-nvme.cfg", "etc/default/grub.d/oxp3-splitlock.cfg"}:
            raise TransactionError(f"Protected boot configuration: {relative}")
        return relative

    def _scope(self, slot, relative):
        return ("shared" if relative.startswith(("home/", "opt/")) else slot) + ":" + relative

    def _check_dir(self, info, relative, user):
        if not stat.S_ISDIR(info.st_mode):
            raise TransactionError(f"Non-directory target ancestor: {relative}")
        if self.enforce_owner:
            user_area = user and relative.startswith("home/") and relative.count("/") >= 1
            allowed = (0, self.uid) if user_area else (0,)
            if info.st_uid not in allowed or info.st_mode & 0o002 or (info.st_uid == 0 and info.st_mode & 0o020):
                raise TransactionError(f"Writable or untrusted target ancestor: {relative}")

    @contextlib.contextmanager
    def _parent(self, relative, *, create=False, user=False):
        relative = self._path(relative)
        target = self.root.joinpath(*relative.split("/"))
        try:
            target.relative_to(self.state)
        except ValueError:
            pass
        else:
            raise TransactionError("A package cannot modify the transaction state directory")
        if relative == "home/.oxp3-maintenance" or relative.startswith("home/.oxp3-maintenance/"):
            raise TransactionError("A package cannot modify the transaction state directory")
        parts = relative.split("/")
        if os.name == "posix":
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                current = []
                for part in parts[:-1]:
                    current.append(part)
                    label = "/".join(current)
                    try:
                        nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except FileNotFoundError:
                        if not create:
                            yield None, parts[-1]
                            return
                        os.mkdir(part, 0o755, dir_fd=fd)
                        os.fsync(fd)
                        nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        if user and label.startswith("home/"):
                            os.fchown(nxt, self.uid, self.gid)
                            os.fsync(nxt)
                    except OSError as exc:
                        raise TransactionError(f"Unsafe target ancestor: {label}") from exc
                    os.close(fd)
                    fd = nxt
                    self._check_dir(os.fstat(fd), label, user)
                yield fd, parts[-1]
            finally:
                os.close(fd)
        else:
            current = self.root
            for part in parts[:-1]:
                current = current / part
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    if not create:
                        yield None, parts[-1]
                        return
                    current.mkdir()
                    info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise TransactionError(f"Unsafe target ancestor: {current}")
                self._check_dir(info, str(current), user)
            yield current, parts[-1]

    def _read(self, relative, *, user=False):
        with self._parent(relative, user=user) as (parent, name):
            if parent is None:
                return dict(_ABSENT)
            try:
                if os.name == "posix":
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                else:
                    info = (parent / name).lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise TransactionError(f"Unsafe target link: {relative}")
                    fd = os.open(parent / name, os.O_RDONLY | os.O_BINARY)
            except FileNotFoundError:
                return dict(_ABSENT)
            except OSError as exc:
                raise TransactionError(f"Cannot safely read target: {relative}") from exc
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise TransactionError(f"Target is not a single regular file: {relative}")
                if self.enforce_owner and info.st_uid not in ((0, self.uid) if user else (0,)):
                    raise TransactionError(f"Untrusted target owner: {relative}")
                with os.fdopen(fd, "rb") as stream:
                    fd = None
                    data = stream.read()
                return {"exists": True, "data": base64.b64encode(data).decode("ascii"),
                        "mode": stat.S_IMODE(info.st_mode),
                        "uid": info.st_uid, "gid": info.st_gid}
            finally:
                if fd is not None:
                    os.close(fd)

    def _write(self, relative, snapshot, *, user=False):
        with self._parent(relative, create=snapshot["exists"], user=user) as (parent, name):
            if parent is None:
                return
            if not snapshot["exists"]:
                try:
                    if os.name == "posix":
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
                    else:
                        (parent / name).unlink()
                except FileNotFoundError:
                    pass
                return
            temporary = ".oxp3-" + uuid.uuid4().hex + ".tmp"
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                fd = os.open(temporary if os.name == "posix" else parent / temporary,
                             flags, snapshot["mode"], **({"dir_fd": parent} if os.name == "posix" else {}))
                with os.fdopen(fd, "wb") as stream:
                    stream.write(base64.b64decode(snapshot["data"], validate=True))
                    stream.flush()
                    if os.name == "posix":
                        os.fchown(stream.fileno(), snapshot["uid"], snapshot["gid"])
                        os.fchmod(stream.fileno(), snapshot["mode"])
                    os.fsync(stream.fileno())
                if os.name == "posix":
                    os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                else:
                    # Windows fixtures cannot atomically replace a readonly file.
                    # Production always takes the POSIX branch with exact metadata.
                    existing_mode = None
                    try:
                        existing_mode = stat.S_IMODE((parent / name).stat().st_mode)
                        os.chmod(parent / name, 0o666)
                    except FileNotFoundError:
                        pass
                    try:
                        os.replace(parent / temporary, parent / name)
                    except BaseException:
                        if existing_mode is not None:
                            os.chmod(parent / name, existing_mode)
                        raise
                    os.chmod(parent / name, snapshot["mode"])
            finally:
                try:
                    if os.name == "posix":
                        os.unlink(temporary, dir_fd=parent)
                    else:
                        (parent / temporary).unlink()
                except FileNotFoundError:
                    pass

    def _desired(self, spec):
        if not isinstance(spec.get("data"), bytes) or not isinstance(spec.get("component"), str):
            raise TransactionError("File needs bytes data and component")
        user = bool(spec.get("user", False))
        uid, gid = (self.uid, self.gid) if user else (0, 0)
        if "uid" in spec and spec["uid"] != uid or "gid" in spec and spec["gid"] != gid:
            raise TransactionError("Package cannot override target ownership")
        desired = _snapshot({"exists": True, "data": base64.b64encode(spec["data"]).decode("ascii"),
                             "mode": spec.get("mode", 0o644), "uid": uid, "gid": gid})
        if desired["mode"] & 0o7000 or desired["mode"] & 0o002 or not user and desired["mode"] & 0o020:
            raise TransactionError("Unsafe package file mode")
        if not self.enforce_owner and os.name != "posix":
            desired["uid"], desired["gid"] = 0, 0
            desired["mode"] = 0o666 if desired["mode"] & 0o200 else 0o444
        return {"component": spec["component"], "user": user,
                "mutable": bool(spec.get("mutable", False)), "snapshot": desired}

    def _live_checked(self, generation):
        actual, edited = {}, set()
        for relative, entry in generation.get("paths", {}).items():
            actual[relative] = self._read(relative, user=entry["user"])
            if actual[relative] != entry["snapshot"]:
                if not entry["mutable"]:
                    raise TransactionError(f"Managed immutable file was modified: {relative}")
                edited.add(relative)
        return actual, edited

    def _other_owners(self, index, slot, relative):
        if not relative.startswith(("home/", "opt/")):
            return []
        return [(name, record["current"]["paths"][relative])
                for name, record in index["slots"].items()
                if name != slot and relative in record.get("current", {}).get("paths", {})]

    def _check_shared(self, index, slot, relative, after):
        for other, entry in self._other_owners(index, slot, relative):
            if after != entry["snapshot"]:
                raise TransactionError(f"Shared target {relative} is owned by slot {other}; restore that owner first")

    def _after_write(self, relative):
        """Fault-injection seam for tests; successful writes are journaled first."""

    def _execute(self, pending, slot=None):
        if slot is not None and pending.get("slot") != self._slot(slot):
            raise TransactionError("Pending transaction belongs to a different slot")
        if slot is None and pending.get("root") != self._identity():
            raise TransactionError("Pending transaction belongs to a different mounted root")
        self._validate_generation_metadata(pending['index_after'])
        operations = sorted(pending["operations"], key=_operation_order)
        # Check every target before performing any recovery writes.
        for op in operations:
            actual = self._read(op["path"], user=op["user"])
            if actual != op["before"] and actual != op["after"]:
                raise TransactionError(f"Recovery conflict; target changed externally: {op['path']}")
        for op in operations:
            actual = self._read(op["path"], user=op["user"])
            if actual == op["after"]:
                continue
            if actual != op["before"]:
                raise TransactionError(f"Concurrent target modification: {op['path']}")
            self._write(op["path"], op["after"], user=op["user"])
            self._after_write(op["path"])
            if self._read(op["path"], user=op["user"]) != op["after"]:
                raise TransactionError(f"Target verification failed: {op['path']}")
        self._state_write("index.json", pending["index_after"])
        (self.state / "pending.json").unlink()
        self._sync_state()
        return pending["result"]

    def recover(self, slot: str | None = None):
        with self.lock():
            pending = self._state_read("pending.json")
            if pending is None:
                return {"recovered": False, "changed": False}
            result = self._execute(pending, slot)
            return {**result, "recovered": True}

    def _commit(self, index, slot, generation, operations, *, preserved=(), action="apply"):
        operations = sorted(operations, key=_operation_order)
        previous = index["slots"].get(slot, {}).get("current")
        if previous == generation and not operations:
            return {"changed": False, "slot": slot, "generation": previous.get("id") if previous else None,
                    "preserved": sorted(preserved), "paths": [], "action": action}
        generation["id"] = index["next_generation"]
        index["next_generation"] += 1
        index["slots"][slot] = {"current": generation, "previous": previous}
        # Reject inconsistent private rollback metadata before queuing any
        # durable operations; recover must always be able to validate its index.
        self._validate_generation_metadata(index)
        result = {"changed": True, "slot": slot, "generation": generation["id"],
                  "preserved": sorted(preserved), "paths": [op["path"] for op in operations], "action": action}
        pending = {"format": 1, "root": self._identity(), "slot": slot,
                   "operations": operations, "index_after": index, "result": result}
        self._state_write("pending.json", pending)
        return self._execute(pending, slot)

    def _ready(self, slot):
        if self._state_read("pending.json") is not None:
            self.recover(slot)
        return self._index()

    def apply(self, files: dict, release: dict, selected: list[str], slot: str, *,
              adopt: dict | None = None, legacy_selected: list[str] | None = None):
        with self.lock():
            slot = self._slot(slot)
            index = self._ready(slot)
            old = index["slots"].get(slot, {}).get("current", {"paths": {}, "selected": [], "release": {}})
            from . import autoflatpaks_compat, animation_changer_compat
            plugin_repairs = (autoflatpaks_compat, animation_changer_compat)
            try:
                for repair in plugin_repairs:
                    repair.validate_transaction(files, self._read, slot=slot)
                    for path, spec in files.items():
                        if spec.get('component') != repair.COMPONENT:
                            continue
                        previous = old['paths'].get(path)
                        if (previous and previous.get('component') != repair.COMPONENT
                                or (adopt or {}).get(path, {}).get('component') not in (None, repair.COMPONENT)):
                            raise ValueError('Installed plugin repair cannot transfer another component recovery original')
            except (ValueError, TypeError, KeyError) as error:
                raise TransactionError(str(error)) from error
            actual, edited = self._live_checked(old)
            entries = {self._path(path): self._desired(spec) for path, spec in files.items()}
            from .split_lock import GRUB, BOOT_REPAIRS
            if (GRUB in edited and GRUB in entries
                    and entries[GRUB]['component'] in BOOT_REPAIRS
                    and entries[GRUB]['snapshot'] != actual[GRUB]):
                raise TransactionError('Managed Valve boot settings changed externally; preserve them for review before adding boot repairs')
            adopted_grub = (adopt or {}).get(GRUB)
            if (GRUB in entries and adopted_grub and adopted_grub.get('preserve')
                    and entries[GRUB]['component'] in BOOT_REPAIRS
                    and entries[GRUB]['snapshot'] != _snapshot(adopted_grub['applied'])):
                raise TransactionError('Adopted Valve boot settings changed externally; preserve them for review before adding boot repairs')
            from .decky_order import SETTINGS, insertion_bytes
            order_edit = copy.deepcopy(old.get('decky_order_edit'))
            if SETTINGS in edited and SETTINGS in entries:
                desired, previous = entries[SETTINGS], old['paths'][SETTINGS]
                light = files.get('var/lib/oxp3-installer/decky/runtime/plugins/OXP3-Light/plugin.json', {})
                before, after = actual[SETTINGS], desired['snapshot']
                expected = insertion_bytes(base64.b64decode(before['data'])) if before['exists'] else None
                if ('oxp3-light' in selected and expected is not None
                        and base64.b64decode(after['data']) not in (expected, base64.b64decode(before['data']))):
                    raise TransactionError('Managed Decky insertion would change other preferences')
                if expected is not None and base64.b64decode(after['data']) == expected:
                    try:
                        light_name = json.loads(light.get('data', b'null')).get('name')
                    except (ValueError, AttributeError, TypeError):
                        light_name = None
                    if (desired['component'] != 'decky' or previous['component'] != 'decky'
                            or not desired['mutable'] or not previous['mutable'] or desired['user'] or previous['user']
                            or 'oxp3-light' not in selected or light.get('component') != 'oxp3-light'
                            or light_name != 'OXP3 Light'):
                        raise TransactionError('Invalid managed Decky Light insertion')
                    order_edit = self._order_edit({'before': before, 'after': after})
                    edited.remove(SETTINGS)
            # Splitting the optional runtime out of the plugin is not an
            # uninstall request. Keep its verified old ownership until the user
            # explicitly selects the new runtime component.
            for path, previous in old['paths'].items():
                if (runtime_path(path) and previous['component'] == OPTI_PLUGIN
                        and {OPTI_PLUGIN, OPTI_RUNTIME}.intersection(selected)):
                    scope = self._scope(slot, path)
                    if scope not in index['originals']:
                        raise TransactionError(f'Legacy Opti runtime original is missing: {path}')
                    _snapshot(index['originals'][scope])
                if retain_legacy_runtime(path, previous['component'], selected):
                    entries.setdefault(path, copy.deepcopy(previous))
            # A first upgrade from the old installer must journal these retained
            # runtime files too; otherwise their true originals would be lost
            # when the plugin's legacy selection is superseded.
            for path, adopted in (adopt or {}).items():
                if path in entries or not retain_legacy_runtime(path, adopted.get('component'), selected):
                    continue
                path = self._path(path)
                applied = _snapshot(adopted['applied'])
                if not applied['exists']:
                    raise TransactionError(f'Legacy Opti runtime has no installed snapshot: {path}')
                entries[path] = self._desired({'data': base64.b64decode(applied['data']),
                    'mode': applied['mode'] & ~0o022, 'component': OPTI_PLUGIN,
                    'user': path == OPTI_RUNTIME_CONFIG, 'mutable': path == OPTI_RUNTIME_CONFIG})
                if entries[path]['snapshot'] != applied:
                    raise TransactionError(f'Unsafe legacy Opti runtime metadata: {path}')
            for path, entry in entries.items():
                if entry["user"] and not path.startswith("home/"):
                    raise TransactionError(f"User-owned files must live under home/: {path}")
                if path in old["paths"] and old["paths"][path]["component"] != entry["component"]:
                    previous = old['paths'][path]
                    if (not transfer_allowed(path, previous['component'], entry['component'], selected)
                            or previous['user'] != entry['user'] or previous['mutable'] != entry['mutable']):
                        raise TransactionError(f"Cannot transfer target between components: {path}")
            generation = {"paths": copy.deepcopy(old["paths"]), "release": copy.deepcopy(release),
                          "selected": sorted(set(selected) | {e["component"] for e in old["paths"].values() if e["component"] not in selected})}
            if order_edit is not None:
                generation['decky_order_edit'] = order_edit
            if legacy_selected is not None or 'legacy_selected' in old:
                legacy = self._legacy_choices(old.get('legacy_selected', []) if legacy_selected is None else legacy_selected)
                generation['legacy_selected'] = [name for name in legacy if name not in generation['selected']]
            adopted_components = set(self._legacy_choices(old.get('legacy_adopted', [])))
            operations, preserved, adoption_before, adoption_preserved = [], set(edited), {}, set()
            for path in sorted(set(old["paths"]) | set(entries)):
                previous = old["paths"].get(path)
                entry = entries.get(path)
                if entry is None and previous["component"] not in selected:
                    continue  # Only explicit restore uninstalls a component.
                before = actual[path] if path in actual else self._read(path, user=entry["user"])
                if path in files:
                    try:
                        for repair in plugin_repairs:
                            repair.validate_before(path, files[path], before)
                    except (ValueError, TypeError, KeyError) as error:
                        raise TransactionError(str(error)) from error
                scope = self._scope(slot, path)
                if previous is None:
                    for other, shared_entry in self._other_owners(index, slot, path):
                        if before != shared_entry["snapshot"]:
                            raise TransactionError(f"Shared target was modified in slot {other}: {path}")
                    adopted = (adopt or {}).get(path)
                    if adopted is not None:
                        if ((adopted.get("component") != entry["component"]
                                and not transfer_allowed(path, adopted.get('component'), entry['component'], selected))
                                or _snapshot(adopted["applied"]) != before):
                            raise TransactionError(f"Installer adoption does not match live target: {path}")
                        original = _snapshot(adopted["original"])
                        adoption_before[path] = copy.deepcopy(before)
                        adopted_components.update(self._legacy_choices([entry['component']]))
                        if adopted.get("preserve"):
                            baseline = _snapshot(adopted.get("baseline"))
                            if not entry["mutable"] or not baseline["exists"] or not before["exists"] or any(baseline[key] != before[key] for key in ("mode", "uid", "gid")):
                                raise TransactionError(f"Invalid mutable installer adoption: {path}")
                            entry["snapshot"] = baseline
                            edited.add(path)
                            preserved.add(path)
                            adoption_preserved.add(path)
                    else:
                        original = before
                    if (scope in index["originals"] and not self._other_owners(index, slot, path)
                            and before != index["originals"][scope]
                            and not (adopted is not None and original == index["originals"][scope])):
                        if not entry["mutable"]:
                            raise TransactionError(f"Previously restored target changed externally: {path}")
                        # The newly materialized bytes may already include the
                        # user's customization. Keep the authoritative original
                        # as baseline so a later restore still recognizes it.
                        entry['snapshot'] = copy.deepcopy(index['originals'][scope])
                        edited.add(path)
                        preserved.add(path)
                    index["originals"].setdefault(scope, original)
                if entry is None:
                    generation["paths"].pop(path, None)
                    after = before if path in edited else index["originals"][scope]
                    if path == SETTINGS and order_edit and path not in edited:
                        after = order_edit['before']
                    if self._other_owners(index, slot, path):
                        after = before  # Unmanage this slot without disturbing another owner.
                elif path in edited:
                    # Retain the previous baseline so later restore can recognize edits.
                    generation["paths"][path] = copy.deepcopy(previous or entry)
                    if previous and transfer_allowed(path, previous['component'], entry['component'], selected):
                        generation['paths'][path]['component'] = entry['component']
                    after = before
                else:
                    generation["paths"][path] = entry
                    after = entry["snapshot"]
                if before != after:
                    self._check_shared(index, slot, path, after)
                    operations.append({"path": path, "before": before, "after": after,
                                       "user": (entry or previous)["user"]})
            # Keep a stable id during equality comparison; commit allocates only on change.
            if adopted_components or 'legacy_adopted' in old:
                generation['legacy_adopted'] = sorted(adopted_components)
            if adoption_before:
                generation['adoption_before'] = self._adoption_snapshots(adoption_before)
                generation['adoption_preserved'] = sorted(adoption_preserved)
            if SETTINGS not in generation['paths']:
                generation.pop('decky_order_edit', None)
            if "id" in old:
                generation["id"] = old["id"]
            return self._commit(index, slot, generation, operations, preserved=preserved)

    def rollback(self, slot: str, *, _aborted_apply=None):
        with self.lock():
            slot = self._slot(slot)
            index = self._ready(slot)
            record = index["slots"].get(slot)
            if not record or record.get("previous") is None:
                raise TransactionError(f"No previous generation for slot {slot}")
            old, target = record["current"], copy.deepcopy(record["previous"])
            actual, edited = self._live_checked(old)
            from .decky_order import SETTINGS
            leaving_order = self._order_edit(old['decky_order_edit']) if 'decky_order_edit' in old else None
            entering_order = self._order_edit(target['decky_order_edit']) if 'decky_order_edit' in target else None
            leaving_adoption = self._adoption_snapshots(old.get('adoption_before', {}))
            entering_adoption = self._adoption_snapshots(target.get('adoption_before', {}))
            # Older adoption generations lack explicit preservation intent.
            # Preserve matching mutable before-images conservatively for those.
            entering_preserved = set(target.get('adoption_preserved', entering_adoption))
            # The fixed wrapper is switched last. Retain its current immutable
            # implementation until and after that switch, so a power failure
            # during rollback leaves a usable CLI for recovery.
            for path, entry in old["paths"].items():
                if (path.startswith("usr/local/lib/oxp3-maintenance/releases/")
                        and entry["component"] == "_maintenance" and not entry["mutable"]):
                    target["paths"].setdefault(path, copy.deepcopy(entry))
            operations = []
            for path in sorted(set(old["paths"]) | set(target["paths"])):
                entry = target["paths"].get(path)
                previous = old["paths"].get(path)
                user = (entry or previous)["user"]
                before = actual.get(path, self._read(path, user=user))
                if (path == SETTINGS and entering_order and entering_order != leaving_order
                        and before == entering_order['before']):
                    after = entry['snapshot'] if entry else before
                    edited.discard(path)
                elif path == SETTINGS and leaving_order and leaving_order != entering_order and path not in edited:
                    after = leaving_order['before']
                elif path in edited:
                    after = before
                    if entry:
                        target["paths"][path] = copy.deepcopy(previous)
                        if path == SETTINGS:
                            if leaving_order:
                                target['decky_order_edit'] = copy.deepcopy(leaving_order)
                            else:
                                target.pop('decky_order_edit', None)
                        if (transfer_allowed(path, entry['component'], previous['component'], old['selected'])
                                or transfer_allowed(path, previous['component'], entry['component'], target['selected'])):
                            # Keep the edited bytes and their current baseline,
                            # but restore ownership for the target generation.
                            # This also supports toggling rollback forward again.
                            target['paths'][path]['component'] = entry['component']
                elif entry:
                    after = entry["snapshot"]
                    if (previous is None and entry['mutable'] and path in entering_preserved
                            and before == entering_adoption.get(path) and before != entry['snapshot']):
                        # A preserved calibration can exactly match the known
                        # adoption source while still differing from its stored
                        # unedited baseline. Reenter ownership without writing it.
                        after = before
                        edited.add(path)
                    elif (previous is None and before != index["originals"][self._scope(slot, path)]
                            and before != entering_adoption.get(path)):
                        if entry["mutable"]:
                            after = before
                            edited.add(path)
                        else:
                            raise TransactionError(f"Rollback target changed externally: {path}")
                else:
                    after = leaving_adoption.get(path, index["originals"][self._scope(slot, path)])
                    if self._other_owners(index, slot, path):
                        after = before
                if before != after:
                    self._check_shared(index, slot, path, after)
                    operations.append({"path": path, "before": before, "after": after, "user": user})
            target["id"] = old["id"]
            if _aborted_apply is not None:
                target['aborted_apply'] = copy.deepcopy(_aborted_apply)
            return self._commit(index, slot, target, operations, preserved=edited, action="rollback")

    def abort_apply(self, slot: str, *, generation: int, source_generation: int | None):
        """Undo the journaled apply, retaining a first installed recovery engine.

        A first adoption has no managed predecessor. Its legacy before-images
        are distinct from the true originals used by an explicit uninstall.
        Bind this operation to both generation IDs so stale lifecycle intent
        cannot undo an unrelated apply or toggle an already completed abort.
        """
        with self.lock():
            slot = self._slot(slot)
            index = self._ready(slot)
            record = index['slots'].get(slot) or {}
            old, previous = record.get('current'), record.get('previous')
            if (type(generation) is not int or generation < 1
                    or source_generation is not None and (type(source_generation) is not int or source_generation < 1)
                    or not old or old['id'] != generation
                    or (previous['id'] if previous else None) != source_generation):
                raise TransactionError('Apply abort does not match the recorded source generation')
            if previous is not None:
                return self.rollback(slot, _aborted_apply={'generation': generation, 'source_generation': source_generation})
            actual, edited = self._live_checked(old)
            engine = old['paths'].get('usr/local/lib/oxp3-maintenance/entry.py', {})
            if (engine.get('component') != '_maintenance' or engine.get('mutable', True)
                    or engine.get('user', True)):
                raise TransactionError('Apply abort requires an immutable recovery engine')
            before_images = self._adoption_snapshots(old.get('adoption_before', {}))
            target = {'paths': {}, 'release': copy.deepcopy(old['release']),
                      'selected': ['_maintenance'], 'id': old['id'],
                      'legacy_selected': self._legacy_choices(list(set(old.get('legacy_selected', []))
                                                                 | set(old.get('legacy_adopted', []))))}
            target['release']['apply_outcome'] = 'aborted_engine_retained'
            target['aborted_apply'] = {'generation': generation, 'source_generation': source_generation}
            operations = []
            from .decky_order import SETTINGS
            order_edit = self._order_edit(old['decky_order_edit']) if 'decky_order_edit' in old else None
            for path, entry in old['paths'].items():
                if entry['component'] == '_maintenance':
                    if entry['mutable']:
                        raise TransactionError('Apply abort requires an immutable recovery engine')
                    target['paths'][path] = copy.deepcopy(entry)
                    if path in ('usr/local/lib/oxp3-maintenance/activation.json',
                                'usr/local/lib/oxp3-maintenance/current-release.json'):
                        if entry['user']:
                            raise TransactionError('Apply abort requires protected recovery metadata')
                        try:
                            metadata = json.loads(base64.b64decode(entry['snapshot']['data']))
                            if path.endswith('/activation.json'):
                                metadata['components'] = {}
                            else:
                                metadata.setdefault('component_revisions_by_slot', {}).pop(slot, None)
                            metadata['apply_outcome'] = 'aborted_engine_retained'
                            after = dict(entry['snapshot'], data=base64.b64encode(
                                (json.dumps(metadata) + '\n').encode()).decode('ascii'))
                        except (ValueError, TypeError, KeyError, AttributeError) as error:
                            raise TransactionError('Invalid retained recovery metadata: ' + path) from error
                        target['paths'][path]['snapshot'] = after
                        if actual[path] != after:
                            operations.append({'path': path, 'before': actual[path], 'after': after, 'user': False})
                    continue
                before = actual[path]
                after = before_images.get(path, index['originals'][self._scope(slot, path)])
                if path == SETTINGS and order_edit:
                    after = order_edit['before']
                if path in edited or self._other_owners(index, slot, path):
                    after = before
                if before != after:
                    self._check_shared(index, slot, path, after)
                    operations.append({'path': path, 'before': before, 'after': after, 'user': entry['user']})
            if not target['paths']:
                raise TransactionError('Apply abort requires a retained recovery engine')
            return self._commit(index, slot, target, operations, preserved=edited, action='abort')

    def restore(self, slot: str, components: list[str] | None = None):
        with self.lock():
            slot = self._slot(slot)
            index = self._ready(slot)
            old = index["slots"].get(slot, {}).get("current")
            if not old:
                return {"changed": False, "slot": slot, "paths": [], "preserved": [], "action": "restore"}
            selected = set(old["selected"] if components is None else components)
            from .split_lock import require_joint_restore
            try:
                require_joint_restore(old['paths'], selected)
            except ValueError as error:
                raise TransactionError(str(error)) from error
            actual, edited = self._live_checked(old)
            from .decky_order import SETTINGS
            order_edit = self._order_edit(old['decky_order_edit']) if 'decky_order_edit' in old else None
            target = copy.deepcopy(old)
            operations, preserved = [], []
            for path, entry in old["paths"].items():
                if components is not None and entry["component"] not in selected:
                    continue
                target["paths"].pop(path)
                before = actual[path]
                after = index["originals"][self._scope(slot, path)]
                if path == SETTINGS and order_edit:
                    after = order_edit['before']
                if path in edited:
                    after = before
                    preserved.append(path)
                if self._other_owners(index, slot, path):
                    after = before
                if before != after:
                    self._check_shared(index, slot, path, after)
                    operations.append({"path": path, "before": before, "after": after, "user": entry["user"]})
            target["selected"] = [component for component in old["selected"] if component not in selected]
            if SETTINGS not in target['paths']:
                target.pop('decky_order_edit', None)
            return self._commit(index, slot, target, operations, preserved=preserved, action="restore")

    def status(self):
        with self.lock():
            index = self._index()
            slots = {}
            for slot, record in index["slots"].items():
                slots[slot] = {}
                for key in ("current", "previous"):
                    generation = record.get(key)
                    slots[slot][key] = None if generation is None else {
                        "id": generation["id"], "release": copy.deepcopy(generation["release"]),
                        "selected": list(generation["selected"]), "path_count": len(generation["paths"])}
                    if generation is not None:
                        for field in ('legacy_selected', 'legacy_adopted'):
                            if field in generation:
                                slots[slot][key][field] = list(generation[field])
            pending = self._state_read("pending.json")
            return {"format": 1, "slots": slots, "pending": None if pending is None else
                    {"slot": pending["slot"], "action": pending["result"]["action"],
                     "path_count": len(pending["operations"])}}

    def managed(self):
        with self.lock():
            index = self._index()
            paths, components = {}, {}
            for slot, record in index["slots"].items():
                generation = record["current"]
                for component in generation["selected"]:
                    components.setdefault(component, {"slots": []})["slots"].append(slot)
                for path, entry in generation["paths"].items():
                    view = paths.setdefault(path, {**_public_entry(entry), "slots": [],
                                                  "scope": "shared" if path.startswith(("home/", "opt/")) else "slot"})
                    view["slots"].append(slot)
            return {"paths": paths, "components": components}
