/* SPDX-License-Identifier: AGPL-3.0-only
 * Copyright (c) 2026 FlightDan and Opti2XMX contributors
 * Narrow LZMS buffer adapter for the explicitly imported FSR XMX module.
 * This is original adapter code; the separately loaded libwim has its own license.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <wimlib.h>

#define HANDLE_TAG UINT64_C(0x4653525844454331)
#define HEADER_SIZE 24u
#define MAX_BLOCK_SIZE 65536u

typedef int (*create_decoder_fn)(enum wimlib_compression_type, size_t,
                                struct wimlib_decompressor **);
typedef int (*decode_fn)(const void *, size_t, void *, size_t,
                        struct wimlib_decompressor *);
typedef void (*free_decoder_fn)(struct wimlib_decompressor *);

struct decoder_handle { uint64_t tag; };
struct buffer_layout { size_t output_size; size_t block_size; };
static HMODULE self_module;
static INIT_ONCE backend_once = INIT_ONCE_STATIC_INIT;
static create_decoder_fn create_decoder;
static decode_fn decode;
static free_decoder_fn free_decoder;

static BOOL fail(DWORD error)
{
    SetLastError(error);
    return FALSE;
}

/* Load the dependency from this adapter's directory, never from a search-path
 * entry supplied by the caller. The DLL remains loaded for our process lifetime.
 */
static BOOL CALLBACK initialize_backend(PINIT_ONCE once, PVOID parameter, PVOID *context)
{
    WCHAR path[32768];
    DWORD length;
    size_t directory_length;
    HMODULE module;
    create_decoder_fn create;
    decode_fn unpack;
    free_decoder_fn destroy;
    (void)once; (void)parameter; (void)context;
    length = GetModuleFileNameW(self_module, path, (DWORD)(sizeof(path) / sizeof(path[0])));
    if (length == 0 || length >= sizeof(path) / sizeof(path[0]))
        return fail(ERROR_BAD_PATHNAME);
    directory_length = length;
    while (directory_length && path[directory_length - 1] != L'\\' &&
           path[directory_length - 1] != L'/')
        --directory_length;
    if (!directory_length || directory_length + sizeof(L"libwim-15.dll") / sizeof(WCHAR) >
                             sizeof(path) / sizeof(path[0]))
        return fail(ERROR_BAD_PATHNAME);
    memcpy(path + directory_length, L"libwim-15.dll", sizeof(L"libwim-15.dll"));
    module = LoadLibraryExW(path, NULL,
                           LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module)
        return FALSE;
    create = (create_decoder_fn)(void *)GetProcAddress(module, "wimlib_create_decompressor");
    unpack = (decode_fn)(void *)GetProcAddress(module, "wimlib_decompress");
    destroy = (free_decoder_fn)(void *)GetProcAddress(module, "wimlib_free_decompressor");
    if (!create || !unpack || !destroy) {
        FreeLibrary(module);
        return fail(ERROR_PROC_NOT_FOUND);
    }
    create_decoder = create;
    decode = unpack;
    free_decoder = destroy;
    return TRUE;
}

static uint32_t read_u32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
           (uint32_t)p[3] << 24;
}

static uint64_t read_u64(const unsigned char *p)
{
    return (uint64_t)read_u32(p) | (uint64_t)read_u32(p + 4) << 32;
}

/* The buffer header checksum is the low byte of standard CRC32 over the
 * 23 header bytes other than the checksum byte at offset 6. This was checked
 * against system Cabinet output and all six input module resource packs.
 */
static unsigned char header_checksum(const unsigned char *p)
{
    uint32_t crc = UINT32_MAX;
    unsigned i, bit;
    for (i = 0; i < HEADER_SIZE; ++i) {
        if (i == 6)
            continue;
        crc ^= p[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? UINT32_C(0xedb88320) : 0);
    }
    return (unsigned char)(~crc);
}

/* Validate all framing before touching the destination or allocating a codec.
 * Offsets advance only after subtraction-based bounds checks, so input lengths
 * and uncompressed sizes cannot wrap size_t.
 */
static BOOL inspect_buffer(const unsigned char *data, size_t size, struct buffer_layout *layout)
{
    static const unsigned char signature[6] = {0x0a, 0x51, 0xe5, 0xc0, 0x18, 0};
    uint64_t output64, block64;
    size_t input = HEADER_SIZE, remaining;
    if (!data || size < HEADER_SIZE || memcmp(data, signature, sizeof(signature)) ||
        data[7] != 5 || data[6] != header_checksum(data))
        return fail(ERROR_BAD_COMPRESSION_BUFFER);
    output64 = read_u64(data + 8);
    block64 = read_u64(data + 16);
    if (!output64 || output64 > SIZE_MAX || !block64 || block64 > MAX_BLOCK_SIZE ||
        block64 > SIZE_MAX)
        return fail(ERROR_BAD_COMPRESSION_BUFFER);
    layout->output_size = (size_t)output64;
    layout->block_size = (size_t)block64;
    remaining = layout->output_size;
    while (remaining) {
        size_t expected = remaining < layout->block_size ? remaining : layout->block_size;
        size_t compressed;
        if (size - input < 4)
            return fail(ERROR_BAD_COMPRESSION_BUFFER);
        compressed = read_u32(data + input);
        input += 4;
        if (!compressed || compressed > expected || compressed > size - input)
            return fail(ERROR_BAD_COMPRESSION_BUFFER);
        input += compressed;
        remaining -= expected;
    }
    if (input != size)
        return fail(ERROR_BAD_COMPRESSION_BUFFER);
    return TRUE;
}

BOOL WINAPI CreateDecompressor(DWORD algorithm, const void *allocation_routines, void **handle)
{
    struct decoder_handle *created;
    if (!handle)
        return fail(ERROR_INVALID_PARAMETER);
    *handle = NULL;
    if (algorithm != 5 || allocation_routines)
        return fail(ERROR_NOT_SUPPORTED);
    if (!InitOnceExecuteOnce(&backend_once, initialize_backend, NULL, NULL))
        return FALSE;
    created = HeapAlloc(GetProcessHeap(), 0, sizeof(*created));
    if (!created)
        return fail(ERROR_NOT_ENOUGH_MEMORY);
    created->tag = HANDLE_TAG;
    *handle = created;
    return TRUE;
}

BOOL WINAPI Decompress(void *handle, const void *compressed_data, size_t compressed_size,
                       void *output, size_t output_capacity, size_t *output_size)
{
    struct decoder_handle *valid = handle;
    struct buffer_layout layout;
    const unsigned char *source = compressed_data;
    unsigned char *destination = output;
    struct wimlib_decompressor *codec = NULL;
    size_t input = HEADER_SIZE, written = 0;
    int status;
    if (!output_size)
        return fail(ERROR_INVALID_PARAMETER);
    *output_size = 0;
    if (!valid || valid->tag != HANDLE_TAG)
        return fail(ERROR_INVALID_HANDLE);
    if (!inspect_buffer(source, compressed_size, &layout))
        return FALSE;
    if (!output || output_capacity < layout.output_size) {
        *output_size = layout.output_size;
        return fail(ERROR_INSUFFICIENT_BUFFER);
    }
    /* The adapter is deliberately x64 only. Reject overlapping input/output;
     * decoding in place is not supported by the upstream codec either.
     */
    if ((uintptr_t)source > UINTPTR_MAX - compressed_size ||
        (uintptr_t)destination > UINTPTR_MAX - layout.output_size ||
        ((uintptr_t)source < (uintptr_t)destination + layout.output_size &&
         (uintptr_t)destination < (uintptr_t)source + compressed_size))
        return fail(ERROR_INVALID_PARAMETER);
    status = create_decoder(WIMLIB_COMPRESSION_TYPE_LZMS, layout.block_size, &codec);
    if (status)
        return fail(status == WIMLIB_ERR_NOMEM ? ERROR_NOT_ENOUGH_MEMORY : ERROR_BAD_COMPRESSION_BUFFER);
    while (written < layout.output_size) {
        size_t expected = layout.output_size - written;
        size_t compressed = read_u32(source + input);
        if (expected > layout.block_size)
            expected = layout.block_size;
        input += 4;
        if (compressed == expected) {
            memcpy(destination + written, source + input, expected);
        } else if (decode(source + input, compressed, destination + written, expected, codec)) {
            free_decoder(codec);
            SecureZeroMemory(destination, layout.output_size);
            return fail(ERROR_BAD_COMPRESSION_BUFFER);
        }
        input += compressed;
        written += expected;
    }
    free_decoder(codec);
    *output_size = written;
    return TRUE;
}

BOOL WINAPI CloseDecompressor(void *handle)
{
    struct decoder_handle *valid = handle;
    if (!valid || valid->tag != HANDLE_TAG)
        return fail(ERROR_INVALID_HANDLE);
    valid->tag = 0;
    return HeapFree(GetProcessHeap(), 0, valid);
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}
