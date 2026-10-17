"""Verify publisher-signed maintenance bundles without importing their contents.

The caller supplies a locally installed, pinned Ed25519 public key. A privileged
caller must first copy the archive to its own private directory, then call this
module again on that copy. No system trust store or network key is consulted.
"""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile


class BundleError(Exception):
    """An unauthenticated, invalid, or unsafe maintenance bundle."""


MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_CONTENT_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 20000
MAX_PATH_BYTES = 512
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SIGNATURE_BYTES = 256
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z")


def _openssl_environment():
    # Never let desktop OPENSSL_CONF, OPENSSL_MODULES, LD_PRELOAD, or a user
    # executable search path affect a privileged signature verification.
    if os.name == "posix":
        return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
    result = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
    result["LC_ALL"] = "C"
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("Bundle manifest contains duplicate JSON keys.")
        result[key] = value
    return result


def _path(name):
    if (not isinstance(name, str) or not name or len(name.encode("utf-8")) > MAX_PATH_BYTES
            or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)
            or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/"))):
        raise BundleError("Bundle contains an unsafe file path.")
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or parts[0] not in ("app", "payload"):
        raise BundleError("Bundle file is outside app/ or payload/.")
    return name


def _verify_signature(raw, signature, public_key, openssl):
    key = Path(public_key)
    if not key.is_file():
        raise BundleError("Trusted maintenance signing key is unavailable. Updates are disabled.")
    try:
        with _regular_input(key, 8192) as stream:
            key_bytes = stream.read(8193)
        encoded = re.fullmatch(rb"\s*-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*", key_bytes)
        public_der = base64.b64decode(re.sub(rb"\s", b"", encoded.group(1)), validate=True) if encoded else b""
        if len(public_der) != 44 or not public_der.startswith(bytes.fromhex("302a300506032b6570032100")):
            raise BundleError("Trusted maintenance signing key must be an Ed25519 public PEM key.")
    except (OSError, ValueError, binascii.Error) as exc:
        raise BundleError("Trusted maintenance signing key could not be read safely.") from exc
    try:
        decoded = base64.b64decode(signature.strip(), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BundleError("Bundle signature is malformed.") from exc
    if len(decoded) != 64:
        raise BundleError("Bundle signature is not an Ed25519 signature.")
    try:
        with tempfile.TemporaryDirectory(prefix="oxp3-signature-") as directory:
            root = Path(directory)
            (root / "manifest").write_bytes(raw)
            (root / "signature").write_bytes(decoded)
            (root / "public.pem").write_bytes(key_bytes)
            result = subprocess.run(
                [str(openssl), "pkeyutl", "-verify", "-pubin", "-inkey", str(root / "public.pem"),
                 "-rawin", "-in", str(root / "manifest"), "-sigfile", str(root / "signature")],
                capture_output=True, timeout=30, check=False, env=_openssl_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleError("Could not verify bundle signature using OpenSSL.") from exc
    if result.returncode:
        raise BundleError("Bundle publisher signature is invalid.")


class _LimitedReader:
    def __init__(self, stream, limit=None):
        self.stream = stream
        self.count = 0
        self.limit = limit if limit is not None else MAX_CONTENT_BYTES + MAX_FILES * 4096 + MAX_MANIFEST_BYTES

    def read(self, size=-1):
        # Bound decompression including tar padding, metadata, and trailing data.
        limit = self.limit
        if size < 0:
            size = 1024 * 1024
        data = self.stream.read(min(size, limit - self.count + 1))
        self.count += len(data)
        if self.count > limit:
            raise BundleError("Bundle exceeds the stream size limit.")
        return data


class _StrictTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        # Reject extended headers before tarfile reads their attacker-sized
        # bodies into memory (GNU long names and PAX headers are unnecessary).
        if self.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
            raise BundleError("Bundle contains an unsupported tar entry.")
        return super()._proc_member(archive)


def _scan(handle, destination=None, expected=None):
    records, special, seen = {}, {}, set()
    total = 0
    with gzip.GzipFile(fileobj=_LimitedReader(handle, MAX_ARCHIVE_BYTES), mode="rb") as compressed:
        with tarfile.open(fileobj=_LimitedReader(compressed), mode="r|", tarinfo=_StrictTarInfo) as archive:
            for member in archive:
                name = member.name
                if name in seen:
                    raise BundleError("Bundle contains duplicate archive paths.")
                seen.add(name)
                if len(seen) > MAX_FILES + 2:
                    raise BundleError("Bundle contains too many files.")
                if not member.isfile() or member.pax_headers or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    raise BundleError("Bundle contains a link, directory, or unsupported tar entry.")
                if member.mode & ~0o777 or member.mode & 0o022:
                    raise BundleError("Bundle contains unsafe file permissions.")
                if member.size < 0:
                    raise BundleError("Bundle has an invalid file size.")
                if name in ("manifest.json", "manifest.sig"):
                    limit = MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_SIGNATURE_BYTES
                    if member.size > limit:
                        raise BundleError("Bundle manifest or signature is too large.")
                    special[name] = archive.extractfile(member).read(limit + 1)
                    continue
                _path(name)
                total += member.size
                if total > MAX_CONTENT_BYTES:
                    raise BundleError("Bundle exceeds the content size limit.")
                if expected is not None and name not in expected:
                    raise BundleError("Bundle changed while being verified.")
                digest = hashlib.sha256()
                output = None
                try:
                    if destination is not None:
                        target = destination.joinpath(*PurePosixPath(name).parts)
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        output = target.open("xb")
                    stream = archive.extractfile(member)
                    count = 0
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        digest.update(chunk)
                        if output is not None:
                            output.write(chunk)
                    if count != member.size:
                        raise BundleError("Bundle contains a truncated file.")
                finally:
                    if output is not None:
                        output.close()
                record = {"sha256": digest.hexdigest(), "size": member.size, "mode": member.mode}
                records[name] = record
                if expected is not None and record != expected[name]:
                    raise BundleError("Bundle changed while being verified.")
                if destination is not None:
                    os.chmod(target, member.mode)
            # tarfile stops at end-of-archive markers. Reject hidden trailing data.
            while True:
                tail = archive.fileobj.read(1024 * 1024)
                if not tail:
                    break
                if any(tail):
                    raise BundleError("Bundle contains trailing data after the tar archive.")
    return records, special


def _authenticate(handle, public_key, openssl):
    records, special = _scan(handle)
    if set(special) != {"manifest.json", "manifest.sig"}:
        raise BundleError("Bundle is missing its signed manifest.")
    manifest = _parse_manifest(special["manifest.json"], special["manifest.sig"], public_key, openssl)
    manifest = _present_manifest(manifest, records)
    return manifest, special


def _parse_manifest(raw, signature, public_key, openssl):
    if len(raw) > MAX_MANIFEST_BYTES or len(signature) > MAX_SIGNATURE_BYTES:
        raise BundleError('Bundle manifest or signature is too large.')
    _verify_signature(raw, signature, public_key, openssl)
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise BundleError("Signed bundle manifest is not valid UTF-8 JSON.") from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest.get("schema") not in (1, 2):
        raise BundleError("Bundle manifest schema is unsupported.")
    if set(manifest).intersection({'signed_files', 'present_packages'}) or any(name.startswith('_') for name in manifest):
        raise BundleError('Signed manifest contains reserved verifier annotation fields.')
    release = manifest.get("release")
    if (not isinstance(release, dict) or not isinstance(release.get("version"), str)
            or len(release["version"]) > 128
            or not _VERSION.fullmatch(release["version"])
            or release.get("channel") not in ("stable", "beta")
            or not isinstance(release.get("display_version"), str)
            or not isinstance(manifest.get("notes", ""), str)):
        raise BundleError("Bundle release metadata is invalid.")
    prerelease = _VERSION.fullmatch(release["version"]).group(1)
    if prerelease and (release["channel"] != "beta" or prerelease.split(".")[0] != "beta"
                       or any(p.isdigit() and len(p) > 1 and p[0] == "0" for p in prerelease.split("."))):
        raise BundleError("Bundle release channel or prerelease metadata is invalid.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise BundleError("Bundle file manifest is invalid.")
    for name, entry in files.items():
        _path(name)
        if any("/".join(name.split("/")[:index]) in files for index in range(1, len(name.split("/")))):
            raise BundleError("Bundle contains overlapping file and directory paths.")
        if (not isinstance(entry, dict) or set(entry) != {"sha256", "size", "mode"}
                or not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])
                or type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_CONTENT_BYTES
                or type(entry["mode"]) is not int or entry["mode"] & ~0o777 or entry["mode"] & 0o022):
            raise BundleError("Bundle file metadata is invalid.")
    # A bundle must carry the actual installer release source and the tool.
    if "payload/components/release.json" not in files or not any(p.startswith("app/oxp3_maintenance/") for p in files):
        raise BundleError("Bundle is missing its maintenance tool or installer release metadata.")
    if sum(record['size'] for record in files.values()) > MAX_CONTENT_BYTES:
        raise BundleError('Signed bundle exceeds the content size limit.')
    if manifest['schema'] == 2:
        _validate_packages(manifest)
        from .distribution import _descriptor
        _descriptor(manifest)
    return manifest


def manifest_digest(manifest):
    """Digest signed content, excluding the verifier's sparse-view annotations."""
    value = dict(manifest)
    if 'signed_files' in value:
        value['files'] = value.pop('signed_files')
    value.pop('present_packages', None)
    value = {name: content for name, content in value.items() if not name.startswith('_')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _validate_packages(manifest):
    packages, mapping = manifest.get('packages'), manifest.get('component_packages')
    if (not isinstance(packages, dict) or not 0 < len(packages) <= 256 or 'core' not in packages
            or not isinstance(mapping, dict) or not 0 < len(mapping) <= 256):
        raise BundleError('Signed package membership is invalid.')
    seen = set()
    for identifier, package in packages.items():
        if (not isinstance(identifier, str) or not re.fullmatch('[a-z][a-z0-9-]{0,79}', identifier)
                or not isinstance(package, dict) or set(package) != {'files', 'components'}
                or not isinstance(package['files'], list) or not package['files']
                or any(not isinstance(p, str) for p in package['files'])
                or len(set(package['files'])) != len(package['files'])
                or set(package['files']) - set(manifest['files']) or seen.intersection(package['files'])
                or not isinstance(package['components'], list)
                or any(not isinstance(c, str) for c in package['components'])
                or len(set(package['components'])) != len(package['components'])):
            raise BundleError('Signed package membership is invalid or overlapping.')
        seen.update(package['files'])
    if seen != set(manifest['files']):
        raise BundleError('Every signed file must belong to exactly one package.')
    for component, groups in mapping.items():
        if (not isinstance(component, str) or not re.fullmatch('[a-z][a-z0-9-]{0,79}', component)
                or not isinstance(groups, list) or not groups or 'core' not in groups
                or any(not isinstance(group, str) or group not in packages for group in groups)
                or len(groups) != len(set(groups))):
            raise BundleError('Signed component package mapping is invalid.')
    for identifier, package in packages.items():
        expected = {c for c, groups in mapping.items() if identifier in groups}
        if set(package['components']) != expected:
            raise BundleError('Signed package and component membership disagree.')
    core = set(packages['core']['files'])
    mandatory = {'payload/components/release.json', 'payload/components/options.json', 'payload/integration/manifest.json'}
    if (not mandatory <= core or any(name.startswith('app/') and name not in core for name in manifest['files'])):
        raise BundleError('The core package must contain the complete tool and selection metadata.')


def _present_manifest(manifest, records):
    if manifest['schema'] == 1:
        if manifest['files'] != records:
            raise BundleError('Bundle files do not match the signed manifest (hash, size, mode, or membership).')
        return manifest
    expected = manifest['files']
    if any(name not in expected or expected[name] != record for name, record in records.items()):
        raise BundleError('Bundle contains unsigned or changed package files.')
    present = []
    for identifier, package in manifest['packages'].items():
        members = set(package['files'])
        overlap = members.intersection(records)
        if overlap and overlap != members:
            raise BundleError('Bundle contains a partial component package.')
        if overlap:
            present.append(identifier)
    if 'core' not in present:
        raise BundleError('Bundle is missing the mandatory core package.')
    return dict(manifest, files=records, signed_files=expected, present_packages=sorted(present))


def _open_archive(archive):
    return _regular_input(archive, MAX_ARCHIVE_BYTES)


def _regular_input(path, limit, *, single_link=False):
    """Do not block on FIFOs or follow a leaf link swapped after an earlier check."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > limit
                or (single_link and info.st_nlink != 1)):
            raise BundleError("Bundle input must be a bounded regular file without links.")
        result = os.fdopen(descriptor, "rb")
        descriptor = None
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)


def inspect_bundle(archive: Path, public_key: Path, *, openssl="openssl") -> dict:
    """Authenticate and hash an archive without extracting or executing its files."""
    try:
        with _open_archive(archive) as handle:
            manifest, _ = _authenticate(handle, public_key, openssl)
            return manifest
    except BundleError:
        raise
    except (OSError, EOFError, tarfile.TarError, ValueError, OverflowError) as exc:
        raise BundleError("Bundle could not be read: invalid or truncated archive.") from exc


def verify_bundle(archive: Path, public_key: Path, destination: Path, *, openssl="openssl") -> dict:
    """Authenticate then extract into an existing, empty, private directory.

    The same open archive is read twice; hashes are checked again during writing.
    Partial output is removed if verification fails. The destination must belong
    to the caller and have no group/other permissions on POSIX systems.
    """
    destination = Path(destination)
    try:
        info = destination.lstat()
        if (not stat.S_ISDIR(info.st_mode) or destination.is_symlink() or any(destination.iterdir())
                or (os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()))):
            raise BundleError("Bundle destination must be an empty private directory owned by this user.")
    except OSError as exc:
        raise BundleError("Bundle destination must be an existing empty private directory.") from exc
    started = False
    try:
        with _open_archive(archive) as handle:
            manifest, special = _authenticate(handle, public_key, openssl)
            handle.seek(0)
            started = True
            records, second_special = _scan(handle, destination, manifest["files"])
            if records != manifest["files"] or second_special != special:
                raise BundleError("Bundle changed while being verified.")
            return manifest
    except (BundleError, OSError, EOFError, tarfile.TarError, ValueError, OverflowError) as exc:
        if started:
            for child in destination.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        if isinstance(exc, BundleError):
            raise
        raise BundleError("Bundle could not be extracted safely.") from exc


def verify_directory(source: Path, public_key: Path, destination: Path, *, openssl="openssl") -> dict:
    """Authenticate an unpacked offline release and copy only signed files.

    The directory is untrusted data: never import its Python modules before this
    check. Symlinks, unlisted files, special files, and changed content are errors.
    Destination follows the same private-directory contract as verify_bundle.
    """
    source, destination = Path(source), Path(destination)
    started = False
    try:
        info = destination.lstat()
        if (not stat.S_ISDIR(info.st_mode) or destination.is_symlink() or any(destination.iterdir())
                or (os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()))):
            raise BundleError("Bundle destination must be an empty private directory owned by this user.")
        if source.is_symlink() or not source.is_dir() or source.resolve() == destination.resolve():
            raise BundleError("Offline bundle source must be a real directory.")
        specials = {}
        for name, limit in (("manifest.json", MAX_MANIFEST_BYTES), ("manifest.sig", MAX_SIGNATURE_BYTES)):
            path = source / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
                raise BundleError("Offline bundle has no safe signed manifest.")
            with _regular_input(path, limit, single_link=True) as stream:
                specials[name] = stream.read(limit + 1)
            if len(specials[name]) > limit:
                raise BundleError("Offline bundle manifest is too large.")
        manifest = _parse_manifest(specials["manifest.json"], specials["manifest.sig"], public_key, openssl)
        seen, entries, total = set(), [], 0
        # os.walk never follows links; reject them explicitly, including directories.
        directory_count = 0
        for parent, directories, filenames in os.walk(source, followlinks=False):
            for name in directories + filenames:
                path = Path(parent) / name
                info = path.lstat()
                relative = path.relative_to(source).as_posix()
                if (stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                        or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                    raise BundleError("Offline bundle contains a link or special file.")
                if stat.S_ISDIR(info.st_mode):
                    directory_count += 1
                    if directory_count > MAX_FILES:
                        raise BundleError("Offline bundle contains too many directories.")
                    if not any(p.startswith(relative + "/") for p in manifest["files"]):
                        raise BundleError("Offline bundle contains an unlisted directory.")
                    continue
                if relative in specials:
                    continue
                _path(relative)
                if relative not in manifest["files"]:
                    raise BundleError("Offline bundle contains an unlisted file.")
                expected = manifest["files"][relative]
                if info.st_size != expected["size"] or (os.name == "posix" and stat.S_IMODE(info.st_mode) != expected["mode"]):
                    raise BundleError("Offline bundle file size or mode does not match its manifest.")
                seen.add(relative)
                entries.append((relative, path))
                total += info.st_size
                if len(seen) > MAX_FILES or total > MAX_CONTENT_BYTES:
                    raise BundleError("Offline bundle exceeds the safety limit.")
        manifest = _present_manifest(manifest, {name: manifest['files'][name] for name in seen})
        started = True
        for relative, path in entries:
            expected = manifest["files"][relative]
            target = destination.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # O_NOFOLLOW also protects against a leaf link swapped after the walk.
            digest, count = hashlib.sha256(), 0
            with _regular_input(path, expected["size"], single_link=True) as stream, target.open("xb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > expected["size"]:
                        raise BundleError("Offline bundle source changed while being verified.")
                    digest.update(chunk)
                    output.write(chunk)
            if count != expected["size"] or digest.hexdigest() != expected["sha256"]:
                raise BundleError("Offline bundle file hash does not match its signed manifest.")
            os.chmod(target, expected["mode"])
        return manifest
    except (BundleError, OSError, ValueError, OverflowError) as exc:
        if started:
            for child in destination.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        if isinstance(exc, BundleError):
            raise
        raise BundleError("Offline bundle could not be copied safely.") from exc
