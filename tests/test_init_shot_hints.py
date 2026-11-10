"""The starter hints must name every subject layer an author can pick.

init-shot is the first thing a new author runs, and its `_design_hints` are
the only guidance they see before designing a shot. The video layer — the one
way to use the native video models — was missing from that list entirely, so
an author designing from the hints would never consider a generated clip.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)


class TestInitShotHints(unittest.TestCase):
    def _hints(self, shot_id):
        spec_path = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        try:
            res = subprocess.run(
                [sys.executable, "pipeline.py", "init-shot", shot_id],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(spec_path) as f:
                spec = json.load(f)
            return "\n".join(spec["_design_hints"])
        finally:
            if os.path.exists(spec_path):
                os.remove(spec_path)

    def test_00_the_hints_name_the_video_layer(self):
        hints = self._hints("hints-video")
        self.assertIn("video layer", hints)

    def test_01_the_hints_name_the_ai_layer_too(self):
        """The two subject layers are alternatives — both must be named."""
        hints = self._hints("hints-ai")
        self.assertIn("ai layer", hints)
        self.assertIn("video layer", hints)

    def test_02_the_hints_say_how_to_choose_between_them(self):
        hints = self._hints("hints-choose")
        self.assertIn("pick ONE", hints)

    def test_03_the_hints_name_the_video_layers_keys(self):
        hints = self._hints("hints-keys")
        for key in ("model", "duration", "muted"):
            with self.subTest(key=key):
                self.assertIn(key, hints)

    def test_04_the_hints_point_at_the_documentation(self):
        hints = self._hints("hints-doc")
        self.assertIn("SKILL.md", hints)
        self.assertIn("generated video clip", hints)

    def test_05_the_existing_hints_are_kept(self):
        """Adding the video layer must not cost the author anything else."""
        hints = self._hints("hints-kept")
        for phrase in ("no layout by design",
                       "ROLL THE DICE",
                       "Three composition languages",
                       "articulated skeletal rig"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, hints)

    def test_06_the_skeleton_still_carries_no_layout(self):
        """The design law: init-shot hands over a schema, not a composition."""
        spec_path = os.path.join(ROOT, "spec", "hints-nolayout.poster.json")
        try:
            res = subprocess.run(
                [sys.executable, "pipeline.py", "init-shot", "hints-nolayout"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(spec_path) as f:
                spec = json.load(f)
            layers = spec["layers"]
            self.assertEqual(len(layers), 1)
            self.assertEqual(layers[0]["type"], "code")
            self.assertEqual(layers[0]["draw"], "grid")
        finally:
            if os.path.exists(spec_path):
                os.remove(spec_path)


if __name__ == "__main__":
    unittest.main()
