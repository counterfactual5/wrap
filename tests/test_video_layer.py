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

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core.schema import validate

_spec = importlib.util.spec_from_file_location(
    "s1_generate_v", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)


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

        with mock.patch.object(s1, "_connector_call", side_effect=fake_call):
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

        with mock.patch.object(s1, "query_video_generation", side_effect=fake_query), \
             mock.patch.object(s1.time, "sleep"):
            data = s1.wait_for_video("42", "MiniMax-H3-Max", interval=0)
        self.assertEqual(data["status"], "succeeded")
        self.assertEqual(len(calls), 3)

    def test_05_wait_raises_on_failed_task(self):
        with mock.patch.object(s1, "query_video_generation",
                               return_value={"status": "failed", "detail": "nope"}):
            with self.assertRaises(RuntimeError) as ctx:
                s1.wait_for_video("42", "MiniMax-H3-Max", interval=0)
        self.assertIn("failed", str(ctx.exception))

    def test_06_download_uses_node_id_when_url_absent(self):
        with mock.patch.object(s1, "fetch_asset_url", return_value="https://x.invalid/v.mp4") as fu, \
             mock.patch.object(s1, "download_file") as df:
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
            "style": "spec/style-quantum.json",
            "layers": [
                {"id": "clip", "type": "video", "asset": "video-e2e-clip",
                 "rect": [0, 0, 1080, 1920], "z": 0, "plate": False},
                {"id": "title", "type": "text", "text": "video layer",
                 "rect": [60, 1500, 960, 120], "fontSize": 72, "z": 2},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }
        spec_path = os.path.join(ROOT, "spec", "video-e2e.poster.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        try:
            # --fixture: build the clip locally. The test must never call the
            # generation backend — it would spend credits and be flaky.
            for stage, extra in (("01_generate.py", ["--fixture"]),
                                 ("02_prepare.py", []),
                                 ("03_compose.py", [])):
                res = subprocess.run(
                    [sys.executable, os.path.join("stages", stage), "--spec", spec_path] + extra,
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

            # The clip must actually move: a rendered-but-static video layer
            # would slip past a green gate only if the metric never ran.
            motion = next((g for g in gates if g["id"] == "motion"), None)
            self.assertIsNotNone(motion)
            self.assertGreater(motion["value"], 0.0001,
                               "video layer rendered a frozen image")
        finally:
            # Remove the asset file AND its manifest rows: the manifest is a
            # frozen ledger, and a test that leaves rows behind makes the
            # working tree dirty on every run (delivery then reads that as a
            # changed tree rather than a green test).
            for path in (spec_path,
                         os.path.join(ROOT, "assets", "video-e2e-clip.mp4")):
                if os.path.exists(path):
                    os.remove(path)
            from core import manifest
            m = manifest.load()
            m["assets"].pop("video-e2e-clip", None)
            m["prepared"].pop("video-e2e/video-e2e-clip", None)
            manifest.save(m)


if __name__ == "__main__":
    unittest.main()
