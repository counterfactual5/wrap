"""A check that did not run must not be recorded as a pass.

Two S4 rows used to say "pass" about work that never happened:

- the freeze gate, when `spec.frame_freeze = true` skips freezedetect;
- the key-purity gate, when the layer is a full-bleed opaque backdrop (there is
  no key to measure, so S2 stored a hardcoded 1.0).

Both now record `pass: null` with a status that says which kind of "not
measured" it is, so a reader of build/gates/*.json can tell "measured and
clean" from "never looked" and from "not applicable".
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.helpers import active_manifest_path, ensure_rendered, preserve_manifest

SPEC = "tests/fixtures/shot-01.poster.json"
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")
SHOT = "shot-01"


def _run(stage, spec_path):
    return subprocess.run(
        [sys.executable, f"stages/{stage}", "--spec", spec_path],
        cwd=ROOT, env=dict(os.environ, POSTER_MANIFEST=active_manifest_path()),
        capture_output=True, text=True, timeout=300)


def _gates(shot_id=SHOT):
    with open(os.path.join(ROOT, "build", "gates", f"{shot_id}.json")) as f:
        return json.load(f)


def _variant(mutate, name):
    """Write a copy of the fixture spec with `mutate` applied; return its path."""
    with open(FIXTURE) as f:
        spec = json.load(f)
    mutate(spec)
    path = os.path.join(ROOT, "build", "gates", f"{name}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(spec, f)
    return path


class _SkippedChecksAreNotPasses(unittest.TestCase):
    def setUp(self):
        ensure_rendered(SPEC, SHOT)

    def test_skipped_freeze_row_is_not_a_pass(self):
        with preserve_manifest():
            path = _variant(lambda s: s.update({"frame_freeze": True}), "freeze-skip")
            try:
                proc = _run("04_gate.py", path)
                rows = _gates()
            finally:
                if os.path.exists(path):
                    os.remove(path)
        freeze = next((r for r in rows if r["id"] == "freeze"), None)
        self.assertIsNotNone(freeze, "the gate file must carry a freeze row")
        self.assertIsNone(freeze["pass"],
                          "a skipped check must not report pass=True")
        self.assertEqual(freeze["status"], "skipped")
        self.assertTrue(freeze["skipped"])
        self.assertIsNone(freeze["value"])
        self.assertIn("frame_freeze", freeze["reason"])

    def test_opaque_backdrop_purity_is_not_measured(self):
        def to_normal(spec):
            for layer in spec["layers"]:
                if layer.get("type") == "ai":
                    layer["blend"] = "normal"
            spec["gates"] = [g for g in spec["gates"]
                             if g.get("metric") == "edge_key_purity"] or [
                {"id": "purity", "metric": "edge_key_purity", "lo": 0.98}]

        with preserve_manifest():
            path = _variant(to_normal, "purity-na")
            try:
                prep = _run("02_prepare.py", path)
                self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
                from core.runtime import manifest
                row = manifest.verified("prepared", f"{SHOT}/city-silhouette")
                self.assertIsNone(row.get("purity"),
                                 "an unmeasurable purity must not be stored as 1.0")
                self.assertEqual(row.get("purity_status"), "not_applicable")
                gate = _run("04_gate.py", path)
                rows = _gates()
            finally:
                if os.path.exists(path):
                    os.remove(path)
        purity = next((r for r in rows if r["metric"] == "edge_key_purity"), None)
        self.assertIsNotNone(purity, "the gate file must carry a purity row")
        self.assertIsNone(purity["pass"],
                          "an inapplicable gate must not report pass=True")
        self.assertEqual(purity["status"], "not_applicable")
        self.assertIsNone(purity["value"])


if __name__ == "__main__":
    unittest.main()
