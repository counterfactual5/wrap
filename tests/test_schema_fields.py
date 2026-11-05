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


class TestShotIdSafety(unittest.TestCase):
    """The shot id names directories under build/ and public/, so it must not
    be able to walk out of them."""

    def _spec(self, shot_id):
        return {
            "id": shot_id,
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }

    def test_00_ordinary_ids_are_accepted(self):
        for sid in ("shot-01", "real-h3-test", "a.b_c", "X9"):
            with self.subTest(sid=sid):
                self.assertEqual(validate(self._spec(sid)), [])

    def test_01_traversal_ids_are_rejected(self):
        for sid in ("../escape", "a/b", "..", "/abs", "with space"):
            with self.subTest(sid=sid):
                errs = validate(self._spec(sid))
                self.assertTrue(any("id must be" in e for e in errs),
                                f"{sid!r} was accepted: {errs}")

    def test_02_the_message_explains_why(self):
        errs = validate(self._spec("../escape"))
        self.assertTrue(any("build/" in e and "public/" in e for e in errs), errs)


class TestVibeValidation(unittest.TestCase):
    """`vibe: false` opts out of the baked ambience. The renderer compares it
    strictly against false, so a non-boolean would run the opposite of what
    the author wrote — the same class of bug as `plate`."""

    def _spec(self, vibe):
        return {
            "id": "vibe-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
            "vibe": vibe,
        }

    def test_00_booleans_are_accepted(self):
        for vibe in (True, False):
            with self.subTest(vibe=vibe):
                self.assertEqual(validate(self._spec(vibe)), [])

    def test_01_non_booleans_are_rejected(self):
        for vibe in ("no", "false", 0, 1, []):
            with self.subTest(vibe=vibe):
                errs = validate(self._spec(vibe))
                self.assertTrue(any("vibe must be" in e for e in errs),
                                f"vibe={vibe!r} was accepted: {errs}")

    def test_02_an_absent_vibe_is_accepted(self):
        spec = self._spec(True)
        del spec["vibe"]
        self.assertEqual(validate(spec), [])


class TestVideoZoomValidation(unittest.TestCase):
    """The renderer interpolates motion.zoom for video layers as well as ai
    layers; the validator must not refuse what the renderer can do."""

    def _spec(self, layer_type, zoom):
        return {
            "id": "zoom-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "l", "type": layer_type, "rect": [0, 0, 1080, 1920],
                        "z": 0, "asset": "a", "keyColor": "#070512",
                        "blend": "normal", "motion": {"type": "geometric",
                                                      "zoom": zoom}}],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }

    def test_00_video_layer_zoom_is_accepted(self):
        self.assertEqual(validate(self._spec("video", [1.0, 1.1])), [])

    def test_01_ai_layer_zoom_still_accepted(self):
        self.assertEqual(validate(self._spec("ai", [1.0, 1.1])), [])

    def test_02_the_numeric_bounds_apply_to_video_too(self):
        errs = validate(self._spec("video", [0.5, 1.5]))
        self.assertTrue(any("zoom must be" in e for e in errs), errs)

    def test_03_zoom_is_still_refused_on_other_layer_kinds(self):
        for layer_type in ("code", "text", "hud", "card"):
            with self.subTest(layer_type=layer_type):
                errs = validate(self._spec(layer_type, [1.0, 1.1]))
                self.assertTrue(any("zoom is only supported" in e for e in errs),
                                f"{layer_type} accepted a zoom: {errs}")


class TestNameValidation(unittest.TestCase):
    """Names that reach file paths must not be able to walk out of their
    directory: the shot id, the layer id, the asset name, the timeline id."""

    def _spec(self, **over):
        spec = {
            "id": "names-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }
        spec.update(over)
        return spec

    def test_00_layer_id_must_be_safe(self):
        for lid in ("../../evil", "a/b", "..", "with space"):
            with self.subTest(lid=lid):
                spec = self._spec()
                spec["layers"][0]["id"] = lid
                errs = validate(spec)
                self.assertTrue(any("layer id must be" in e for e in errs),
                                f"layer id {lid!r} was accepted: {errs}")

    def test_01_asset_name_must_be_safe(self):
        for asset in ("../../evil", "a/b", ".."):
            with self.subTest(asset=asset):
                spec = self._spec()
                spec["layers"][0] = {"id": "hero", "type": "ai", "asset": asset,
                                      "keyColor": "#070512", "blend": "normal",
                                      "rect": [0, 0, 1080, 1920], "z": 0}
                errs = validate(spec)
                self.assertTrue(any("asset must be" in e for e in errs),
                                f"asset {asset!r} was accepted: {errs}")

    def test_02_ordinary_layer_ids_and_assets_pass(self):
        for lid, asset in (("bg", "city-silhouette"), ("Hero-1", "a.b_c")):
            with self.subTest(lid=lid):
                spec = self._spec()
                spec["layers"][0] = {"id": lid, "type": "ai", "asset": asset,
                                      "keyColor": "#070512", "blend": "normal",
                                      "rect": [0, 0, 1080, 1920], "z": 0}
                self.assertEqual(validate(spec), [])

    def test_03_timeline_id_must_be_safe(self):
        from core.schema import validate_timeline
        for tid in ("../../evil", "a/b"):
            with self.subTest(tid=tid):
                errs = validate_timeline({"id": tid, "shots": ["spec/shot-01.poster.json"]})
                self.assertTrue(any("timeline id must be" in e for e in errs), errs)

    def test_04_an_ordinary_timeline_id_passes(self):
        from core.schema import validate_timeline
        self.assertEqual(
            validate_timeline({"id": "full-sequence",
                               "shots": ["spec/shot-01.poster.json"]}), [])
