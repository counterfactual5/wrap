"""Every draw the spec accepts must have a rendering regression test.

`core/spec/constants.py`'s DRAWS is the contract: whatever it lists, an author may
write in a spec. The suite only guarded three of the eighteen — the twelve
hero scenes, plus bar / field / captions, had none, so a refactor of
remotion/layers/ could break them while `make verify` stayed green.

The test takes its list FROM DRAWS, so adding a draw without a test fails
right here rather than in someone's finished episode.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.quality import pixels as metrics
from core.spec.constants import DRAWS
from tests.contract.agreement import (
    classify_missing,
    missing_draws,
    parser_fresh_or_fail,
    renderer_dispatch_names,
    renderer_draws,
    renderer_fallback_draws,
)

# grid and dots are backgrounds: S2 prepares them as PNGs and S3 composites
# them. Every other draw is a Remotion component rendered in S3.
BACKGROUND_DRAWS = ("grid", "dots")
COMPONENT_DRAWS = sorted(d for d in DRAWS if d not in BACKGROUND_DRAWS)

# The canvas is the real one: several components (captions, path) draw at
# fixed pixel sizes, so a tiny canvas would make them invisible and the
# assertion would measure the canvas, not the component.
W, H = 1080, 1920
FRAMES = 30


def _remove_if_present(path):
    if os.path.exists(path):
        os.remove(path)


def _layer_for(draw):
    """A code layer that uses the draw, with whatever that draw needs.

    `bar` needs a color; `captions` needs its items, otherwise it draws
    nothing at all (an empty subtitle track is a valid, invisible state)."""
    layer = {"id": "subject", "type": "code", "draw": draw,
             "rect": [0, 0, W, H], "z": 0}
    if draw == "bar":
        layer["color"] = "#E03A3A"
    if draw == "captions":
        layer["params"] = {"items": [{"frame": 0, "text": "hello"}]}
    if draw == "path":
        # reveal defaults to [0, 60] frames — a 30-frame shot would only
        # draw half of it. Cover the whole shot, and draw across the canvas
        # so the stroke is actually visible.
        layer["params"] = {
            "d": "M 60,960 L 1020,960",
            "stroke": "#B84DFF", "width": 8,
            "reveal": [0, FRAMES - 1],
        }
    return layer


def _spec_for(draw):
    return {
        "id": f"draw-{draw}",
        "canvas": {"w": W, "h": H, "bg": "#070512"},
        "fps": 30,
        "durationInFrames": FRAMES,
        "vibe": False,
        "style": "tests/fixtures/style-quantum.json",
        "layers": [_layer_for(draw)],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.9}],
    }


class TestDrawContract(unittest.TestCase):
    """One rendering test per draw value the spec accepts."""

    def setUp(self):
        # The real stages write the frozen ledger while they run. Point them at
        # a throwaway ledger (POSTER_MANIFEST) so a working-tree snapshot
        # taken WHILE the test runs does not read those writes as "the tree
        # changed" — and the project's own manifest stays untouched.
        self._ledger = os.path.join(ROOT, ".tmp", "draw-contract-manifest.json")
        os.makedirs(os.path.dirname(self._ledger), exist_ok=True)
        self._env = {"POSTER_MANIFEST": self._ledger}
        self._saved = {k: os.environ.get(k) for k in self._env}
        os.environ.update(self._env)
        self.addCleanup(self._restore_env)
        self.addCleanup(_remove_if_present, self._ledger)

    def _restore_env(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _render(self, draw):
        spec = _spec_for(draw)
        # The temporary spec lives under .tmp/ (gitignored): a spec file in
        # spec/ would be an untracked file, and a working-tree snapshot taken
        # while the test runs would count it as a change.
        spec_path = os.path.join(ROOT, ".tmp", f"{spec['id']}.poster.json")
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)
        # Explicit cleanup: addCleanup runs when the test method ends, but a
        # subTest failure can leave the spec behind, and these files would
        # then be picked up by the pipeline's own spec glob.
        self.addCleanup(_remove_if_present, spec_path)
        res = subprocess.run(
            [sys.executable, "stages/03_compose.py", "--spec", spec_path],
            cwd=ROOT, capture_output=True, text=True, env={**os.environ, **self._env})
        self.assertEqual(res.returncode, 0,
                         f"{draw} failed to render:\n{res.stdout}\n{res.stderr}")
        frames_dir = os.path.join(ROOT, "build", "frames", spec["id"])
        frames = sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir)
                        if f.endswith(".png"))
        self.assertTrue(frames, f"{draw} produced no frame")
        return frames

    def test_00_every_component_draw_renders_something(self):
        for draw in COMPONENT_DRAWS:
            with self.subTest(draw=draw):
                frames = self._render(draw)
                # The contract is "this draw puts something on screen", not
                # how it looks: compare against the background the spec
                # declares, so a flat-colour draw (bar) counts as content and
                # an untouched background does not.
                #
                # Several draws enter over time (captions appear on their
                # item's frame, a path draws itself along a reveal window),
                # so the LAST frame is the one that shows what they draw.
                bg = (0x07, 0x05, 0x12)
                rgb = metrics.read_rgb(frames[-1], W, H)
                painted = sum(1 for i in range(0, len(rgb), 3)
                              if abs(rgb[i] - bg[0]) > 12
                              or abs(rgb[i + 1] - bg[1]) > 12
                              or abs(rgb[i + 2] - bg[2]) > 12)
                self.assertGreater(painted / (len(rgb) // 3), 0.0005,
                                   f"{draw} rendered nothing (background only)")

    def test_01_the_contract_and_the_tests_agree(self):
        """A draw added to the contract without a rendering path must fail
        here, not in someone's finished episode.

        Two directions, both machine-checked:
          * the contract must not accept a draw the renderer never draws —
            the renderer side is parsed from the renderer's own source, so
            it cannot drift away from the renderer the way a copied list
            would;
          * every component draw must be exercised by the render test
            above.

        If this check complains that a draw has no rendering path, the fix
        belongs in the renderer (or in the parser, tests/contract/agreement.py)
        — never by removing the draw from the contract.
        """
        # The canary first: if the parser no longer sees the renderer the
        # way it used to, the checks below would narrow their own idea of
        # the renderer — and a sub-set check cannot complain about that.
        # The message comes from one place, so a stale parser always says
        # the same thing: fix the parser, not the contract.
        self.assertTrue(parser_fresh_or_fail(),
                        "the parser went stale — fix "
                        "tests/contract/agreement.py, not the contract")
        # The fallback is not an implementation: a draw that only the
        # fallback can draw is not handled by the renderer at all.
        fallback_only = ((set(DRAWS) & renderer_fallback_draws())
                         - renderer_draws())
        self.assertEqual(
            fallback_only, set(),
            f"the contract names draws that only the chain's fallback draws: "
            f"{sorted(fallback_only)} — give them their own branch in the "
            f"renderer (rendering exactly the same thing); do not remove the "
            f"draw from the contract")
        # The out-of-bounds verdict keeps its old meaning: the renderer
        # cannot draw this draw at all — not even by falling back to
        # something else. (The assertion above is the sharper one: the
        # contract names a draw that only the fallback could draw.)
        out_of_bounds, parser_drift = classify_missing(
            set(DRAWS), renderer_draws() | renderer_fallback_draws(),
            renderer_dispatch_names())
        # The classification splits the raw difference the cross-layer check
        # reports: missing_draws is the whole set, the two parts say WHY.
        self.assertEqual(
            missing_draws(set(DRAWS), renderer_draws()),
            out_of_bounds | parser_drift)
        self.assertEqual(
            out_of_bounds, set(),
            f"the contract accepts draws the renderer never draws: "
            f"{sorted(out_of_bounds)}"
            + ("  (if the renderer recently changed how it dispatches on "
               "draw, fix the parser in tests/contract/agreement.py first — "
               "the contract must not shrink to make a check green)"
               if out_of_bounds else ""))
        self.assertEqual(
            parser_drift, set(),
            f"the renderer dispatches on these draws but the parser did not "
            f"catch a branch for them — the renderer changed how it "
            f"dispatches; fix tests/contract/agreement.py, not the contract: "
            f"{sorted(parser_drift)}")
        # Every component draw must be exercised by the test above.
        self.assertTrue(set(COMPONENT_DRAWS).issubset(set(DRAWS)))

    def test_02_background_draws_are_prepared_by_s2(self):
        """grid / dots are backgrounds: S2 writes them as PNGs."""
        for draw in BACKGROUND_DRAWS:
            with self.subTest(draw=draw):
                spec = _spec_for(draw)
                spec_path = os.path.join(ROOT, ".tmp", f"{spec['id']}.poster.json")
                os.makedirs(os.path.dirname(spec_path), exist_ok=True)
                with open(spec_path, "w") as f:
                    json.dump(spec, f, indent=2)
                self.addCleanup(_remove_if_present, spec_path)
                res = subprocess.run(
                    [sys.executable, "stages/02_prepare.py", "--spec", spec_path],
                    cwd=ROOT, capture_output=True, text=True,
                    env={**os.environ, **self._env})
                self.assertEqual(res.returncode, 0,
                                 f"{draw} failed to prepare:\n{res.stderr}")
                # S2 names the prepared file after the LAYER id.
                prepared = os.path.join(ROOT, "build", "prepared",
                                        spec["id"], "subject.png")
                self.assertTrue(os.path.exists(prepared),
                                f"{draw} produced no prepared background")


if __name__ == "__main__":
    unittest.main()
