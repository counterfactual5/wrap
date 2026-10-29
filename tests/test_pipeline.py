"""End-to-end and reproducibility tests for the poster pipeline."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import manifest, metrics
from schema import load_spec, validate


class TestPipeline(unittest.TestCase):
    def test_00_spec_validation(self):
        spec = load_spec()
        self.assertEqual(len(validate(spec)), 0)

        # Negative test: invalid spec must be caught
        bad_spec = dict(spec)
        bad_spec["durationInFrames"] = -1
        self.assertGreater(len(validate(bad_spec)), 0)

    def test_01_metrics_pure(self):
        # Edge key purity test
        w, h = 100, 100
        pure_white = bytes((255, 255, 255)) * (w * h)
        purity = metrics.edge_key_purity(pure_white, w, h, (255, 255, 255), ring=8, tol=12)
        self.assertEqual(purity, 1.0)

        # Red ratio test
        pure_red = bytes((200, 50, 50)) * (w * h)
        red_ratio = metrics.red_ratio_of_frame(pure_red, w, h)
        self.assertEqual(red_ratio, 1.0)

    def test_02_stages_run(self):
        # S1 (ensure assets verified)
        res = subprocess.run([sys.executable, "01_generate.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S2 (prepare & key purity check)
        res = subprocess.run([sys.executable, "02_prepare.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S3 (compose video & frames)
        res = subprocess.run([sys.executable, "03_compose.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S4 (gates)
        res = subprocess.run([sys.executable, "04_gate.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        with open(os.path.join(ROOT, "build", "gates.json")) as f:
            gates = json.load(f)
        for g in gates:
            self.assertTrue(g["pass"], f"Gate {g['id']} failed: {g}")

    def test_03_reproducibility(self):
        """Invariant: Same spec + same manifest -> exact same video sha256."""
        v1 = manifest.sha256(os.path.join(ROOT, "build", "shot-01.mp4"))

        # Re-run S3 compose
        res = subprocess.run([sys.executable, "03_compose.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        v2 = manifest.sha256(os.path.join(ROOT, "build", "shot-01.mp4"))
        self.assertEqual(v1, v2, f"Bit-for-bit mismatch: {v1} != {v2}")


if __name__ == "__main__":
    unittest.main()
