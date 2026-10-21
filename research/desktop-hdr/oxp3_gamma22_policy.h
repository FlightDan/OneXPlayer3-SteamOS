// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <span>
#include <cstdint>
namespace KWin {
struct Oxp3Gamma22Luminance { double average; double peak; };
inline constexpr Oxp3Gamma22Luminance oxp3Gamma22Luminance(bool x2miniProfile)
{
    return x2miniProfile ? Oxp3Gamma22Luminance{475, 700} : Oxp3Gamma22Luminance{472, 1100};
}
inline bool oxp3Gamma22Panel(bool optIn, bool internal, std::span<const uint8_t> edid)
{
    constexpr uint8_t header[]{0x00,0xff,0xff,0xff,0xff,0xff,0xff,0x00};
    if (!optIn || !internal || edid.size() < 128) return false;
    for (unsigned i=0; i<8; ++i) if (edid[i] != header[i]) return false;
    return edid[8] == 0x4c && edid[9] == 0x83 && edid[10] == 0x01 && edid[11] == 0x43;
}
}
