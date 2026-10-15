# Graphite Quiet asset record

Requested direction: default dark theme; low-luminance SteamOS / Windows silhouettes; coherent background and functional icons.

Wallpaper: generated with the built-in image_gen tool. Original clean background: exec-5c4903f8-6782-4f5d-ba69-628bda496716.png. Shipping file: theme/background.png. On 2026-10-15 the user approved a bottom-right vertical controller legend and requested equal, more generous row gaps. The shipping wallpaper now includes only that static legend; system tiles, logos, functional tools, selection and native status remain separate runtime UI.

Final edited generation: exec-8a3220ec-5c88-420a-aeef-b290a3da664a.png, copied unchanged from built-in image_gen output (1584 by 993 RGB PNG). Labels: D-pad / Select, A / Confirm, B / Back, matching gamepad.ini. The two visible vertical gaps measure 52 and 51 pixels at source resolution. The clean background remains recoverable from Git; the local pre-replacement copy is work/refind-controller-legend-20261015/background-before.png.

Controller legend edit prompt:

> Edit the clean graphite wallpaper using the approved preview as a style reference. Add only a bottom-right vertical stack of D-pad Select, circular A Confirm, circular B Back. Keep the center empty for authentic runtime UI. Match the muted slate silver icon family and Outfit-style text; align icons vertically and labels to the left. Increase the vertical blank gaps, keep B near the lower inset, and make the visible gap from D-pad to A equal to the gap from A to B. Preserve graphite arcs, low luminance and landscape composition; no panels, glow, colored buttons or extra text.

Generation prompt:

> Use case: stylized-concept. Asset type: production background wallpaper for a handheld gaming PC dark rEFInd dual-boot menu, landscape 16:10, 1920x1200. Primary request: quiet premium almost-black charcoal wallpaper, precise minimal graphic design. A few very large, subtle graphite sculptural arcs sweeping along the far left and right edges, barely illuminated soft satin edges, like dark industrial design paper relief. Huge completely uncluttered central negative space for two system logo controls that will be overlaid later, and clear quiet top and bottom regions for interface text. Entire picture is low luminance, charcoal black #0b0e12 with extremely restrained cool gray #191e25 relief, no blue glow, no light hotspots, no bright highlights. Mood: calm, premium, discreet. Absolutely NO logo, no text, no letters, no icons, no buttons, no interface mockup, no grid, no noise, no starfield, no mountains, no watermark. Background artwork only, edge detail remains unobtrusive, center stays nearly flat dark charcoal.

UI assets: authored in code for crisp edges, consistent line weight and exact system names. The Steam mark uses the saved vector source, not a generated approximation. Icons remain darker than their text. The selection outline identifies focus without making the silhouette white. Eleven PNG icons, two selection plates and a 96-glyph font sprite are included; generators preserve source notes in PNG metadata.

The screenshot used to judge the delivered theme must come from the installed QEMU/OVMF menu, not a composited preview. Real-device firmware touch support and native resolution remain hardware test items.

2026-10-15 verification: the shipping assets were loaded by rEFInd in isolated QEMU/OVMF folder-backed EFI fixtures at 1280x800 and 1920x1200, with SteamOS, Windows and tool focus captures. The controller legend remains clear of the runtime UI and screen edges. Current capture: [controller legend menu](../../docs/refind-controller-menu.png). Local captures: work/refind-controller-legend-20261015/. Installation, exact wallpaper byte readback and uninstall restoration also passed on a disposable directory fixture; no physical-device installation or input test was performed in this change.
