"""Video layer tests: spec validation, S1 transport, S2 preparation.

A video layer is a first-class asset type: the spec declares it, S1 freezes
a clip for it, S2 prepares a scaled copy. These tests cover the contract
without spending generation credits — the backend is stubbed and the clip
used is the deterministic local fixture.
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.spec.shot import validate

_spec = importlib.util.spec_from_file_location(
    "s1_generate_v", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

# The video transport lives in core/generation/video.py; wait_for_video /
# download_video look up their collaborators in THAT module's namespace, so
# mocks target gen_video (s1 re-exports only what main() calls directly).
from core.generation import video as gen_video


def _video_spec(**over):
    spec = {
        "id": "video-test",
        "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [
            {"id": "clip", "type": "video", "asset": "clip-a",
             "rect": [0, 0, 1080, 1920], "z": 0},
        ],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
    }
    spec.update(over)
    return spec


class TestVideoSpecValidation(unittest.TestCase):
    def test_00_video_layer_is_a_valid_type(self):
        errs = validate(_video_spec())
        self.assertEqual(errs, [], f"a well-formed video layer was rejected: {errs}")

    def test_01_video_layer_requires_asset(self):
        spec = _video_spec()
        del spec["layers"][0]["asset"]
        errs = validate(spec)
        self.assertTrue(any("asset" in e for e in errs), errs)

    def test_02_video_layer_rejects_bad_fit(self):
        spec = _video_spec()
        spec["layers"][0]["fit"] = "squish"
        errs = validate(spec)
        self.assertTrue(any("fit" in e for e in errs), errs)

    def test_03_video_layer_rejects_bad_trim(self):
        spec = _video_spec()
        spec["layers"][0]["trim"] = [5, 1]  # end before start
        errs = validate(spec)
        self.assertTrue(any("trim" in e for e in errs), errs)

    def test_04_video_layer_accepts_valid_trim(self):
        spec = _video_spec()
        spec["layers"][0]["trim"] = [0.5, 3.0]
        self.assertEqual(validate(spec), [])

    def test_05_video_layer_rejects_non_boolean_loop(self):
        spec = _video_spec()
        spec["layers"][0]["loop"] = "yes"
        errs = validate(spec)
        self.assertTrue(any("loop" in e for e in errs), errs)


class TestVideoTransport(unittest.TestCase):
    """S1 must drive the async submit -> poll -> download path."""

    def test_00_submit_returns_task_id(self):
        captured = {}

        def fake_call(tool, payload, timeout=None):
            captured["tool"] = tool
            captured["payload"] = payload
            return {"task_id": "999", "status": "submitted", "model": payload["model"]}

        with mock.patch.object(gen_video, "_connector_call", side_effect=fake_call):
            task_id, model = s1.submit_video_generation(
                "a calm wave", model="MiniMax-H3-Max", duration=5,
                ratio="9:16", resolution="768P")
        self.assertEqual(task_id, "999")
        self.assertEqual(model, "MiniMax-H3-Max")
        self.assertEqual(captured["tool"], "connector__matrix__submit_video_generation")
        self.assertEqual(captured["payload"]["duration"], 5)
        self.assertEqual(captured["payload"]["ratio"], "9:16")

    def test_01_submit_rejects_duration_outside_model_range(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("x", model="MiniMax-H3-Max", duration=2)
        self.assertIn("duration", str(ctx.exception))

    def test_02_submit_rejects_unknown_model(self):
        with self.assertRaises(RuntimeError):
            s1.submit_video_generation("x", model="SomeOtherModel")

    def test_03_submit_rejects_unsupported_resolution(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("x", model="MiniMax-H3-Max", duration=5,
                                       resolution="2K")
        self.assertIn("resolution", str(ctx.exception))

    def test_04_wait_polls_until_succeeded(self):
        statuses = [
            {"status": "submitted"},
            {"status": "running"},
            {"status": "succeeded", "node_id": "42", "video_url": "https://x.invalid/v.mp4"},
        ]
        calls = []

        def fake_query(task_id, model):
            calls.append(task_id)
            return statuses[len(calls) - 1]

        with mock.patch.object(gen_video, "query_video_generation", side_effect=fake_query), \
             mock.patch.object(gen_video.time, "sleep"):
            data = s1.wait_for_video("42", "MiniMax-H3-Max", interval=0)
        self.assertEqual(data["status"], "succeeded")
        self.assertEqual(len(calls), 3)

    def test_05_wait_raises_on_failed_task(self):
        with mock.patch.object(gen_video, "query_video_generation",
                               return_value={"status": "failed", "detail": "nope"}):
            with self.assertRaises(RuntimeError) as ctx:
                s1.wait_for_video("42", "MiniMax-H3-Max", interval=0)
        self.assertIn("failed", str(ctx.exception))

    def test_06_download_uses_node_id_when_url_absent(self):
        with mock.patch.object(gen_video, "fetch_asset_url", return_value="https://x.invalid/v.mp4") as fu, \
             mock.patch.object(gen_video, "download_file") as df:
            s1.download_video({"node_id": "42"}, "/tmp/out.mp4")
        fu.assert_called_once_with("42")
        df.assert_called_once_with("https://x.invalid/v.mp4", "/tmp/out.mp4")


class TestVideoModelCatalog(unittest.TestCase):
    """The catalog is the doc's source of truth for model capabilities."""

    def test_00_known_models(self):
        self.assertIn("MiniMax-H3", s1.VIDEO_MODELS)
        self.assertIn("MiniMax-H3-Max", s1.VIDEO_MODELS)
        self.assertIn("MiniMax-Hailuo-2.3", s1.VIDEO_MODELS)

    def test_01_h3_has_native_audio_hailuo_does_not(self):
        self.assertTrue(s1.VIDEO_MODELS["MiniMax-H3"]["audio"])
        self.assertFalse(s1.VIDEO_MODELS["MiniMax-Hailuo-2.3"]["audio"])

    def test_02_duration_ranges_match_backend_contract(self):
        self.assertEqual((s1.VIDEO_MODELS["MiniMax-H3"]["min_dur"],
                          s1.VIDEO_MODELS["MiniMax-H3"]["max_dur"]), (4, 15))
        self.assertEqual((s1.VIDEO_MODELS["MiniMax-H3-Max"]["min_dur"],
                          s1.VIDEO_MODELS["MiniMax-H3-Max"]["max_dur"]), (5, 15))
        self.assertEqual((s1.VIDEO_MODELS["MiniMax-Hailuo-2.3"]["min_dur"],
                          s1.VIDEO_MODELS["MiniMax-Hailuo-2.3"]["max_dur"]), (6, 10))


class TestVideoFixture(unittest.TestCase):
    """The fixture path must produce a real, playable mp4 without credits."""

    def test_00_fixture_is_a_real_mp4(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "clip.mp4")
            s1._write_video_fixture(out, seconds=1)
            self.assertTrue(os.path.exists(out))
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_name,width,height", "-of", "csv=p=0", out],
                capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertIn("h264", probe.stdout)


class TestVideoEndToEnd(unittest.TestCase):
    """A spec with a video layer must survive S1 -> S4 end to end.

    Uses the fixture transport (no generation credits): S1 writes a local
    deterministic clip, S2 scales it, S3 renders it, S4 gates it. A video
    layer that renders but freezes would fail the motion/freeze gates —
    which is exactly the class of bug this path exists to catch.
    """

    def test_00_video_spec_runs_through_the_gates(self):
        spec = {
            "id": "video-e2e",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "vibe": False,
            "style": "tests/fixtures/style-quantum.json",
            "layers": [
                {"id": "clip", "type": "video", "asset": "video-e2e-clip",
                 "rect": [0, 0, 1080, 1920], "z": 0, "plate": False},
                {"id": "title", "type": "text", "text": "video layer",
                 "rect": [60, 1500, 960, 120], "fontSize": 72, "z": 2},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }
        # The temp spec lives under .tmp/ (gitignored): a spec file in spec/ would
        # be an untracked file, and a tree snapshot taken while it exists
        # would read the file's removal as "the tree changed".
        spec_path = os.path.join(ROOT, ".tmp", "video-e2e.poster.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        from tests.helpers import preserve_manifest
        with preserve_manifest():
            try:
                # --fixture: build the clip locally. The test must never call
                # the generation backend — it would spend credits and be flaky.
                for stage, extra in (("01_generate.py", ["--fixture"]),
                                     ("02_prepare.py", []),
                                     ("03_compose.py", [])):
                    res = subprocess.run(
                        [sys.executable, os.path.join("stages", stage),
                         "--spec", spec_path] + extra,
                        cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0,
                                     f"{stage} failed:\n{res.stdout}\n{res.stderr}")

                res = subprocess.run(
                    [sys.executable, "stages/04_gate.py", "--spec", spec_path],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0,
                                 f"S4 rejected the video layer:\n{res.stdout}\n{res.stderr}")

                with open(os.path.join(ROOT, "build", "gates", "video-e2e.json")) as f:
                    gates = json.load(f)
                for g in gates:
                    self.assertTrue(g["pass"], f"gate {g['id']} failed: {g}")

                # The clip must actually move: a rendered-but-static video
                # layer would slip past a green gate only if the metric never
                # ran.
                motion = next((g for g in gates if g["id"] == "motion"), None)
                self.assertIsNotNone(motion)
                self.assertGreater(motion["value"], 0.0001,
                                   "video layer rendered a frozen image")
            finally:
                # Remove the asset file; the ledger is restored wholesale by
                # preserve_manifest (a row-by-row cleanup would leave the rows
                # S2/S3 added for this shot behind, and the working tree dirty).
                for path in (spec_path,
                             os.path.join(ROOT, "assets", "video-e2e-clip.mp4")):
                    if os.path.exists(path):
                        os.remove(path)


class TestVideoFirstFrameAndReferenceValidation(unittest.TestCase):
    """Task C: Video first_frame / last_frame / reference_images validation and S1 unified dispatch."""

    def test_00_first_frame_payload_has_input_image_url_first_frame_and_adaptive_ratio(self):
        """A video layer declaring first_frame sends input_image.url, reference_type='first_frame', and ratio='adaptive' across all 3 origins (code grid/dots, ai asset, manifest asset)."""
        from tests.helpers import preserve_manifest

        for origin_kind, first_ref in (("code", "bg"), ("manifest", "city-silhouette"), ("ai", "ai-plate")):
            with self.subTest(origin=origin_kind):
                layers = [
                    {"id": "bg", "type": "code", "draw": "grid", "rect": [0, 0, 1080, 1920], "z": 0},
                    {"id": "clip", "type": "video", "asset": f"vid-{origin_kind}",
                     "model": "MiniMax-H3-Max", "duration": 6,
                     "first_frame": first_ref,
                     "rect": [0, 0, 1080, 1920], "z": 2},
                ]
                if origin_kind == "ai":
                    layers.insert(1, {
                        "id": "plate", "type": "ai", "asset": "ai-plate",
                        "keyColor": "#070512", "blend": "normal",
                        "rect": [0, 0, 1080, 1920], "z": 1,
                    })
                spec = {
                    "id": f"vf-{origin_kind}",
                    "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
                    "fps": 30,
                    "durationInFrames": 60,
                    "style": "tests/fixtures/style.json",
                    "layers": layers,
                    "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
                }
                self.assertEqual(validate(spec), [])

                spec_path = os.path.join(ROOT, ".tmp", f"vf-{origin_kind}.poster.json")
                os.makedirs(os.path.dirname(spec_path), exist_ok=True)
                with open(spec_path, "w") as f:
                    json.dump(spec, f)

                captured_video_payload = {}
                uploaded_paths = []

                def fake_upload(path):
                    self.assertTrue(os.path.exists(path), f"uploaded source PNG must exist on disk: {path}")
                    uploaded_paths.append(path)
                    return f"https://example.invalid/uploaded/{os.path.basename(path)}"

                def fake_connector_call(tool, payload, timeout=None, attempts=3):
                    if tool == "connector__matrix__submit_video_generation":
                        captured_video_payload.update(payload)
                        return {"task_id": "task-vf-1", "status": "submitted"}
                    if tool == "connector__matrix__query_video_generation":
                        return {"status": "succeeded", "video_url": "https://example.invalid/out.mp4"}
                    raise AssertionError(f"unexpected tool {tool}")

                def fake_download(url, target_path, attempts=3):
                    if target_path.endswith(".mp4"):
                        s1._write_video_fixture(target_path, seconds=1)
                    else:
                        from core.media.draw import write_fixture
                        write_fixture(target_path, w=320, h=320)

                def fake_gen_image(prompt, asset_name, **kw):
                    return "node-ai-1"

                with preserve_manifest():
                    try:
                        with mock.patch.object(s1, "upload_temp_url", side_effect=fake_upload), \
                             mock.patch.object(s1, "download_file", side_effect=fake_download), \
                             mock.patch.object(s1, "call_generate_image", side_effect=fake_gen_image), \
                             mock.patch.object(s1, "fetch_asset_url", return_value="https://example.invalid/ai.png"), \
                             mock.patch.object(gen_video, "_connector_call", side_effect=fake_connector_call), \
                             mock.patch.object(gen_video, "download_file", side_effect=fake_download), \
                             mock.patch.object(gen_video, "fetch_asset_url", return_value="https://example.invalid/ai.mp4"), \
                             mock.patch.object(sys, "argv", ["01_generate.py", "--spec", spec_path, "--force"]):
                            rc = s1.main()
                        self.assertEqual(rc, 0)
                        self.assertEqual(len(uploaded_paths), 1)
                        self.assertIn("input_image", captured_video_payload)
                        self.assertTrue(
                            captured_video_payload["input_image"]["url"].startswith("https://example.invalid/uploaded/")
                        )
                        self.assertEqual(captured_video_payload["reference_type"], "first_frame")
                        self.assertEqual(captured_video_payload["ratio"], "adaptive")
                    finally:
                        for p in (
                            spec_path,
                            os.path.join(ROOT, "assets", f"vid-{origin_kind}.mp4"),
                            os.path.join(ROOT, "assets", "ai-plate.png"),
                            os.path.join(ROOT, "build", "prepared", f"vf-{origin_kind}", "bg.png"),
                        ):
                            if os.path.exists(p):
                                os.remove(p)

    def test_01_unsupported_model_capabilities_rejected_in_validate(self):
        """Models that do not support last_frame or reference_images are rejected during validate()."""
        # 1. Hailuo-2.3 does not support last_frame
        s_hailuo_lf = _video_spec()
        s_hailuo_lf["layers"][0].update({
            "model": "MiniMax-Hailuo-2.3",
            "duration": 6,
            "first_frame": "city-silhouette",
            "last_frame": "city-silhouette",
        })
        errs = validate(s_hailuo_lf)
        self.assertTrue(any("does not support last_frame" in e for e in errs), errs)

        # 2. H3-Max and Hailuo-2.3 do not support reference_images (only MiniMax-H3 does)
        for m in ("MiniMax-H3-Max", "MiniMax-Hailuo-2.3"):
            with self.subTest(model=m):
                s_ref = _video_spec()
                s_ref["layers"][0].update({
                    "model": m,
                    "duration": 6,
                    "reference_images": ["city-silhouette"],
                })
                errs = validate(s_ref)
                self.assertTrue(any("does not support reference_images" in e for e in errs), errs)

        # 3. MiniMax-H3 accepts both first_frame + last_frame and reference_images
        s_h3 = _video_spec()
        s_h3["layers"][0].update({
            "model": "MiniMax-H3",
            "duration": 6,
            "first_frame": "city-silhouette",
            "last_frame": "city-silhouette",
            "reference_images": ["city-silhouette"],
        })
        self.assertEqual(validate(s_h3), [])

        # 4. Non-PNG code layer (e.g. draw='bar') as first_frame is rejected at validate()
        s_bar_ref = _video_spec()
        s_bar_ref["layers"].insert(0, {
            "id": "bar-layer", "type": "code", "draw": "bar",
            "color": "#ff0000", "rect": [0, 0, 200, 50], "z": 1,
        })
        s_bar_ref["layers"][1]["first_frame"] = "bar-layer"
        errs = validate(s_bar_ref)
        self.assertTrue(any("only ['dots', 'grid'] code layers render to a static PNG" in e for e in errs), errs)

    def test_02_discrete_duration_rejected_and_snapped(self):
        """Hailuo-2.3 accepts 6 or 10 seconds and nothing between.

        Its duration is an API enum, not a range: a 7s request is rejected by
        the backend, so the validator must refuse it and the clip length must
        land on a value the backend actually accepts.
        """
        # 1. validate() refuses a duration the API's enum would reject
        s7 = _video_spec()
        s7["layers"][0].update({"model": "MiniMax-Hailuo-2.3", "duration": 7})
        errs = validate(s7)
        self.assertTrue(any("duration must be one of [6, 10]s" in e for e in errs), errs)

        # 2. the values the enum does accept pass
        for ok_dur in (6, 10):
            with self.subTest(duration=ok_dur):
                s_ok = _video_spec()
                s_ok["layers"][0].update({"model": "MiniMax-Hailuo-2.3", "duration": ok_dur})
                self.assertEqual(validate(s_ok), [])

        # 3. a continuous-range model is unaffected
        s_h3 = _video_spec()
        s_h3["layers"][0].update({"model": "MiniMax-H3", "duration": 7})
        self.assertEqual(validate(s_h3), [])

        # 4. the transport refuses it too, before spending anything
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("a calm wave", model="MiniMax-Hailuo-2.3", duration=7)
        self.assertIn("one of [6, 10]", str(ctx.exception))

    def test_03_clip_duration_snaps_to_an_accepted_value(self):
        """A shot length the API cannot express is rounded UP to one it can."""
        H = "MiniMax-Hailuo-2.3"
        self.assertEqual(s1._clip_duration(3, H), 6)
        self.assertEqual(s1._clip_duration(6, H), 6)
        self.assertEqual(s1._clip_duration(7, H), 10)
        self.assertEqual(s1._clip_duration(9, H), 10)
        self.assertEqual(s1._clip_duration(12, H), 10)
        # 1080P and the legacy subject mode cap Hailuo at 6s
        self.assertEqual(s1._clip_duration(7, H, resolution="1080P"), 6)
        self.assertEqual(s1._clip_duration(9, H, resolution="768P", reference_type="subject"), 6)
        # a continuous-range model keeps its plain rounding
        self.assertEqual(s1._clip_duration(7, "MiniMax-H3"), 7)
        self.assertEqual(s1._clip_duration(3, "MiniMax-H3"), 4)
        self.assertEqual(s1._clip_duration(20, "MiniMax-H3"), 15)

    def test_04_unwired_reference_media_rejected(self):
        """reference_videos / reference_audios would be silently dropped.

        The backend accepts them, but S1 cannot resolve a video or audio
        source, so accepting them would produce a text-to-video clip with the
        reference quietly missing. The contract refuses them instead.
        """
        for field in ("reference_videos", "reference_audios"):
            with self.subTest(field=field):
                s = _video_spec()
                s["layers"][0].update({
                    "model": "MiniMax-H3", "duration": 6,
                    field: ["city-silhouette"],
                })
                errs = validate(s)
                self.assertTrue(any("is not supported yet" in e for e in errs), errs)

    def test_05_duration_capability_survives_env_override(self):
        """POSTER_MODELS_JSON can override a model's accepted durations.

        The override path normalizes `durations` into a tuple the same way it
        does `resolutions`; without that, a JSON list would reach the
        capability table in a different shape than the built-in one. Run in a
        subprocess so the reload cannot leak into the other tests.
        """
        env = dict(os.environ)
        env["POSTER_MODELS_JSON"] = json.dumps({
            "MiniMax-Hailuo-2.3": {"durations": [4, 8]},
        })
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from core.generation import models\n"
            "print(models.video_allowed_durations('MiniMax-Hailuo-2.3'))\n"
        ) % ROOT
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "(4, 8)")

    def test_06_hailuo_subject_reference_type_rejected_in_validate(self):
        """P1-6: MiniMax-Hailuo-2.3 reference_type='subject' fails upstream and must be rejected by validate() before billing."""
        s_subj = _video_spec()
        s_subj["layers"][0].update({
            "model": "MiniMax-Hailuo-2.3",
            "duration": 6,
            "first_frame": "city-silhouette",
            "reference_type": "subject",
        })
        errs = validate(s_subj)
        self.assertTrue(
            any("MiniMax-Hailuo-2.3 reference_type must be one of ['first_frame'], got 'subject'" in e for e in errs),
            errs,
        )
        self.assertTrue(
            any("video_generation_failed" in e for e in errs),
            errs,
        )

    def test_07_ai_layer_id_reference_and_multi_image_references(self):
        """Free composition:
        1. Referencing an 'ai' layer by its layer ID (when layer.id != layer.asset) works in validate() and S1;
        2. 'ai' layers accept reference_images (1..16) and reject non-static code layers at validate() time;
        3. S1 uploads all reference_images for 'ai' layers in topological order.
        """
        from tests.helpers import preserve_manifest

        # Reject non-static code layer (draw='field') on ai.input_asset and ai.reference_images
        bad_spec = {
            "id": "ai-bad-ref",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "particles", "type": "code", "draw": "field", "rect": [0, 0, 1080, 1920], "z": 0},
                {"id": "hero", "type": "ai", "asset": "hero-img", "keyColor": "#070512", "blend": "normal",
                 "input_asset": "particles", "rect": [0, 0, 1080, 1920], "z": 1},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
        }
        errs = validate(bad_spec)
        self.assertTrue(any("only ['dots', 'grid'] code layers render to a static PNG" in e for e in errs), errs)

        # Valid chain: code grid ('bg-grid') + manifest asset ('city-silhouette') -> ai layer ('hero-layer', asset 'hero-fused') -> video ('clip', first_frame='hero-layer')
        combo_spec = {
            "id": "combo-chain",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "style": "tests/fixtures/style.json",
            "layers": [
                {"id": "bg-grid", "type": "code", "draw": "grid", "rect": [0, 0, 1080, 1920], "z": 0},
                # Put video layer BEFORE hero-layer in spec['layers'] to verify topological sort by layer.id!
                {"id": "clip", "type": "video", "asset": "combo-vid",
                 "model": "MiniMax-H3-Max", "duration": 6,
                 "first_frame": "hero-layer",
                 "rect": [0, 0, 1080, 1920], "z": 1},
                {"id": "hero-layer", "type": "ai", "asset": "hero-fused",
                 "keyColor": "#070512", "blend": "normal",
                 "reference_images": ["bg-grid", "city-silhouette"],
                 "rect": [0, 0, 1080, 1920], "z": 2},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
        }
        self.assertEqual(validate(combo_spec), [])

        spec_path = os.path.join(ROOT, ".tmp", "combo-chain.poster.json")
        with open(spec_path, "w") as f:
            json.dump(combo_spec, f)

        gen_order = []
        captured_img_urls = []

        def fake_upload(path):
            self.assertTrue(os.path.exists(path), f"uploaded reference must exist: {path}")
            return f"https://example.invalid/up/{os.path.basename(path)}"

        def fake_gen_image(prompt, asset_name, **kw):
            gen_order.append(("ai", asset_name))
            captured_img_urls.extend(kw.get("input_urls") or [])
            return "node-fused-1"

        def fake_connector_call(tool, payload, timeout=None, attempts=3):
            if tool == "connector__matrix__submit_video_generation":
                gen_order.append(("video", payload.get("input_image", {}).get("url")))
                return {"task_id": "t-combo-1", "status": "submitted"}
            if tool == "connector__matrix__query_video_generation":
                return {"status": "succeeded", "video_url": "https://example.invalid/v.mp4"}
            raise AssertionError(f"unexpected tool {tool}")

        def fake_download(url, target_path, attempts=3):
            if target_path.endswith(".mp4"):
                s1._write_video_fixture(target_path, seconds=1)
            else:
                from core.media.draw import write_fixture
                write_fixture(target_path, w=320, h=320)

        with preserve_manifest():
            try:
                with mock.patch.object(s1, "upload_temp_url", side_effect=fake_upload), \
                     mock.patch.object(s1, "download_file", side_effect=fake_download), \
                     mock.patch.object(s1, "call_generate_image", side_effect=fake_gen_image), \
                     mock.patch.object(s1, "fetch_asset_url", return_value="https://example.invalid/fused.png"), \
                     mock.patch.object(gen_video, "_connector_call", side_effect=fake_connector_call), \
                     mock.patch.object(gen_video, "download_file", side_effect=fake_download), \
                     mock.patch.object(gen_video, "fetch_asset_url", return_value="https://example.invalid/fused.mp4"), \
                     mock.patch.object(sys, "argv", ["01_generate.py", "--spec", spec_path, "--force"]):
                    rc = s1.main()
                self.assertEqual(rc, 0)
                # Verify topological order: ai ('hero-fused') generated BEFORE video ('combo-vid')
                self.assertEqual([k for k, _ in gen_order], ["ai", "video"])
                self.assertEqual(len(captured_img_urls), 2)
                self.assertTrue(any("bg-grid.png" in u for u in captured_img_urls))
                self.assertTrue(any("city-silhouette.png" in u for u in captured_img_urls))
                self.assertTrue(gen_order[1][1].endswith("/hero-fused.png"))
            finally:
                for p in (
                    spec_path,
                    os.path.join(ROOT, "assets", "hero-fused.png"),
                    os.path.join(ROOT, "assets", "combo-vid.mp4"),
                    os.path.join(ROOT, "build", "prepared", "combo-chain", "bg-grid.png"),
                ):
                    if os.path.exists(p):
                        os.remove(p)

    def test_08_multi_layer_same_asset_different_rects_prepared_cleanly(self):
        """Two AI layers in the same shot sharing one asset with different rects do not clobber each other in S2/S3."""
        from tests.helpers import preserve_manifest
        import shutil
        from core.media.png import read_size

        spec = {
            "id": "shared-asset-shot",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 30,
            "style": "tests/fixtures/style.json",
            "layers": [
                {"id": "lantern-big", "type": "ai", "asset": "city-silhouette",
                 "keyColor": "#070512", "blend": "normal", "cutout": True,
                 "rect": [100, 100, 600, 600], "z": 1},
                {"id": "lantern-small", "type": "ai", "asset": "city-silhouette",
                 "keyColor": "#070512", "blend": "normal", "cutout": True,
                 "rect": [700, 100, 200, 200], "z": 2},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
        }
        spec_path = os.path.join(ROOT, ".tmp", "shared-asset-shot.poster.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f)

        with preserve_manifest():
            try:
                res = subprocess.run(
                    [sys.executable, "stages/02_prepare.py", "--spec", spec_path],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                primary_p = os.path.join(ROOT, "build", "prepared", "shared-asset-shot", "city-silhouette.png")
                secondary_p = os.path.join(ROOT, "build", "prepared", "shared-asset-shot", "lantern-small__layer.png")
                self.assertTrue(os.path.exists(primary_p))
                self.assertTrue(os.path.exists(secondary_p))
                w1, h1 = read_size(primary_p)
                w2, h2 = read_size(secondary_p)
                self.assertGreater(w1, w2)
                self.assertGreater(h1, h2)
            finally:
                if os.path.exists(spec_path):
                    os.remove(spec_path)
                shutil.rmtree(os.path.join(ROOT, "build", "prepared", "shared-asset-shot"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

