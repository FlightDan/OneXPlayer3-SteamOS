import unittest
from generate import generate, validate

class HdrRegression(unittest.TestCase):
    def test_repeated_generation_keeps_accepted_mapping(self):
        first = generate()
        self.assertEqual(first, generate())
        for expected in ('max_content_light_level = 1100,', 'max_frame_average_luminance = 472,', 'eotf = gamescope.eotf.gamma22,'):
            self.assertIn(expected, first)
    def test_panel_and_composition_are_scoped(self):
        source = generate()
        self.assertIn('== "AMS881KB01-0"', source)
        self.assertIn('display.vendor == "SDC"', source)
        self.assertEqual(source.count('gamescope.hook("OnPostPaint"'), 1)
        self.assertNotIn('string.find(display.model, "AMS881KB01"', source)
    def test_existing_colorimetry_and_mode_anchors_remain(self):
        source = generate()
        for expected in ('r = { x = 0.6835, y = 0.3154 }', '[60] = 1904', '[144] = 56'):
            self.assertIn(expected, source)
        self.assertNotIn('intel_backlight', source)
    def test_older_or_missing_composition_is_refused(self):
        for stale in (generate().replace('max_frame_average_luminance = 472', 'max_frame_average_luminance = 475'),
                      generate().replace('gamescope.hook("OnPostPaint", function()', '-- removed callback')):
            with self.assertRaises(RuntimeError): validate(stale)

if __name__ == '__main__': unittest.main()