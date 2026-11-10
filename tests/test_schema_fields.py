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
                self.assertTrue(any("zoom is not supported" in e for e in errs),
                                f"{layer_type} accepted a zoom: {errs}")

    def test_04_code_layer_zoom_is_accepted_for_the_draws_the_renderer_prepares(self):
        # grid and dots go through PreparedLayer (remotion/Shot.tsx) — the same
        # component that interpolates motion.zoom for ai layers.
        for draw in ("grid", "dots"):
            with self.subTest(draw=draw):
                self.assertEqual(validate(self._spec("code", [1.0, 1.1], draw=draw)), [])

    def test_05_code_layer_zoom_is_refused_for_the_draws_the_renderer_ignores(self):
        # CodeLayerComp reads only motion.pan; a zoom there would be silently
        # dropped, so the validator has to keep refusing it.
        for draw in ("bar", "field", "path", "captions"):
            with self.subTest(draw=draw):
                errs = validate(self._spec("code", [1.0, 1.1], draw=draw))
                self.assertTrue(any("zoom is not supported" in e for e in errs),
                                f"code/{draw} accepted a zoom: {errs}")
                self.assertTrue(any("code" in e for e in errs),
                                f"the message does not name the layer kind: {errs}")

    def test_06_the_numeric_bounds_apply_to_code_layers_too(self):
        errs = validate(self._spec("code", [0.5, 1.5], draw="grid"))
        self.assertTrue(any("zoom must be" in e for e in errs), errs)


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
                errs = validate_timeline({"id": tid, "shots": ["tests/fixtures/shot-01.poster.json"]})
                self.assertTrue(any("timeline id must be" in e for e in errs), errs)

    def test_04_an_ordinary_timeline_id_passes(self):
        from core.schema import validate_timeline
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

    def test_01_text_field_types(self):
        base = {"id": "t", "type": "text", "text": "x", "rect": [0, 0, 10, 10], "z": 0}
        errs = validate(self._spec({**base, "fontSize": "big"}))
        self.assertTrue(any("fontSize" in e for e in errs), errs)
        errs = validate(self._spec({**base, "fontWeight": []}))
        self.assertTrue(any("fontWeight" in e for e in errs), errs)
        errs = validate(self._spec({**base, "subtext": 5}))
        self.assertTrue(any("subtext" in e for e in errs), errs)
        self.assertEqual(validate(self._spec({**base, "fontSize": 54,
                                              "fontWeight": 800,
                                              "subtext": "hi"})), [])

    def test_02_card_and_hud_types_are_enumerated(self):
        errs = validate(self._spec({"id": "c", "type": "card",
                                    "cardType": "timeline",
                                    "rect": [0, 0, 10, 10], "z": 0}))
        self.assertTrue(any("cardType must be one of" in e for e in errs), errs)
        errs = validate(self._spec({"id": "h", "type": "hud",
                                    "hudType": "unknown",
                                    "rect": [0, 0, 10, 10], "z": 0}))
        self.assertTrue(any("hudType must be one of" in e for e in errs), errs)
        for card in ("capsule", "formula", "quote"):
            with self.subTest(card=card):
                self.assertEqual(validate(self._spec(
                    {"id": "c", "type": "card", "cardType": card,
                     "rect": [0, 0, 10, 10], "z": 0})), [])
        # "scanline" was in the docs and the TS type but had no renderer
        # branch — it is not a drawable hud type.
        for hud in ("badge", "telemetry", "equalizer", "progress"):
            with self.subTest(hud=hud):
                self.assertEqual(validate(self._spec(
                    {"id": "h", "type": "hud", "hudType": hud,
                     "rect": [0, 0, 10, 10], "z": 0})), [])

    def test_03_scanline_is_not_a_hud_type(self):
        """It was listed in the docs and the TS type but had no renderer
        branch, so a spec using it drew nothing."""
        errs = validate(self._spec({"id": "h", "type": "hud",
                                    "hudType": "scanline",
                                    "rect": [0, 0, 10, 10], "z": 0}))
        self.assertTrue(any("hudType must be one of" in e for e in errs), errs)

    def test_04_card_details_must_be_a_list_of_objects(self):
        base = {"id": "c", "type": "card", "cardType": "quote",
                "rect": [0, 0, 10, 10], "z": 0}
        errs = validate(self._spec({**base, "details": "两行"}))
        self.assertTrue(any("details must be" in e for e in errs), errs)
        self.assertEqual(validate(self._spec(
            {**base, "details": [{"label": "a", "desc": "b"}]})), [])

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

    def test_09_carry_state_from(self):
        from core.schema import carry_state_from
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

    def test_10_rig_tools_pivot_split_and_poses(self):
        import os
        import tempfile
        from core import manifest, rig
        from core.png import write_png
        from tests.helpers import preserve_manifest

        # 1. Exact source-to-canvas pivot math (including aspect-preserving contain pad)
        piv = rig.source_to_canvas_pivot(896, 1200, [260, 290, 448, 600], 638, 612)
        self.assertEqual(piv, [579, 596])

        # 2. Test inspect_sprite, split_sprite, and derive_pose_preset with temporary assets
        tmp_src = "test-rig-hero"
        tmp_body = "test-rig-body"
        tmp_part = "test-rig-part"
        tmp_pose = "test-rig-shatter"
        created_files = [
            os.path.join(rig.ROOT, "assets", f"{n}.png")
            for n in (tmp_src, tmp_body, tmp_part, tmp_pose)
        ] + [os.path.join(rig.ROOT, "build", f"inspect_sprite_{tmp_src}.png")]

        with preserve_manifest():
            try:
                w, h = 120, 160
                buf = bytearray(b"\xff\xff\xff" * (w * h))
                # Draw a dark body (x: 30..70, y: 30..130) and a weapon (x: 70..100, y: 20..120)
                for y in range(20, 130):
                    for x in range(30, 100):
                        if (x <= 70 and y >= 30) or (x >= 70 and y <= 120):
                            idx = (y * w + x) * 3
                            buf[idx:idx + 3] = b"\x80\x20\x10"
                src_rel = f"assets/{tmp_src}.png"
                write_png(os.path.join(rig.ROOT, src_rel), w, h, bytes(buf))
                manifest.register("assets", tmp_src, src_rel, source="test")

                insp = rig.inspect_sprite(tmp_src, rect=[100, 100, 240, 320], joint=[70, 75])
                self.assertEqual(insp["canvas_pivot"], [240, 250])
                self.assertTrue(os.path.exists(os.path.join(rig.ROOT, insp["annotated_image"])))

                sp = rig.split_sprite(
                    tmp_src, tmp_body, tmp_part,
                    box=[70, 15, 105, 125], joint=[70, 75],
                    joint_radius=8, rect=[100, 100, 240, 320],
                )
                self.assertEqual(sp["canvas_pivot"], [240, 250])
                self.assertIsNotNone(manifest.verified("assets", tmp_body))
                self.assertIsNotNone(manifest.verified("assets", tmp_part))

                dp = rig.derive_pose_preset(tmp_body, tmp_pose, preset="shatter")
                self.assertEqual(dp["preset"], "shatter")
                self.assertIsNotNone(manifest.verified("assets", tmp_pose))
            finally:
                for p in created_files:
                    if os.path.exists(p):
                        os.remove(p)

    def test_11_gait_eases_and_caption_voiceover_sync(self):
        import os
        import tempfile
        from core import audio
        from core.schema import carry_state_from

        ai_base = _ai()
        # 1. Validate gait modes and parameters
        self.assertTrue(any("gait.mode" in e for e in validate(self._spec({**ai_base, "gait": {"mode": "teleport"}}))))
        self.assertTrue(any("gait.freq" in e for e in validate(self._spec({**ai_base, "gait": {"mode": "puppet", "freq": 0}}))))
        self.assertTrue(any("gait.range" in e for e in validate(self._spec({**ai_base, "gait": {"mode": "shudder", "range": [50, 20]}}))))
        # 2. Validate new eases (snap, overshoot, step) + valid gait
        valid_layer = {
            **ai_base,
            "gait": {"mode": "puppet", "freq": 4.2, "bob": 9, "sway": 4.0, "range": [0, 80]},
            "anim": {
                "x": [[0, -120], [40, 20, "snap"], [75, 220, "overshoot"], [100, 220, "step"]],
            },
        }
        self.assertEqual(validate(self._spec(valid_layer)), [])

        # 3. carry_state_from strips range on persistent gait and drops transient shudder
        carried = carry_state_from(self._spec(valid_layer), "shot-next")
        self.assertEqual(carried["layers"][0]["gait"], {"mode": "puppet", "freq": 4.2, "bob": 9, "sway": 4.0})
        shudder_spec = self._spec({**ai_base, "gait": {"mode": "shudder", "range": [10, 30]}})
        carried_shudder = carry_state_from(shudder_spec, "shot-next")
        self.assertNotIn("gait", carried_shudder["layers"][0])

        # 4. Validate caption-voiceover agreement (rejects mismatched script, accepts matching clauses)
        vo_text = "今天我们来聊聊这个话题，它背后的原理其实并不复杂。"
        bad_cap = {
            "id": "caps",
            "type": "code",
            "draw": "captions",
            "rect": [100, 900, 800, 100],
            "z": 5,
            "params": {
                "items": [{"frame": 0, "text": "完全无关的另一句话，和旁白没有任何对应关系。"}]
            },
        }
        s_bad = self._spec(bad_cap)
        s_bad["audio"] = {"voiceover": vo_text}
        errs = validate(s_bad)
        self.assertTrue(any("does not match audio.voiceover" in e for e in errs), errs)

        clauses = audio.clauses_from_boundaries(
            vo_text,
            [{"type": "SentenceBoundary", "offset_sec": 0.1, "duration_sec": 4.5, "text": vo_text}],
            total_duration=4.8,
            fps=30,
        )
        self.assertGreaterEqual(len(clauses), 2)
        good_cap = {
            **bad_cap,
            "params": {"items": [{"frame": c["frame"], "text": c["text"], "hl": c["hl"]} for c in clauses]},
        }
        s_good = self._spec(good_cap)
        s_good["audio"] = {"voiceover": vo_text}
        self.assertEqual(validate(s_good), [])

        # 5. Test opera percussion BGM synthesis
        with tempfile.TemporaryDirectory() as d:
            wav_path = os.path.join(d, "opera.wav")
            audio.generate_opera_bgm(1.5, fps=30, punches=[15, 30], out_path=wav_path)
            self.assertTrue(os.path.exists(wav_path))
            self.assertGreater(os.path.getsize(wav_path), 10000)

    def test_12_joint_derives_pivot_and_rejects_guessed_pivot(self):
        """A hinge pivot is a point on the source picture; a hand-guessed canvas
        pivot is what detached a sword hand from its sleeve."""
        import json
        import os
        import tempfile
        from core import manifest, schema
        from core.png import write_png
        from tests.helpers import preserve_manifest

        # `joint` only makes sense where S2 scales with aspect-preserving contain
        bad = validate(self._spec({**_ai(), "joint": [10, 10]}))
        self.assertTrue(any("joint needs cutout" in e for e in bad), bad)
        self.assertTrue(any("joint must be" in e for e in
                            validate(self._spec({**_ai(cutout=True), "joint": [1]}))))
        self.assertEqual(validate(self._spec({**_ai(cutout=True), "joint": [10, 10]})), [])

        name = "test-joint-part"
        asset = os.path.join(schema.ROOT, "assets", f"{name}.png")
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
        from core import rig, schema

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
        from core import schema

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
        from core import manifest, rig, schema
        from core.png import write_png
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
        sheet_path = os.path.join(schema.ROOT, "assets", f"{sheet_name}.png")

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
                self.assertTrue(os.path.exists(os.path.join(schema.ROOT, torso["path"])))
                self.assertTrue(os.path.exists(os.path.join(schema.ROOT, blade["path"])))

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
                          os.path.join(schema.ROOT, "assets", "test-mod-torso.png"),
                          os.path.join(schema.ROOT, "assets", "test-mod-blade.png")]:
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                        except OSError:
                            pass

    def test_16_puppet_quad_limb_topology_contract(self):
        """Anatomy Topology Contract: A humanoid puppet with articulated limbs must have
        both dual legs (front + back) and dual arms (front + back) to prevent amputee defects."""
        base_spec = {
            "id": "puppet-test",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 60,
            "gates": [{"id": "m", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
            "layers": [
                {
                    "id": "hero", "type": "ai", "asset": "hero-torso",
                    "rect": [200, 200, 200, 400], "z": 10,
                    "keyColor": "#ffffff", "blend": "normal"
                },
                {
                    "id": "hero-arm-front", "type": "ai", "asset": "hero-arm",
                    "parent": "hero", "rect": [200, 200, 100, 200], "z": 12,
                    "kit": {"type": "limb", "socket": [50, 100], "joint": [20, 20]},
                    "keyColor": "#ffffff", "blend": "normal"
                },
                {
                    "id": "hero-arm-back", "type": "ai", "asset": "hero-arm-back",
                    "parent": "hero", "rect": [200, 200, 100, 200], "z": 6,
                    "kit": {"type": "limb", "socket": [40, 95], "joint": [20, 20]},
                    "keyColor": "#ffffff", "blend": "normal"
                }
            ]
        }

        # 1. Torso + Dual Arms (no legs articulated) -> PASS
        errs = validate(base_spec)
        self.assertEqual(errs, [])

        # 2. Torso + Dual Arms + ONLY 1 LEG -> FAILS with one-legged defect warning
        bad_leg_spec = dict(base_spec)
        bad_leg_spec["layers"] = list(base_spec["layers"]) + [
            {
                "id": "hero-leg", "type": "ai", "asset": "hero-leg",
                "parent": "hero", "rect": [200, 200, 100, 200], "z": 9,
                "kit": {"type": "limb", "socket": [50, 350], "joint": [20, 20]},
                "keyColor": "#ffffff", "blend": "normal"
            }
        ]
        errs = validate(bad_leg_spec)
        self.assertTrue(any("humanoid puppet has only 1 leg" in e for e in errs),
                        f"Single-legged amputee puppet should be caught: {errs}")

        # 3. Torso + Dual Legs + ONLY 1 ARM -> FAILS with one-armed defect warning
        bad_arm_spec = {
            "id": "puppet-test",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 60,
            "gates": [{"id": "m", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
            "layers": [
                {
                    "id": "hero", "type": "ai", "asset": "hero-torso",
                    "rect": [200, 200, 200, 400], "z": 10,
                    "keyColor": "#ffffff", "blend": "normal"
                },
                {
                    "id": "hero-arm-front", "type": "ai", "asset": "hero-arm",
                    "parent": "hero", "rect": [200, 200, 100, 200], "z": 12,
                    "kit": {"type": "limb", "socket": [50, 100], "joint": [20, 20]},
                    "keyColor": "#ffffff", "blend": "normal"
                },
                {
                    "id": "hero-leg-front", "type": "ai", "asset": "hero-leg",
                    "parent": "hero", "rect": [200, 200, 100, 200], "z": 9,
                    "kit": {"type": "limb", "socket": [50, 350], "joint": [20, 20]},
                    "keyColor": "#ffffff", "blend": "normal"
                },
                {
                    "id": "hero-leg-back", "type": "ai", "asset": "hero-leg",
                    "parent": "hero", "rect": [200, 200, 100, 200], "z": 8,
                    "kit": {"type": "limb", "socket": [40, 345], "joint": [20, 20]},
                    "keyColor": "#ffffff", "blend": "normal"
                }
            ]
        }
        errs = validate(bad_arm_spec)
        self.assertTrue(any("humanoid puppet has only 1 arm" in e for e in errs),
                        f"Single-armed amputee puppet should be caught: {errs}")

        # 4. Torso + Dual Arms + Dual Legs (Complete 4 Limbs) -> PASS
        good_spec = dict(base_spec)
        good_spec["layers"] = list(base_spec["layers"]) + [
            {
                "id": "hero-leg-front", "type": "ai", "asset": "hero-leg",
                "parent": "hero", "rect": [200, 200, 100, 200], "z": 9,
                "kit": {"type": "limb", "socket": [50, 350], "joint": [20, 20]},
                "keyColor": "#ffffff", "blend": "normal"
            },
            {
                "id": "hero-leg-back", "type": "ai", "asset": "hero-leg",
                "parent": "hero", "rect": [200, 200, 100, 200], "z": 8,
                "kit": {"type": "limb", "socket": [40, 345], "joint": [20, 20]},
                "keyColor": "#ffffff", "blend": "normal"
            }
        ]
        errs = validate(good_spec)
        self.assertEqual(errs, [])



