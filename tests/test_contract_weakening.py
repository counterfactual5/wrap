"""The contract must not be quietly narrowed.

`core/schema.py`'s DRAWS is what an author may write in a spec; the Remotion
renderer is what actually draws. The cross-layer check
(`tests/contract_agreement.py`) guards one direction — a draw the contract
accepts but the renderer cannot draw. The other direction was unguarded.

Delete an entry from DRAWS and BOTH sides shrink together: every check that
iterates FROM the contract (`tests/test_draw_contract.py` takes its render
list from DRAWS, `tests/test_docs_draw_contract.py` walks DRAWS) sees a
smaller contract and stays green. Measured on this repository: with one draw
removed from DRAWS and nothing else touched — not the Skill, not the
renderer — `make verify` still passed (198 tests, rc=0). The capability was
gone and no check said so. The only trace is the author's "draw must be one
of [...]", which does not say the draw existed yesterday.

This module pins the second direction: every draw the renderer has an
explicit branch for must be in the contract, or the contract was narrowed and
the check says which draw.

Nothing here copies a list. The renderer side is parsed from the renderer's
own source (`renderer_draws`), the contract side is read live from
`core.schema.DRAWS`. A copied list would be a second implementation of the
contract, drifting exactly when the first one changes — the failure mode
`tests/contract_agreement.py` exists to prevent.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core import schema
from tests.contract_agreement import (
    contract_draws,
    contract_leads_renderer,
    parser_fresh_or_fail,
    renderer_draws,
)


class TestContractWeakening(unittest.TestCase):
    """The renderer may not lead the contract.

    The policy is deliberate friction: until now the renderer was allowed to
    be ahead of the contract (a renderer-only draw was simply not offered to
    authors). It is no longer — a renderer branch must be in the contract,
    and a contract that dropped one is reported instead of silently
    narrowing what authors may write.
    """

    def test_00_the_renderer_does_not_lead_the_contract(self):
        # The canary first: if the parser no longer sees the renderer the
        # way it used to, the set below would be a narrowed idea of the
        # renderer, and could report a disagreement that is not one.
        self.assertTrue(parser_fresh_or_fail(),
                        "the parser went stale — fix "
                        "tests/contract_agreement.py, not the contract")
        leading = contract_leads_renderer()
        self.assertEqual(
            leading, set(),
            f"the renderer draws {sorted(leading)} but the contract does not "
            f"accept them: the contract was narrowed — add the draw to "
            f"core.schema.DRAWS (the renderer already draws it) or remove the "
            f"branch from the renderer; do not shrink the contract silently")

    def test_01_a_narrowed_contract_is_reported_by_name(self):
        """The counter-proof: weaken the LIVE contract and the check must
        name the draw that was lost.

        The victim is taken from the live contract (and from the draws the
        renderer actually has) rather than written down here: a literal list
        of draw names in this file would be a second copy of the contract —
        exactly what `tests/contract_agreement.py` warns against.
        """
        live = contract_draws()
        self.assertTrue(live, "the contract is empty — nothing to weaken")
        # The victim is a draw the RENDERER has a branch for: dropping such a
        # draw from the contract is what makes the renderer lead it. (Taken
        # from the intersection, so the name always means "the renderer drew
        # it and the contract lost it" — never the fallback-only case.)
        drawn = renderer_draws() & live
        self.assertTrue(drawn, "the renderer and the contract share no draw")
        victim = sorted(drawn)[0]
        original = schema.DRAWS
        try:
            # The live list, narrowed by one draw — the same edit a
            # maintainer makes when they "clean up" a draw they think is
            # unused.
            schema.DRAWS = set(original) - {victim}
            self.assertNotEqual(schema.DRAWS, original,
                                "the contract did not actually shrink")
            leading = contract_leads_renderer()
        finally:
            schema.DRAWS = original
        self.assertIn(
            victim, leading,
            f"narrowing the contract by dropping {victim!r} went unreported: "
            f"leading={sorted(leading)}")
        # Restoring the contract must clear the report — the check reads the
        # live list, it does not remember a verdict.
        self.assertEqual(contract_leads_renderer(), set(),
                         "the report survived restoring the contract")


class TestPolicyIsDocumented(unittest.TestCase):
    """The policy is written down where it will be read.

    Two places: next to the list a maintainer edits, and in the Skill an
    author reads. Plus the two gaps this check does NOT cover — a check that
    claims more than it covers is its own kind of quiet narrowing.
    """

    SCHEMA = os.path.join(ROOT, "core", "schema.py")
    SKILL = os.path.join(ROOT, "skills", "wrap",
                         "SKILL.md")

    def _text(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _flat(self, path):
        """The file's text with whitespace collapsed.

        The assertions below look for whole sentences, not single words: a
        word like "BOTH" can appear anywhere in a file, and a sentence can
        wrap across lines. Collapsing the whitespace lets one fragment match
        a wrapped sentence without pinning the line breaks.
        """
        return " ".join(self._text(path).split())

    def test_00_the_policy_sits_next_to_the_list(self):
        text = self._flat(self.SCHEMA)
        # assertTrue, not assertIn: the failure message of assertIn dumps
        # the whole file, and this file is 300 lines of validator.
        self.assertTrue("The renderer may not lead the contract" in text,
                        "core/schema.py does not warn that the renderer may "
                        "not lead the contract")
        self.assertTrue("test_contract_weakening" in text,
                        "core/schema.py does not point at the check that "
                        "guards this direction")

    def test_01_the_policy_is_in_the_skill(self):
        text = self._flat(self.SKILL)
        self.assertTrue("The renderer may not lead the contract" in text,
                        "the Skill does not state the policy")
        self.assertTrue("test_contract_weakening" in text,
                        "the Skill does not point at the check")

    def test_02_the_two_gaps_are_written_down(self):
        """What this check does NOT cover, said out loud."""
        text = self._flat(self.SKILL)
        self.assertTrue("BOTH the contract and the renderer stays green" in text,
                        "the Skill does not say that removing a draw from both "
                        "the contract and the renderer stays green")
        self.assertTrue("present but unreachable still" in text,
                        "the Skill does not say that the renderer side is read "
                        "from the source, so an unreachable branch still counts "
                        "as implemented")


if __name__ == "__main__":
    unittest.main()
