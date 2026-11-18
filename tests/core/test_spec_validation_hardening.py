"""Spec validation hardening: every field the pipeline reads must be checked.

A field the validator does not check is a field the renderer has to guess
about — and a guess that fails in S4 (after a full render) or that produces
a *wrong number* (a negative luma threshold makes every pixel look changed)
is worse than a refusal, because nothing says the output is wrong.

Each test below pins one defect: it fails against the pre-fix validator and
passes against the fixed one.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from core.runtime import manifest
from core.spec.channels import validate_captions_against_voiceover
from core.spec.loader import load_spec
from core.spec.shot import validate
from core.spec.state import carry_state_from
from core.spec.timeline import validate_timeline


def _spec(layer=None, gates=None, **over):
    """A minimal shot spec: one component layer, one motion gate."""
    spec = {
        "id": "hardening",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [layer if layer is not None else
                   {"id": "bg", "type": "component", "component": "Backdrop",
                    "rect": [0, 0, 1080, 1920], "z": 0}],
        "gates": gates if gates is not None else
                 [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }
    spec.update(over)
    return spec


def _ai(**extra):
    layer = {"id": "hero", "type": "ai", "asset": "hero", "keyColor": "#070512",
             "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


class TestLayerZIsDeclared(unittest.TestCase):
    """Defect 1: `z` was not checked at all.

    The renderer stacks the layers by z (remotion/Shot.tsx sorts on it), so
    a missing or non-integer z leaves the stacking order to chance — and two
    layers without a z used to trip a FALSE "duplicate z None".
    """

    def test_00_z_must_be_present_and_an_int(self):
        for bad in ("missing", None, "top", 1.5, True):
            with self.subTest(z=bad):
                layer = {"id": "bg", "type": "component", "component": "Backdrop",
                         "rect": [0, 0, 1080, 1920]}
                if bad != "missing":
                    layer["z"] = bad
                errs = validate(_spec(layer))
                self.assertTrue(any("z must be an int" in e for e in errs),
                                f"z={bad!r} was accepted: {errs}")
                self.assertTrue(any(e.startswith("bg:") for e in errs),
                                f"the error must name the layer: {errs}")

    def test_01_two_layers_without_z_do_not_report_a_duplicate(self):
        spec = _spec()
        spec["layers"] = [
            {"id": "a", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10]},
            {"id": "b", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10]},
        ]
        errs = validate(spec)
        self.assertFalse(any("duplicate z" in e for e in errs),
                         f"a missing z is not a duplicate: {errs}")
        self.assertEqual(len([e for e in errs if "z must be an int" in e]), 2, errs)

    def test_02_a_real_duplicate_is_still_reported(self):
        spec = _spec()
        spec["layers"] = [
            {"id": "a", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10], "z": 3},
            {"id": "b", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10], "z": 3},
        ]
        errs = validate(spec)
        self.assertTrue(any("duplicate z 3" in e for e in errs), errs)

    def test_03_ordinary_z_values_pass(self):
        spec = _spec()
        spec["layers"] = [
            {"id": "a", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10], "z": 0},
            {"id": "b", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10], "z": 1},
        ]
        self.assertEqual(validate(spec), [])


class TestGateBoundsAreNumbers(unittest.TestCase):
    """Defect 2: the gate's lo/hi were compared without a type check.

    A string bound passed validation and only blew up in S4 — after the
    whole shot had been rendered — or crashed the validator itself.
    """

    def _gate(self, **gate):
        base = {"id": "m", "metric": "changed_pixel_ratio", "lo": 0.0, "hi": 1.0}
        base.update(gate)
        return validate(_spec(gates=[base]))

    def test_00_string_bounds_are_refused(self):
        errs = self._gate(lo="0.1", hi="0.9")
        self.assertTrue(any("lo must be a number" in e for e in errs), errs)
        self.assertTrue(any("hi must be a number" in e for e in errs), errs)

    def test_01_mixed_types_do_not_crash_the_validator(self):
        errs = self._gate(lo="0.1", hi=0.9)
        self.assertTrue(any("lo must be a number" in e for e in errs), errs)
        self.assertFalse(any("hi must be a number" in e for e in errs), errs)

    def test_02_bounds_still_compare_when_both_are_numbers(self):
        errs = self._gate(lo=0.9, hi=0.1)
        self.assertTrue(any("lo > hi" in e for e in errs), errs)

    def test_03_a_bool_is_not_a_bound(self):
        errs = self._gate(lo=True)
        self.assertTrue(any("lo must be a number" in e for e in errs), errs)

    def test_04_ordinary_bounds_pass(self):
        self.assertEqual(self._gate(lo=0.0001, hi=0.15), [])


class TestGateKnobsArePositiveNumbers(unittest.TestCase):
    """Defect 3: lumaDelta / ring / tol were read by the pipeline but never
    checked. A NEGATIVE lumaDelta is not a failure — it is a wrong number:
    `abs(p - q) > -3` is always true, so the measured ratio is always 1.0.
    """

    def _gate(self, **gate):
        base = {"id": "m", "metric": "changed_pixel_ratio", "lo": 0.0, "hi": 1.0}
        base.update(gate)
        return validate(_spec(gates=[base]))

    def test_00_luma_delta_must_be_a_positive_number(self):
        for bad in ("six", -3, 0, True):
            with self.subTest(lumaDelta=bad):
                errs = self._gate(lumaDelta=bad)
                self.assertTrue(any("lumaDelta must be a positive number" in e
                                    for e in errs), f"{bad!r} was accepted: {errs}")

    def test_01_ring_and_tol_must_be_positive_numbers(self):
        for knob in ("ring", "tol"):
            for bad in ("wide", -1, 0):
                with self.subTest(knob=knob, value=bad):
                    errs = self._gate(**{knob: bad})
                    self.assertTrue(any(f"{knob} must be a positive number" in e
                                        for e in errs), f"{bad!r} was accepted: {errs}")

    def test_02_positive_knobs_pass(self):
        self.assertEqual(self._gate(lumaDelta=6, ring=8, tol=12), [])


class TestSpringChannelsAreDeclared(unittest.TestCase):
    """Defect 4: a null spring channel skipped the membership check and the
    renderer merged it into 'rotate' — the engine ships no defaults, so a
    spring must not silently drive a channel the author never named.
    """

    def _spring(self, **spring):
        base = {"omega": 10, "zeta": 0.5, "coupling": 1, "maxAccel": 100,
                "channel": "x", "driverChannel": "rotate"}
        base.update(spring)
        layer = {"id": "bg", "type": "component", "component": "Backdrop",
                 "rect": [0, 0, 1080, 1920], "z": 0, "spring": base}
        return validate(_spec(layer))

    def test_00_a_null_channel_is_refused(self):
        errs = self._spring(channel=None)
        self.assertTrue(any("spring.channel must be one of" in e for e in errs), errs)
        self.assertTrue(any("no default spring channel" in e for e in errs), errs)

    def test_01_a_null_driver_channel_is_refused(self):
        errs = self._spring(driverChannel=None)
        self.assertTrue(any("spring.driverChannel must be one of" in e for e in errs), errs)

    def test_02_an_unknown_channel_is_refused(self):
        errs = self._spring(channel="opacity")
        self.assertTrue(any("spring.channel must be one of" in e for e in errs), errs)

    def test_03_declared_channels_pass(self):
        self.assertEqual(self._spring(), [])


class TestImageReferenceChecksTheTargetLayerType(unittest.TestCase):
    """Defect 5: the reference check compared the name against the set of
    ai ASSET names while looking it up among the layer IDS, so the type
    check was skipped whenever a name was both.
    """

    def _spec(self):
        spec = _spec()
        spec["layers"] = [
            # an ai layer whose ASSET is named "hero" ...
            _ai(id="body", asset="hero"),
            # ... and a COMPONENT layer whose ID is "hero"
            {"id": "hero", "type": "component", "component": "Backdrop",
             "rect": [0, 0, 10, 10], "z": 1},
            # ... which a third layer then names as its image source
            _ai(id="user", asset="other", input_asset="hero"),
        ]
        return spec

    def test_00_a_component_layer_cannot_be_an_image_source(self):
        errs = validate(self._spec())
        self.assertTrue(any("must reference an ai layer or a frozen image asset" in e
                            for e in errs), errs)

    def test_01_an_ai_layer_id_is_a_valid_image_source(self):
        spec = _spec()
        spec["layers"] = [
            _ai(id="body", asset="hero", z=0),
            _ai(id="user", asset="other", z=1, input_asset="body"),
        ]
        self.assertEqual(validate(spec), [])


class TestCarryStateCarriesOnlyLayers(unittest.TestCase):
    """Defect 6: the next shot inherited the previous shot's audio, so it
    read out the previous narration. Gates are per-shot acceptance
    thresholds, not layer state either.
    """

    def _prev(self):
        return _spec(audio={"voiceover": "Old narration line", "voice": "Narrator",
                            "bgm": "bed.wav"})

    def test_00_audio_is_not_carried(self):
        out = carry_state_from(self._prev(), "shot-02")
        self.assertNotIn("audio", out)
        self.assertEqual(out.get("audio"), None)

    def test_01_gates_are_reset(self):
        out = carry_state_from(self._prev(), "shot-02")
        self.assertEqual(out["gates"], [])

    def test_02_tracks_are_reset_and_layers_are_carried(self):
        prev = _spec(audio={"voiceover": "Old narration line"})
        prev["layers"] = [_ai(anim={"x": [[0, 0], [50, 240]]})]
        out = carry_state_from(prev, "shot-02")
        self.assertEqual(out["tracks"], {"captions": [], "events": []})
        self.assertEqual(out["layers"][0]["anim"]["x"], [[0, 240], [59, 240]])
        self.assertEqual(out["id"], "shot-02")


class TestCaptionsShareTheVoiceoverSourceOfTruth(unittest.TestCase):
    """Defect 7: the captions/voiceover check existed but nothing called it,
    so hand-written captions were never compared with the spoken line.
    """

    VOICEOVER = "The quick brown fox jumps over the lazy dog"

    def _spec(self, captions, voiceover=None):
        spec = _spec()
        spec["tracks"] = {"captions": captions, "events": []}
        if voiceover is not None:
            spec["audio"] = {"voiceover": voiceover, "voice": "Narrator"}
        return spec

    def test_00_a_caption_that_is_not_spoken_is_refused(self):
        errs = validate(self._spec(
            [{"frame": 0, "text": "entirely unrelated narration"}], self.VOICEOVER))
        self.assertTrue(any("does not match audio.voiceover" in e for e in errs), errs)

    def test_01_a_caption_that_is_spoken_passes(self):
        errs = validate(self._spec(
            [{"frame": 0, "text": "the lazy dog"}], self.VOICEOVER))
        self.assertEqual(errs, [])

    def test_02_a_voiceover_that_is_a_file_path_is_not_compared(self):
        errs = validate(self._spec(
            [{"frame": 0, "text": "entirely unrelated narration"}], "narration.wav"))
        self.assertEqual(errs, [])

    def test_03_no_voiceover_means_nothing_to_compare(self):
        errs = validate(self._spec([{"frame": 0, "text": "anything at all"}]))
        self.assertEqual(errs, [])

    def test_04_the_helper_is_still_reachable_and_usable(self):
        errs = []
        validate_captions_against_voiceover(
            [{"frame": 0, "text": "entirely unrelated narration"}],
            self.VOICEOVER, "shot-01", errs)
        self.assertTrue(errs)


class TestMalformedSpecsReportErrorsInsteadOfCrashing(unittest.TestCase):
    """Defect 8: a wrong type escaped as a bare traceback instead of the
    "invalid spec: ..." message the CLI contract promises.
    """

    def test_00_a_non_object_canvas_is_an_error(self):
        errs = validate(_spec(canvas="1080x1920"))
        self.assertTrue(any("canvas must be an object" in e for e in errs), errs)

    def test_01_null_layers_and_gates_are_errors(self):
        for key in ("layers", "gates"):
            with self.subTest(key=key):
                spec = _spec()
                spec[key] = None
                errs = validate(spec)
                self.assertTrue(any(f"{key} must be a list" in e for e in errs), errs)

    def test_02_a_gate_that_is_not_an_object_is_an_error(self):
        errs = validate(_spec(gates=["not-a-gate"]))
        self.assertTrue(any("gate must be an object" in e for e in errs), errs)

    def test_03_a_non_object_motion_is_an_error(self):
        layer = {"id": "bg", "type": "component", "component": "Backdrop",
                 "rect": [0, 0, 1080, 1920], "z": 0, "motion": "geometric"}
        errs = validate(_spec(layer))
        self.assertTrue(any("motion must be an object" in e for e in errs), errs)

    def test_04_a_non_string_layer_type_is_an_error(self):
        layer = {"id": "bg", "type": [], "rect": [0, 0, 1080, 1920], "z": 0}
        errs = validate(_spec(layer))
        self.assertTrue(any("type must be a string" in e for e in errs), errs)

    def test_05_a_non_string_anim_ease_is_an_error(self):
        layer = {"id": "bg", "type": "component", "component": "Backdrop",
                 "rect": [0, 0, 1080, 1920], "z": 0,
                 "anim": {"x": [[0, 0], [30, 5, ["bad"]]]}}
        errs = validate(_spec(layer))
        self.assertTrue(any("ease must be one of" in e for e in errs), errs)

    def test_06_a_spec_that_is_not_an_object_is_an_error(self):
        self.assertEqual(validate(["not", "a", "spec"]), ["spec must be an object"])

    def test_07_load_spec_reports_an_invalid_spec_as_a_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.json")
            with open(path, "w") as f:
                json.dump({"id": "x", "canvas": "nope", "fps": 30,
                           "durationInFrames": 60, "layers": [], "gates": []}, f)
            with self.assertRaises(ValueError) as ctx:
                load_spec(path)
            self.assertIn("invalid spec", str(ctx.exception))


class TestKeyColorIsCheckedLikeAColor(unittest.TestCase):
    """Defect 9: a null keyColor crashed the validator instead of being
    reported as a bad colour.
    """

    def test_00_a_null_key_color_is_an_error(self):
        errs = validate(_spec(_ai(keyColor=None)))
        self.assertTrue(any("keyColor must be #rrggbb" in e for e in errs), errs)

    def test_01_a_valid_key_color_passes(self):
        self.assertEqual(validate(_spec(_ai())), [])


class TestTimelineShotPathsStayInsideTheProject(unittest.TestCase):
    """Defect 10: the shot's spec path was only checked for existence, so a
    number reached the pipeline (and crashed it) and a `..` path walked out
    of the project root.
    """

    def test_00_a_non_string_spec_path_is_refused(self):
        errs = validate_timeline({"id": "t", "shots": [{"spec": 42}]})
        self.assertTrue(any("must be a non-empty string" in e for e in errs), errs)

    def test_01_a_traversing_path_is_refused(self):
        for bad in ("../../evil.json", "spec/../../evil.json", "a/../b.json"):
            with self.subTest(path=bad):
                errs = validate_timeline({"id": "t", "shots": [{"spec": bad}]})
                self.assertTrue(any(".." in e for e in errs),
                                f"{bad!r} was accepted: {errs}")
                errs = validate_timeline({"id": "t", "shots": [bad]})
                self.assertTrue(any(".." in e for e in errs),
                                f"{bad!r} was accepted: {errs}")

    def test_02_an_absolute_path_outside_the_project_is_refused(self):
        errs = validate_timeline({"id": "t", "shots": [{"spec": "/etc/hosts"}]})
        self.assertTrue(any("absolute path" in e for e in errs), errs)

    def test_03_ordinary_relative_paths_pass(self):
        self.assertEqual(
            validate_timeline({"id": "t", "shots": ["tests/fixtures/shot-01.poster.json"]}),
            [])
        self.assertEqual(
            validate_timeline({"id": "t", "shots": [
                {"spec": "spec/shot-01.poster.json", "beat": "hook", "reason": "x"}]}),
            [])


class TestManifestToleratesANullSection(unittest.TestCase):
    """Defect 11: `setdefault` only fills a MISSING key, so a hand-trimmed
    `{"assets": null}` survived and crashed the ledger on the next read or
    write.
    """

    def _ledger(self, tmp, payload):
        path = os.path.join(tmp, "manifest.json")
        with open(path, "w") as f:
            json.dump(payload, f)
        return path

    def test_00_a_null_section_is_normalized_to_an_empty_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._ledger(tmp, {"assets": None, "prepared": {}, "video": None})
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": path}):
                ledger = manifest.load()
                self.assertEqual(ledger["assets"], {})
                self.assertEqual(ledger["video"], {})

    def test_01_verified_does_not_crash_on_a_null_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._ledger(tmp, {"assets": None, "prepared": {}, "video": {}})
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": path}):
                self.assertIsNone(manifest.verified("assets", "anything"))

    def test_02_register_writes_into_a_null_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._ledger(tmp, {"assets": None, "prepared": {}, "video": {}})
            asset = os.path.join(tmp, "asset.bin")
            with open(asset, "wb") as f:
                f.write(b"asset")
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": path}), \
                    mock.patch.object(manifest, "ROOT", tmp):
                row = manifest.register("assets", "thing", "asset.bin")
                self.assertEqual(row["path"], "asset.bin")
                self.assertIsNotNone(manifest.verified("assets", "thing"))


class TestTruncatedPngDoesNotEscapeResolution(unittest.TestCase):
    """Defect 12: struct.error is neither an OSError nor a ValueError, so a
    truncated PNG escaped the error handling as a traceback instead of
    leaving the layer alone.
    """

    def test_00_a_truncated_asset_is_left_alone(self):
        from core.spec import resolution as schema

        with tempfile.TemporaryDirectory() as tmp:
            name = "truncated-png-asset"
            rel = "assets/%s.png" % name
            asset = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(asset), exist_ok=True)
            with open(asset, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")  # header only — no size chunk
            ledger = os.path.join(tmp, "manifest.json")
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": ledger}), \
                    mock.patch.object(manifest, "ROOT", tmp), \
                    mock.patch.object(schema, "ROOT", tmp):
                manifest.register("assets", name, rel, source="test")
                spec = _spec(_ai(asset=name, cutout=True,
                                  cutoutSimilarity=0.14, cutoutBlend=0.06,
                                  joint=[10, 10]))
                resolved = schema.resolve_joints(spec)
            # The layer is left exactly as authored — no pivot is invented.
            self.assertNotIn("pivot", resolved["layers"][0])

    def test_01_a_truncated_asset_is_left_alone_by_load_spec(self):
        from core.spec import resolution as schema

        with tempfile.TemporaryDirectory() as tmp:
            name = "truncated-png-spec-asset"
            rel = "assets/%s.png" % name
            asset = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(asset), exist_ok=True)
            with open(asset, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
            ledger = os.path.join(tmp, "manifest.json")
            spec_path = os.path.join(tmp, "shot.poster.json")
            with open(spec_path, "w") as f:
                json.dump(_spec(_ai(asset=name, cutout=True,
                                    cutoutSimilarity=0.14, cutoutBlend=0.06,
                                    joint=[10, 10])), f)
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": ledger}), \
                    mock.patch.object(manifest, "ROOT", tmp), \
                    mock.patch.object(schema, "ROOT", tmp):
                manifest.register("assets", name, rel, source="test")
                loaded = load_spec(spec_path)
            self.assertEqual(loaded["layers"][0]["asset"], name)


class TestAnimScaleIsPositive(unittest.TestCase):
    """Defect 13: opacity was bounded but scale was not, so scale(0) made a
    layer invisible and a negative scale mirrored it — a silent mirror the
    engine already expresses with flipX.
    """

    def _anim(self, channel, values):
        layer = {"id": "bg", "type": "component", "component": "Backdrop",
                 "rect": [0, 0, 1080, 1920], "z": 0,
                 "anim": {channel: [[0, values[0]], [30, values[1]]]}}
        return validate(_spec(layer))

    def test_00_a_zero_or_negative_scale_is_refused(self):
        for bad in (0, -2):
            with self.subTest(scale=bad):
                errs = self._anim("scale", [1, bad])
                self.assertTrue(any("anim.scale values must be > 0" in e for e in errs),
                                f"scale={bad} was accepted: {errs}")

    def test_01_opacity_still_keeps_its_own_bound(self):
        errs = self._anim("opacity", [0, 5])
        self.assertTrue(any("anim.opacity values must be within [0, 1]" in e
                            for e in errs), errs)

    def test_02_a_positive_scale_passes(self):
        self.assertEqual(self._anim("scale", [1, 1.5]), [])


class TestPoseAssetsAreManifestAssetNames(unittest.TestCase):
    """Defect 14: a pose asset was checked with valid_name only, so
    "hero.png" passed — a name that can never be a manifest key, and that
    only failed much later in S2/S4.
    """

    def _pose(self, asset):
        return validate(_spec(_ai(poses=[{"frame": 0, "asset": asset}])))

    def test_00_a_pose_asset_with_an_extension_is_refused(self):
        errs = self._pose("hero.png")
        self.assertTrue(any("manifest asset" in e for e in errs), errs)

    def test_01_a_pose_asset_with_a_path_is_refused(self):
        errs = self._pose("assets/hero")
        self.assertTrue(any("manifest asset" in e for e in errs), errs)

    def test_02_a_bare_pose_asset_passes(self):
        self.assertEqual(self._pose("hero-pose"), [])


class TestTimelineRejectsUnknownKeys(unittest.TestCase):
    """Defect 15: the continuity block refused unknown keys while the
    timeline's own top level and its shot entries accepted anything.
    """

    def test_00_an_unknown_top_level_key_is_refused(self):
        errs = validate_timeline({"id": "t", "shots": ["a.json"], "typo_key": 1})
        self.assertTrue(any("unknown key 'typo_key'" in e for e in errs), errs)

    def test_01_an_unknown_shot_key_is_refused(self):
        errs = validate_timeline({"id": "t", "shots": [{"spec": "a.json", "typo": 1}]})
        self.assertTrue(any("unknown key 'typo'" in e for e in errs), errs)

    def test_02_the_known_keys_are_accepted(self):
        errs = validate_timeline({
            "id": "t",
            "bgm": "bed.wav",
            "bgmUnderVoice": 0.24,
            "allow_black": True,
            "allow_bgm_override_silent": False,
            "continuity": {"max_char_jump_px": 18.0,
                           "require_seamless_handoff": True,
                           "min_visible_opacity": 0.2},
            "shots": [{"spec": "a.json", "beat": "hook", "reason": "the opening"}],
        })
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
