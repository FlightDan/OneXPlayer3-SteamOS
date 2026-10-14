"""Generate an append-only GPT plan from freshly read layout metadata; no writes."""
MIB = 1024 * 1024
GIB = 1024 * MIB
PARTS = [
    ('esp', 256 * MIB, 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'),
    ('efi-A', 64 * MIB, 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'),
    ('efi-B', 64 * MIB, 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'),
    ('rootfs-A', 11 * GIB, '4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709'),
    ('rootfs-B', 11 * GIB, '4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709'),
    ('var-A', GIB, '4D21B016-B534-45C2-A9FB-5C16E091FD2D'),
    ('var-B', GIB, '4D21B016-B534-45C2-A9FB-5C16E091FD2D'),
]


def plan(table, start, size):
    if table.get('label') != 'gpt' or table.get('sectorsize') != 512:
        raise ValueError('Only GPT with 512-byte logical sectors is supported')
    if start % MIB or size % MIB or size < 64 * GIB:
        raise ValueError('An aligned unallocated range of at least 64 GiB is required')
    end = start + size
    if start < max(MIB, table['firstlba'] * 512) or end > table['lastlba'] * 512:
        raise ValueError('Selected range crosses GPT boundaries')
    previous_end = 0
    for partition in sorted(table['partitions'], key=lambda p: p['start']):
        part_start = partition['start'] * 512
        part_end = part_start + partition['size'] * 512
        if part_start < previous_end or part_end <= part_start:
            raise ValueError('Invalid or overlapping existing partition layout')
        previous_end = part_end
        if start < part_end and part_start < end:
            raise ValueError('Selected range overlaps an existing partition')
        if partition.get('name') in {name for name, _, _ in PARTS} | {'home'}:
            raise ValueError('Existing SteamOS or ambiguous partition labels require separate repair mode')
    cursor = start
    result = []
    for name, length, kind in PARTS + [('home', end - start - sum(p[1] for p in PARTS), '933AC7E1-2EB4-4F13-B844-0E14E2AEF915')]:
        result.append({'name': name, 'start': cursor // 512, 'size': length // 512, 'type': kind})
        cursor += length
    assert cursor == end
    return result
