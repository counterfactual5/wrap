"""Test multi-shot concat command."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from tests.helpers import ensure_rendered, preserve_manifest


class TestConcat(unittest.TestCase):
    def test_00_concat_builds_a_missing_shot_end_to_end(self):
        """A shot with no rendered mp4 must be built by the concat command
        itself — assets, preparation, render, gate — not just rendered.

        S3 refuses to render without the prepared rows, so a build contract
        that runs only S3+S4 leaves a fresh checkout dead on "prepared
        '<shot>/<layer>' not manifest-verified"."""
        shot_spec = "tests/fixtures/shot-01.poster.json"
        mp4 = os.path.join(ROOT, "build", "shot-01.mp4")
        frames = os.path.join(ROOT, "build", "frames", "shot-01")
        prepared = os.path.join(ROOT, "build", "prepared", "shot-01")

        existed = os.path.exists(mp4)
        backup = None
        if existed:
            backup = mp4 + ".bak"
            os.replace(mp4, backup)
        try:
            tl_path = os.path.join(ROOT, "build", "test_timeline.json")
            out_mp4 = os.path.join(ROOT, "build", "test_full_concat.mp4")
            os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
            with open(tl_path, "w") as f:
                json.dump({"id": "full-sequence", "shots": [shot_spec]}, f, indent=2)
            try:
                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path,
                     "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0,
                                 f"concat could not build the missing shot:\n"
                                 f"{res.stdout}\n{res.stderr}")
                self.assertTrue(os.path.exists(out_mp4))
                self.assertTrue(os.path.exists(prepared),
                                "the build contract must prepare the assets too")
                gates_path = os.path.join(ROOT, "build", "gates_full_full-sequence.json")
                self.assertTrue(os.path.exists(gates_path))
                with open(gates_path) as f:
                    gates = json.load(f)
                for g in gates:
                    self.assertTrue(g["pass"], f"gate {g['id']} failed: {g}")
            finally:
                for p in (tl_path, out_mp4,
                          os.path.join(ROOT, "build", "gates_full_full-sequence.json")):
                    if os.path.exists(p):
                        os.remove(p)
        finally:
            if backup is not None:
                os.replace(backup, mp4)

    def test_concat_command(self):
        # 1. Test help
        res = subprocess.run([sys.executable, "pipeline.py", "concat", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, "pipeline.py concat help failed")

        # 2. Test actual concat with a temporary timeline
        tl_path = os.path.join(ROOT, "build", "test_timeline.json")
        out_mp4 = os.path.join(ROOT, "build", "test_full_concat.mp4")
        os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
        with open(tl_path, "w") as f:
            json.dump({"id": "full-sequence", "shots": ["tests/fixtures/shot-01.poster.json"]}, f, indent=2)

        with preserve_manifest():
            try:
                # The shot must be rendered before it can be assembled —
                # `make clean` removes build/, and the dependency used to be
                # implicit in a leftover artifact.
                ensure_rendered("tests/fixtures/shot-01.poster.json", "shot-01")

                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path, "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True
                )
                self.assertEqual(res.returncode, 0, f"concat execution failed:\n{res.stderr}")
                self.assertTrue(os.path.exists(out_mp4))
                self.assertGreater(os.path.getsize(out_mp4), 1000)

                # Full-video gates: written per timeline id, all entries pass,
                # duration is always gated (audio gates only when a track exists).
                gates_path = os.path.join(ROOT, "build", "gates_full_full-sequence.json")
                self.assertTrue(os.path.exists(gates_path), "full-video gates file missing")
                with open(gates_path) as f:
                    gates = json.load(f)
                self.assertTrue(gates, "full-video gates empty")
                for g in gates:
                    self.assertTrue(g["pass"], f"Full-video gate {g['id']} failed: {g}")
                ids = {g["id"] for g in gates}
                self.assertIn("duration", ids)
                self.assertIn("black", ids)
            finally:
                for p in (tl_path, out_mp4,
                          os.path.join(ROOT, "build", "gates_full_full-sequence.json")):
                    if os.path.exists(p):
                        os.remove(p)


if __name__ == "__main__":
    unittest.main()
