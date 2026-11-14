"""The contract must not be quietly narrowed.

`core/spec/constants.py`'s `LAYER_TYPES` is what a spec may declare; the
Remotion renderer is what actually draws. `tests/contract/agreement.py`
guards one direction — a type the contract accepts but the renderer cannot
draw. The other direction was unguarded.

Delete an entry from `LAYER_TYPES` and both sides shrink together: the
cross-layer check sees a smaller contract and stays green. The capability
is gone and no check said so. This module pins the second direction by
counter-proof: narrowing the LIVE contract must be OBSERVABLE — a spec that
used the narrowed type must stop validating, through the same loud gate
every author hits.

Two vocabulary facts are also pinned, post zero-template migration:

  * `DRAWS` is the removed procedural draw vocabulary: defined in the
    contract module, empty, and loud.
  * `LAYER_TYPES` names exactly the surviving media/component vocabulary.

Nothing here copies a list. The renderer side is parsed from the renderer's
own source (`renderer_layer_types`), the contract side is read live from
`core.spec.constants`. A copied list would be a second implementation of the
contract, drifting exactly when the first one changes — the failure mode
`tests/contract/agreement.py` exists to prevent.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.spec import constants  # noqa: E402
from core.spec.shot import validate  # noqa: E402
from tests.contract.agreement import (  # noqa: E402
    contract_layer_types,
    contract_leads_renderer,
    missing_types,
    parser_fresh_or_fail,
    renderer_layer_types,
)


def _spec(layer):
    return {
        "id": "weakening-probe",
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


class TestContractNotQuietlyNarrowed(unittest.TestCase):
    def test_00_the_two_invariants_hold(self):
        # The canary first: if the parser no longer sees the renderer the
        # way it used to, the checks below would be comparing against a
        # narrowed idea of the renderer.
        self.assertTrue(parser_fresh_or_fail(),
                        "the parser went stale — fix "
                        "tests/contract/agreement.py, not the contract")
        missing = missing_types(contract_layer_types(), renderer_layer_types())
        self.assertEqual(
            missing, set(),
            f"the contract accepts layer types the renderer never draws: "
            f"{sorted(missing)} — add the rendering path in the renderer or "
            f"remove the type from core.spec.constants.LAYER_TYPES; do not "
            f"leave the contract promising something nothing draws")
        # A beyond-contract renderer branch is allowed ONLY as a loud
        # refusal: the validator must reject it by name (see
        # test_contract_agreement for the full check).
        for ltype in contract_leads_renderer():
            errs = validate(_spec(_layer(ltype)))
            self.assertTrue(errs, f"{ltype!r} must be refused by the validator")

    def test_01_a_narrowed_contract_is_observable_through_the_gate(self):
        """The counter-proof: weaken the LIVE contract and an author's spec
        must start failing validation. If narrowing were invisible, this
        test would be the only tripwire — and it must trip."""
        live = contract_layer_types()
        self.assertTrue(live, "the contract is empty — nothing to weaken")
        for victim in sorted(live):
            original = constants.LAYER_TYPES
            try:
                constants.LAYER_TYPES = set(original) - {victim}
                self.assertNotEqual(constants.LAYER_TYPES, original,
                                    "the contract did not actually shrink")
                errs = validate(_spec(_layer(victim)))
                self.assertTrue(
                    errs,
                    f"narrowing the contract by dropping {victim!r} was NOT "
                    f"observable: a spec declaring {victim!r} still validated")
            finally:
                constants.LAYER_TYPES = original
        # Restoring the contract must clear the effect — the gate reads the
        # live list, it does not remember a verdict.
        for ltype in sorted(live):
            self.assertEqual(validate(_spec(_layer(ltype))), [])


class TestPolicyIsDocumented(unittest.TestCase):
    """The policy is written down where it will be read: next to the lists a
    maintainer edits."""

    # Keep policy checks next to the live contract vocabulary.
    CONTRACT = os.path.join(ROOT, "core", "spec", "constants.py")

    def _text(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _flat(self, path):
        """The file's text with whitespace collapsed, so a sentence can wrap."""
        return " ".join(self._text(path).split())

    def test_00_the_migration_policy_sits_next_to_the_lists(self):
        text = self._flat(self.CONTRACT)
        self.assertTrue("zero-template migration" in text,
                        "core/spec/constants.py does not state the migration law")
        self.assertTrue("migration boundary" in text,
                        "core/spec/constants.py does not say what DRAWS now is")
        self.assertTrue("DRAWS = set()" in text,
                        "the removed draw vocabulary must be an explicit empty set")

    def test_01_the_vocabulary_is_defined_in_the_contract_module(self):
        """The policy check must inspect the source of the live vocabulary."""
        self.assertEqual(os.path.realpath(constants.__file__), self.CONTRACT)
        self.assertRegex(self._text(self.CONTRACT), r"(?m)^LAYER_TYPES\s*=\s*\{")
        self.assertRegex(self._text(self.CONTRACT), r"(?m)^DRAWS\s*=\s*set\(\)")
        from core.spec import DRAWS, LAYER_TYPES
        self.assertIs(DRAWS, constants.DRAWS)
        self.assertIs(LAYER_TYPES, constants.LAYER_TYPES)
        self.assertEqual(set(DRAWS), set(),
                         "the procedural draw vocabulary must stay removed")
        self.assertEqual(set(LAYER_TYPES), {"ai", "video", "component"})


if __name__ == "__main__":
    unittest.main()
