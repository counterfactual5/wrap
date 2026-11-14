"""Hardening for the cross-layer check: the extraction, and its counter-proofs.

The cross-layer invariant itself lives in tests/contract/test_draw_contract.py (it is
where that file's "a draw added to the contract must fail here" promise
lives). This file owns the harder half: proving that the check is actually
looking at the renderer, and that it would catch a contract that outruns it.

Why this matters: R1 (commit c064196) shipped a case where the contract
refused something the renderer had already implemented, and the only thing
that caught it was a human/agent review — the kind of detector that fails
silently (this run's review actor produced no output four times in a row).

What is machine-checked here is the draw-NAME axis: the contract must not
accept a draw the renderer has no path for, and the renderer side must be
derived from the renderer's own source rather than from a list copied into
Python. The capability axis (which motion channels each layer kind gets) is
still read by a human — see the scope note in tests/contract/agreement.py.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

from tests.contract.agreement import (
    classify_missing,
    contract_draws,
    missing_draws,
    parse_dispatch_names,
    parse_draws,
    parser_fresh_or_fail,
    parser_stale,
    renderer_dispatch_names,
    renderer_draws,
    renderer_fallback_draws,
)

from core.spec import constants


class TestTheParserIsDerived(unittest.TestCase):
    """The renderer side must come from the renderer's source. A parser that
    quietly stopped matching — or an extraction function rewritten into a
    hard-coded list — would leave the cross-layer check green while it
    checks nothing. That is the failure this class exists to catch."""

    def test_00_a_renamed_branch_follows_the_source(self):
        src = "if (layer.draw === 'grid') { return <Grid/>; }"
        self.assertEqual(parse_draws(src), {"grid"})
        # The name follows the source: the result is derived, not a list.
        self.assertEqual(parse_draws(src.replace("'grid'", "'grids'")), {"grids"})

    def test_01_quotes_and_spacing_do_not_matter(self):
        for src in ("layer.draw === 'grid'", 'layer.draw === "grid"',
                    "layer.draw==='grid'", "layer.draw === 'grid'"):
            with self.subTest(src=src):
                self.assertEqual(parse_draws(src), {"grid"})

    def test_02_a_comment_only_snippet_parses_to_nothing(self):
        src = "// layer.draw === 'grid' used to be a branch here"
        self.assertEqual(parse_draws(src), set())

    def test_03_the_real_renderer_is_parsed_not_copied(self):
        """The set the check uses must come from the source: change the source
        and the set must change with it. A hard-coded list would not."""
        real = renderer_draws()
        self.assertIn("geodesic", real)
        self.assertIn("bar", real)
        for name in real:
            self.assertRegex(name, r"^[a-z][a-z0-9-]*$")

    def test_04_the_extraction_follows_a_modified_source(self):
        """The decisive one: feed the extractor a source in which a draw was
        renamed and watch the name disappear. An extraction rewritten as a
        hard-coded list cannot pass this."""
        src = ("if (layer.draw === 'geodesic') { return <Geodesic/>; }\n"
               "if (layer.draw === 'ripples') { return <Ripples/>; }\n")
        self.assertEqual(parse_draws(src), {"geodesic", "ripples"})
        renamed = src.replace("'geodesic'", "'geodesicc'")
        self.assertEqual(parse_draws(renamed), {"geodesicc", "ripples"})
        self.assertNotIn("geodesic", parse_draws(renamed))
        # ... and the same through the seam the checker uses:
        self.assertEqual(renderer_draws(src=src), {"geodesic", "ripples"})
        self.assertNotIn("geodesic",
                         renderer_draws(src=src.replace("'geodesic'",
                                                       "'geodesicc'")))

    def test_05_a_switch_case_is_a_dispatch_too(self):
        """A renderer that switches instead of comparing is still a
        dispatch: the parser must notice it as a stale parser, not as a
        contract that is suddenly wrong."""
        src = "switch (layer.draw) { case 'grid': return <Grid/>; }"
        self.assertEqual(parse_draws(src), set())
        self.assertIn("grid", parse_dispatch_names(src))

    def test_06_a_negated_comparison_is_not_a_dispatch(self):
        """`layer.draw !== 'grid'` says the renderer does NOT draw it.
        Counting that as a dispatch would point the reader at the parser
        for a draw the renderer actively rejects."""
        src = "if (layer.draw !== 'grid') { return null; }"
        self.assertEqual(parse_draws(src), set())
        self.assertEqual(parse_dispatch_names(src), set())

    def test_07_a_comparison_on_another_axis_is_not_a_dispatch(self):
        """The dispatch scan is about the draw axis. A comparison on some
        other axis must not make an unimplemented draw look dispatched."""
        src = "if (layer.style === 'grid') { return <Grid/>; }"
        self.assertEqual(parse_dispatch_names(src), set())


class TestTheParserCanary(unittest.TestCase):
    """The cross-layer check is a sub-set check: it complains when the
    contract runs ahead of the renderer, and stays silent when the renderer
    grows. But if the renderer's SHAPE moves out of the parser's reach, the
    implementation set shrinks on its own — and a sub-set check cannot
    complain about a set that shrank by itself. That is the one direction
    in which this check would go quietly green.

    The canary watches the parser's own patterns against the real source.
    It is derived from the parser's code, not from a hand-written list of
    "syntax families" (a hand-written list would be the registry this
    whole file exists to avoid)."""

    def test_00_the_real_source_exercises_every_parser_pattern(self):
        self.assertEqual(parser_stale(), [],
                         f"the parser no longer sees the renderer: "
                         f"{parser_stale()}")

    def test_01_a_changed_renderer_shape_is_reported_as_a_stale_parser(self):
        """The mutation counter-proof: change the shape of a copy of the
        real source and the canary must say the parser is stale — not
        quietly shrink the implementation set."""
        from tests.contract.agreement import _renderer_source
        real = _renderer_source()
        broken = real.replace("layer.draw ===", "layer.draw ~=")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        self.assertTrue(parser_stale(src=broken),
                        "a renderer that stopped using `layer.draw ===` was "
                        "not reported as a stale parser")

    def test_03_a_draw_only_the_fallback_can_draw_is_reported(self):
        """The counter-proof for the fallback rule: take the real source,
        remove the explicit bar branch, and the check must say that the
        contract's bar is only the fallback's to draw — not that the
        renderer can draw it."""
        from tests.contract.agreement import _renderer_source
        real = _renderer_source()
        broken = real.replace("if (layer.draw === 'bar')", "if (false)")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        self.assertNotIn("bar", renderer_draws(src=broken),
                         "the mutation did not remove the explicit branch")
        self.assertIn("bar", renderer_fallback_draws(src=broken),
                      "the mutation removed the fallback too")
        fallback_only = ({"bar"} & renderer_fallback_draws(src=broken)) \
            - renderer_draws(src=broken)
        self.assertEqual(fallback_only, {"bar"},
                         "a draw only the fallback can draw was not reported")

    def test_04_the_real_renderer_draws_every_contract_draw_explicitly(self):
        """With the renderer as it is, no contract draw is left to the
        fallback alone."""
        from core.spec.constants import DRAWS
        fallback_only = (set(DRAWS) & renderer_fallback_draws()) \
            - renderer_draws()
        self.assertEqual(fallback_only, set())

    def test_02_one_changed_branch_is_enough_to_be_reported(self):
        """The partial case, and the one that matters: the pattern still
        matches the other fifteen branches, so a whole-pattern check stays
        green while the implementation set has quietly lost a draw."""
        from tests.contract.agreement import _renderer_source
        real = _renderer_source()
        broken = real.replace("layer.draw === 'grid'",
                              "layer[\'draw\'] === 'grid'")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        # the mutation really removed the draw from the parsed set
        self.assertNotEqual(parse_draws(broken), parse_draws(real))
        stale = parser_stale(src=broken)
        self.assertTrue(stale,
                        "a single branch that changed shape was not reported")
        self.assertTrue(any("grid" in s for s in stale),
                        f"the changed branch was not named: {stale}")

    def test_03_the_canary_does_not_depend_on_the_contract(self):
        """The canary must not be able to go green by touching the
        contract: it reads the renderer, not the schema."""
        constants.DRAWS.add("probe-canary-draw")
        try:
            self.assertEqual(parser_stale(), [])
        finally:
            constants.DRAWS.discard("probe-canary-draw")


class TestTheInvariantAndItsCounterProofs(unittest.TestCase):
    def test_00_a_crafted_mismatch_is_flagged(self):
        self.assertEqual(
            missing_draws({"grid", "phantom-draw"}, {"grid", "dots"}),
            {"phantom-draw"})
        self.assertEqual(missing_draws({"grid"}, {"grid", "dots"}), set())

    def test_01_the_end_to_end_counter_proof(self):
        """Put a draw the renderer has no branch for into the contract, and
        the cross-layer check must report exactly that draw.

        The injection is in-process and restored in a finally: the contract
        module is imported, not rewritten on disk, so the working tree is
        untouched."""
        # A stale parser would make this counter-proof report the wrong
        # thing — so the freshness guard runs first, and says the same
        # thing everywhere: fix the parser, not the contract.
        parser_fresh_or_fail()
        constants.DRAWS.add("phantom-draw")
        try:
            missing = missing_draws(contract_draws(), renderer_draws())
            self.assertEqual(missing, {"phantom-draw"})
        finally:
            constants.DRAWS.discard("phantom-draw")
        self.assertNotIn("phantom-draw", contract_draws())

    def test_02_a_parser_drift_is_not_the_contract_s_fault(self):
        """A draw the renderer DISPATCHES on but the parser did not catch
        means the parser went stale. It must be told apart from a real
        disagreement, so that nobody 'fixes' a stale parser by deleting
        draws from the contract."""
        out_of_bounds, parser_drift = classify_missing(
            {"grid", "phantom-draw", "dots"},
            {"grid"},
            {"grid", "dots", "phantom-draw"})
        self.assertEqual(out_of_bounds, set())
        self.assertEqual(parser_drift, {"phantom-draw", "dots"})

    def test_03_a_draw_the_renderer_never_dispatches_is_out_of_bounds(self):
        out_of_bounds, parser_drift = classify_missing(
            {"grid", "never-heard-of-it"},
            {"grid"},
            {"grid"})
        self.assertEqual(out_of_bounds, {"never-heard-of-it"})
        self.assertEqual(parser_drift, set())

    def test_04_an_ordinary_string_is_not_a_dispatch(self):
        """A draw name that merely appears as some ordinary string in the
        source is not a dispatch. Classifying it as one would point the
        reader at the parser and let a capability be quietly dropped."""
        src = "const palette = { 'phantom-draw': '#fff' };"
        self.assertEqual(parse_dispatch_names(src), set())
        out_of_bounds, parser_drift = classify_missing(
            {"phantom-draw"}, set(), parse_dispatch_names(src))
        self.assertEqual(out_of_bounds, {"phantom-draw"})
        self.assertEqual(parser_drift, set())

    def test_05_the_real_source_yields_no_drift(self):
        """The dispatch scan runs on the real renderer source. With the
        current renderer — which dispatches draws by comparison, not by
        switch case — no contract draw may end up in the drift class: that
        class means "the parser is behind", and today it is not."""
        out_of_bounds, parser_drift = classify_missing(
            set(contract_draws()), renderer_draws(), renderer_dispatch_names())
        self.assertEqual(parser_drift, set())
        self.assertEqual(out_of_bounds, set())


if __name__ == "__main__":
    unittest.main()
