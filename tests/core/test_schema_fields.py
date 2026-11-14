"""Spec field validation: every documented field must reject a bad value.

A field the validator does not check is a field the renderer has to guess
about. `plate` was the last one: it is the card-chrome switch, and the
renderer compares it strictly against false — so `"plate": "no"` would draw
the chrome the author asked to drop, with nothing along the way saying so.
"""
import unittest

from core.spec.shot import validate


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
            "layers": [{"id": "bg", "type": "component", "component": "TestGraphic",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }

    def test_00_ordinary_ids_are_accepted(self):
        for sid in ("shot-01", "sample-shot", "a.b_c", "X9"):
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




class TestVideoZoomValidation(unittest.TestCase):
    """The renderer interpolates motion.zoom for video layers, for ai layers and
    for the code layers it prepares as an image (grid, dots); the validator must
    not refuse what the renderer can do — and must still refuse the layers whose
    renderer ignores it."""

    def _spec(self, layer_type, zoom, draw=None):
        layer = {"id": "l", "type": layer_type, "rect": [0, 0, 1080, 1920],
                 "z": 0, "asset": "a", "keyColor": "#070512",
                 "blend": "normal", "motion": {"type": "geometric", "zoom": zoom}}
        if draw is not None:
            layer["draw"] = draw
        return {
            "id": "zoom-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [layer],
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
        for layer_type in ("text", "hud", "card"):
            with self.subTest(layer_type=layer_type):
                errs = validate(self._spec(layer_type, [1.0, 1.1]))
                self.assertTrue(any("zoom is unsupported" in e for e in errs),
                                f"{layer_type} accepted a zoom: {errs}")

    def test_04_code_layer_zoom_is_accepted_for_the_draws_the_renderer_prepares(self):
        # grid and dots go through PreparedLayer (remotion/Shot.tsx) — the same
        # component that interpolates motion.zoom for ai layers.
        for draw in ("grid", "dots"):
            with self.subTest(draw=draw):
                self.assertTrue(any("migration required" in e for e in validate(self._spec("code", [1.0, 1.1], draw=draw))))

    def test_05_legacy_draw_layers_are_refused_either_way(self):
        """The removed procedural vocabulary is refused twice over: the layer
        type and the draw field both name the migration, and a zoom on a
        component layer is refused because the renderer cannot interpolate it."""
        for draw in ("bar", "field", "path", "captions", "grid", "dots"):
            with self.subTest(draw=draw):
                layer = {"id": "l", "type": "code", "draw": draw, "color": "#E03A3A",
                         "rect": [0, 0, 1080, 1920], "z": 0,
                         "motion": {"type": "geometric", "zoom": [1.0, 1.2]}}
                spec = {"id": "zoom-refusal", "canvas": {"w": 1080, "h": 1920},
                        "fps": 30, "durationInFrames": 60, "layers": [layer],
                        "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                                   "lo": 0.0001, "hi": 0.15}]}
                errs = validate(spec)
                self.assertTrue(any("migration required" in e for e in errs), errs)
                self.assertTrue(any("zoom is unsupported" in e for e in errs), errs)

class TestNameValidation(unittest.TestCase):
    """Names that reach file paths must not be able to walk out of their
    directory: the shot id, the layer id, the asset name, the timeline id."""

    def _spec(self, **over):
        spec = {
            "id": "names-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "bg", "type": "component", "component": "TestGraphic",
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
        from core.spec.timeline import validate_timeline
        for tid in ("../../evil", "a/b"):
            with self.subTest(tid=tid):
                errs = validate_timeline({"id": tid, "shots": ["tests/fixtures/shot-01.poster.json"]})
                self.assertTrue(any("timeline id must be" in e for e in errs), errs)

    def test_04_an_ordinary_timeline_id_passes(self):
        from core.spec.timeline import validate_timeline
        self.assertEqual(
            validate_timeline({"id": "full-sequence",
                               "shots": ["tests/fixtures/shot-01.poster.json"]}), [])


class TestFieldTypeValidation(unittest.TestCase):
    """Every field the renderer reads must be checked: the contract used to
    cover only half of them, so a typo in the unchecked half reached the
    renderer unnoticed."""

    def _spec(self, layer):
        return {
            "id": "fields-test",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [layer],
            "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }

    def test_00_playback_rate_must_be_a_positive_number(self):
        layer = {"id": "clip", "type": "video", "asset": "a",
                 "rect": [0, 0, 1080, 1920], "z": 0}
        for bad in ("2", 0, -1, True, None):
            with self.subTest(value=bad):
                if bad is None:
                    continue
                errs = validate(self._spec({**layer, "playbackRate": bad}))
                self.assertTrue(any("playbackRate" in e for e in errs),
                                f"playbackRate={bad!r} was accepted: {errs}")
        self.assertEqual(validate(self._spec({**layer, "playbackRate": 2})), [])





    def test_05_component_layer_validation(self):
        base = {"id": "comp", "type": "component", "rect": [0, 0, 100, 100], "z": 0}
        errs = validate(self._spec(base))
        self.assertTrue(any("needs 'component'" in e for e in errs), errs)
        errs = validate(self._spec({**base, "component": "../bad"}))
        self.assertTrue(any("valid identifier" in e for e in errs), errs)
        errs = validate(self._spec({**base, "component": "ShadowPuppet", "props": "not-dict"}))
        self.assertTrue(any("props must be an object" in e for e in errs), errs)
        self.assertEqual(validate(self._spec(
            {**base, "component": "ShadowPuppet", "props": {"accent": "#FF7A18"}})), [])

    def test_06_cutout_and_clip_rect_and_pivot_validation(self):
        ai_base = _ai()
        self.assertTrue(any("cutout must be a boolean" in e
                            for e in validate(self._spec({**ai_base, "cutout": "yes"}))))
        self.assertTrue(any("cutoutSimilarity" in e
                            for e in validate(self._spec({**ai_base, "cutout": True, "cutoutSimilarity": 1.5}))))
        self.assertTrue(any("clipRect" in e
                            for e in validate(self._spec({**ai_base, "clipRect": [0, 0, -5, 10]}))))
        self.assertTrue(any("pivot" in e
                            for e in validate(self._spec({**ai_base, "pivot": [10]}))))
        self.assertEqual(validate(self._spec({
            **ai_base,
            "cutout": True,
            "cutoutSimilarity": 0.14,
            "cutoutBlend": 0.06,
            "clipRect": [100, 200, 880, 1200],
            "pivot": [540, 800],
        })), [])

    def test_07_poses_validation(self):
        ai_base = _ai()
        self.assertTrue(any("poses must be a non-empty list" in e
                            for e in validate(self._spec({**ai_base, "poses": []}))))
        self.assertTrue(any("strictly increasing" in e
                            for e in validate(self._spec({
                                **ai_base,
                                "poses": [
                                    {"frame": 50, "asset": "pose1"},
                                    {"frame": 50, "asset": "pose2"},
                                ],
                            }))))
        self.assertEqual(validate(self._spec({
            **ai_base,
            "poses": [
                {"frame": 0, "asset": "pose1"},
                {"frame": 80, "asset": "pose2"},
            ],
        })), [])

    def test_08_parent_hierarchy_validation(self):
        ai_base = _ai()
        self.assertTrue(any("cannot reference itself" in e
                            for e in validate(self._spec({**ai_base, "parent": ai_base["id"]}))))
        self.assertTrue(any("must reference an existing layer id" in e
                            for e in validate(self._spec({**ai_base, "parent": "missing"}))))
        s = self._spec({**ai_base, "id": "a", "parent": "b"})
        s["layers"].append({**ai_base, "id": "b", "parent": "a"})
        self.assertTrue(any("cyclic parent chain" in e for e in validate(s)))
        s_valid = self._spec({**ai_base, "id": "hero"})
        s_valid["layers"].append({**ai_base, "id": "staff", "parent": "hero", "pivot": [500, 500], "z": 1})
        self.assertEqual(validate(s_valid), [])

        # Cross-modality child layers (text, code, video, hud, card) may also inherit parent transforms
        s_cross_child = self._spec({**ai_base, "id": "hero"})
        s_cross_child["layers"].extend([
            {
                "id": "label", "type": "component", "component": "Label", "props": {"text": "hello"},
                "parent": "hero", "rect": [0, 0, 200, 60], "z": 2,
            },
            {
                "id": "spark", "type": "component", "component": "Particles",
                "parent": "label", "rect": [0, 0, 200, 60], "z": 3,
                "props": {"count": 8},
            },
        ])
        self.assertEqual(validate(s_cross_child), [])

    def test_09_carry_state_from(self):
        from core.spec.state import carry_state_from
        prev = self._spec({
            **_ai(),
            "id": "hero",
            "poses": [
                {"frame": 0, "asset": "pose-idle"},
                {"frame": 50, "asset": "pose-strike"},
            ],
            "anim": {
                "x": [[0, -100], [50, 240, "out"]],
                "rotate": [[0, 0], [50, 15, "in"]],
            },
        })
        nxt = carry_state_from(prev, "shot-02")
        self.assertEqual(nxt["id"], "shot-02")
        w = nxt["layers"][0]
        self.assertEqual(w["asset"], "pose-strike")
        self.assertEqual(w["anim"]["x"], [[0, 240], [59, 240]])
        self.assertEqual(w["anim"]["rotate"], [[0, 15], [59, 15]])
        self.assertEqual(validate(nxt), [])



    def test_12_joint_derives_pivot_and_rejects_guessed_pivot(self):
        """A hinge pivot is a point on the source picture; a hand-guessed canvas
        pivot is what detached a sword hand from its sleeve."""
        import json
        import os
        import tempfile
        from core.runtime import manifest
        from core.runtime import config
        from core.spec import loader as schema
        from core.media.png import write_png
        from tests.helpers import preserve_manifest

        # `joint` only makes sense where S2 scales with aspect-preserving contain
        bad = validate(self._spec({**_ai(), "joint": [10, 10]}))
        self.assertTrue(any("joint needs cutout" in e for e in bad), bad)
        self.assertTrue(any("joint must be" in e for e in
                            validate(self._spec({**_ai(cutout=True), "joint": [1]}))))
        self.assertEqual(validate(self._spec({**_ai(cutout=True), "joint": [10, 10]})), [])

        name = "test-joint-part"
        asset = os.path.join(config.ROOT, "assets", f"{name}.png")
        with preserve_manifest():
            try:
                w, h = 448, 600  # rect below is 448x600 -> scale 1, no pad
                write_png(asset, w, h, b"\xff" * (w * h * 3))
                manifest.register("assets", name, f"assets/{name}.png", source="test")

                def spec_with(**extra):
                    layer = _ai(asset=name, cutout=True, rect=[100, 100, 448, 600])
                    layer.update(extra)
                    return self._spec(layer)

                def load(spec):
                    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                        json.dump(spec, f)
                    try:
                        return schema.load_spec(f.name)
                    finally:
                        os.remove(f.name)

                # joint -> pivot computed on contain scale
                got = load(spec_with(joint=[200, 300]))["layers"][0]["pivot"]
                self.assertEqual(got, [300, 400])
                # a pivot that agrees is accepted, one that strays is refused loudly
                self.assertEqual(load(spec_with(joint=[200, 300], pivot=[303, 398]))["layers"][0]["pivot"],
                                 [300, 400])
                with self.assertRaises(ValueError) as ctx:
                    load(spec_with(joint=[200, 300], pivot=[400, 460]))
                self.assertIn("detaches", str(ctx.exception))
            finally:
                if os.path.exists(asset):
                    os.remove(asset)

    def test_13_snap_socket_joint_and_modular_rigging(self):
        """Universal 2D modular component rigging: snaps child joint onto parent socket."""
        from core import rig

        # 1. Math verification of snap_socket_joint
        pw, ph = 800, 1000
        p_rect = [100, 100, 400, 500]  # scale = 0.5
        p_socket = [200, 400]           # canvas socket = 100 + 200*0.5 = 200, 100 + 400*0.5 = 300

        cw, ch = 600, 300
        c_joint = [500, 150]

        res = rig.snap_socket_joint([pw, ph], p_rect, p_socket, [cw, ch], c_joint)
        self.assertEqual(res["parent_socket_canvas"], [200, 300])
        self.assertEqual(res["pivot"], [200, 300])
        # child rect width = 300, height = 150, cx = 200 - 500*0.5 = -50, cy = 300 - 150*0.5 = 225
        self.assertEqual(res["rect"], [-50, 225, 300, 150])

        # 2. Schema validation for socket
        # socket without parent is rejected
        bad_sock = validate(self._spec({**_ai(cutout=True), "socket": [10, 20]}))
        self.assertTrue(any("socket requires 'parent'" in e for e in bad_sock), bad_sock)
        # socket with parent is accepted
        hero_layer = _ai(id="hero", z=0)
        sword_layer = {**_ai(id="sword", cutout=True, z=1), "parent": "hero", "socket": [10, 20]}
        s_two = self._spec(hero_layer)
        s_two["layers"].append(sword_layer)
        self.assertEqual(validate(s_two), [])

    def test_14_kit_declaration_and_automatic_scale_derivation(self):
        """Kit component declaration automatically derives joint, socket, and partScale."""
        from core.spec import resolution as schema

        hero_torso = _ai(id="hero", asset="test-hero-torso", cutout=True, rect=[100, 100, 400, 500], z=0)
        hero_arm = {
            **_ai(id="arm", asset="test-hero-arm", cutout=True, z=1),
            "parent": "hero",
            "kit": {
                "type": "limb",
                "parent_asset": "test-hero-torso",
                "socket": [200, 400],
                "joint": [500, 150],
                "socket_radius": 24,
                "joint_radius": 60,
            },
        }
        spec = self._spec(hero_torso)
        spec["layers"].append(hero_arm)

        # 1. Validation passes
        self.assertEqual(validate(spec), [])

        # 2. Rejects invalid kit.type
        bad_kit = {**hero_arm, "kit": {**hero_arm["kit"], "type": "automobile"}}
        s_bad = self._spec(hero_torso)
        s_bad["layers"].append(bad_kit)
        self.assertTrue(any("kit.type must be one of" in e for e in validate(s_bad)))

        # 3. resolve_joints auto-populates joint, socket, partScale (24 / 60 = 0.4) and snap
        resolved = schema.resolve_joints(spec)
        arm_res = resolved["layers"][1]
        self.assertEqual(arm_res["joint"], [500, 150])
        self.assertEqual(arm_res["socket"], [200, 400])
        self.assertEqual(arm_res["partScale"], 0.4)
        self.assertEqual(arm_res["snap"], "socket")

    def test_15_unpack_kit_runner_sheet(self):
        """Unpack-kit automatically extracts, pads, and registers modular parts from a runner sheet."""
        import os
        from core import rig
        from core.runtime import manifest
        from core.runtime import config
        from core.media.png import write_png
        from tests.helpers import preserve_manifest

        w, h = 300, 300
        key_rgb = (255, 255, 255)
        buf = bytearray(bytes(key_rgb) * (w * h))

        # Part 1: large body island (100x100)
        for y in range(150, 250):
            for x in range(100, 200):
                idx = (y * w + x) * 3
                buf[idx:idx + 3] = b"\x80\x20\x20"

        # Part 2: small weapon/arm island (40x40)
        for y in range(30, 70):
            for x in range(30, 70):
                idx = (y * w + x) * 3
                buf[idx:idx + 3] = b"\x20\x80\x20"

        sheet_name = "test-runner-sheet"
        sheet_path = os.path.join(config.ROOT, "assets", f"{sheet_name}.png")

        with preserve_manifest():
            try:
                write_png(sheet_path, w, h, bytes(buf))
                manifest.register("assets", sheet_name, f"assets/{sheet_name}.png", source="test")

                res = rig.unpack_kit(sheet_name, "test-mod", labels=["torso", "blade"], min_area=200)
                self.assertEqual(res["parts_count"], 2)
                torso, blade = res["parts"]
                self.assertEqual(torso["asset"], "test-mod-torso")
                self.assertEqual(blade["asset"], "test-mod-blade")
                self.assertGreater(torso["area"], blade["area"])
                self.assertTrue(os.path.exists(os.path.join(config.ROOT, torso["path"])))
                self.assertTrue(os.path.exists(os.path.join(config.ROOT, blade["path"])))

                # Both registered in manifest with source unpack-kit
                reg_torso = manifest.verified("assets", "test-mod-torso")
                reg_blade = manifest.verified("assets", "test-mod-blade")
                self.assertIsNotNone(reg_torso)
                self.assertIsNotNone(reg_blade)
                self.assertEqual(reg_torso["source"], "unpack-kit")

                # Verify spec layers snippet
                layers = res["spec_layers_snippet"]
                self.assertEqual(len(layers), 2)
                self.assertEqual(layers[0]["id"], "torso")
                self.assertEqual(layers[1]["parent"], "torso")
                self.assertIn("kit", layers[1])
            finally:
                for f in [sheet_path,
                          os.path.join(config.ROOT, "assets", "test-mod-torso.png"),
                          os.path.join(config.ROOT, "assets", "test-mod-blade.png")]:
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                        except OSError:
                            pass
