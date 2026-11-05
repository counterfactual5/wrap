"""Spec field validation: every documented field must reject a bad value.

A field the validator does not check is a field the renderer has to guess
about. `plate` was the last one: it is the card-chrome switch, and the
renderer compares it strictly against false — so `"plate": "no"` would draw
the chrome the author asked to drop, with nothing along the way saying so.
"""
import unittest

from core.schema import validate


def _spec(layer):
    return {
        "id": "fields",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [layer],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }


def _ai(**extra):
    layer = {"id": "hero", "type": "ai", "asset": "a", "keyColor": "#070512",
             "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


def _video(**extra):
    layer = {"id": "clip", "type": "video", "asset": "v",
             "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


class TestPlateValidation(unittest.TestCase):
    def test_00_non_boolean_plate_is_rejected(self):
        for bad in ("no", "false", 0, 1, [], {}):
            with self.subTest(plate=bad):
                errs = validate(_spec(_ai(plate=bad)))
                self.assertTrue(any("plate" in e for e in errs),
                                f"plate={bad!r} was accepted: {errs}")

    def test_01_the_message_says_what_is_allowed(self):
        errs = validate(_spec(_ai(plate="no")))
        self.assertTrue(any("true or false" in e for e in errs), errs)

    def test_02_boolean_plate_is_accepted(self):
        self.assertEqual(validate(_spec(_ai(plate=True))), [])
        self.assertEqual(validate(_spec(_ai(plate=False))), [])

    def test_03_absent_plate_is_accepted(self):
        self.assertEqual(validate(_spec(_ai())), [])

    def test_04_video_layer_plate_is_checked_too(self):
        errs = validate(_spec(_video(plate="x")))
        self.assertTrue(any("plate" in e for e in errs), errs)
        self.assertEqual(validate(_spec(_video(plate=False))), [])


class TestOtherFieldsStillChecked(unittest.TestCase):
    """The plate check must not have displaced the others."""

    def test_00_blend_is_an_enum(self):
        errs = validate(_spec(_ai(blend="Multiply")))
        self.assertTrue(any("blend" in e for e in errs), errs)

    def test_01_draw_is_an_enum(self):
        errs = validate(_spec({"id": "c", "type": "code", "draw": "Grid",
                               "rect": [0, 0, 1080, 1920], "z": 0}))
        self.assertTrue(any("draw" in e for e in errs), errs)

    def test_02_loop_and_muted_are_booleans(self):
        for field in ("loop", "muted"):
            with self.subTest(field=field):
                errs = validate(_spec(_video(**{field: "yes"})))
                self.assertTrue(any(field in e for e in errs), errs)

    def test_03_prompt_must_be_a_string(self):
        errs = validate(_spec(_ai(prompt=123)))
        self.assertTrue(any("prompt" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
