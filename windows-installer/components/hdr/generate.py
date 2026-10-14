"""Emit the hardened maintained profile; deployment and compatibility are separate."""
from pathlib import Path


def validate(source):
    required = (
        'max_content_light_level = 1100,', 'max_frame_average_luminance = 472,',
        'min_content_light_level = 0.0005,', 'eotf = gamescope.eotf.gamma22,',
        'string.match(display.model, "^%s*(.-)%s*$") == "AMS881KB01-0"',
        'gamescope.hook("OnPostPaint", function()', 'local oxp3_gamma22_matched = false',
        '[60] = 1904', '[144] = 56',
    )
    if any(source.count(item) != 1 for item in required):
        raise RuntimeError('Maintained HDR template is missing or duplicates an accepted anchor')
    if source.count('gamescope.convars.composite_force.value = true') != 2 or 'max_frame_average_luminance = 475' in source:
        raise RuntimeError('HDR composition/mapping regressed')
    return source


def generate():
    return validate(Path(__file__).with_name('upstream.lua').read_text(encoding='utf-8'))


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2: raise SystemExit('Usage: generate.py OUTPUT.lua')
    Path(sys.argv[1]).write_text(generate(), encoding='utf-8')