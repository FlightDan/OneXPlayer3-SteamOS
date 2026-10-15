---
name: Graphite Quiet
description: A restrained dark rEFInd menu with low-luminance system silhouettes.
colors:
  tile: "#12171D"
  silhouette: "#7D8792"
  label: "#C3CAD3"
  outline: "#303A45"
  selection-fill: "#1B2532"
  selection-outline: "#91ACC9"
  font-sprite-source: "#3C352C"
typography:
  system-label:
    fontFamily: "Outfit Regular"
    fontSize: "25px"
    fontWeight: 400
  tool-label:
    fontFamily: "Outfit Regular"
    fontSize: "14px"
    fontWeight: 400
  native-status:
    fontFamily: "DM Mono Regular"
    fontSize: "20px"
    fontWeight: 400
rounded:
  system-tile: "22px"
  system-selection: "30px"
  tool-selection: "22px"
components:
  system-tile:
    backgroundColor: "{colors.tile}"
    textColor: "{colors.label}"
    typography: "{typography.system-label}"
    rounded: "{rounded.system-tile}"
    size: "256px"
  system-selection:
    backgroundColor: "{colors.selection-fill}"
    rounded: "{rounded.system-selection}"
    size: "272px"
  tool:
    textColor: "{colors.label}"
    typography: "{typography.tool-label}"
    size: "96px"
  tool-selection:
    backgroundColor: "{colors.selection-fill}"
    rounded: "{rounded.tool-selection}"
    size: "112px"
---

# Design System: Graphite Quiet

## Overview

**Creative North Star: "Graphite Quiet"**

Darkness provides a calm field, with form appearing through restrained changes in value. Broad graphite arcs stay near the margins; the central space belongs to two recognizable silhouettes. Meticulous edges and balanced negative space give the composition its finish.

This identity is local to rEFInd; the Windows installer's WPF design system is separate. The confirmed direction is default dark, with low-luminance SteamOS and Windows silhouettes and a coherent background and functional icon family.

**Key Characteristics:**

- Dim silhouettes on graphite surfaces.
- Clear external selection contours and quiet labels.
- Large system targets above compact functional tools.
- Uncluttered central space within subtle edge artwork.

## Colors

Charcoal, slate and soft silver form the palette. Frontmatter owns the authored UI colors. The primary accent is `selection-outline`, supported by `selection-fill`. Neutral `tile` and `outline` establish resting tiles; `silhouette` unifies all marks and `label` provides stronger text contrast.

**The Quiet Silhouette Rule.** Keep marks dimmer than labels; communicate selection through the external contour.

The wallpaper is an image rather than a flat color token. `theme/background.png` includes the approved bottom-right controller legend; its provenance is recorded in [ASSETS.md](ASSETS.md).

## Typography

Outfit Regular labels are rasterized into the system and tool PNGs at the frontmatter sizes. DM Mono Regular supplies the native rEFInd status sprite, with 96 glyph cells of 12 by 28 pixels.

rEFInd complements sprite RGB on the dark backdrop: `font-sprite-source` is an encoding value that displays as `label`, not a visible text color.

**The Firmware Text Rule.** Judge status text in the running menu after inversion, not by viewing the font sprite alone.

## Layout

Two square system targets sit above Power, Restart, Firmware and Info, with native status text beneath. System assets are 256 pixels and tools 96 pixels; their external selection plates are 272 and 112 pixels respectively. Firmware determines final placement and resolution; there are no web breakpoints.

System labels are centered at (128, 199). The Steam mark occupies a 112-pixel square at (72, 43); Windows uses four 49-pixel panes with 6-pixel gaps. Tool labels are centered at (48, 71). Asset pixel sizes do not guarantee physical size on a device.

The static controller legend occupies the bottom-right wallpaper margin, with D-pad Select, A Confirm and B Back stacked vertically. Icons share a vertical centerline and labels share a left edge. Keep equal visible space between icon bounds, allowing for the cross being taller than the circular buttons: the approved source has 52 and 51 pixel gaps. The legend scales with the wallpaper; system icons and native status remain separate runtime elements.

## Elevation & Depth

UI assets use tonal layering and outlines, with no shadow or glow. Subtle wallpaper arcs provide depth at the margins. Selection adds a filled plate beneath the icon and a brighter outer contour while preserving the mark's brightness.

## Shapes

System tiles have gently rounded corners and a 1-pixel outline. Selection contours use a 3-pixel stroke and the frontmatter radii. Functional symbols primarily use 3-pixel strokes with 2-pixel internal details. Optical alignment connects the circular Steam mark, geometric Windows panes and compact tool symbols.

## Components

- **System tiles:** Authored SteamOS and Windows PNGs with explicit names; Steam uses the saved vector silhouette.
- **Selection plates:** Separate large and small plates behind the selected system or tool. Labels and marks stay stable across selection changes.
- **Functional tools:** Power, Restart, Firmware and Info use the same dim strokes and quiet labels.
- **Volume symbols:** Five 64-pixel assets share a drive outline; badges are hidden in the main menu.
- **Native status:** Runtime rEFInd text uses the complemented DM Mono sprite.

[build-refind-theme.py](../../scripts/build-refind-theme.py) authors SVG/Pillow UI assets using 4× supersampling and Lanczos reduction; generated wallpaper remains separate.

Visual review disposition: **Ship for the reviewed scope**, after correcting native font inversion. Published QEMU/OVMF reference captures: [SteamOS selected](../../docs/refind-dark-menu.png), [Windows selected](../../docs/refind-dark-windows.png) and [tool selected](../../docs/refind-dark-tools.png). Original working-directory captures remain local. Real-device firmware touch, hardware boot behavior and native device resolution remain untested by this visual review.

2026-10-15 controller legend update: [current menu capture](../../docs/refind-controller-menu.png), verified in QEMU/OVMF at 1280x800 and 1920x1200 with all three focus states. The earlier captures above document the original theme before the legend was added.

## Do's and Don'ts

- **Do** keep marks dimmer than labels.
- **Do** preserve the approved wallpaper legend spacing and author interactive UI separately.
- **Do** validate selection and status text in actual QEMU/OVMF captures.
- **Do** keep this identity scoped to rEFInd.
- **Don't** replace the saved Steam silhouette with a generated approximation.
- **Don't** add glow or brighten the selected silhouette.
- **Don't** treat emulator visual review as hardware or firmware touch certification.
