"""The contract and the renderer must agree — checked by the machine, not by a review.

R1 (commit c064196) was a case where the spec contract refused something the
Remotion renderer actually implemented (`motion.zoom` on prepared code
layers). The only detector that caught it was a human/agent review — the
kind of detector that fails silently.

These tests make the agreement machine-checked, on the layer-type axis (the
procedural draw axis was removed in the zero-template migration; its refusal
contract lives in `test_migration_rejection.py`):

  * every type the contract accepts has a rendering path — the renderer side
    is derived from the renderer's own source, never from a copied list;
  * every type the renderer branches on but the contract refuses is refused
    LOUDLY by the validator — a beyond-contract renderer branch may exist as
    a compatibility alias, but it must be unreachable through a loud gate,
    never silently accepted and never silently drawn as something else.

The counter-proofs matter as much as the invariants: the checks below must
actually fail on a crafted mismatch — otherwise they would be decoration.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.contract.agreement import (  # noqa: E402
    contract_layer_types,
    contract_leads_renderer,
    missing_types,
    parser_fresh_or_fail,
    renderer_layer_types,
)

from core.spec.shot import validate  # noqa: E402


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


def _layer(ltype):
    if ltype == "ai":
        return {"id": "l", "type": "ai", "asset": "a", "keyColor": "#070512",
                "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0}
    if ltype == "video":
        return {"id": "l", "type": "video", "asset": "v",
                "rect": [0, 0, 1080, 1920], "z": 0}
    return {"id": "l", "type": ltype, "component": "Probe",
            "rect": [0, 0, 1080, 1920], "z": 0}


class TestContractRendererAgreement(unittest.TestCase):
    def setUp(self):
        # The canary first: if the parser no longer sees the renderer the
        # way it used to, the sets below would be a narrowed idea of the
        # renderer — and a sub-set check cannot complain about that.
        self.assertTrue(parser_fresh_or_fail(),
                        "the parser went stale — fix "
                        "tests/contract/agreement.py, not the contract")

    def test_00_the_invariant_flags_a_type_the_renderer_does_not_draw(self):
        """The counter-proof: a crafted mismatch must be caught. If this
        fails, the invariant below is decoration and the file is worthless."""
        self.assertEqual(
            missing_types({"ai", "phantom-type"}, {"ai", "video"}),
            {"phantom-type"})
        self.assertEqual(missing_types({"ai"}, {"ai", "video"}), set())

    def test_01_every_contract_type_has_a_rendering_path(self):
        missing = missing_types(contract_layer_types(), renderer_layer_types())
        self.assertEqual(missing, set(),
                         f"the contract accepts layer types the renderer never "
                         f"draws: {sorted(missing)}")

    def test_02_a_beyond_contract_renderer_type_is_refused_loudly(self):
        """The renderer may keep a compatibility branch the contract refuses,
        but then the validator must refuse it too — loudly, by name. A type
        accepted by NEITHER side is dead vocabulary; a type accepted by the
        renderer but waved through by the contract would be a silent gate."""
        beyond = contract_leads_renderer()
        for ltype in beyond:
            with self.subTest(ltype=ltype):
                errs = validate(_spec(_layer(ltype)))
                self.assertTrue(
                    any("type must be one of" in e for e in errs),
                    f"renderer type {ltype!r} is outside the contract but the "
                    f"validator did not refuse it: {errs}")

    def test_03_ai_zoom_is_accepted_and_component_zoom_is_refused(self):
        """R1's surviving dimension: motion.zoom is a camera on prepared
        media (ai/video). A component layer would silently drop it — the
        contract refuses it instead of promising something the renderer
        never interpolates."""
        layer = {"id": "l", "type": "ai", "asset": "a", "keyColor": "#070512",
                 "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0,
                 "motion": {"type": "geometric", "zoom": [1.0, 1.2]}}
        self.assertEqual(validate(_spec(layer)), [])
        layer["type"] = "component"
        layer["component"] = "Probe"
        del layer["asset"], layer["keyColor"], layer["blend"]
        errs = validate(_spec(layer))
        self.assertTrue(any("zoom is unsupported" in e for e in errs), errs)
        layer["motion"] = {"type": "geometric", "pan": [0, 40]}
        errs = validate(_spec(layer))
        self.assertTrue(any("migration required" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
