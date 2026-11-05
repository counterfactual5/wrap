"""Assembling a timeline must not silently generate (and bill) assets.

The build contract fills a missing shot by running S1 → S2 → S3 → S4. S1 can
also GENERATE, which costs a model call — so "assemble what I have" must not
turn into "generate what is missing" without the author knowing. A shot whose
assets are not frozen yet is reported instead, with the command to run.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import missing_assets


def _write(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class TestMissingAssets(unittest.TestCase):
    def test_00_frozen_assets_are_not_missing(self):
        with open(os.path.join(ROOT, "spec", "shot-01.poster.json")) as f:
            spec = json.load(f)
        self.assertEqual(missing_assets(spec), [])

    def test_01_an_unfrozen_asset_is_reported(self):
        spec = {
            "id": "probe",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 30,
            "layers": [{"id": "hero", "type": "ai", "asset": "not-frozen-at-all",
                        "keyColor": "#ffffff", "blend": "multiply",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [],
        }
        self.assertEqual(missing_assets(spec), ["not-frozen-at-all"])

    def test_02_layers_without_assets_are_ignored(self):
        spec = {
            "id": "probe",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 30,
            "layers": [{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [],
        }
        self.assertEqual(missing_assets(spec), [])


class TestConcatDoesNotGenerate(unittest.TestCase):
    """The end-to-end guarantee: a missing asset stops the concat, and no
    asset file appears."""

    def test_00_concat_refuses_and_generates_nothing(self):
        shot_id = "no-generate"
        spec_path = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        tl_path = os.path.join(ROOT, "spec", f"{shot_id}-timeline.json")
        out_mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
        asset_name = f"{shot_id}-asset"
        asset_path = os.path.join(ROOT, "assets", f"{asset_name}.png")
        _write(spec_path, {
            "id": shot_id,
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 30,
            "vibe": False,
            "style": "spec/style-quantum.json",
            "layers": [{"id": "hero", "type": "ai", "asset": asset_name,
                        "keyColor": "#ffffff", "blend": "multiply",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        })
        _write(tl_path, {"id": f"{shot_id}-seq",
                         "shots": [f"spec/{shot_id}.poster.json"]})
        try:
            res = subprocess.run(
                [sys.executable, "pipeline.py", "concat", "--timeline", tl_path,
                 "--output", out_mp4],
                cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(res.returncode, 0,
                                "concat assembled a shot whose assets are missing")
            self.assertIn(asset_name, res.stdout + res.stderr,
                          "the error must name the missing asset")
            self.assertIn("generate", res.stdout + res.stderr,
                          "the error must point at the command to run")
            self.assertFalse(os.path.exists(asset_path),
                             "concat generated the asset — it must not")
        finally:
            for p in (spec_path, tl_path, out_mp4, asset_path):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
