# FSR XMX LZMS buffer adapter

`fsrxdec.dll` is an x64 Windows DLL implementing only `CreateDecompressor` (ordinal
40), `Decompress` (43), and `CloseDecompressor` (45) for algorithm 5, LZMS buffer
mode. It loads the pinned `libwim-15.dll` beside itself. It does not replace
`Cabinet.dll` or change Wine's global DLL configuration.

The consumer integration must change only the `Cabinet.dll` import name in the
explicitly supported, hash-verified user-supplied XMX module copy to the equal
length `fsrxdec.dll`. This directory contains no third-party FSR or DLSS module.

The supported buffer format has a 24-byte header, algorithm byte 5, a header
checksum, an uncompressed length, and block sizes from 1 through 65536 bytes.
Each block has a 32-bit compressed length; an equal-size block is stored literally.
The actual validated XMX payload uses 65536-byte blocks. Raw mode, other algorithms,
custom allocation routines, zero-length payloads, and overlapping buffers are
unsupported. Handles must be genuine live handles returned by this adapter; the
caller must not close a handle while using it.

The adapter validates all framing before decoding and returns the required size
with `ERROR_INSUFFICIENT_BUFFER` for a size query or short destination. Invalid
framing and codec failures return `ERROR_BAD_COMPRESSION_BUFFER`. On a codec failure
the requested output region is cleared and the reported output size is zero.
LZMS has no payload checksum, so a successful decode alone does not authenticate
the data. The importing application must verify its pinned input DLL hashes.

Original adapter code uses the parent project's AGPL-3.0-only license. Windows
libwim 1.14.5 is separately available under LGPL-2.1-or-later. Keep the generated
`licenses/` and `sources/` directories with every distributed adapter payload;
`sources/wimlib-1.14.5.tar.gz` is the complete corresponding upstream source.
The official precompiled libwim does not link to GPL-only libntfs-3g. Pins and
official download URLs are in `dependency-source.json`.

Build using PowerShell 7 and the official, hash-pinned archives:

```powershell
./build.ps1 -ZigArchive /path/zig-x86_64-windows-0.15.2.zip `
  -WimlibArchive /path/wimlib-1.14.5-windows-x86_64-bin.zip `
  -WimlibSource /path/wimlib-1.14.5.tar.gz `
  -WorkDirectory /path/new-build-work -OutputDirectory /path/new-output
```

`-ZigExe` optionally reuses an extracted compiler after comparing its executable
with the one inside the pinned archive. Its sibling compiler libraries must come
from that same archive. Build directories and output must be kept outside public
source exports unless explicitly packaged. The output manifest records every
distributed file's actual size and SHA-256. Its fixed `manifest.json` has a `files`
array containing only `bin/fsrxdec.dll` and `bin/libwim-15.dll`; each entry records
`path`, `size`, and `sha256`. The `distribution_files` array separately covers
the notices and corresponding sources. Only those two DLLs are deployed beside
the imported game module; keep the remaining files in the distribution.

Run the Windows differential verification with Python:

```powershell
python ./test_fsrxdec.py --dll /path/new-output/bin/fsrxdec.dll --report /path/report.json
```

Add `--module /path/amd_fidelityfx_upscaler_dx12.dll` to statically read the supported
module and compare its six compressed resource packs against system Cabinet.
The test does not load or execute that module. Tests load only the newly built
adapter, pinned libwim, and the system's Cabinet API. Proton game validation is a
separate integration gate.
