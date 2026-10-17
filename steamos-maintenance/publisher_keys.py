"""Windows publisher identity: Ed25519, CurrentUser DPAPI, and private ACLs.

Initialization is explicit. The store is intentionally non-recovering: incomplete
state, unexpected files, or plaintext left by a crashed signer need investigation.
The encrypted blob requires this Windows account/profile; back it up accordingly.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


DEFAULT_STORE = Path(__file__).resolve().parent.parent / ".release-private" / "maintenance-ed25519"
PUBLIC_FILE = "public.pem"
PRIVATE_FILE = "private.dpapi"
METADATA_FILE = "identity.json"
_FILES = {PUBLIC_FILE, PRIVATE_FILE, METADATA_FILE, ".lock"}
_ED25519_SPKI = bytes.fromhex("302a300506032b6570032100")


class KeyStoreError(RuntimeError):
    """An unusable key store; messages never include private key material."""


def _windows() -> None:
    if os.name != "nt":
        raise KeyStoreError("Publisher key storage requires Windows CurrentUser DPAPI.")


def _run(openssl: str, args: list[str], data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run([openssl, *args], input=data, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeyStoreError("Cannot execute the supplied OpenSSL executable.") from exc
    if result.returncode:
        raise KeyStoreError("OpenSSL key operation failed.")
    return result.stdout


def _sid() -> str:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise KeyStoreError("Cannot read the current Windows identity.")
    try:
        length = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise KeyStoreError("Cannot read the current Windows identity.")
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise KeyStoreError("Cannot read the current Windows identity.")
        try:
            return sid_text.value
        finally:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def _acl(path: Path, sid: str, *, set_private: bool = False) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    flags = "OICI" if path.is_dir() else ""
    expected_sddl = f"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;{sid})"
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(expected_sddl, 1, ctypes.byref(descriptor), None):
        raise KeyStoreError("Cannot construct private Windows permissions.")
    normalized = wintypes.LPWSTR()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(normalized), None):
            raise KeyStoreError("Cannot construct private Windows permissions.")
        expected_sddl = normalized.value
        if set_private:
            if not advapi.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise KeyStoreError("Cannot secure the publisher key store.")
    finally:
        if normalized:
            kernel.LocalFree(ctypes.cast(normalized, ctypes.c_void_p))
        kernel.LocalFree(descriptor)
    descriptor = ctypes.c_void_p()
    if advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor)):
        raise KeyStoreError("Cannot inspect publisher key permissions.")
    output = wintypes.LPWSTR()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(output), None):
            raise KeyStoreError("Cannot inspect publisher key permissions.")
        sddl = output.value
    finally:
        if output:
            kernel.LocalFree(ctypes.cast(output, ctypes.c_void_p))
        kernel.LocalFree(descriptor)
    # Accept only our two explicit, full-control allow entries. Never repair an
    # existing ACL silently: that could conceal a previously exposed identity.
    prefix, *aces = sddl.split("(")
    expected_prefix, *expected = expected_sddl.split("(")
    if prefix != expected_prefix or len(aces) != 2 or set(aces) != set(expected):
        raise KeyStoreError("Publisher key permissions are not restricted to this account and SYSTEM.")


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    if decrypt:
        operation = crypt.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        ok = operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        operation = crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        ok = operation(ctypes.byref(source), "SteamOS maintenance publisher Ed25519", None, None, None, 1, ctypes.byref(target))
    try:
        if not ok:
            raise KeyStoreError("Windows CurrentUser DPAPI could not unlock the publisher identity." if decrypt else "Windows CurrentUser DPAPI could not protect the publisher identity.")
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(source_buffer, 0, len(data))
        if target.data:
            ctypes.memset(target.data, 0, target.size)
            kernel.LocalFree(target.data)


def _safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for component in reversed((path, *path.parents)):
        if component.exists() or component.is_symlink():
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise KeyStoreError("Publisher key paths must not contain symlinks or Windows reparse points.")
    return path


def _inspect(store: Path, sid: str) -> None:
    _safe_path(store)
    if not store.is_dir():
        raise KeyStoreError("Publisher key store is not a directory.")
    _acl(store, sid)
    for item in store.iterdir():
        _safe_path(item)
        if item.name not in _FILES or not item.is_file() or item.stat().st_nlink != 1:
            raise KeyStoreError("Publisher key store contains unexpected or unsafe files; investigate incomplete initialization or a crashed signer.")
        _acl(item, sid)


@contextmanager
def _locked(store: Path, sid: str):
    import msvcrt
    path = store / ".lock"
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _safe_path(path)
        _acl(path, sid)
        descriptor = os.open(path, os.O_RDWR)
    else:
        try:
            _acl(path, sid, set_private=True)
            os.write(descriptor, b"0")
        except BaseException:
            os.close(descriptor)
            raise
    try:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise KeyStoreError("Publisher key store is busy in another process.") from exc
        try:
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(descriptor)


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise KeyStoreError("Install cryptography or supply an OpenSSL executable.") from exc
    return serialization, Ed25519PrivateKey


def _generate(openssl: str | None) -> bytes:
    if openssl:
        return _run(openssl, ["genpkey", "-algorithm", "ED25519"])
    serialization, key_type = _crypto()
    return key_type.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _public(private: bytes, openssl: str | None) -> tuple[bytes, str]:
    if openssl:
        public = _run(openssl, ["pkey", "-pubout", "-outform", "PEM"], private)
        der = _run(openssl, ["pkey", "-pubin", "-outform", "DER"], public)
    else:
        serialization, key_type = _crypto()
        try:
            key = serialization.load_pem_private_key(private, password=None)
            if not isinstance(key, key_type):
                raise KeyStoreError("Publisher identity must be an Ed25519 key.")
            public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        except (ValueError, TypeError) as exc:
            raise KeyStoreError("Publisher private key is invalid.") from exc
    if len(der) != 44 or not der.startswith(_ED25519_SPKI):
        raise KeyStoreError("Publisher identity must be an Ed25519 key.")
    return public.replace(b"\r\n", b"\n"), "sha256:" + hashlib.sha256(der).hexdigest()


def _load(store: Path, sid: str, openssl: str | None) -> tuple[dict, bytes]:
    _inspect(store, sid)
    if {p.name for p in store.iterdir()} != _FILES:
        raise KeyStoreError("Publisher key store is incomplete; refusing to generate a replacement identity.")
    try:
        metadata = json.loads((store / METADATA_FILE).read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError()
        private = _dpapi((store / PRIVATE_FILE).read_bytes(), decrypt=True)
        public, fingerprint = _public(private, openssl)
        expected = {"version": 1, "algorithm": "Ed25519", "protection": "Windows-DPAPI-CurrentUser", "sid": sid, "fingerprint": fingerprint}
        if metadata != expected or (store / PUBLIC_FILE).read_bytes() != public:
            raise KeyStoreError("Publisher key metadata or public/private identity does not match.")
        return expected, private
    except (OSError, ValueError, UnicodeError) as exc:
        raise KeyStoreError("Publisher key store is corrupt or unreadable.") from exc


def _status(store: Path, metadata: dict) -> dict:
    return {"status": "ready", "store": str(store), "public_key": str(store / PUBLIC_FILE), "fingerprint_sha256": metadata["fingerprint"].removeprefix("sha256:"), **metadata}


def _write(store: Path, name: str, data: bytes, sid: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=store)
    temp = Path(temporary)
    try:
        _acl(temp, sid, set_private=True)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, store / name)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temp.unlink(missing_ok=True)


def ensure_keys(store: Path = DEFAULT_STORE, *, openssl: str | None = None) -> dict:
    """Explicitly initialize a new store, or validate its existing identity."""
    _windows()
    store = _safe_path(store)
    sid = _sid()
    store.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(store)
    try:
        store.mkdir()
    except FileExistsError:
        _inspect(store, sid)
        created = False
    else:
        _acl(store, sid, set_private=True)
        created = True
    with _locked(store, sid):
        if not created:
            metadata, _ = _load(store, sid, openssl)
            return _status(store, metadata)
        private = _generate(openssl)
        public, fingerprint = _public(private, openssl)
        metadata = {"version": 1, "algorithm": "Ed25519", "protection": "Windows-DPAPI-CurrentUser", "sid": sid, "fingerprint": fingerprint}
        protected = _dpapi(private, decrypt=False)
        _write(store, PRIVATE_FILE, protected, sid)
        _write(store, PUBLIC_FILE, public, sid)
        _write(store, METADATA_FILE, (json.dumps(metadata, indent=2) + "\n").encode(), sid)
        verified, _ = _load(store, sid, openssl)
        return _status(store, verified)


def key_status(store: Path = DEFAULT_STORE, *, openssl: str | None = None) -> dict:
    """Read-only status. Absence never initializes a key or even a directory."""
    _windows()
    store = _safe_path(store)
    if not store.exists():
        return {"status": "missing", "store": str(store)}
    sid = _sid()
    _inspect(store, sid)
    if not (store / ".lock").exists():
        raise KeyStoreError("Publisher key store is incomplete.")
    with _locked(store, sid):
        metadata, _ = _load(store, sid, openssl)
        return _status(store, metadata)


@contextmanager
def signing_key(store: Path = DEFAULT_STORE, *, openssl: str | None = None):
    """Yield a temporary PEM path under the store ACL; remove it on every exit.

    The exclusive lock remains held until the caller finishes signing. An abrupt
    process/OS exit can leave a PEM, which subsequent operations reject explicitly.
    """
    _windows()
    store = _safe_path(store)
    sid = _sid()
    _inspect(store, sid)
    if not (store / ".lock").exists():
        raise KeyStoreError("Publisher key store is incomplete.")
    with _locked(store, sid):
        _, private = _load(store, sid, openssl)
        descriptor, temporary = tempfile.mkstemp(prefix="signing-", suffix=".pem", dir=store)
        path = Path(temporary)
        try:
            _acl(path, sid, set_private=True)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(private)
                stream.flush()
                os.fsync(stream.fileno())
            yield path
        finally:
            if descriptor != -1:
                os.close(descriptor)
            path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "init"), nargs="?", default="status")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--openssl", help="Optional OpenSSL executable; otherwise use Python cryptography.")
    args = parser.parse_args(argv)
    try:
        result = (ensure_keys if args.action == "init" else key_status)(args.store, openssl=args.openssl)
    except KeyStoreError as exc:
        parser.exit(1, f"Publisher keys: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
