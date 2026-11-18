"""Regression tests for the accent-colour mask's channel symmetry.

The mask used to widen the RED channel's tolerance band by an extra 30
(`tol + 30`) while leaving green and blue at `tol`. That made the same gate
measure a saturated accent far more loosely than a desaturated one: for a
neutral grey the red channel accepted a 70px band while green and blue
accepted 40px, so shadowed pixels of the very same grey fell outside the
mask and the measured ratio came out systematically low.

These tests pin the property that makes the mask meaningful: the accepted
set must be invariant under channel permutation, and must be symmetric for a
neutral (all-equal) target.
"""
import unittest

from core.quality import pixels


class ColorMaskSymmetryTests(unittest.TestCase):
    def _tables(self, rgb):
        return pixels._mask_tables(rgb)

    def _matches(self, px, tables):
        r, g, b = px
        t_r, t_g, t_b = tables
        return bool(t_r[r] and t_g[g] and t_b[b])

    def test_01_every_channel_gets_the_same_tolerance(self):
        """The three channels must use one tolerance, not a red-privileged one."""
        # A neutral grey: all three channels have the same target value, so all
        # three accepted bands must be identical.
        tables = self._tables((128, 128, 128))
        t_r, t_g, t_b = tables
        accepted_r = [v for v in range(256) if t_r[v]]
        accepted_g = [v for v in range(256) if t_g[v]]
        accepted_b = [v for v in range(256) if t_b[v]]
        self.assertEqual(accepted_r, accepted_g,
                         "red and green bands must match for a neutral target")
        self.assertEqual(accepted_g, accepted_b,
                         "green and blue bands must match for a neutral target")

    def test_02_neutral_grey_shadows_still_match(self):
        """A grey's darker/lighter shades must be inside the mask.

        Under the old red-privileged mask, a grey of 70 or 200 against a
        #808080 target failed to match, so an accent rendered in grey measured
        lower than the very same accent in a saturated hue.
        """
        tables = self._tables((128, 128, 128))
        for shade in (100, 128, 160):
            self.assertTrue(
                self._matches((shade, shade, shade), tables),
                f"neutral grey shade {shade} must match a #808080 target")

    def test_03_mask_is_invariant_under_channel_permutation(self):
        """Swapping channels of the target must swap the accepted set the same way.

        #E03A3A (red) and #3AE03A (green) must be treated symmetrically: the
        engine must not privilege red by name.
        """
        red_target = (0xE0, 0x3A, 0x3A)
        green_target = (0x3A, 0xE0, 0x3A)

        red_tables = self._tables(red_target)
        green_tables = self._tables(green_target)

        # The exact target always matches, in every channel position.
        self.assertTrue(self._matches(red_target, red_tables))
        self.assertTrue(self._matches(green_target, green_tables))

        # A pixel that is the red target's colour matches the red target;
        # the same numeric colour is judged the same way against the green
        # target (which has that value in the green slot, low elsewhere).
        self.assertTrue(self._matches((0xE0, 0x3A, 0x3A), red_tables))
        self.assertTrue(self._matches((0x3A, 0xE0, 0x3A), green_tables))

        # A saturated red pixel must NOT sneak into the green target's mask
        # merely because red used to be privileged.
        self.assertFalse(self._matches((0xE0, 0x3A, 0x3A), green_tables),
                         "a red-dominant pixel must not match a green target")

    def test_04_exact_target_still_matches_fully(self):
        """The existing contract: the exact target colour matches every pixel."""
        for target in ((0x3A, 0x6F, 0xE0), (0xE0, 0x3A, 0x3A),
                       (0x80, 0x80, 0x80), (0x00, 0xFF, 0x00)):
            w = h = 4
            frame = bytes(target) * (w * h)
            tables = self._tables(target)
            self.assertEqual(
                pixels.color_ratio_of_frame(frame, w, h, tables), 1.0,
                f"exact target {target} must fully match")

    def test_05_distant_colours_do_not_match(self):
        """A colour far from the target must not be counted as it."""
        tables = self._tables((0x3A, 0x6F, 0xE0))
        self.assertFalse(self._matches((0xE0, 0x3A, 0x3A), tables),
                         "red must not match a blue target")
        self.assertFalse(self._matches((0x00, 0x00, 0x00), tables),
                         "black must not match a blue target")


if __name__ == "__main__":
    unittest.main()
