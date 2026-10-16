#!/usr/bin/env python3
"""Build a reproducible Ed25519-signed maintenance release.

--payload is an explicitly prepared Linux payload with components/release.json
and optional integration/, plugins/, waydroid/, hdr/, controls/, licenses/ trees.
Windows installer cache/runtime folders are never copied implicitly. Provision
source/trusted-public-key.pem from the publisher's real key; private keys belong
outside all input trees. This command does not create release versions or keys.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile

from oxp3_maintenance.bundle import (
    BundleError, MAX_ARCHIVE_BYTES, MAX_CONTENT_BYTES, MAX_FILES, _path,
    inspect_bundle, _openssl_environment,
)
from oxp3_maintenance.releases import _Version

PAYLOAD_TREES = ("components", "integration", "plugins", "waydroid", "hdr", "controls", "licenses")
LAUNCHERS = ("entry.py", "oxp3-maintenance.sh", "OXP3-Maintenance.desktop", "Install-OXP3-Maintenance.desktop")
_IGNORED = {"__pycache__", "node_modules", "cache", "logs", "work", "dist", "build", "credentials.json", "credentials", "token", "tokens", "secrets"}


def _run(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=30, check=False, env=_openssl_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleError("Could not run OpenSSL for release signing.") from exc
    if result.returncode:
        raise BundleError("OpenSSL rejected the release signing key or signing operation.")
    return result.stdout


def _allowed(path, *, payload=False):
    ignored = _IGNORED - {'dist'} if payload else _IGNORED
    return not any(part.startswith(".") or part.lower() in ignored for part in path.parts) and path.suffix.lower() not in {".pyc", ".pyo", ".key", ".pem", ".p12", ".pfx"}


def _collect_tree(root, prefix, *, python_only=False, payload=False):
    result = {}
    if not root.is_dir() or root.is_symlink():
        raise BundleError("Prepared bundle input directory is unavailable or a symlink: " + str(root))
    for parent, directories, filenames in os.walk(root, followlinks=False):
        for directory in directories:
            if (Path(parent) / directory).is_symlink():
                raise BundleError("Prepared bundle input contains a symlink.")
        directories[:] = sorted(d for d in directories if _allowed((Path(parent) / d).relative_to(root), payload=payload))
        for filename in sorted(filenames):
            path = Path(parent) / filename
            relative = path.relative_to(root)
            if not _allowed(relative, payload=payload) or (python_only and path.suffix != ".py"):
                continue
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                raise BundleError("Prepared bundle input contains a link or special file.")
            result[prefix + "/" + relative.as_posix()] = path
    return result


def _metadata(payload):
    path = payload / "components" / "release.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise BundleError("Prepared payload must include its actual components/release.json; no release metadata is fabricated.")
    try:
        release = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(release, dict):
            raise ValueError()
        version = _Version(release["version"])
        if release.get("channel") not in ("stable", "beta"):
            raise ValueError()
        if release["channel"] == "stable" and version.pre:
            raise ValueError()
        if version.pre and version.pre[0] != "beta":
            raise ValueError()
        if not isinstance(release.get("display_version"), str) or not release["display_version"]:
            raise ValueError()
        if not isinstance(release.get("notes", ""), str):
            raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise BundleError("components/release.json must contain SemVer version, display_version, and stable/beta channel.") from exc
    if version.text != release["version"]:
        raise BundleError("components/release.json version must be SemVer without a leading v.")
    return release


def build_bundle(payload: Path, source: Path, private_key: Path, output: Path, *, openssl="openssl") -> dict:
    """Sign only explicit app/runtime files and verify the completed archive."""
    payload, source, private_key, output = map(Path, (payload, source, private_key, output))
    release = _metadata(payload)
    trusted = source / "trusted-public-key.pem"
    if trusted.is_symlink() or not trusted.is_file():
        raise BundleError("Provision source/trusted-public-key.pem from the publisher before building a release.")
    if not private_key.is_file():
        raise BundleError("Publisher private signing key is unavailable.")
    for root in (source, payload):
        if private_key.resolve().is_relative_to(root.resolve()):
            raise BundleError("Keep the private signing key outside all bundle input directories.")
        if output.resolve().is_relative_to(root.resolve()):
            raise BundleError("Bundle output must be outside all bundle input directories.")
    public_der = _run([str(openssl), "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"])
    trusted_der = _run([str(openssl), "pkey", "-pubin", "-in", str(trusted), "-outform", "DER"])
    if (public_der != trusted_der or len(public_der) != 44
            or not public_der.startswith(bytes.fromhex("302a300506032b6570032100"))):
        raise BundleError("Signing key must be Ed25519 and match source/trusted-public-key.pem.")
    inputs = _collect_tree(source / "oxp3_maintenance", "app/oxp3_maintenance", python_only=True)
    if not inputs:
        raise BundleError("Maintenance Python package is missing.")
    for name in LAUNCHERS:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise BundleError("Maintenance launcher is missing: " + name)
        inputs["app/" + name] = path
    inputs["app/trusted-public-key.pem"] = trusted
    for name in ('README.md', 'VALIDATION.md'):
        path = source / name
        if path.is_file() and not path.is_symlink():
            inputs['app/' + name] = path
    for name in PAYLOAD_TREES:
        root = payload / name
        if root.exists():
            inputs.update(_collect_tree(root, "payload/" + name, payload=True))
    if len(inputs) > MAX_FILES:
        raise BundleError("Prepared payload contains too many files.")
    records, total = {}, 0
    # Snapshot content before signing so source changes cannot create invalid releases.
    # Disk staging avoids keeping firmware/plugin payloads in process memory.
    with tempfile.TemporaryDirectory(prefix="oxp3-publish-") as directory:
        staging = Path(directory)
        for index, (name, path) in enumerate(sorted(inputs.items())):
            _path(name)
            info = path.stat()
            total += info.st_size
            if total > MAX_CONTENT_BYTES:
                raise BundleError("Prepared payload exceeds the size limit.")
            mode = 0o755 if path.suffix == ".sh" or path.name == "PluginLoader" or (os.name == "posix" and info.st_mode & 0o111) else 0o644
            digest, count = hashlib.sha256(), 0
            with path.open("rb") as stream, (staging / str(index)).open("wb") as target:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    # Do not accidentally package credential/key files disguised by extension.
                    if b"-----BEGIN PRIVATE KEY-----" in chunk or b"-----BEGIN OPENSSH PRIVATE KEY-----" in chunk or b"-----BEGIN RSA PRIVATE KEY-----" in chunk:
                        raise BundleError("Prepared inputs contain private key material.")
                    count += len(chunk)
                    if count > info.st_size:
                        raise BundleError("Prepared input changed during the build.")
                    digest.update(chunk)
                    target.write(chunk)
            if count != info.st_size:
                raise BundleError("Prepared input changed during the build.")
            records[name] = {"sha256": digest.hexdigest(), "size": count, "mode": mode}
        manifest = {"schema": 1, "release": release, "files": records, "notes": release.get("notes", "")}
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        manifest_path, signature_path = staging / "manifest.json", staging / "signature"
        manifest_path.write_bytes(raw)
        _run([str(openssl), "pkeyutl", "-sign", "-inkey", str(private_key), "-rawin", "-in", str(manifest_path), "-out", str(signature_path)])
        signature = signature_path.read_bytes()
        if len(signature) != 64:
            raise BundleError("Publisher key did not produce an Ed25519 signature.")
        created = False
        try:
            with output.open("xb") as file:
                created = True
                with gzip.GzipFile(fileobj=file, mode="wb", filename="", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                        for name, content in (("manifest.json", raw), ("manifest.sig", base64.b64encode(signature) + b"\n")):
                            entry = tarfile.TarInfo(name)
                            entry.size, entry.mode, entry.mtime = len(content), 0o644, 0
                            archive.addfile(entry, io.BytesIO(content))
                        for index, (name, metadata) in enumerate(sorted(records.items())):
                            entry = tarfile.TarInfo(name)
                            entry.size, entry.mode, entry.mtime = metadata["size"], metadata["mode"], 0
                            with (staging / str(index)).open("rb") as content:
                                archive.addfile(entry, content)
            if output.stat().st_size > MAX_ARCHIVE_BYTES:
                raise BundleError("Compressed release exceeds the archive size limit.")
            inspect_bundle(output, trusted, openssl=openssl)
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args(argv)
    try:
        manifest = build_bundle(args.payload, args.source, args.private_key, args.output, openssl=args.openssl)
        write_catalog(args.payload, manifest, args.output, args.private_key, openssl=args.openssl)
    except (BundleError, OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, "Release build failed: %s\n" % exc)
    print("Built signed maintenance release %s: %s" % (manifest["release"]["version"], args.output))
    return 0


def write_catalog(payload, manifest, archive, private_key, *, openssl='openssl'):
    from oxp3_maintenance.catalog import create, canonical, names, verify
    value = create(payload, manifest, archive)
    raw = canonical(value)
    catalog_name, signature_name = names(manifest['release']['version'])
    parent = Path(archive).parent
    outputs = [parent / catalog_name, parent / signature_name]
    if any(path.exists() for path in outputs):
        raise BundleError('Capability catalog output already exists')
    with tempfile.TemporaryDirectory(prefix='oxp3-catalog-sign-') as directory:
        source, signature = Path(directory) / 'catalog', Path(directory) / 'signature'
        source.write_bytes(raw)
        _run([str(openssl), 'pkeyutl', '-sign', '-inkey', str(private_key), '-rawin', '-in', str(source), '-out', str(signature)])
        encoded = base64.b64encode(signature.read_bytes()) + b'\n'
        # The public key has already been checked against the private key by build_bundle.
        key = Path(directory) / 'public.pem'
        public_der = _run([str(openssl), 'pkey', '-in', str(private_key), '-pubout', '-outform', 'DER'])
        key.write_bytes(b'-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(public_der) + b'\n-----END PUBLIC KEY-----\n')
        verify(raw, encoded, key, expected_version=manifest['release']['version'], openssl=openssl)
        created = []
        try:
            for path, content in zip(outputs, (raw, encoded)):
                with path.open('xb') as file:
                    created.append(path)
                    file.write(content)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
    return value


if __name__ == "__main__":
    sys.exit(main())
