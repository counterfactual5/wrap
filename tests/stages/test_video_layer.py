"""Video layer tests: spec validation, S1 transport, S2 preparation.

A video layer is a first-class asset type: the spec declares it, S1 freezes
a clip for it, S2 prepares a scaled copy. These tests cover the contract
without spending generation credits — the backend is stubbed and the clip
used is a deterministic local test clip (tests.helpers.make_test_clip).

Model capabilities are ENV-DECLARED (POSTER_MODELS_JSON); there is no
built-in catalog. In-process tests patch `core.generation.models.VIDEO_MODELS`
with the test manifest; subprocess-based tests pass tests.helpers.env_with_models().
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

from core.spec.layers import validate_video_generation
from core.spec.shot import validate
from core.generation import models
from tests.helpers import (
    TEST_IMAGE_MODELS, TEST_MODELS_JSON, TEST_VIDEO_MODELS,
    env_with_models, make_test_clip, write_fixture,
)

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


class TestDeclaredModels(unittest.TestCase):
    """Capabilities are declared per environment; every refusal names what to do."""

    def setUp(self):
        self._patch = mock.patch.dict(models.VIDEO_MODELS, TEST_VIDEO_MODELS)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_00_an_empty_catalog_refuses_with_the_env_instruction(self):
        with mock.patch.object(models, "VIDEO_MODELS", {}):
            with self.assertRaises(RuntimeError) as ctx:
                models.resolve_video_model("Test-Max")
        self.assertIn("POSTER_MODELS_JSON", str(ctx.exception))
        self.assertIn("no fallback", str(ctx.exception))

    def test_01_an_unknown_model_is_refused_without_fallback(self):
        with self.assertRaises(RuntimeError) as ctx:
            models.resolve_video_model("SomeOtherModel")
        self.assertIn("SomeOtherModel", str(ctx.exception))
        self.assertIn("Test-Max", str(ctx.exception))

    def test_02_the_production_fixture_writer_is_a_tombstone(self):
        """No placeholder may be written by the pipeline: test media belongs
        to test support code (tests.helpers.make_test_clip)."""
        from core.generation.fixtures import _write_video_fixture
        with self.assertRaises(RuntimeError) as ctx:
            _write_video_fixture("/tmp/never.mp4")
        self.assertIn("removed", str(ctx.exception))


class TestVideoTransport(unittest.TestCase):
    """S1 must drive the async submit -> poll -> download path."""

    def setUp(self):
        self._patch = mock.patch.dict(models.VIDEO_MODELS, TEST_VIDEO_MODELS)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_00_submit_returns_task_id(self):
        captured = {}

        def fake_call(tool, payload, timeout=None):
            captured["tool"] = tool
            captured["payload"] = payload
            return {"task_id": "999", "status": "submitted", "model": payload["model"]}

        with mock.patch.object(gen_video, "_connector_call", side_effect=fake_call):
            task_id, model = s1.submit_video_generation(
                "a calm wave", model="Test-Max", duration=5,
                ratio="9:16", resolution="768P")
        self.assertEqual(task_id, "999")
        self.assertEqual(model, "Test-Max")
        self.assertEqual(captured["tool"], "connector__matrix__submit_video_generation")
        self.assertEqual(captured["payload"]["duration"], 5)
        self.assertEqual(captured["payload"]["ratio"], "9:16")

    def test_01_submit_rejects_duration_outside_model_range(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("x", model="Test-Max", duration=2, resolution="768P")
        self.assertIn("duration", str(ctx.exception))

    def test_02_submit_rejects_unknown_model(self):
        with self.assertRaises(RuntimeError):
            s1.submit_video_generation("x", model="SomeOtherModel")

    def test_03_submit_rejects_unsupported_resolution(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("x", model="Test-Max", duration=5,
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
            data = s1.wait_for_video("42", "Test-Max", interval=0)
        self.assertEqual(data["status"], "succeeded")
        self.assertEqual(len(calls), 3)

    def test_05_wait_raises_on_failed_task(self):
        with mock.patch.object(gen_video, "query_video_generation",
                               return_value={"status": "failed", "detail": "nope"}):
            with self.assertRaises(RuntimeError) as ctx:
                s1.wait_for_video("42", "Test-Max", interval=0)
        self.assertIn("failed", str(ctx.exception))

    def test_06_download_uses_node_id_when_url_absent(self):
        with mock.patch.object(gen_video, "fetch_asset_url", return_value="https://x.invalid/v.mp4") as fu, \
             mock.patch.object(gen_video, "download_file") as df:
            s1.download_video({"node_id": "42"}, "/tmp/out.mp4")
        fu.assert_called_once_with("42")
        df.assert_called_once_with("https://x.invalid/v.mp4", "/tmp/out.mp4")


class TestLocalClipFixture(unittest.TestCase):
    """Test media must be a real, playable mp4 built by test support code."""

    def test_00_clip_is_a_real_mp4(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "clip.mp4")
            make_test_clip(out, seconds=1)
            self.assertTrue(os.path.exists(out))
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_name,width,height", "-of", "csv=p=0", out],
                capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertIn("h264", probe.stdout)


class TestVideoEndToEnd(unittest.TestCase):
    """A spec with a video layer must survive S1 -> S4 end to end.

    The clip is registered as explicit test media (tests.helpers), so S1
    reuses it — no generation, no connector. A video layer that renders but
    freezes would fail the motion/freeze gates — which is exactly the class
    of bug this path exists to catch.
    """

    def test_00_video_spec_runs_through_the_gates(self):
        spec = {
            "id": "video-e2e",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "clip", "type": "video", "asset": "video-e2e-clip",
                 "model": "Test-Max", "resolution": "768P",
                 "prompt": "a moving test clip",
                 "rect": [0, 0, 1080, 1920], "z": 0},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }
        spec_path = os.path.join(ROOT, ".tmp", "video-e2e.poster.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        from tests.helpers import preserve_manifest
        with preserve_manifest():
            clip_rel = "assets/video-e2e-clip.mp4"
            clip_path = os.path.join(ROOT, clip_rel)
            try:
                make_test_clip(clip_path, seconds=3)
                from core.runtime import manifest
                manifest.register("assets", "video-e2e-clip", clip_rel,
                                  source="test-media")

                for stage in ("01_generate.py", "02_prepare.py", "03_compose.py"):
                    res = subprocess.run(
                        [sys.executable, os.path.join("stages", stage),
                         "--spec", spec_path],
                        cwd=ROOT, capture_output=True, text=True,
                        env=env_with_models())
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
                for path in (spec_path, clip_path):
                    if os.path.exists(path):
                        os.remove(path)


class TestVideoFirstFrameAndReferenceValidation(unittest.TestCase):
    """Video first_frame / last_frame / reference validation and S1 dispatch.

    Structural references are checked by `validate` (what a spec may name);
    model CAPABILITY checks happen at generation time via
    core.spec.layers.validate_video_generation against the env catalog.
    """

    def setUp(self):
        self._patch = mock.patch.dict(models.VIDEO_MODELS, TEST_VIDEO_MODELS)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_00_first_frame_payload_has_input_image_url_first_frame_and_adaptive_ratio(self):
        """A video layer declaring first_frame sends input_image.url,
        reference_type='first_frame', and ratio='adaptive' (ai origin, and a
        frozen manifest asset origin)."""
        from tests.helpers import preserve_manifest

        for origin_kind, first_ref in (("manifest", "city-silhouette"), ("ai", "ai-plate")):
            with self.subTest(origin=origin_kind):
                layers = [
                    {"id": "clip", "type": "video", "asset": f"vid-{origin_kind}",
                     "model": "Test-Max", "duration": 6, "resolution": "768P",
                     "prompt": "a clip starting on the plate",
                     "first_frame": first_ref,
                     "rect": [0, 0, 1080, 1920], "z": 2},
                ]
                if origin_kind == "ai":
                    layers.insert(0, {
                        "id": "plate", "type": "ai", "asset": "ai-plate",
                        "prompt": "a still plate",
                        "keyColor": "#070512", "blend": "normal",
                        "rect": [0, 0, 1080, 1920], "z": 1,
                    })
                spec = {
                    "id": f"vf-{origin_kind}",
                    "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
                    "fps": 30,
                    "durationInFrames": 60,
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
                        make_test_clip(target_path, seconds=1)
                    else:
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
                        for rel in (
                            spec_path,
                            os.path.join(ROOT, "assets", f"vid-{origin_kind}.mp4"),
                            os.path.join(ROOT, "assets", "ai-plate.png"),
                            os.path.join(ROOT, "build", "prepared", f"vf-{origin_kind}"),
                        ):
                            import shutil
                            if os.path.isdir(rel):
                                shutil.rmtree(rel, ignore_errors=True)
                            elif os.path.exists(rel):
                                os.remove(rel)

    def test_01_capability_refusals_happen_at_generation_time(self):
        """Structural `validate` no longer inspects model catalogs (frozen
        assets must validate without any declared model); the capability
        table is consulted by validate_video_generation, right before S1
        spends anything."""
        # 1. structural validate accepts an arbitrary model name...
        s_any = _video_spec()
        s_any["layers"][0]["model"] = "Anything-At-All"
        self.assertEqual(validate(s_any), [])
        # 2. ...but the generation-time check refuses an undeclared one.
        errs = validate_video_generation(s_any["layers"][0], "Anything-At-All")
        self.assertTrue(any("No configured video capabilities" in e for e in errs), errs)

        # 3. a declared model without last_frame support is refused there.
        s_lf = _video_spec()
        s_lf["layers"][0].update({
            "model": "Test-NoLF", "duration": 6, "resolution": "768P",
            "first_frame": "city-silhouette", "last_frame": "city-silhouette",
        })
        errs = validate_video_generation(s_lf["layers"][0], "Test-NoLF")
        self.assertTrue(any("does not support last_frame" in e for e in errs), errs)

        # 4. a declared model without reference_media support is refused.
        s_ref = _video_spec()
        s_ref["layers"][0].update({
            "model": "Test-NoLF", "duration": 6, "resolution": "768P",
            "reference_images": ["city-silhouette"],
        })
        errs = validate_video_generation(s_ref["layers"][0], "Test-NoLF")
        self.assertTrue(any("does not support reference_images" in e for e in errs), errs)

        # 5. a fully capable model accepts both.
        s_ok = _video_spec()
        s_ok["layers"][0].update({
            "model": "Test-Max", "duration": 6, "resolution": "768P",
            "first_frame": "city-silhouette", "last_frame": "city-silhouette",
            "reference_images": ["city-silhouette"],
        })
        self.assertEqual(validate_video_generation(s_ok["layers"][0], "Test-Max"), [])

        # 6. a component layer cannot anchor a first_frame — only ai layers
        # (or frozen manifest assets) render to a static image.
        s_comp = _video_spec()
        s_comp["layers"].insert(0, {
            "id": "comp", "type": "component", "component": "Probe",
            "rect": [0, 0, 200, 50], "z": 1,
        })
        s_comp["layers"][1]["first_frame"] = "comp"
        errs = validate(s_comp)
        self.assertTrue(any("must reference an ai layer" in e for e in errs), errs)

    def test_02_discrete_duration_rejected_and_snapped(self):
        """A discrete duration enum (e.g. 6 or 10 seconds and nothing between)
        is refused by the generation-time check and snapped by the clip
        length picker, before anything is spent."""
        # 1. the generation-time check refuses a duration the enum rejects
        s7 = _video_spec()
        s7["layers"][0].update({"model": "Test-Discrete", "duration": 7})
        errs = validate_video_generation(s7["layers"][0], "Test-Discrete")
        self.assertTrue(any("duration must be one of [6, 10]s" in e for e in errs), errs)

        # 2. the values the enum accepts pass
        for ok_dur in (6, 10):
            with self.subTest(duration=ok_dur):
                s_ok = _video_spec()
                s_ok["layers"][0].update({"model": "Test-Discrete", "duration": ok_dur})
                self.assertEqual(validate_video_generation(s_ok["layers"][0], "Test-Discrete"), [])

        # 3. a continuous-range model is unaffected
        s_h3 = _video_spec()
        s_h3["layers"][0].update({"model": "Test-Max", "duration": 7})
        self.assertEqual(validate_video_generation(s_h3["layers"][0], "Test-Max"), [])

        # 4. the transport refuses it too, before spending anything
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("a calm wave", model="Test-Discrete", duration=7)
        self.assertIn("one of [6, 10]", str(ctx.exception))

    def test_03_clip_duration_snaps_to_an_accepted_value(self):
        """A shot length the API cannot express is rounded UP to one it can."""
        D = "Test-Discrete"
        self.assertEqual(s1._clip_duration(3, D), 6)
        self.assertEqual(s1._clip_duration(6, D), 6)
        self.assertEqual(s1._clip_duration(7, D), 10)
        self.assertEqual(s1._clip_duration(9, D), 10)
        self.assertEqual(s1._clip_duration(12, D), 10)
        # a continuous-range model keeps its plain rounding
        self.assertEqual(s1._clip_duration(7, "Test-Max"), 7)
        self.assertEqual(s1._clip_duration(3, "Test-Max"), 4)
        self.assertEqual(s1._clip_duration(20, "Test-Max"), 15)

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
                    "model": "Test-Max", "duration": 6,
                    field: ["city-silhouette"],
                })
                errs = validate(s)
                self.assertTrue(any("is not supported yet" in e for e in errs), errs)

    def test_05_env_manifest_is_strict_and_typed(self):
        """POSTER_MODELS_JSON fully replaces the (empty) built-in catalog.

        A complete manifest is applied and `durations` is normalized to a
        tuple; a partial entry is REFUSED at import — no half-declared model
        may reach a paid call. Run in subprocesses so import-time state
        cannot leak."""
        # A complete override applies, durations tuple-ized.
        env = env_with_models()
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from core.generation import models\n"
            "print(models.video_allowed_durations('Test-Discrete'))\n"
        ) % ROOT
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "(6, 10)")

        # A partial entry is refused with the missing capability names.
        bad = env_with_models(
            POSTER_MODELS_JSON=json.dumps({"Half-Declared": {"durations": [4, 8]}}))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=bad, timeout=60)
        self.assertNotEqual(out.returncode, 0,
                            "a partial capability manifest must be refused")
        self.assertIn("missing required capabilities", out.stderr)

    def test_06_subject_reference_type_rejected_at_generation_time(self):
        """A reference_type the model declares unsupported (it fails upstream
        AFTER billing) is refused before the call."""
        s_subj = _video_spec()
        s_subj["layers"][0].update({
            "model": "Test-Subjectless",
            "duration": 6,
            "resolution": "768P",
            "first_frame": "city-silhouette",
            "reference_type": "subject",
        })
        errs = validate_video_generation(s_subj["layers"][0], "Test-Subjectless")
        self.assertTrue(
            any("reference_type must be one of ['first_frame'], got 'subject'" in e for e in errs),
            errs,
        )
    def test_07_ai_layer_id_reference_and_multi_image_references(self):
        """Free composition:
        1. Referencing an 'ai' layer by its layer ID (when layer.id != layer.asset) works in validate() and S1;
        2. 'ai' layers accept reference_images (1..16) and reject non-ai layer references at validate() time;
        3. S1 uploads all reference_images for 'ai' layers in topological order.
        """
        from tests.helpers import preserve_manifest

        # A component layer is not a static image: ai.reference_images refuses it.
        bad_spec = {
            "id": "ai-bad-ref",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "particles", "type": "component", "component": "Particles",
                 "rect": [0, 0, 1080, 1920], "z": 0},
                {"id": "hero", "type": "ai", "asset": "hero-img", "keyColor": "#070512", "blend": "normal",
                 "input_asset": "particles", "rect": [0, 0, 1080, 1920], "z": 1},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
        }
        errs = validate(bad_spec)
        self.assertTrue(any("must reference an ai layer" in e for e in errs), errs)

        # Valid chain: manifest asset ('city-silhouette') + ai plate ('plate', asset 'plate-a')
        # -> fused ai layer ('hero-layer', asset 'hero-fused') -> video ('clip', first_frame='hero-layer').
        # The video layer is declared BEFORE its dependencies in spec['layers']
        # to verify S1's topological sort.
        combo_spec = {
            "id": "combo-chain",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "clip", "type": "video", "asset": "combo-vid",
                 "model": "Test-Max", "duration": 6, "resolution": "768P",
                 "prompt": "a clip anchored on the fused plate",
                 "first_frame": "hero-layer",
                 "rect": [0, 0, 1080, 1920], "z": 1},
                {"id": "hero-layer", "type": "ai", "asset": "hero-fused",
                 "prompt": "a fused plate",
                 "keyColor": "#070512", "blend": "normal",
                 "reference_images": ["plate", "city-silhouette"],
                 "rect": [0, 0, 1080, 1920], "z": 2},
                {"id": "plate", "type": "ai", "asset": "plate-a",
                 "prompt": "a base plate",
                 "keyColor": "#070512", "blend": "normal",
                 "rect": [0, 0, 1080, 1920], "z": 3},
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
                make_test_clip(target_path, seconds=1)
            else:
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
                # Topological order: base plate -> fused ai -> video.
                self.assertEqual([k for k, _ in gen_order], ["ai", "ai", "video"])
                self.assertEqual(gen_order[0][1], "plate-a")
                self.assertEqual(gen_order[1][1], "hero-fused")
                self.assertEqual(len(captured_img_urls), 2)
                self.assertTrue(any(u.endswith("city-silhouette.png") for u in captured_img_urls))
                self.assertTrue(gen_order[2][1].endswith("/hero-fused.png"))
            finally:
                import shutil
                for rel in (
                    spec_path,
                    os.path.join(ROOT, "assets", "hero-fused.png"),
                    os.path.join(ROOT, "assets", "plate-a.png"),
                    os.path.join(ROOT, "assets", "combo-vid.mp4"),
                    os.path.join(ROOT, "build", "prepared", "combo-chain"),
                ):
                    if os.path.isdir(rel):
                        shutil.rmtree(rel, ignore_errors=True)
                    elif os.path.exists(rel):
                        os.remove(rel)

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
