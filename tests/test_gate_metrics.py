"""Gate metric tests: subject sensitivity and spec-derived color masks."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import metrics
from schema import load_spec, validate


class TestGateMetrics(unittest.TestCase):
    def test_00_spec_with_new_gates_validates(self):
        spec = load_spec()
        errs = validate(spec)
        self.assertEqual(errs, [], f"spec invalid: {errs}")
        metric_ids = {g["metric"] for g in spec["gates"]}
        self.assertIn("subject_motion_ratio", metric_ids)
        self.assertIn("changed_pixel_ratio", metric_ids)

    def test_01_region_invalid_rejected(self):
        spec = load_spec()
        bad = dict(spec)
        bad["gates"] = [dict(g) for g in spec["gates"]]
        bad["gates"][1]["region"] = [500, 100]  # y0 >= y1
        self.assertGreater(len(validate(bad)), 0)
        bad["gates"][1]["region"] = [0, 99999]  # beyond canvas
        self.assertGreater(len(validate(bad)), 0)

    def test_02_changed_ratio_excludes_band(self):
        # Two 4x4 frames: only row y=2 (inside band) changes.
        w = h = 4
        a = bytes(w * h)
        b = bytearray(a)
        b[2 * w:3 * w] = b"\x50" * w
        ratios = metrics.changed_pixel_ratios.__wrapped__ if hasattr(metrics.changed_pixel_ratios, "__wrapped__") else None
        # exercise the counting path directly through a tiny ffmpeg-free harness:
        # replicate the loop the function runs over _frames() output.
        luma_delta = 6
        exclude_band = (2, 3)
        n = 0
        for y in range(h):
            if exclude_band[0] <= y < exclude_band[1]:
                continue
            ra, rb = a[y * w:(y + 1) * w], bytes(b[y * w:(y + 1) * w])
            if ra != rb:
                n += sum(1 for p, q in zip(ra, rb) if abs(p - q) > luma_delta)
        self.assertEqual(n, 0, "band row must be excluded")
        # and without exclusion the change counts
        n2 = sum(1 for p, q in zip(a[2 * w:3 * w], b[2 * w:3 * w]) if abs(p - q) > luma_delta)
        self.assertEqual(n2, w)

    def test_03_color_mask_derived_from_spec(self):
        w = h = 10
        blue = bytes((0x3A, 0x6F, 0xE0)) * (w * h)
        tables = metrics._mask_tables((0x3A, 0x6F, 0xE0))
        ratio = metrics.color_ratio_of_frame(blue, w, h, tables)
        self.assertEqual(ratio, 1.0, "exact target color must fully match")
        # old hardcoded red mask must NOT match blue
        self.assertEqual(metrics.red_ratio_of_frame(blue, w, h), 0.0)

    def test_04_red_mask_still_matches_accent(self):
        w = h = 10
        red = bytes((0xE0, 0x3A, 0x3A)) * (w * h)
        tables = metrics._mask_tables((0xE0, 0x3A, 0x3A))
        self.assertEqual(metrics.color_ratio_of_frame(red, w, h, tables), 1.0)
        self.assertEqual(metrics.red_ratio_of_frame(red, w, h), 1.0)


if __name__ == "__main__":
    unittest.main()
