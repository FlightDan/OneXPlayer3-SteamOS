"""Windows differential tests; never load the optional input FSR module."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

PINNED_MODULE = "fdcae2df13f196b7d64058d8b581ffd1dbaaed0a00b451c27196da3dd73cb8bb"
PINNED_WIMLIB = "ba853ee1e3fc5f5798581f02e8e066ba07a0a2375f0bf444fe981431fd508495"
SIGNATURE = bytes.fromhex("0a51e5c01800")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fix_checksum(data):
    data = bytearray(data)
    data[6] = zlib.crc32(data[:6] + data[7:24]) & 255
    return bytes(data)


def bind_decoder(library):
    library.CreateDecompressor.argtypes = [W.DWORD, C.c_void_p, C.POINTER(C.c_void_p)]
    library.CreateDecompressor.restype = W.BOOL
    library.Decompress.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    library.Decompress.restype = W.BOOL
    library.CloseDecompressor.argtypes = [C.c_void_p]
    library.CloseDecompressor.restype = W.BOOL


def create(library):
    handle = C.c_void_p()
    assert library.CreateDecompressor(5, None, C.byref(handle)), C.get_last_error()
    assert handle.value
    return handle


def decompress(library, payload):
    handle = create(library)
    try:
        source = C.create_string_buffer(payload)
        size = C.c_size_t()
        assert not library.Decompress(handle, source, len(payload), None, 0, C.byref(size))
        assert C.get_last_error() == 122 and size.value > 0
        output = C.create_string_buffer(size.value)
        assert library.Decompress(handle, source, len(payload), output, len(output), C.byref(size)), C.get_last_error()
        assert size.value == len(output)
        return output.raw
    finally:
        assert library.CloseDecompressor(handle)


def compress(system, payload):
    handle = C.c_void_p()
    assert system.CreateCompressor(5, None, C.byref(handle))
    try:
        source = C.create_string_buffer(payload)
        size = C.c_size_t()
        assert not system.Compress(handle, source, len(payload), None, 0, C.byref(size))
        assert C.get_last_error() == 122
        output = C.create_string_buffer(size.value)
        assert system.Compress(handle, source, len(payload), output, len(output), C.byref(size))
        return output.raw[:size.value]
    finally:
        assert system.CloseCompressor(handle)


def exported_ordinals(path):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    assert struct.unpack_from("<H", data, pe + 4)[0] == 0x8664
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    sections = []
    for index in range(count):
        at = optional + optional_size + index * 40
        virtual_size, address, raw_size, raw = struct.unpack_from("<IIII", data, at + 8)
        sections.append((address, max(virtual_size, raw_size), raw))

    def offset(rva):
        return next(raw + rva - address for address, size, raw in sections if address <= rva < address + size)

    export = offset(struct.unpack_from("<I", data, optional + 112)[0])
    base, _, names_count, _, names, ordinals = struct.unpack_from("<IIIIII", data, export + 16)
    result = {}
    for index in range(names_count):
        start = offset(struct.unpack_from("<I", data, offset(names) + index * 4)[0])
        name = data[start:data.index(b"\0", start)].decode("ascii")
        result[name] = base + struct.unpack_from("<H", data, offset(ordinals) + index * 2)[0]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--module", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    dll_path = args.dll.resolve()
    assert sha((dll_path.parent / "libwim-15.dll").read_bytes()) == PINNED_WIMLIB
    exports = exported_ordinals(dll_path)
    assert exports == {"CreateDecompressor": 40, "Decompress": 43, "CloseDecompressor": 45}, exports
    adapter = C.WinDLL(str(dll_path), use_last_error=True)
    # The only comparison implementation is the operating system DLL.
    system = C.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32/cabinet.dll"), use_last_error=True)
    for library in (adapter, system):
        bind_decoder(library)
    for name, ordinal in exports.items():
        assert C.cast(getattr(adapter, name), C.c_void_p).value == C.cast(adapter[ordinal], C.c_void_p).value
    system.CreateCompressor.argtypes = [W.DWORD, C.c_void_p, C.POINTER(C.c_void_p)]
    system.CreateCompressor.restype = W.BOOL
    system.Compress.argtypes = system.Decompress.argtypes
    system.Compress.restype = W.BOOL
    system.CloseCompressor.argtypes = [C.c_void_p]
    system.CloseCompressor.restype = W.BOOL
    rng = random.Random(0x465352)
    cases = []
    for length in (1, 2, 10, 65535, 65536, 65537, 262151):
        for kind in ("repeat", "random"):
            payload = (b"LZMS differential fixture\0" * ((length // 26) + 2))[:length] if kind == "repeat" else rng.randbytes(length)
            assert len(payload) == length
            packed = compress(system, payload)
            expected = decompress(system, packed)
            actual = decompress(adapter, packed)
            assert actual == expected == payload, (length, kind)
            cases.append({"size": length, "kind": kind, "compressed_size": len(packed), "sha256": sha(actual)})

    # Stored blocks follow the same framing and require no raw decoder call.
    stored_raw = rng.randbytes(321)
    stored = fix_checksum(SIGNATURE + bytes([0, 5]) + struct.pack("<QQI", len(stored_raw), len(stored_raw), len(stored_raw)) + stored_raw)
    assert decompress(system, stored) == decompress(adapter, stored) == stored_raw
    valid = compress(system, b"Z" * 65536)
    bad = []
    for length in (0, 1, 5, 6, 7, 8, 16, 23, 24, len(valid) - 1):
        bad.append((f"truncated_{length}", valid[:length]))
    for name, at, replacement in (
        ("signature", 0, b"\0"), ("algorithm", 7, b"\4"),
        ("zero_output", 8, bytes(8)), ("oversized_output", 8, b"\xff" * 8),
        ("zero_block", 16, bytes(8)), ("oversized_block", 16, struct.pack("<Q", 65537)),
        ("zero_compressed_block", 24, bytes(4)), ("oversized_compressed_block", 24, struct.pack("<I", 65537)),
    ):
        mutated = bytearray(valid)
        mutated[at:at + len(replacement)] = replacement
        bad.append((name, fix_checksum(mutated)))
    checksum_bad = bytearray(valid)
    checksum_bad[6] ^= 1
    bad += [("checksum", bytes(checksum_bad)), ("trailing_bytes", valid + b"extra")]
    handle = create(adapter)
    try:
        for name, packed in bad:
            source = C.create_string_buffer(packed)
            output = C.create_string_buffer(b"\xa5" * 65536, 65536)
            size = C.c_size_t(123)
            assert not adapter.Decompress(handle, source, len(packed), output, len(output), C.byref(size)), name
            assert C.get_last_error() == 605 and size.value == 0, (name, C.get_last_error(), size.value)
            assert output.raw == b"\xa5" * 65536, name
        source = C.create_string_buffer(valid)
        small = C.create_string_buffer(b"\xa5" * 8, 8)
        size = C.c_size_t()
        assert not adapter.Decompress(handle, source, len(valid), small, len(small), C.byref(size))
        assert C.get_last_error() == 122 and size.value == 65536 and small.raw == b"\xa5" * 8
        assert not adapter.Decompress(handle, source, len(valid), None, 0, None)
        assert C.get_last_error() == 87
        # Correct framing with a deliberately impossible one-byte raw LZMS stream.
        corrupt_stream = fix_checksum(valid[:24] + struct.pack("<I", 1) + b"\0")
        source = C.create_string_buffer(corrupt_stream)
        output = C.create_string_buffer(b"\xa5" * 65536, 65536)
        assert not adapter.Decompress(handle, source, len(corrupt_stream), output, len(output), C.byref(size))
        assert C.get_last_error() == 605 and size.value == 0 and output.raw == bytes(65536)
    finally:
        assert adapter.CloseDecompressor(handle)
    for algorithm, allocator in ((4, None), (5 | (1 << 29), None), (5, C.c_void_p(1))):
        handle = C.c_void_p(123)
        assert not adapter.CreateDecompressor(algorithm, allocator, C.byref(handle))
        assert C.get_last_error() == 50 and handle.value is None
    assert not adapter.CreateDecompressor(5, None, None) and C.get_last_error() == 87
    assert not adapter.CloseDecompressor(None) and C.get_last_error() == 6
    for _ in range(50):
        assert decompress(adapter, valid) == b"Z" * 65536

    # Check the missing-dependency path in a fresh process, so the already loaded
    # libwim cannot accidentally satisfy the probe through the loader's cache.
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="missing-libwim-", dir=args.report.parent) as temporary:
        missing_adapter = Path(temporary) / "fsrxdec.dll"
        shutil.copyfile(dll_path, missing_adapter)
        probe = """import ctypes as C, sys
from ctypes import wintypes as W
d = C.WinDLL(sys.argv[1], use_last_error=True)
d.CreateDecompressor.argtypes = [W.DWORD, C.c_void_p, C.POINTER(C.c_void_p)]
d.CreateDecompressor.restype = W.BOOL
h = C.c_void_p(123)
ok = d.CreateDecompressor(5, None, C.byref(h))
assert not ok and h.value is None and C.get_last_error() == 126, (ok, h.value, C.get_last_error())
"""
        subprocess.run([sys.executable, "-c", probe, str(missing_adapter.resolve())], check=True, capture_output=True, text=True)

    packs = []
    if args.module:
        data = args.module.read_bytes()
        assert sha(data) == PINNED_MODULE, "Refuse unknown input module; static reads only"
        cursor = 0
        while (cursor := data.find(SIGNATURE, cursor)) >= 0:
            total, block = struct.unpack_from("<QQ", data, cursor + 8)
            end, remaining, blocks = cursor + 24, total, 0
            while remaining:
                compressed = struct.unpack_from("<I", data, end)[0]
                assert 0 < compressed <= min(block, remaining)
                end += 4 + compressed
                remaining -= min(block, remaining)
                blocks += 1
            packed = data[cursor:end]
            expected = decompress(system, packed)
            actual = decompress(adapter, packed)
            assert actual == expected and len(actual) == total, hex(cursor)
            pack = {"offset": hex(cursor), "output_size": total, "compressed_size": len(packed), "blocks": blocks, "output_sha256": sha(actual), "equal_to_system": True}
            packs.append(pack)
            print(json.dumps(pack), flush=True)
            cursor = end
        assert len(packs) == 6
    report = {"result": "passed", "dll": str(dll_path), "dll_sha256": sha(dll_path.read_bytes()),
              "exports": exports, "synthetic_cases": cases, "malformed_framing_cases": len(bad),
              "repeated_handle_cycles": 50, "raw_codec_failure_clears_output": True,
              "unsupported_api_variants_rejected": True, "real_module_packs": packs,
              "missing_dependency_returns_error": True,
              "input_module_loaded": False, "elapsed_seconds": time.monotonic() - started,
              "scope": "Windows x64 CPU differential verification; Proton/game integration not tested"}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "dll_sha256": report["dll_sha256"], "synthetic_cases": len(cases), "real_packs": len(packs), "seconds": report["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
