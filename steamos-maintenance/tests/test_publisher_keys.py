import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import publisher_keys as keys


class PublisherKeyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name) / "identity"

    def test_missing_status_does_not_create_anything(self):
        with mock.patch.object(keys, "_windows"):
            self.assertEqual(keys.key_status(self.store)["status"], "missing")
        self.assertFalse(self.store.exists())

    def test_nonwindows_is_explicit(self):
        with mock.patch.object(keys.os, "name", "posix"):
            with self.assertRaisesRegex(keys.KeyStoreError, "requires Windows"):
                keys.ensure_keys(self.store)
        self.assertFalse(self.store.exists())

    def test_cli_defaults_to_status(self):
        with mock.patch.object(keys, "key_status", return_value={"status": "missing"}) as status, mock.patch.object(keys, "ensure_keys") as init, mock.patch("builtins.print"):
            self.assertEqual(keys.main(["--store", str(self.store)]), 0)
        status.assert_called_once_with(self.store, openssl=None)
        init.assert_not_called()

    def test_invalid_private_key_fails_without_echoing_input(self):
        secret = b"not-a-key-private-secret"
        with self.assertRaises(keys.KeyStoreError) as error:
            keys._public(secret, None)
        self.assertNotIn(secret.decode(), str(error.exception))

    def test_openssl_errors_do_not_echo_stderr(self):
        result = mock.Mock(returncode=1, stderr=b"private-secret", stdout=b"")
        with mock.patch.object(keys.subprocess, "run", return_value=result):
            with self.assertRaises(keys.KeyStoreError) as error:
                keys._run("openssl", ["pkey"], b"private-secret")
        self.assertNotIn("private-secret", str(error.exception))

    def test_reparse_point_in_any_ancestor_is_rejected(self):
        original = Path.lstat
        ancestor = Path(self.temporary.name)

        def attributes(path, *args, **kwargs):
            if path == ancestor:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", attributes):
            with self.assertRaisesRegex(keys.KeyStoreError, "reparse"):
                keys._safe_path(self.store)


@unittest.skipUnless(os.name == "nt", "Native Windows DPAPI and ACL integration")
class PublisherKeyWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name) / "identity"

    def initialize(self):
        return keys.ensure_keys(self.store)

    def test_roundtrip_idempotence_sign_verify_and_cleanup(self):
        from cryptography.hazmat.primitives import serialization
        identity = self.initialize()
        before = {p.name: p.read_bytes() for p in self.store.iterdir()}
        self.assertEqual(keys.ensure_keys(self.store), identity)
        self.assertEqual(keys.key_status(self.store), identity)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.store.iterdir()})
        self.assertEqual(len(identity["fingerprint_sha256"]), 64)
        self.assertNotIn(b"BEGIN PRIVATE KEY", (self.store / keys.PRIVATE_FILE).read_bytes())
        with keys.signing_key(self.store) as path:
            self.assertTrue(path.exists())
            private = serialization.load_pem_private_key(path.read_bytes(), password=None)
            public = serialization.load_pem_public_key(Path(identity["public_key"]).read_bytes())
            public.verify(private.sign(b"release manifest"), b"release manifest")
            keys._acl(path, keys._sid())
        self.assertFalse(path.exists())
        self.assertEqual({p.name for p in self.store.iterdir()}, keys._FILES)

    def test_signer_exception_always_removes_plaintext(self):
        self.initialize()
        with self.assertRaisesRegex(RuntimeError, "caller failed"):
            with keys.signing_key(self.store) as path:
                raise RuntimeError("caller failed")
        self.assertFalse(path.exists())
        self.assertEqual(keys.key_status(self.store)["status"], "ready")

    def test_incomplete_store_never_rotates(self):
        self.initialize()
        blob = (self.store / keys.PRIVATE_FILE).read_bytes()
        (self.store / keys.METADATA_FILE).unlink()
        with self.assertRaisesRegex(keys.KeyStoreError, "incomplete"):
            keys.ensure_keys(self.store)
        self.assertEqual((self.store / keys.PRIVATE_FILE).read_bytes(), blob)

    def test_corrupt_blob_fails_closed(self):
        self.initialize()
        (self.store / keys.PRIVATE_FILE).write_bytes(b"corrupt")
        with self.assertRaisesRegex(keys.KeyStoreError, "DPAPI"):
            keys.key_status(self.store)

    def test_metadata_and_keypair_tampering_fail_closed(self):
        self.initialize()
        metadata_path = self.store / keys.METADATA_FILE
        metadata = json.loads(metadata_path.read_text())
        metadata["fingerprint"] = "sha256:" + "0" * 64
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(keys.KeyStoreError, "does not match"):
            keys.key_status(self.store)

    def test_public_key_mismatch_fails_closed(self):
        self.initialize()
        public, _ = keys._public(keys._generate(None), None)
        (self.store / keys.PUBLIC_FILE).write_bytes(public)
        with self.assertRaisesRegex(keys.KeyStoreError, "does not match"):
            keys.ensure_keys(self.store)

    def test_orphan_plaintext_fails_closed(self):
        self.initialize()
        orphan = self.store / "signing-orphan.pem"
        orphan.write_text("orphan")
        with self.assertRaisesRegex(keys.KeyStoreError, "unexpected"):
            keys.key_status(self.store)

    def test_lock_rejects_another_holder(self):
        self.initialize()
        with keys._locked(self.store, keys._sid()):
            with self.assertRaisesRegex(keys.KeyStoreError, "busy"):
                keys.key_status(self.store)

    def test_insecure_existing_acl_is_rejected_not_repaired(self):
        import ctypes
        from ctypes import wintypes
        self.initialize()
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        descriptor = ctypes.c_void_p()
        self.assertTrue(advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{keys._sid()})(A;OICI;FR;;;WD)", 1, ctypes.byref(descriptor), None))
        try:
            self.assertTrue(advapi.SetFileSecurityW(str(self.store), 0x80000004, descriptor))
        finally:
            kernel.LocalFree(descriptor)
        with self.assertRaisesRegex(keys.KeyStoreError, "permissions"):
            keys.ensure_keys(self.store)
        with self.assertRaisesRegex(keys.KeyStoreError, "permissions"):
            keys._acl(self.store, keys._sid())

    def test_hardlinked_key_file_is_rejected(self):
        self.initialize()
        os.link(self.store / keys.PUBLIC_FILE, Path(self.temporary.name) / "public-alias.pem")
        with self.assertRaisesRegex(keys.KeyStoreError, "unsafe"):
            keys.key_status(self.store)

    def test_empty_existing_directory_is_not_initialized(self):
        self.store.mkdir()
        keys._acl(self.store, keys._sid(), set_private=True)
        with self.assertRaisesRegex(keys.KeyStoreError, "incomplete"):
            keys.ensure_keys(self.store)
        self.assertFalse((self.store / keys.PRIVATE_FILE).exists())


if __name__ == "__main__":
    unittest.main()
