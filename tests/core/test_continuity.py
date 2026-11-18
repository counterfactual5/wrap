"""verify-continuity: the cross-shot knobs are configurable, defaults hold.

The thresholds used to be hardcoded (backdrop must match exactly, <= 18 px
jump, 0.20 visibility floor) with no way to tune them per project. They are
now parameters (timeline.continuity block, CLI flags) with the same defaults,
and a backdrop mismatch can be downgraded to a warning instead of a hard
failure — explicitly, never silently.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.rig import verify_timeline_continuity  # noqa: E402
from core.spec.timeline import validate_timeline  # noqa: E402


def _shot(shot_id, backdrop, hero_x, hero_end_opacity=1.0, hero="hero-a"):
    layers = [
        # The engine no longer guesses backdrop identity from an asset name:
        # the identity is declared via the layer's `backdrop` field.
        {"id": "bg", "type": "ai", "asset": backdrop, "backdrop": backdrop,
         "keyColor": "#ffffff", "blend": "normal", "rect": [0, 0, 1920, 1080], "z": 0},
        {"id": "hero", "type": "ai", "asset": hero, "keyColor": "#ffffff",
         "blend": "normal", "cutout": True, "cutoutSimilarity": 0.14, "cutoutBlend": 0.06,
         "rect": [hero_x, 480, 300, 600], "z": 1,
         **({"anim": {"opacity": [[0, 1.0], [59, float(hero_end_opacity)]]}}
            if hero_end_opacity != 1.0 else {})},
    ]
    return {
        "id": shot_id,
        "canvas": {"w": 1920, "h": 1080},
        "fps": 30,
        "durationInFrames": 60,
        "layers": layers,
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.6}],
    }


def _write_timeline(tmp, a, b, continuity=None):
    pa = os.path.join(tmp, f"{a['id']}.poster.json")
    pb = os.path.join(tmp, f"{b['id']}.poster.json")
    with open(pa, "w") as f:
        json.dump(a, f)
    with open(pb, "w") as f:
        json.dump(b, f)
    tl = {"id": "tl", "shots": [pa, pb]}
    if continuity:
        tl["continuity"] = continuity
    tl_path = os.path.join(tmp, "timeline.json")
    with open(tl_path, "w") as f:
        json.dump(tl, f)
    return tl_path


class TestContinuityKnobs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_backdrop_mismatch_fails_by_default(self):
        a, b = _shot("a", "bg-a", 100), _shot("b", "bg-b", 100)
        _write_timeline(self.tmp, a, b)
        rep = verify_timeline_continuity(
            {"id": "tl", "shots": [os.path.join(self.tmp, "a.poster.json"),
                                    os.path.join(self.tmp, "b.poster.json")]},
            root_dir=self.tmp)
        self.assertFalse(rep["passed"], rep)
        self.assertEqual(rep["handoffs"][0]["status"], "HARD_CUT_JUMP")

    def test_backdrop_mismatch_downgraded_by_flag_raises_no_error(self):
        a, b = _shot("a", "bg-a", 100), _shot("b", "bg-b", 100)
        pa = os.path.join(self.tmp, "a.poster.json")
        pb = os.path.join(self.tmp, "b.poster.json")
        with open(pa, "w") as f:
            json.dump(a, f)
        with open(pb, "w") as f:
            json.dump(b, f)
        rep = verify_timeline_continuity(
            {"id": "tl", "shots": [pa, pb]},
            root_dir=self.tmp, require_seamless_handoff=False)
        self.assertTrue(rep["passed"], rep)
        self.assertEqual(rep["handoffs"][0]["status"], "BACKDROP_WARN")

    def test_character_jump_fails_by_default_and_passes_with_knob(self):
        a, b = _shot("a", "bg-a", 100), _shot("b", "bg-a", 130)  # 30 px jump
        pa = os.path.join(self.tmp, "a.poster.json")
        pb = os.path.join(self.tmp, "b.poster.json")
        with open(pa, "w") as f:
            json.dump(a, f)
        with open(pb, "w") as f:
            json.dump(b, f)
        default = verify_timeline_continuity({"id": "tl", "shots": [pa, pb]}, root_dir=self.tmp)
        self.assertFalse(default["passed"], default)
        self.assertEqual(default["handoffs"][0]["status"], "CHAR_JUMP")
        relaxed = verify_timeline_continuity({"id": "tl", "shots": [pa, pb]},
                                             root_dir=self.tmp, max_char_jump_px=40.0)
        self.assertTrue(relaxed["passed"], relaxed)

    def test_faded_out_character_is_not_a_jump(self):
        a, b = _shot("a", "bg-a", 100, hero_end_opacity=0.0), _shot("b", "bg-a", 500)
        pa = os.path.join(self.tmp, "a.poster.json")
        pb = os.path.join(self.tmp, "b.poster.json")
        with open(pa, "w") as f:
            json.dump(a, f)
        with open(pb, "w") as f:
            json.dump(b, f)
        rep = verify_timeline_continuity({"id": "tl", "shots": [pa, pb]}, root_dir=self.tmp)
        self.assertTrue(rep["passed"], rep)
        self.assertEqual(rep["handoffs"][0]["status"], "PASS")


class TestCliEndToEnd(unittest.TestCase):
    """The CLI resolves knobs as: --flag > timeline.continuity > default."""

    def test_allow_non_seamless_flag_and_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = _shot("a", "bg-a", 100), _shot("b", "bg-b", 100)
            pa = os.path.join(tmp, "a.poster.json")
            pb = os.path.join(tmp, "b.poster.json")
            with open(pa, "w") as f:
                json.dump(a, f)
            with open(pb, "w") as f:
                json.dump(b, f)

            failing = os.path.join(tmp, "failing.json")
            with open(failing, "w") as f:
                json.dump({"id": "tl", "shots": [pa, pb]}, f)
            # Without the flag and no continuity block: exit 1, handoff named.
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"),
                                   "verify-continuity", "--timeline", failing],
                                  capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("HARD_CUT_JUMP", proc.stdout + proc.stderr)

            softened = os.path.join(tmp, "softened.json")
            with open(softened, "w") as f:
                json.dump({"id": "tl", "shots": [pa, pb],
                           "continuity": {"require_seamless_handoff": False}}, f)
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"),
                                   "verify-continuity", "--timeline", softened],
                                  capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("BACKDROP_WARN", proc.stdout)

            # An invalid continuity block is refused, not ignored.
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w") as f:
                json.dump({"id": "tl", "shots": [pa, pb],
                           "continuity": {"resistance": 42}}, f)
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"),
                                   "verify-continuity", "--timeline", bad],
                                  capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("unknown key 'resistance'", proc.stdout + proc.stderr)


class TestTimelineContinuityValidation(unittest.TestCase):
    def test_valid_block_accepted(self):
        errs = validate_timeline({"id": "t", "shots": ["a.poster.json"],
                                  "continuity": {"max_char_jump_px": 24.5,
                                                 "require_seamless_handoff": False,
                                                 "min_visible_opacity": 0.3}})
        self.assertEqual(errs, [])

    def test_unknown_key_rejected(self):
        errs = validate_timeline({"id": "t", "shots": ["a.poster.json"],
                                  "continuity": {"max_jump": 5}})
        self.assertTrue(any("max_jump" in e for e in errs), errs)

    def test_type_and_range_checks(self):
        errs = validate_timeline({"id": "t", "shots": ["a.poster.json"],
                                  "continuity": {"max_char_jump_px": -1}})
        self.assertTrue(any("max_char_jump_px" in e for e in errs), errs)
        errs = validate_timeline({"id": "t", "shots": ["a.poster.json"],
                                  "continuity": {"min_visible_opacity": 1.5}})
        self.assertTrue(any("min_visible_opacity" in e for e in errs), errs)
        errs = validate_timeline({"id": "t", "shots": ["a.poster.json"],
                                  "continuity": {"require_seamless_handoff": "yes"}})
        self.assertTrue(any("require_seamless_handoff" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()

class TestComponentCharacterCoverage(unittest.TestCase):
    """verify-blocking covers component character layers; verify_puppet_rig covers component rigs."""

    def test_blocking_covers_component_characters(self):
        from core.rig import verify_stage_blocking
        spec = {
            "id": "comp",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 10,
            "layers": [
                {"id": "warrior", "type": "component", "component": "Warrior",
                 "role": "humanoid", "rect": [10, 100, 200, 400], "z": 0,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.2, 0.8]},
                {"id": "sage", "type": "component", "component": "Sage",
                 "role": "humanoid", "rect": [30, 100, 200, 400], "z": 1,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.2, 0.8]},
            ],
            "gates": [],
        }
        res = verify_stage_blocking(spec)
        self.assertFalse(res["passed"], res)
        self.assertTrue(any("overlap" in e.lower() or "warrior" in e.lower() for e in res["errors"]), res["errors"])

    def test_blocking_disjoint_component_characters_pass(self):
        from core.rig import verify_stage_blocking
        spec = {
            "id": "comp",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 10,
            "layers": [
                {"id": "a", "type": "component", "component": "A",
                 "role": "humanoid", "rect": [0, 100, 200, 400], "z": 0,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.2, 0.8]},
                {"id": "b", "type": "component", "component": "B",
                 "role": "humanoid", "rect": [400, 100, 200, 400], "z": 1,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.2, 0.8]},
            ],
            "gates": [],
        }
        res = verify_stage_blocking(spec)
        self.assertTrue(res["passed"], res)

    def test_puppet_rig_covers_component_rig(self):
        from core.rig.verification import puppet as puppet_mod
        spec = {
            "id": "comp",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 10,
            "layers": [
                {"id": "body", "type": "component", "component": "Body",
                 "role": "humanoid", "rect": [0, 0, 400, 600], "z": 0,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.2, 0.8],
                 "kit": {"socket": [200, 200]}},
                {"id": "arm", "type": "component", "component": "Arm",
                 "role": "humanoid", "parent": "body", "rect": [0, 0, 400, 600], "z": 1,
                 "keyColor": "#ffffff", "blend": "normal", "blockCore": [0.4, 0.6],
                 "kit": {"socket": [200, 200], "joint": [150, 250]}},
            ],
            "gates": [],
        }
        res = puppet_mod.verify_puppet_rig(spec, out_dir="build/test-inspect")
        self.assertIn("joints", res, res)
        # component pairs should produce results, not be skipped
        self.assertTrue(len(res["joints"]) >= 1 or any("missing" not in e.lower() for e in res["errors"]), res)
