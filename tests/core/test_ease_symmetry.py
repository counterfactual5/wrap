"""An unknown ease must fail on BOTH ends of the contract.

`core/rig/kinematics.py`'s `apply_ease` raises ValueError for an ease
outside ANIM_EASES; `remotion/kinematics.ts`'s `applyEase` used to fall
through to `default: return t` — a silent linear. The validator
(`core/spec/channels.py`) rejects such an ease, so the divergence was
unreachable through the normal pipeline — but a spec fed straight to the
renderer (a Remotion Studio preview of a hand-edited or stale props file)
never passes that check, and then the two ends disagreed: Python raised,
TypeScript rendered a straight line and said nothing.

The renderer half is exercised by `tests/renderer/contract_ease_unknown.cjs`
against the real TypeScript source. This file pins the Python half and the
shared vocabulary.
"""
import os
import shutil
import subprocess
import unittest

from core.rig.kinematics import apply_ease, eval_channel
from core.spec.constants import ANIM_EASES

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PythonEaseRejectsUnknownTests(unittest.TestCase):
    def test_01_unknown_ease_raises(self):
        with self.assertRaises(ValueError) as ctx:
            apply_ease(0.5, "bogus_ease")
        self.assertIn("unknown ease", str(ctx.exception))
        self.assertIn("bogus_ease", str(ctx.exception))

    def test_02_the_error_lists_the_legal_eases(self):
        with self.assertRaises(ValueError) as ctx:
            apply_ease(0.5, "not-an-ease")
        message = str(ctx.exception)
        for ease in sorted(ANIM_EASES):
            self.assertIn(ease, message,
                          f"the error must list {ease}: {message}")

    def test_03_every_legal_ease_still_evaluates(self):
        expected = {
            "linear": 0.5,
            "in": 0.25,
            "out": 0.75,
            "snap": 0.9375,
            "step": 0.0,
        }
        for ease, value in expected.items():
            self.assertAlmostEqual(apply_ease(0.5, ease), value, places=9,
                                   msg=f"{ease} must keep its curve")
        self.assertTrue(apply_ease(0.5, "inout") == apply_ease(0.5, "inout"))
        self.assertTrue(apply_ease(0.5, "overshoot") == apply_ease(0.5, "overshoot"))

    def test_04_eval_channel_rejects_an_unknown_ease_too(self):
        """The channel evaluator must not swallow the bad ease either."""
        kfs = [[0, 0], [10, 100, "bogus_ease"]]
        with self.assertRaises(ValueError):
            eval_channel(kfs, 5, 0.0)


class RendererEaseRejectsUnknownTests(unittest.TestCase):
    def test_05_renderer_rejects_an_unknown_ease(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for renderer contract tests")
        script = os.path.join("tests", "renderer", "contract_ease_unknown.cjs")
        proc = subprocess.run([node, script], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         f"the renderer ease contract failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("PASS unknown ease throws", proc.stdout)


class EaseVocabularyIsSharedTests(unittest.TestCase):
    def test_06_both_ends_declare_the_same_eases(self):
        """The TS side must list exactly the Python vocabulary.

        `EASES` in remotion/kinematics.ts is the TS mirror of
        `core/spec/constants.py:ANIM_EASES`. A drift between them is the
        same class of bug this file guards: one end accepting a value the
        other rejects.
        """
        import json as _json

        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for renderer contract tests")
        probe = (
            "const fs=require('fs');const ts=require('typescript');"
            "const Module=require('module');"
            "require.extensions['.ts']=(m,f)=>{m._compile(ts.transpileModule("
            "fs.readFileSync(f,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,"
            "esModuleInterop:true}}).outputText,f);};"
            "console.log(JSON.stringify(require('./remotion/kinematics.ts').EASES));"
        )
        proc = subprocess.run([node, "-e", probe],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         f"could not read the TS ease vocabulary:\n{proc.stderr}")
        ts_eases = set(_json.loads(proc.stdout.strip().splitlines()[-1]))
        self.assertEqual(
            ts_eases, set(ANIM_EASES),
            "the TypeScript and Python ease vocabularies must match; "
            f"TS={sorted(ts_eases)} Python={sorted(ANIM_EASES)}")


if __name__ == "__main__":
    unittest.main()
