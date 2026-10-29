"""Test multi-shot concat command."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestConcat(unittest.TestCase):
    def test_concat_command(self):
        # 1. Test help
        res = subprocess.run([sys.executable, "pipeline.py", "concat", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, "pipeline.py concat help failed")

        # 2. Test actual concat with a temporary timeline
        tl_path = os.path.join(ROOT, "build", "test_timeline.json")
        out_mp4 = os.path.join(ROOT, "build", "full.mp4")
        os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
        with open(tl_path, "w") as f:
            json.dump({"id": "full-sequence", "shots": ["spec/shot-01.poster.json"]}, f, indent=2)

        try:
            res = subprocess.run(
                [sys.executable, "pipeline.py", "concat", "--timeline", tl_path, "--output", out_mp4],
                cwd=ROOT, capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0, f"concat execution failed:\n{res.stderr}")
            self.assertTrue(os.path.exists(out_mp4))
            self.assertGreater(os.path.getsize(out_mp4), 1000)
        finally:
            if os.path.exists(tl_path):
                os.remove(tl_path)
            if os.path.exists(out_mp4):
                os.remove(out_mp4)


if __name__ == "__main__":
    unittest.main()
