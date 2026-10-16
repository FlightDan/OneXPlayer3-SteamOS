"""Run with python -m unittest discover -s tests -p test_transactions.py."""
import base64
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from oxp3_maintenance.transactions import Store, TransactionError


def spec(data=b"one", component="theme", mutable=False, user=False, mode=0o644):
    return {"data": data, "component": component, "mutable": mutable, "user": user, "mode": mode}


def hold_lock(root, state, acquired, release):
    store = Store(Path(root), Path(state), enforce_owner=False)
    with store.lock():
        acquired.set()
        release.wait(2 * float(os.environ.get('OXP_TEST_PROCESS_TIMEOUT', '5')))


def acquire_lock(root, state, acquired):
    store = Store(Path(root), Path(state), enforce_owner=False)
    with store.lock():
        acquired.set()


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.state = self.base / "state"
        self.store = Store(self.root, self.state, uid=getattr(os, "getuid", lambda: 0)(),
                           gid=getattr(os, "getgid", lambda: 0)(), enforce_owner=False)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def apply(self, files, version="1", slot="A", selected=None, **kwargs):
        return self.store.apply(files, {"version": version}, selected or ["theme"], slot, **kwargs)

    def test_update_changes_target_set_rollback_and_original_restore(self):
        original = self.write("etc/theme.conf", b"image")
        os.chmod(original, 0o444)
        original_mode = stat.S_IMODE(original.stat().st_mode)
        self.apply({"etc/theme.conf": spec(), "opt/theme/old": spec(b"old")})
        self.apply({"etc/theme.conf": spec(b"two"), "opt/theme/new": spec(b"new")}, "2")
        self.assertFalse((self.root / "opt/theme/old").exists())
        self.store.rollback("A")
        self.assertEqual(original.read_bytes(), b"one")
        self.assertEqual((self.root / "opt/theme/old").read_bytes(), b"old")
        self.assertFalse((self.root / "opt/theme/new").exists())
        self.store.restore("A")
        self.assertEqual(original.read_bytes(), b"image")
        self.assertEqual(stat.S_IMODE(original.stat().st_mode), original_mode)
        self.assertFalse((self.root / "opt/theme/old").exists())

    def test_noop_retains_previous_generation(self):
        files = {"etc/theme.conf": spec()}
        first = self.apply(files)
        self.assertFalse(self.apply(files)["changed"])
        self.assertEqual(self.store.status()["slots"]["A"]["current"]["id"], first["generation"])
        self.assertIsNone(self.store.status()["slots"]["A"]["previous"])

    def test_immutable_edits_fail_before_any_write(self):
        self.apply({"etc/a": spec(), "etc/z": spec()})
        self.write("etc/z", b"external")
        with self.assertRaisesRegex(TransactionError, "immutable"):
            self.apply({"etc/a": spec(b"two"), "etc/z": spec(b"two")}, "2")
        self.assertEqual((self.root / "etc/a").read_bytes(), b"one")
        self.assertIsNone(self.store.status()["pending"])

    def test_mutable_edits_survive_update_rollback_restore(self):
        path = self.write("home/deck/theme/config", b"preproject")
        self.apply({"home/deck/theme/config": spec(mutable=True, user=True)})
        path.write_bytes(b"user choice")
        result = self.apply({"home/deck/theme/config": spec(b"two", mutable=True, user=True)}, "2")
        self.assertEqual(result["preserved"], ["home/deck/theme/config"])
        self.assertEqual(path.read_bytes(), b"user choice")
        self.store.rollback("A")
        self.store.restore("A")
        self.assertEqual(path.read_bytes(), b"user choice")
        self.assertNotIn("home/deck/theme/config", self.store.managed()["paths"])

    def test_unedited_mutable_restores_original(self):
        path = self.write("home/deck/config", b"preproject")
        self.apply({"home/deck/config": spec(mutable=True, user=True)})
        self.apply({"home/deck/config": spec(b"two", mutable=True, user=True)}, "2")
        self.assertEqual(path.read_bytes(), b"two")
        self.store.restore("A")
        self.assertEqual(path.read_bytes(), b"preproject")

    def test_edited_obsolete_mutable_is_preserved(self):
        self.apply({"home/deck/config": spec(mutable=True, user=True)})
        self.write("home/deck/config", b"user")
        self.apply({}, "2")
        self.assertEqual((self.root / "home/deck/config").read_bytes(), b"user")
        self.assertNotIn("home/deck/config", self.store.managed()["paths"])
        result = self.store.rollback("A")
        self.assertEqual(result["preserved"], ["home/deck/config"])
        self.assertEqual((self.root / "home/deck/config").read_bytes(), b"user")
        self.store.restore("A")
        self.assertEqual((self.root / "home/deck/config").read_bytes(), b"user")

    def test_deselection_is_not_implicit_uninstall(self):
        self.apply({"etc/theme": spec(), "etc/plugin": spec(component="plugin")}, selected=["theme", "plugin"])
        self.apply({"etc/theme": spec(b"two")}, "2", selected=["theme"])
        self.assertEqual((self.root / "etc/plugin").read_bytes(), b"one")
        self.store.restore("A", ["theme"])
        self.assertTrue((self.root / "etc/plugin").exists())

    def test_failure_after_write_recovers_without_step_record(self):
        self.apply({"etc/a": spec(), "etc/b": spec()})
        calls = []
        def fail(path):
            calls.append(path)
            raise RuntimeError("power loss")
        self.store._after_write = fail
        with self.assertRaisesRegex(RuntimeError, "power loss"):
            self.apply({"etc/a": spec(b"two"), "etc/b": spec(b"two")}, "2")
        self.assertIsNotNone(self.store.status()["pending"])
        self.assertEqual((self.root / "etc/a").read_bytes(), b"two")
        self.assertEqual((self.root / "etc/b").read_bytes(), b"one")
        fresh = Store(self.root, self.state, enforce_owner=False)
        self.assertTrue(fresh.recover("A")["recovered"])
        self.assertEqual((self.root / "etc/b").read_bytes(), b"two")
        self.assertIsNone(fresh.status()["pending"])
        self.assertFalse(fresh.recover("A")["recovered"])
        fresh.restore("A")
        self.assertFalse((self.root / "etc/a").exists())

    def test_runtime_switch_is_last_and_crash_keeps_previous_wrapper(self):
        wrapper = "usr/local/lib/oxp3-maintenance/entry.py"
        source1 = "usr/local/lib/oxp3-maintenance/releases/1/entry.py"
        source2 = "usr/local/lib/oxp3-maintenance/releases/2/entry.py"
        activation = "usr/local/lib/oxp3-maintenance/activation.json"
        self.apply({wrapper: spec(b"wrapper1", "_maintenance"),
                    source1: spec(b"source1", "_maintenance"),
                    activation: spec(b"activation1", "_maintenance")}, selected=["_maintenance"])
        writes = []
        def fail_on_source(path):
            writes.append(path)
            if path == source2:
                raise RuntimeError("crash before switch")
        self.store._after_write = fail_on_source
        with self.assertRaisesRegex(RuntimeError, "crash before switch"):
            self.apply({wrapper: spec(b"wrapper2", "_maintenance"),
                        source1: spec(b"source1", "_maintenance"),
                        source2: spec(b"source2", "_maintenance"),
                        activation: spec(b"activation2", "_maintenance")}, "2", selected=["_maintenance"])
        self.assertEqual((self.root / source2).read_bytes(), b"source2")
        self.assertEqual((self.root / wrapper).read_bytes(), b"wrapper1")
        self.assertEqual((self.root / source1).read_bytes(), b"source1")
        self.store._after_write = writes.append
        self.store.recover("A")
        self.assertEqual(writes[-1], wrapper)
        self.assertLess(writes.index(source2), writes.index(activation))
        self.assertEqual((self.root / wrapper).read_bytes(), b"wrapper2")
        writes.clear()
        def fail_rollback(path):
            writes.append(path)
            if path == activation:
                raise RuntimeError("rollback interrupted")
        self.store._after_write = fail_rollback
        with self.assertRaisesRegex(RuntimeError, "rollback interrupted"):
            self.store.rollback("A")
        self.assertEqual((self.root / wrapper).read_bytes(), b"wrapper2")
        self.assertEqual((self.root / source2).read_bytes(), b"source2")
        self.store._after_write = writes.append
        self.store.recover("A")
        self.assertEqual(writes[-1], wrapper)
        self.assertEqual((self.root / wrapper).read_bytes(), b"wrapper1")
        self.assertEqual((self.root / source2).read_bytes(), b"source2")
        self.assertIn(source2, self.store.managed()["paths"])
        writes.clear()
        self.store.restore("A")
        self.assertEqual(writes[-1], wrapper)
        self.assertFalse((self.root / wrapper).exists())

    def test_recovery_conflict_prevents_further_writes(self):
        self.apply({"etc/a": spec(), "etc/b": spec()})
        self.store._after_write = lambda path: (_ for _ in ()).throw(RuntimeError("crash"))
        with self.assertRaises(RuntimeError):
            self.apply({"etc/a": spec(b"two"), "etc/b": spec(b"two")}, "2")
        self.write("etc/b", b"external")
        with self.assertRaisesRegex(TransactionError, "Recovery conflict"):
            self.store.recover("A")
        self.assertEqual((self.root / "etc/b").read_bytes(), b"external")
        self.assertIsNotNone(self.store.status()["pending"])

    def test_recovery_requires_slot_or_matching_root_identity(self):
        self.store._after_write = lambda path: (_ for _ in ()).throw(RuntimeError("crash"))
        with self.assertRaises(RuntimeError):
            self.apply({"etc/a": spec()})
        with self.assertRaisesRegex(TransactionError, "different slot"):
            self.store.recover("B")
        journal = json.loads((self.state / "pending.json").read_text())
        journal["root"]["dev"] = -1
        (self.state / "pending.json").write_text(json.dumps(journal))
        with self.assertRaisesRegex(TransactionError, "different mounted root"):
            self.store.recover()
        self.assertTrue(self.store.recover("A")["recovered"])

    def test_adoption_restores_installer_original_and_verifies_applied(self):
        path = self.write("etc/theme", b"installer")
        snapshot = self.store._read("etc/theme")
        original = {**snapshot, "data": base64.b64encode(b"image").decode()}
        self.apply({"etc/theme": spec()}, adopt={"etc/theme": {
            "original": original, "applied": snapshot, "component": "theme"}})
        self.store.restore("A")
        self.assertEqual(path.read_bytes(), b"image")
        with self.assertRaisesRegex(TransactionError, "adoption"):
            self.apply({"etc/theme": spec()}, adopt={"etc/theme": {
                "original": original, "applied": snapshot, "component": "theme"}})

    def test_restored_target_external_change_does_not_get_overwritten(self):
        self.apply({"etc/theme": spec()})
        self.store.restore("A")
        self.write("etc/theme", b"new outside installation")
        with self.assertRaisesRegex(TransactionError, "changed externally"):
            self.apply({"etc/theme": spec()})

    def test_unrelated_slots_and_shared_coownership(self):
        self.apply({"etc/theme": spec(), "opt/shared": spec()}, slot="A")
        self.apply({"etc/other": spec(), "opt/shared": spec()}, slot="B")
        self.store.restore("B")
        self.assertEqual((self.root / "opt/shared").read_bytes(), b"one")
        self.assertEqual((self.root / "etc/theme").read_bytes(), b"one")
        self.assertFalse((self.root / "etc/other").exists())
        self.assertEqual(self.store.status()["slots"]["A"]["current"]["release"], {"version": "1"})
        self.apply({"opt/shared": spec()}, slot="B")
        with self.assertRaisesRegex(TransactionError, "owned by slot B"):
            self.apply({"etc/theme": spec(), "opt/shared": spec(b"two")}, "2", slot="A")
        self.assertEqual((self.root / "opt/shared").read_bytes(), b"one")

    def test_shared_mutable_edit_is_preserved_when_dropping_one_owner(self):
        files = {"home/deck/config": spec(mutable=True, user=True)}
        self.apply(files, slot="A")
        self.apply(files, slot="B")
        self.write("home/deck/config", b"user")
        self.assertEqual(self.store.restore("B")["preserved"], ["home/deck/config"])
        self.assertEqual((self.root / "home/deck/config").read_bytes(), b"user")
        self.assertEqual(self.store.managed()["paths"]["home/deck/config"]["slots"], ["A"])

    def test_transaction_state_cannot_be_a_package_target(self):
        for path in ("home/.oxp3-maintenance/index.json", "home/.oxp3-maintenance"):
            with self.subTest(path=path), self.assertRaisesRegex(TransactionError, "state directory"):
                self.apply({path: spec()})
        nested = Store(self.root, self.root / "etc/private-state", enforce_owner=False)
        with self.assertRaisesRegex(TransactionError, "state directory"):
            nested.apply({"etc/private-state/index.json": spec()}, {}, ["theme"], "A")

    def test_status_and_managed_contain_no_blob(self):
        self.apply({"etc/theme": spec(b"SUPER_SECRET_CONTENT")})
        view = json.dumps({"status": self.store.status(), "managed": self.store.managed()})
        self.assertNotIn("SUPER_SECRET_CONTENT", view)
        self.assertNotIn(base64.b64encode(b"SUPER_SECRET_CONTENT").decode(), view)
        self.assertNotIn('"data"', view)

    def test_link_ancestors_and_leaf_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "etc").mkdir()
        try:
            (self.root / "etc/linked").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        with self.assertRaises(TransactionError):
            self.apply({"etc/linked/file": spec()})
        self.assertFalse((outside / "file").exists())
        target = outside / "file"
        target.write_bytes(b"outside")
        (self.root / "etc/file").symlink_to(target)
        with self.assertRaises(TransactionError):
            self.apply({"etc/file": spec()})
        self.assertEqual(target.read_bytes(), b"outside")

    def test_hardlinks_rejected(self):
        source = self.write("etc/a", b"original")
        try:
            os.link(source, self.root / "etc/b")
        except OSError as exc:
            self.skipTest(f"Hardlink creation unavailable: {exc}")
        with self.assertRaisesRegex(TransactionError, "single regular"):
            self.apply({"etc/a": spec()})

    @unittest.skipUnless(os.name == "nt", "Windows junction defense")
    def test_windows_junction_ancestor_rejected_without_symlink_privilege(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "etc").mkdir()
        link = self.root / "etc/junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(TransactionError, "Unsafe target ancestor"):
            self.apply({"etc/junction/file": spec()})
        self.assertFalse((outside / "file").exists())

    def test_leaf_link_check_is_exercised_on_every_platform(self):
        target = self.write("etc/link", b"outside")
        original = Path.lstat
        def simulated_link(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == target:
                fields = list(info)
                fields[0] = stat.S_IFLNK | 0o777
                return os.stat_result(fields)
            return info
        if os.name != "posix":
            with patch.object(Path, "lstat", simulated_link), self.assertRaisesRegex(TransactionError, "Unsafe target link"):
                self.apply({"etc/link": spec()})
        else:
            # Real O_NOFOLLOW behavior is tested by test_link_ancestors_and_leaf.
            target.unlink()
            target.symlink_to("missing")
            with self.assertRaises(TransactionError):
                self.apply({"etc/link": spec()})

    def test_protected_paths_and_ownership_specifications(self):
        for path in ("../etc/x", "/etc/x", "etc/../x", "etc//x", "etc/passwd", "etc/shadow",
                     "etc/systemd/system/atomupd.service", "etc/systemd/system/rauc.service.d/mask.conf",
                     "efi/EFI/BOOT/BOOTX64.EFI", "etc/default/grub", "root/secret"):
            with self.subTest(path=path), self.assertRaises(TransactionError):
                self.apply({path: spec()})
        with self.assertRaisesRegex(TransactionError, "ownership"):
            self.apply({"etc/theme": {**spec(), "uid": 1000}})
        with self.assertRaisesRegex(TransactionError, "User-owned"):
            self.apply({"etc/theme": spec(user=True)})

    def test_reentrant_global_lock(self):
        with self.store.lock():
            with self.store.lock():
                self.apply({"etc/theme": spec()})
                self.assertIn("A", self.store.status()["slots"])

    def test_cross_process_lock_serializes(self):
        timeout = float(os.environ.get('OXP_TEST_PROCESS_TIMEOUT', '5'))
        ctx = multiprocessing.get_context("spawn")
        first, second, release = ctx.Event(), ctx.Event(), ctx.Event()
        a = ctx.Process(target=hold_lock, args=(str(self.root), str(self.state), first, release))
        b = ctx.Process(target=acquire_lock, args=(str(self.root), str(self.state), second))
        try:
            a.start()
            self.assertTrue(first.wait(timeout))
            b.start()
            self.assertFalse(second.wait(0.3))
            release.set()
            self.assertTrue(second.wait(timeout))
            a.join(timeout)
            b.join(timeout)
            self.assertEqual(a.exitcode, 0)
            self.assertEqual(b.exitcode, 0)
        finally:
            release.set()
            for process in (a, b):
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout)

    @unittest.skipUnless(os.name == "posix", "POSIX metadata and ownership only")
    def test_system_and_user_modes_and_owners_restored(self):
        path = self.write("home/deck/config", b"original")
        os.chmod(path, 0o600)
        self.apply({"home/deck/config": spec(user=True, mode=0o640)})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.store.restore("A")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.stat().st_uid, self.store.uid)


if __name__ == "__main__":
    unittest.main()
