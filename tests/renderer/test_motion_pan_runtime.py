"""The renderer must not apply the removed word `motion.pan`.

The contract refuses `motion.pan` loudly ("migration required: motion.pan
removed; use anim.x"), so a spec carrying it never reaches the renderer
through the normal path. The renderer must not apply it anyway: an
implicit render of a removed word is a contract hole, and one that the
layer-type contract check cannot see.

`tests/contract/test_motion_pan_removed.py` pins the source. This file
pins the BEHAVIOUR: the renderer is executed (no Chromium, no network —
the same harness as `contract.cjs`) and the rendered markup is inspected.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MotionPanRuntimeTests(unittest.TestCase):
    def test_renderer_ignores_motion_pan_and_keeps_zoom(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for renderer contract tests")
        script = os.path.join("tests", "renderer", "contract_motion_pan.cjs")
        proc = subprocess.run([node, script], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         f"the renderer contract failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("motion.pan is not applied", proc.stdout)


if __name__ == "__main__":
    unittest.main()
