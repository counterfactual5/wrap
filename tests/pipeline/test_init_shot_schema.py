"""init-shot hands over a schema, not a composition.

The only design decision init-shot may make is NONE: geometry (canvas, fps,
frame count) and the empty tracks are REQUIRED arguments, and the skeleton
ships no layers, no gates, no palette, no style, no component suggestions.
A baked skeleton here is how every episode converged to one identical look.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)


def _init(shot_id, *extra):
    return subprocess.run(
        [sys.executable, "pipeline.py", "init-shot", shot_id, *extra],
        cwd=ROOT, capture_output=True, text=True)


class TestInitShotRequiresExplicitGeometry(unittest.TestCase):
    def test_00_canvas_fps_and_frames_are_required(self):
        for missing in (["--canvas", "1080", "1920"],
                        ["--fps", "30", "--frames", "150"]):
            res = _init("schema-required-probe", *missing)
            self.assertNotEqual(res.returncode, 0,
                                "init-shot ran without full explicit geometry")
            joined = res.stderr + res.stdout
            self.assertTrue(any(flag in joined for flag in ("--canvas", "--fps", "--frames")),
                            f"the error does not name the missing flag: {joined}")

    def test_01_the_values_are_taken_verbatim(self):
        spec_path = os.path.join(ROOT, "spec", "schema-verbatim.poster.json")
        try:
            res = _init("schema-verbatim", "--canvas", "1280", "720",
                        "--fps", "24", "--frames", "96")
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(spec_path) as f:
                spec = json.load(f)
            self.assertEqual(spec["canvas"], {"w": 1280, "h": 720})
            self.assertEqual(spec["fps"], 24)
            self.assertEqual(spec["durationInFrames"], 96)
        finally:
            if os.path.exists(spec_path):
                os.remove(spec_path)


class TestInitShotIsSchemaOnly(unittest.TestCase):
    def _spec(self, shot_id):
        spec_path = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        try:
            res = _init(shot_id, "--canvas", "1080", "1920",
                        "--fps", "30", "--frames", "150")
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(spec_path) as f:
                return json.load(f)
        finally:
            if os.path.exists(spec_path):
                os.remove(spec_path)

    def test_00_the_skeleton_has_no_composition(self):
        spec = self._spec("schema-nolayout")
        self.assertEqual(spec["layers"], [], "the skeleton shipped layers")
        self.assertNotIn("style", spec, "the skeleton shipped a style default")
        for key in ("vibe", "ambient", "palette", "background", "theme"):
            self.assertNotIn(key, spec, f"the skeleton shipped a design default: {key}")

    def test_01_the_skeleton_has_no_component_or_timing_suggestions(self):
        spec = self._spec("schema-nocomp")
        self.assertNotIn("checklist", spec, "the skeleton shipped audit criteria")
        self.assertNotIn("_design_hints", spec,
                         "the skeleton shipped built-in design guidance")
        self.assertEqual(spec["tracks"], {"captions": [], "events": []})

    def test_02_the_skeleton_validates(self):
        from core.spec.shot import validate
        spec = self._spec("schema-valid")
        spec["gates"] = spec.get("gates", [])
        self.assertEqual(validate(spec), [], f"init-shot wrote an invalid spec: {validate(spec)}")

    def test_03_init_shot_does_not_read_a_default_fixture_spec(self):
        """The engine must not silently read tests/fixtures as its default
        input: load_spec requires an explicit path, and load_spec() raises."""
        from core.spec.loader import load_spec
        with self.assertRaises(ValueError):
            load_spec()


class TestInitShotFromShot(unittest.TestCase):
    def test_00_carry_state_carries_layers_not_geometry_defaults(self):
        import tempfile
        from core.spec.state import carry_state_from
        prev = {
            "id": "prev-shot", "canvas": {"w": 1080, "h": 1920}, "fps": 30,
            "durationInFrames": 90,
            "layers": [{"id": "hero", "type": "ai", "asset": "hero-base",
                        "keyColor": "#ffffff", "blend": "normal",
                        "rect": [240, 480, 600, 900], "z": 1,
                        "poses": [{"frame": 0, "asset": "hero-base"},
                                  {"frame": 45, "asset": "hero-pose-b"}],
                        "anim": {"x": [[0, 0], [89, 120]]}}],
            "gates": [], "tracks": {"captions": [], "events": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prev.poster.json")
            with open(path, "w") as f:
                json.dump(prev, f)
            out = carry_state_from(prev, "next-shot")
        self.assertEqual(out["id"], "next-shot")
        # End-of-shot state carried; geometry stays the caller's decision.
        self.assertEqual(out["layers"][0]["asset"], "hero-pose-b")
        self.assertEqual(out["layers"][0]["anim"]["x"][0], [0, 120])
        self.assertEqual(out["tracks"], {"captions": [], "events": []})


if __name__ == "__main__":
    unittest.main()
