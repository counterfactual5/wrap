"""The removed vocabulary must be refused, loudly — never silently ignored.

Zero-template migration: layer types are only `ai` / `video` / `component`,
the procedural draw vocabulary is gone, and the shadow-puppet aesthetic
checks are gone with it. A legacy spec (code / text / hud / card layers,
`draw`, `plate`, `gait`, `punches`, `vibe`, caption `hl`/`size` styling,
…) must produce an explicit migration error from the validator and from
`load_spec` — a silent ignore would render something different from what
the author wrote, which is the worst possible outcome.

The renderer side is pinned too: an unknown layer type must reach a LOUD
throw (`Unsupported layer type`), parsed live from the renderer source —
no fallback artwork.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.spec import constants  # noqa: E402
from core.spec.loader import load_spec  # noqa: E402
from core.spec.shot import validate  # noqa: E402
from tests.contract.agreement import (  # noqa: E402
    parse_layer_types,
    renderer_layer_types,
    strip_comments,
    _renderer_source,
)


def _spec(layer=None, **extra):
    spec = {
        "id": "migration-probe",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [layer] if layer else [],
        "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
        "tracks": {"captions": [], "events": []},
    }
    spec.update(extra)
    return spec


def _ai(**extra):
    layer = {"id": "hero", "type": "ai", "asset": "a", "keyColor": "#070512",
             "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


class TestRemovedLayerTypesAreRefused(unittest.TestCase):
    def test_00_every_legacy_type_is_named_and_refused(self):
        for ltype in ("code", "text", "hud", "card", "image", "scene"):
            with self.subTest(ltype=ltype):
                errs = validate(_spec({"id": "l", "type": ltype,
                                       "rect": [0, 0, 1080, 1920], "z": 0}))
                self.assertTrue(
                    any("migration required" in e and "type must be one of" in e
                        for e in errs),
                    f"legacy type {ltype!r} was not refused with a migration "
                    f"error: {errs}")

    def test_01_the_message_names_the_surviving_vocabulary(self):
        errs = validate(_spec({"id": "l", "type": "text", "text": "hi",
                               "rect": [0, 0, 1080, 1920], "z": 0}))
        joined = "\n".join(errs)
        for t in ("ai", "video", "component"):
            self.assertIn(f"'{t}'", joined)

    def test_02_the_renderer_throws_on_unknown_types(self):
        """The renderer's own gate: an unknown type must throw, parsed live
        from the renderer source — never a fallback drawing."""
        src = strip_comments(_renderer_source())
        self.assertRegex(src, r"Unsupported layer type")
        # And the renderer only branches on the contract's media/component
        # vocabulary plus loud-refused compatibility aliases (checked in
        # test_contract_agreement); no legacy type may come back as a branch.
        for ltype in ("code", "text", "hud", "card"):
            self.assertNotIn(ltype, renderer_layer_types(),
                             f"legacy type {ltype!r} reappeared as a renderer branch")


class TestRemovedFieldsAreRefused(unittest.TestCase):
    def test_00_removed_renderer_draw_fields(self):
        for field, value in (
            ("draw", "grid"), ("params", {"items": []}),
            ("text", "hello"), ("fontSize", 64), ("fontWeight", "bold"),
            ("subtext", "under"), ("color", "#E03A3A"),
            ("hudType", "badge"), ("cardType", "capsule"),
            ("details", []), ("title", "t"), ("quote", "q"),
        ):
            with self.subTest(field=field):
                errs = validate(_spec(_ai(**{field: value})))
                self.assertTrue(
                    any("migration required: removed field" in e
                        and f"'{field}'" in e for e in errs),
                    f"removed field {field!r} was silently accepted: {errs}")

    def test_01_removed_aesthetic_fields(self):
        for field, value in (
            ("plate", False), ("gait", {"mode": "walk", "freq": 2}),
            ("depth", 0.5), ("translucent", True),
            ("shadowColor", "#001122"), ("controlRod", True),
            ("rodAnchor", [0.5, 0.5]), ("rodAnchors", [[0.5, 0.5]]),
        ):
            with self.subTest(field=field):
                errs = validate(_spec(_ai(**{field: value})))
                self.assertTrue(
                    any("migration required: removed field" in e for e in errs),
                    f"removed field {field!r} was silently accepted: {errs}")

    def test_02_removed_shot_fields(self):
        for field, value in (
            ("vibe", False), ("vibe_grade", True), ("ambient", False),
            ("punches", [12]), ("captions", []), ("events", []),
        ):
            with self.subTest(field=field):
                errs = validate(_spec(**{field: value}))
                self.assertTrue(
                    any("migration required: removed root field" in e for e in errs),
                    f"removed root field {field!r} was silently accepted: {errs}")

    def test_03_removed_audio_ambient_switch(self):
        errs = validate(_spec(audio={"ambient": True}))
        self.assertTrue(any("migration required" in e for e in errs), errs)

    def test_04_removed_motion_pan(self):
        errs = validate(_spec(_ai(motion={"type": "geometric", "pan": [0, 40]})))
        self.assertTrue(any("migration required" in e and "pan" in e for e in errs), errs)

    def test_05_removed_anim_depth_channel(self):
        errs = validate(_spec(_ai(anim={"depth": [[0, 0.0], [30, 1.0]]})))
        self.assertTrue(any("anim channel" in e for e in errs), errs)

    def test_06_removed_caption_styling_in_tracks(self):
        errs = validate(_spec(tracks={"captions": [
            {"frame": 0, "text": "hi", "hl": "hi", "size": 36}]}))
        self.assertTrue(
            any("migration required" in e and "nonvisual" in e for e in errs),
            f"caption styling fields were silently accepted: {errs}")

    def test_07_load_spec_surfaces_migration_errors(self):
        import json
        import tempfile
        spec = _spec({"id": "l", "type": "text", "text": "hi",
                      "rect": [0, 0, 1080, 1920], "z": 0})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "legacy.poster.json")
            with open(path, "w") as f:
                json.dump(spec, f)
            with self.assertRaises(ValueError) as ctx:
                load_spec(path)
        self.assertIn("migration required", str(ctx.exception))


class TestSurvivingVocabularyStillWorks(unittest.TestCase):
    def test_00_tracks_shape_is_accepted(self):
        spec = _spec(tracks={
            "captions": [{"frame": 0, "end_frame": 30, "text": "hello"},
                         {"frame": 31, "text": "world"}],
            "events": [{"frame": 12, "kind": "contact"}],
        })
        self.assertEqual(validate(spec), [])

    def test_01_tracks_shape_is_checked(self):
        errs = validate(_spec(tracks={"captions": "nope"}))
        self.assertTrue(any("tracks.captions must be a list" in e for e in errs), errs)
        errs = validate(_spec(tracks={"captions": [{"frame": 5, "text": ""}]}))
        self.assertTrue(any("text must be non-empty" in e for e in errs), errs)
        errs = validate(_spec(tracks={"captions": [{"frame": 9, "end_frame": 4, "text": "x"}]}))
        self.assertTrue(any("end_frame" in e for e in errs), errs)
        errs = validate(_spec(tracks={"captions": [{"frame": 9, "text": "b"}, {"frame": 9, "text": "a"}]}))
        self.assertTrue(any("strictly increasing" in e for e in errs), errs)
        # Arbitrary project-defined named timing tracks are now allowed. They
        # still have to be ordered, frame-based lists of objects.
        errs = validate(_spec(tracks={"mood": []}))
        self.assertEqual(errs, [])
        errs = validate(_spec(tracks={"mood": [{"frame": 0, "kind": "calm"}]}))
        self.assertEqual(errs, [])
        errs = validate(_spec(tracks={"mood": [{"kind": "calm"}]}))
        self.assertTrue(any("frame" in e for e in errs), errs)
        errs = validate(_spec(tracks={"mood": [{"frame": 0}, {"frame": -1}]}))
        self.assertTrue(any("non-negative integer" in e for e in errs), errs)
        errs = validate(_spec(tracks={"mood": [{"frame": 4}, {"frame": 3}]}))
        self.assertTrue(any("tracks.mood.frame must be" in e and "non-decreasing" in e for e in errs), errs)
        errs = validate(_spec(tracks={"captions": [{"text": "no frame"}]}))
        self.assertTrue(any("non-negative integer" in e for e in errs), errs)

    def test_02_component_props_are_free(self):
        layer = {"id": "l", "type": "component", "component": "Anything",
                 "rect": [0, 0, 1080, 1920], "z": 0,
                 "props": {"text": "标题", "colors": ["#fff", "#000"],
                           "nested": {"any": [1, 2, 3]}}}
        self.assertEqual(validate(_spec(layer)), [])

    def test_03_color_gates_need_an_explicit_color(self):
        spec = _spec(gates=[{"id": "accent", "metric": "accent_color_ratio",
                             "lo": 0.0, "hi": 0.5}])
        errs = validate(spec)
        self.assertTrue(any("explicit color" in e or "color must be explicit" in e
                            for e in errs),
                        "a color gate without an explicit color was accepted")
        spec["gates"][0]["color"] = "red"
        errs = validate(spec)
        self.assertTrue(any("color must be explicit" in e for e in errs), errs)
        spec["gates"][0]["color"] = "#E03A3A"
        self.assertEqual(validate(spec), [])
        spec["gates"][0]["metric"] = "red_pixel_ratio"
        self.assertEqual(validate(spec), [])

    def test_04_the_draw_vocabulary_is_gone_everywhere(self):
        self.assertEqual(set(constants.DRAWS), set())
        # And the renderer source no longer dispatches on a draw axis at all.
        src = strip_comments(_renderer_source())
        self.assertNotRegex(src, r"layer\.draw\s*===?")


if __name__ == "__main__":
    unittest.main()
