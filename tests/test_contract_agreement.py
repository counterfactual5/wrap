"""The contract and the renderer must agree — checked by the machine, not by a review.

R1 (commit c064196) was a case where `core/schema.py` refused something the
Remotion renderer actually implemented: `motion.zoom` on a code layer drawn as
grid or dots. The only detector that caught it was a human/agent review — the
kind of detector that fails silently (this run's review actor produced no
output four times in a row).

These tests make the agreement machine-checked:

  * every draw the contract accepts has a rendering path — the safe
    direction: the contract must never accept something the renderer does not
    draw. The renderer side is derived from the renderer's own source, never
    from a list copied into Python;
  * the R1 dimension specifically: a code layer's `motion.zoom` is accepted,
    while the code layers the renderer ignores it for stay refused.

The counter-proof matters as much as the invariant: the checks below must
actually fail on a crafted mismatch — otherwise they would be decoration.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

from tests.contract_agreement import (  # noqa: E402
    contract_draws,
    missing_draws,
    renderer_draws,
)

from core.schema import validate  # noqa: E402


def _spec(layer):
    return {
        "id": "contract-agreement",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [layer],
        "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }


class TestContractRendererAgreement(unittest.TestCase):
    def test_00_the_invariant_flags_a_draw_the_renderer_does_not_draw(self):
        """The counter-proof: a crafted mismatch must be caught. If this fails,
        the invariant below is decoration and the whole file is worthless."""
        self.assertEqual(
            missing_draws({"grid", "phantom-draw"}, {"grid", "dots"}),
            {"phantom-draw"})
        self.assertEqual(missing_draws({"grid"}, {"grid", "dots"}), set())

    def test_01_every_contract_draw_has_a_rendering_path(self):
        missing = missing_draws(contract_draws(), renderer_draws())
        self.assertEqual(missing, set(),
                         f"the contract accepts draws the renderer never draws: "
                         f"{sorted(missing)}")

    def test_02_a_code_layers_zoom_is_accepted_where_the_renderer_has_it(self):
        """R1's dimension: the renderer interpolates motion.zoom for the code
        layers it prepares as an image (grid, dots) — the same component it
        uses for ai layers. The contract must not refuse it."""
        layer = {"id": "l", "type": "code", "draw": "grid",
                 "rect": [0, 0, 1080, 1920], "z": 0,
                 "motion": {"type": "geometric", "zoom": [1.0, 1.2]}}
        self.assertEqual(validate(_spec(layer)), [])

    def test_03_a_code_layer_without_a_zoom_path_is_still_refused(self):
        """bar / field / path / captions go through the component that reads
        only motion.pan — a zoom there would be dropped silently."""
        for draw in ("bar", "field", "path", "captions"):
            with self.subTest(draw=draw):
                layer = {"id": "l", "type": "code", "draw": draw,
                         "color": "#E03A3A", "rect": [0, 0, 1080, 1920], "z": 0,
                         "motion": {"type": "geometric", "zoom": [1.0, 1.2]}}
                errs = validate(_spec(layer))
                self.assertTrue(any("zoom is not supported" in e for e in errs),
                                f"code/{draw} accepted a zoom: {errs}")


class TestTheExistingContractTestIsNotVacuous(unittest.TestCase):
    """`tests/test_draw_contract.py` promises that a draw added to the contract
    without a rendering path fails there. Today it does not: the assertion is
    a tautology (`assertIn(draw, set(DRAWS))` — every draw is in DRAWS), and
    adding a draw with no rendering path leaves the rendering contract test
    green (only the documentation contract notices, because the Skill document
    has to list the draw too)."""

    def test_00_the_draw_contract_test_asserts_more_than_a_tautology(self):
        path = os.path.join(ROOT, "tests", "test_draw_contract.py")
        with open(path) as f:
            src = f.read()
        self.assertNotIn(
            "self.assertIn(draw, set(DRAWS))", src,
            "the draw contract test still asserts the tautology it always did")
        self.assertIn("missing_draws", src,
                      "the draw contract test does not use the cross-layer "
                      "invariant yet")


if __name__ == "__main__":
    unittest.main()
