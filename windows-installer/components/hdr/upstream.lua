-- Accepted OXP3 Gamma 2.2 HDR: software peak mapping1100, full-frame472.
-- Optical peak brightness is unmeasured. Force composition in SDR too.
-- Keep conversion in Gamescope if Steam overwrites GAMESCOPE_COMPOSITE_FORCE.
local oxp3_gamma22_matched = false
local oxp3_gamma22_reported = false
gamescope.hook("OnPostPaint", function()
    if oxp3_gamma22_matched then
        if not gamescope.convars.composite_force.value then
            gamescope.convars.composite_force.value = true
            gamescope.log(gamescope.log_priority.warning, "oxp3 gamma22: composition override corrected")
        end
        if not oxp3_gamma22_reported and gamescope.convars.hdr_enabled.value then
            gamescope.log(gamescope.log_priority.info, "oxp3 gamma22: HDR requested; composite_force="..tostring(gamescope.convars.composite_force.value))
            oxp3_gamma22_reported = true
        end
    end
end)
-- ONEXPLAYER 3 Samsung SDC AMS881KB01-0 OLED: treat like Steam Deck OLED / OXP F1 OLED:
-- keep the panel in its native gamma-2.2 mode and let gamescope do HDR tone-mapping internally (no BT.2020/PQ VSC SDP is sent).
-- This panel has real continuous VRR from 30-144Hz (confirmed by user + two real kernel-reported
-- native modes at 60Hz and 144Hz via `modetest -c`: same pixel clock 380160kHz, same hsync/vsync
-- width, only vertical front porch differs). Both real data points fit a simple formula exactly
-- (vtotal = clock_hz / (htotal * refresh), front_porch = vtotal - vdisp - 64), so the table below
-- was generated from that formula rather than measured per-Hz -- verified to reproduce the two real
-- driver-reported modes (56 @144Hz, 1904 @60Hz) exactly before being trusted for the rest of the range.
-- Revert: delete this file and relogin game mode (HDR + extra refresh rates off). Installed by oxp3-apply-fixes.sh.
local oxp3_oled_colorimetry = {   -- from EDID
    r = { x = 0.6835, y = 0.3154 },
    g = { x = 0.2402, y = 0.7138 },
    b = { x = 0.1396, y = 0.0439 },
    w = { x = 0.3134, y = 0.3291 },
}
local oxp3_oled_refresh_rates = {
        30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44,
        45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
        60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
        75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89,
        90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104,
        105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119,
        120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134,
        135, 136, 137, 138, 139, 140, 141, 142, 143, 144,
}
gamescope.config.known_displays.oxp3_sdc_oled = {
    pretty_name = "ONEXPLAYER 3 SDC AMS881KB01-0 OLED",
    dynamic_refresh_rates = oxp3_oled_refresh_rates,
    dynamic_modegen = function(base_mode, refresh)
        debug("Generating mode "..refresh.."Hz for ONEXPLAYER 3 SDC OLED")
        local vfps = {
        [30] = 5072, [31] = 4868, [32] = 4676, [33] = 4496, [34] = 4327, [35] = 4167,
        [36] = 4016, [37] = 3873, [38] = 3738, [39] = 3610, [40] = 3488, [41] = 3372,
        [42] = 3262, [43] = 3156, [44] = 3056, [45] = 2960, [46] = 2868, [47] = 2780,
        [48] = 2696, [49] = 2615, [50] = 2538, [51] = 2463, [52] = 2391, [53] = 2322,
        [54] = 2256, [55] = 2192, [56] = 2130, [57] = 2071, [58] = 2013, [59] = 1958,
        [60] = 1904, [61] = 1852, [62] = 1802, [63] = 1753, [64] = 1706, [65] = 1660,
        [66] = 1616, [67] = 1573, [68] = 1531, [69] = 1491, [70] = 1451, [71] = 1413,
        [72] = 1376, [73] = 1340, [74] = 1305, [75] = 1270, [76] = 1237, [77] = 1205,
        [78] = 1173, [79] = 1142, [80] = 1112, [81] = 1083, [82] = 1054, [83] = 1026,
        [84] = 999, [85] = 972, [86] = 946, [87] = 921, [88] = 896, [89] = 872,
        [90] = 848, [91] = 825, [92] = 802, [93] = 780, [94] = 758, [95] = 737,
        [96] = 716, [97] = 696, [98] = 676, [99] = 656, [100] = 637, [101] = 618,
        [102] = 600, [103] = 581, [104] = 564, [105] = 546, [106] = 529, [107] = 512,
        [108] = 496, [109] = 480, [110] = 464, [111] = 448, [112] = 433, [113] = 418,
        [114] = 403, [115] = 389, [116] = 375, [117] = 361, [118] = 347, [119] = 333,
        [120] = 320, [121] = 307, [122] = 294, [123] = 281, [124] = 269, [125] = 257,
        [126] = 245, [127] = 233, [128] = 221, [129] = 209, [130] = 198, [131] = 187,
        [132] = 176, [133] = 165, [134] = 155, [135] = 144, [136] = 134, [137] = 123,
        [138] = 113, [139] = 103, [140] = 94, [141] = 84, [142] = 75, [143] = 65,
        [144] = 56,
        }
        local vfp = vfps[refresh]
        if vfp == nil then
            warn("Couldn't do refresh "..refresh.." on ONEXPLAYER 3 SDC OLED")
            return base_mode
        end
        local mode = base_mode
        gamescope.modegen.adjust_front_porch(mode, vfp)
        mode.vrefresh = gamescope.modegen.calc_vrefresh(mode)
        return mode
    end,
    hdr = {
        supported = true,
        force_enabled = true,
        eotf = gamescope.eotf.gamma22,
        max_content_light_level = 1100,
        max_frame_average_luminance = 472,
        min_content_light_level = 0.0005,
    },
    colorimetry = oxp3_oled_colorimetry,
    matches = function(display)
        if display.vendor == "SDC" and display.model ~= nil and string.match(display.model, "^%s*(.-)%s*$") == "AMS881KB01-0" then
            oxp3_gamma22_matched = true
            gamescope.convars.composite_force.value = true
            gamescope.log(gamescope.log_priority.info, "oxp3 gamma22 daily1100: maxCLL=1100 maxFALL=472; composite_force="..tostring(gamescope.convars.composite_force.value))
            return 6000
        end
        return -1
    end,
}
debug("oxp3: registered OXP3 SDC OLED with gamma22 HDR + 30-144Hz dynamic refresh (Deck-OLED style)")
