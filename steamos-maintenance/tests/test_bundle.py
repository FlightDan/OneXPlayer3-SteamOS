import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import build_bundle as builder
from oxp3_maintenance import bundle as b

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None


class BundleTests(unittest.TestCase):
    """Use real OpenSSL when present; a cryptographic test adapter otherwise.

    The fallback exercises the exact pkey/pkeyutl argument contract and real
    Ed25519 signing/verification, without shipping a production dependency.
    """
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.key = self.root / "publisher-private.pem"
        self.public = self.root / "publisher-public.pem"
        self.openssl = shutil.which("openssl")
        if self.openssl:
            subprocess.run([self.openssl, "genpkey", "-algorithm", "ED25519", "-out", str(self.key)], check=True, capture_output=True)
            subprocess.run([self.openssl, "pkey", "-in", str(self.key), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        elif Ed25519PrivateKey is not None:
            key = Ed25519PrivateKey.generate()
            self.key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            self.public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
            self.openssl = "test-openssl-adapter"
            patch = mock.patch("subprocess.run", side_effect=self._openssl_adapter)
            patch.start()
            self.addCleanup(patch.stop)
        else:
            self.skipTest("OpenSSL CLI (or cryptography for the test-only adapter) is required")
        self.source, self.payload = self.root / "source", self.root / "payload"
        (self.source / "oxp3_maintenance").mkdir(parents=True)
        (self.payload / "components").mkdir(parents=True)
        (self.source / "oxp3_maintenance" / "__init__.py").write_text("raise RuntimeError('must never import bundle code')\n", encoding="utf-8")
        (self.source / "trusted-public-key.pem").write_bytes(self.public.read_bytes())
        for name in builder.LAUNCHERS:
            (self.source / name).write_text("#!/bin/sh\n# test launcher\n", encoding="utf-8")
        (self.payload / "components" / "release.json").write_text(json.dumps({"version": "1.2.3", "display_version": "OXP3 1.2.3", "channel": "stable", "notes": "Release notes"}), encoding="utf-8")
        self.archive = self.root / "release.tar.gz"

    def _openssl_adapter(self, args, **kwargs):
        self.assertTrue(kwargs.get("capture_output"))
        self.assertEqual(kwargs.get("timeout"), 30)
        def argument(flag):
            return args[args.index(flag) + 1]
        try:
            if args[1] == "pkey":
                self.assertEqual(argument("-outform"), "DER")
                raw = Path(argument("-in")).read_bytes()
                if "-pubin" in args:
                    key = serialization.load_pem_public_key(raw)
                else:
                    self.assertIn("-pubout", args)
                    key = serialization.load_pem_private_key(raw, password=None).public_key()
                output = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            else:
                self.assertEqual(args[1], "pkeyutl")
                self.assertIn("-rawin", args)
                data = Path(argument("-in")).read_bytes()
                raw_key = Path(argument("-inkey")).read_bytes()
                if "-verify" in args:
                    self.assertIn("-pubin", args)
                    key = serialization.load_pem_public_key(raw_key)
                    key.verify(Path(argument("-sigfile")).read_bytes(), data)
                else:
                    self.assertIn("-sign", args)
                    key = serialization.load_pem_private_key(raw_key, password=None)
                    Path(argument("-out")).write_bytes(key.sign(data))
                output = b""
            return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b"")
        except (ValueError, InvalidSignature):
            return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"signature failed")

    def _build(self, output=None):
        return builder.build_bundle(self.payload, self.source, self.key, output or self.archive, openssl=self.openssl)

    def _destination(self, name="private"):
        path = self.root / name
        path.mkdir(mode=0o700)
        return path

    def _sign(self, raw):
        source, signature = self.root / "raw-manifest", self.root / "raw-signature"
        source.write_bytes(raw)
        builder._run([self.openssl, "pkeyutl", "-sign", "-inkey", str(self.key), "-rawin", "-in", str(source), "-out", str(signature)])
        return base64.b64encode(signature.read_bytes())

    def _custom(self, *, changes=None, extra=None, member_type=None, name="payload/components/release.json", signature=None, raw=None, format=tarfile.USTAR_FORMAT):
        contents = {"app/oxp3_maintenance/__init__.py": b"print('untrusted')\n", name: b"{}"}
        files = {path: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": 0o644} for path, data in contents.items()}
        manifest = {"schema": 1, "release": {"version": "1.2.3", "display_version": "1.2.3", "channel": "stable"}, "files": files, "notes": ""}
        if changes:
            changes(manifest, contents)
        raw = raw if raw is not None else json.dumps(manifest).encode()
        signature = self._sign(raw) if signature is None else signature
        with tarfile.open(self.archive, "w:gz", format=format) as archive:
            for path, data in {"manifest.json": raw, "manifest.sig": signature, **contents}.items():
                info = tarfile.TarInfo(path)
                info.size, info.mode = len(data), 0o644
                if member_type is not None and path == name:
                    info.type, info.linkname, info.size = member_type, "../../escape", 0
                archive.addfile(info, io.BytesIO(data))
            if extra is not None:
                info = tarfile.TarInfo(extra)
                info.size, info.mode = 1, 0o644
                archive.addfile(info, io.BytesIO(b"x"))
        return manifest

    def test_signed_builder_roundtrip_and_no_code_execution(self):
        manifest = self._build()
        self.assertEqual(b.inspect_bundle(self.archive, self.public, openssl=self.openssl), manifest)
        destination = self._destination()
        self.assertEqual(b.verify_bundle(self.archive, self.public, destination, openssl=self.openssl), manifest)
        self.assertTrue((destination / "app/entry.py").is_file())
        self.assertTrue((destination / "payload/components/release.json").is_file())

    def test_reproducible_ordered_archive(self):
        self._build()
        second = self.root / "second.tar.gz"
        self._build(second)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())
        with tarfile.open(self.archive) as archive:
            names = archive.getnames()
        self.assertEqual(names[2:], sorted(names[2:]))

    def test_builder_excludes_private_caches_credentials(self):
        (self.source / ".env").write_text("TOKEN=secret")
        (self.source / "oxp3_maintenance/__pycache__").mkdir()
        (self.source / "oxp3_maintenance/__pycache__/cached.pyc").write_bytes(b"cache")
        (self.payload / "components/.aws").mkdir()
        (self.payload / "components/.aws/credentials").write_text("secret")
        (self.payload / "components/credentials.json").write_text("secret")
        (self.payload / "components/private.pem").write_bytes(self.key.read_bytes())
        (self.payload / "cache").mkdir()
        (self.payload / "cache/secret").write_text("secret")
        files = self._build()["files"]
        self.assertFalse(any("cache" in path or "credentials" in path or "private.pem" in path or ".env" in path for path in files))
        with tarfile.open(self.archive) as archive:
            self.assertFalse(any(self.key.read_bytes() in archive.extractfile(member).read() for member in archive))

    def test_builder_preserves_prepared_runtime_dist_but_excludes_source_and_private_trees(self):
        runtime = {
            'components/windows-reboot/dist/index.js': b'Windows restart frontend',
            'components/opti2xmx/dist/index.js': b'Opti2XMX frontend',
            'plugins/example/dist/index.js': b'Prepared plugin frontend',
        }
        excluded_payload = {
            'components/windows-reboot/dist/cache/cached.js': b'cached',
            'components/windows-reboot/dist/credentials.json': b'private',
            'components/windows-reboot/dist/signing.key': self.key.read_bytes(),
            'components/windows-reboot/dist/.private/secret.js': b'private',
            'components/windows-reboot/dist/node_modules/dependency/index.js': b'dependency',
            'dist/unselected/index.js': b'outside explicit payload trees',
        }
        for relative, raw in {**runtime, **excluded_payload}.items():
            path = self.payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        for relative in ('dist/built.py', 'cache/cached.py', 'credentials/private.py'):
            path = self.source / 'oxp3_maintenance' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("raise RuntimeError('excluded source artifact')\n")
        manifest = self._build()
        self.assertEqual(b.inspect_bundle(self.archive, self.public, openssl=self.openssl), manifest)
        expected = {'payload/' + name for name in runtime}
        self.assertTrue(expected.issubset(manifest['files']))
        self.assertTrue(all('payload/' + name not in manifest['files'] for name in excluded_payload))
        self.assertFalse(any(name.startswith(('app/oxp3_maintenance/dist/',
            'app/oxp3_maintenance/cache/', 'app/oxp3_maintenance/credentials/')) for name in manifest['files']))
        with tarfile.open(self.archive) as archive:
            for relative, raw in runtime.items():
                self.assertEqual(archive.extractfile('payload/' + relative).read(), raw)

    def test_builder_requires_release_metadata_and_real_trust_anchor(self):
        (self.payload / "components/release.json").unlink()
        with self.assertRaisesRegex(b.BundleError, "actual components/release.json"):
            self._build()
        self.assertFalse(self.archive.exists())

    def test_builder_rejects_private_key_inside_source(self):
        inside = self.source / "private.pem"
        inside.write_bytes(self.key.read_bytes())
        with self.assertRaisesRegex(b.BundleError, "outside"):
            builder.build_bundle(self.payload, self.source, inside, self.archive, openssl=self.openssl)

    def test_builder_rejects_mismatched_public_key(self):
        (self.source / "trusted-public-key.pem").write_text("not a public key")
        with self.assertRaises(b.BundleError):
            self._build()

    def test_signature_tamper_and_missing_key_fail_closed(self):
        self._custom(signature=base64.b64encode(b"\0" * 64))
        with self.assertRaisesRegex(b.BundleError, "signature is invalid"):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)
        with self.assertRaisesRegex(b.BundleError, "Updates are disabled"):
            b.inspect_bundle(self.archive, self.root / "missing.pem", openssl=self.openssl)
        self.public.write_bytes(b"not an Ed25519 key")
        with self.assertRaisesRegex(b.BundleError, "Ed25519 public PEM"):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_posix_openssl_has_system_search_path_and_no_injected_config(self):
        with mock.patch.dict(os.environ, {"PATH": "/tmp/user-bin", "LD_PRELOAD": "injected.so", "OPENSSL_CONF": "/tmp/injected.cnf", "OPENSSL_MODULES": "/tmp/modules"}):
            with mock.patch.object(os, "name", "posix"):
                environment = b._openssl_environment()
        self.assertEqual(environment, {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})

    def test_hash_mismatch_unlisted_missing_duplicate_members(self):
        for changes, extra in [(lambda m, c: c.update({"payload/components/release.json": b"changed"}), None), (None, "payload/components/extra"), (lambda m, c: c.pop("payload/components/release.json"), None), (None, "app/oxp3_maintenance/__init__.py")]:
            with self.subTest(extra=extra):
                self._custom(changes=changes, extra=extra)
                with self.assertRaises(b.BundleError):
                    b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_unsafe_paths_links_and_extended_headers(self):
        for name in ["../escape", "/absolute", "payload/../escape", "payload//escape", "payload/./escape", "payload\\escape", "C:/escape", "unlisted/file"]:
            with self.subTest(name=name):
                self._custom(name=name)
                with self.assertRaises(b.BundleError):
                    b.inspect_bundle(self.archive, self.public, openssl=self.openssl)
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE]:
            self._custom(member_type=kind)
            with self.assertRaises(b.BundleError):
                b.inspect_bundle(self.archive, self.public, openssl=self.openssl)
        self._custom(name="payload/" + "a" * 200, format=tarfile.GNU_FORMAT)
        with self.assertRaisesRegex(b.BundleError, "unsupported"):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_archive_bomb_limits_and_truncation(self):
        self._custom()
        for constant, value in [("MAX_FILES", 1), ("MAX_CONTENT_BYTES", 1), ("MAX_ARCHIVE_BYTES", 1), ("MAX_MANIFEST_BYTES", 1), ("MAX_PATH_BYTES", 5)]:
            with self.subTest(constant=constant), mock.patch.object(b, constant, value):
                with self.assertRaises(b.BundleError):
                    b.inspect_bundle(self.archive, self.public, openssl=self.openssl)
        raw = self.archive.read_bytes()
        self.archive.write_bytes(raw[:len(raw)//2])
        with self.assertRaises(b.BundleError):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_trailing_archive_data_rejected(self):
        self._custom()
        self.archive.write_bytes(self.archive.read_bytes() + gzip.compress(b"hidden data"))
        with self.assertRaisesRegex(b.BundleError, "trailing"):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_duplicate_json_keys_rejected_even_when_signed(self):
        self._custom(raw=b'{"schema":1,"schema":1}')
        with self.assertRaisesRegex(b.BundleError, "duplicate JSON"):
            b.inspect_bundle(self.archive, self.public, openssl=self.openssl)

    def test_destination_must_be_empty_and_no_failed_extraction(self):
        self._build()
        destination = self._destination()
        (destination / "owned").write_text("preserve")
        with self.assertRaises(b.BundleError):
            b.verify_bundle(self.archive, self.public, destination, openssl=self.openssl)
        self.assertEqual((destination / "owned").read_text(), "preserve")
        (destination / "owned").unlink()
        self._custom(signature=base64.b64encode(b"\0" * 64))
        with self.assertRaises(b.BundleError):
            b.verify_bundle(self.archive, self.public, destination, openssl=self.openssl)
        self.assertEqual(list(destination.iterdir()), [])

    def test_offline_directory_copy_hash_membership_and_symlink_checks(self):
        self._build()
        unpacked = self._destination("offline")
        # Test fixture archive is trusted here; production never uses extractall.
        with tarfile.open(self.archive) as archive:
            archive.extractall(unpacked, filter="data")
        destination = self._destination()
        result = b.verify_directory(unpacked, self.public, destination, openssl=self.openssl)
        self.assertEqual(result["release"]["version"], "1.2.3")
        shutil.rmtree(destination)
        destination.mkdir(mode=0o700)
        (unpacked / "payload/components/release.json").write_bytes(b"tampered")
        with self.assertRaises(b.BundleError):
            b.verify_directory(unpacked, self.public, destination, openssl=self.openssl)
        self.assertEqual(list(destination.iterdir()), [])
        (unpacked / "extra").write_text("not in manifest")
        with self.assertRaises(b.BundleError):
            b.verify_directory(unpacked, self.public, destination, openssl=self.openssl)

    def test_offline_hardlinks_and_symlinks_rejected(self):
        self._build()
        unpacked = self._destination("offline")
        with tarfile.open(self.archive) as archive:
            archive.extractall(unpacked, filter="data")
        destination = self._destination()
        target = unpacked / "app/entry.py"
        saved = self.root / "hardlink"
        os.link(target, saved)
        with self.assertRaisesRegex(b.BundleError, "link"):
            b.verify_directory(unpacked, self.public, destination, openssl=self.openssl)
        saved.unlink()
        try:
            (unpacked / "app/link").symlink_to(target)
        except OSError:
            return  # Windows may not permit symlink creation for test fixtures.
        with self.assertRaisesRegex(b.BundleError, "link"):
            b.verify_directory(unpacked, self.public, destination, openssl=self.openssl)
        self.assertEqual(list(destination.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
