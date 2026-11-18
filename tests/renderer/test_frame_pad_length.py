"""The engine must renumber frames with the padding the RENDERER wrote.

`npx remotion render ... --image-sequence-pattern=[frame].png` names the
rendered frames by padding the frame number to the width of the LAST frame
number (`@remotion/renderer`'s `getFilePadLength`). The engine then
renumbers them itself (`core/rendering/remotion.py`), so it has to read
the same rule — otherwise it looks for "0.png" where the renderer wrote
"00000.png" and the shot has no frames.

This test asks the INSTALLED renderer what it does (no copy of the rule in
Python) and checks that the engine's mirror still agrees.
"""
import ast
import json
import os
import shutil
import subprocess
import unittest

from core.rendering import remotion

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


class TestTheFramePadMatchesTheInstalledRenderer(unittest.TestCase):
    def _renderer_pad_lengths(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for renderer contract tests")
        script = os.path.join("tests", "renderer", "frame_pad_length.cjs")
        proc = subprocess.run([node, script], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_00_the_renderer_pads_by_the_last_frame_number(self):
        rows = self._renderer_pad_lengths()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(frames=row["n"]):
                expected = len(str(row["n"] - 1))
                self.assertEqual(row["actual_frames"], expected)
                self.assertEqual(row["from_zero"], expected)

    def test_01_the_engine_mirrors_that_formula(self):
        """The engine's own pad computation, read from its AST — a comment
        must not be able to satisfy it."""
        with open(remotion.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        pads = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "pad"
                            for t in node.targets)):
                pads.append(node.value)
        self.assertEqual(len(pads), 1, f"expected one pad computation, got {pads}")
        # len(str(spec["durationInFrames"] - 1)) — checked structurally, so
        # the spelling of the expression does not matter.
        value = pads[0]
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(value.func.id, "len")
        self.assertEqual(len(value.args), 1)
        inner = value.args[0]
        self.assertIsInstance(inner, ast.Call)
        self.assertEqual(inner.func.id, "str")
        self.assertEqual(len(inner.args), 1)
        difference = inner.args[0]
        self.assertIsInstance(difference, ast.BinOp)
        self.assertIsInstance(difference.op, ast.Sub)
        frame_count, minus_one = difference.left, difference.right
        self.assertIsInstance(frame_count, ast.Subscript)
        self.assertEqual(ast.unparse(frame_count.value), "spec")
        self.assertEqual(ast.unparse(frame_count.slice), "'durationInFrames'")
        self.assertIsInstance(minus_one, ast.Constant)
        self.assertEqual(minus_one.value, 1)


if __name__ == "__main__":
    unittest.main()
