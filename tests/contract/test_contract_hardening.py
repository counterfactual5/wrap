"""Hardening for the cross-layer check: the extraction, and its counter-proofs.

The cross-layer invariant itself lives in tests/contract/test_contract_agreement.py.
This file owns the harder half: proving that the check is actually looking at
the renderer, and that it would catch a contract that outruns it.

What is machine-checked here is the layer-TYPE axis: the contract must not
accept a type the renderer has no path for, and the renderer side must be
derived from the renderer's own source rather than from a list copied into
Python. (The procedural draw axis was removed in the zero-template
migration; its refusal contract lives in test_migration_rejection.py.)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

from tests.contract.agreement import (  # noqa: E402
    classify_missing,
    contract_layer_types,
    missing_types,
    parse_dispatch_names,
    parse_layer_types,
    parser_fresh_or_fail,
    parser_stale,
    renderer_dispatch_names,
    renderer_layer_types,
)

from core.spec import constants  # noqa: E402


class TestTheParserIsDerived(unittest.TestCase):
    """The renderer side must come from the renderer's source. A parser that
    quietly stopped matching — or an extraction function rewritten into a
    hard-coded list — would leave the cross-layer check green while it
    checks nothing. That is the failure this class exists to catch."""

    def test_00_a_renamed_branch_follows_the_source(self):
        src = "if (layer.type === 'component') { return <Comp/>; }"
        self.assertEqual(parse_layer_types(src), {"component"})
        # The name follows the source: the result is derived, not a list.
        self.assertEqual(parse_layer_types(src.replace("'component'", "'widgets'")), {"widgets"})

    def test_01_quotes_and_spacing_do_not_matter(self):
        for src in ("layer.type === 'ai'", 'layer.type === "ai"',
                    "layer.type==='ai'", "layer.type === 'ai'"):
            with self.subTest(src=src):
                self.assertEqual(parse_layer_types(src), {"ai"})

    def test_02_a_comment_only_snippet_parses_to_nothing(self):
        src = "// layer.type === 'ai' used to be a branch here"
        self.assertEqual(parse_layer_types(src), set())

    def test_03_the_real_renderer_is_parsed_not_copied(self):
        """The set the check uses must come from the source: change the source
        and the set must change with it. A hard-coded list would not."""
        real = renderer_layer_types()
        self.assertIn("component", real)
        self.assertIn("ai", real)
        self.assertIn("video", real)
        for name in real:
            self.assertRegex(name, r"^[a-z][a-z0-9-]*$")

    def test_04_the_extraction_follows_a_modified_source(self):
        """The decisive one: feed the extractor a source in which a type was
        renamed and watch the name disappear. An extraction rewritten as a
        hard-coded list cannot pass this."""
        src = ("if (layer.type === 'component') { return <Comp/>; }\n"
               "if (layer.type === 'video') { return <Vid/>; }\n")
        self.assertEqual(parse_layer_types(src), {"component", "video"})
        renamed = src.replace("'component'", "'components'")
        self.assertEqual(parse_layer_types(renamed), {"components", "video"})
        self.assertNotIn("component", parse_layer_types(renamed))
        # ... and the same through the seam the checker uses:
        self.assertEqual(renderer_layer_types(src=src), {"component", "video"})
        self.assertNotIn("component",
                         renderer_layer_types(src=src.replace("'component'",
                                                             "'components'")))

    def test_05_a_switch_case_is_a_dispatch_too(self):
        """A renderer that switches instead of comparing is still a
        dispatch: the parser must notice it as a stale parser, not as a
        contract that is suddenly wrong."""
        src = "switch (layer.type) { case 'ai': return <Ai/>; }"
        self.assertEqual(parse_layer_types(src), set())
        self.assertIn("ai", parse_dispatch_names(src))

    def test_06_a_negated_comparison_is_not_a_dispatch(self):
        """`layer.type !== 'ai'` says the renderer does NOT draw it.
        Counting that as a dispatch would point the reader at the parser
        for a type the renderer actively rejects."""
        src = "if (layer.type !== 'ai') { return null; }"
        self.assertEqual(parse_layer_types(src), set())
        self.assertEqual(parse_dispatch_names(src), set())

    def test_07_a_comparison_on_another_axis_is_not_a_dispatch(self):
        """The dispatch scan is about the type axis. A comparison on some
        other axis must not make an unimplemented type look dispatched."""
        src = "if (layer.fit === 'contain') { return <C/>; }"
        self.assertEqual(parse_dispatch_names(src), set())
        self.assertEqual(parse_layer_types(src), set())


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
        broken = real.replace("layer.type ===", "layer.type ~=")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        self.assertTrue(parser_stale(src=broken),
                        "a renderer that stopped using `layer.type ===` was "
                        "not reported as a stale parser")

    def test_02_the_loud_fallback_must_stay_loud(self):
        """The renderer's dispatch ends in `Unsupported layer type` — it
        refuses an unknown type instead of drawing a substitute. The throw
        is a registered capability: a renderer that went back to silently
        drawing something for unknown types would be reported here."""
        from tests.contract.agreement import _renderer_source
        real = _renderer_source()
        self.assertRegex(real, r"Unsupported layer type")
        broken = real.replace("Unsupported layer type", "fallback draw")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        self.assertTrue(parser_stale(src=broken),
                        "a renderer that lost its loud unknown-type refusal "
                        "was not reported as a stale parser")

    def test_03_one_changed_branch_is_enough_to_be_reported(self):
        """The partial case, and the one that matters: the pattern still
        matches the other branches, so a whole-pattern check stays
        green while the implementation set has quietly lost a type."""
        from tests.contract.agreement import _renderer_source
        real = _renderer_source()
        broken = real.replace("layer.type === 'component'",
                              "layer['type'] === 'component'")
        self.assertNotEqual(broken, real, "the fixture did not change shape")
        # the mutation really removed the type from the parsed set
        self.assertNotEqual(parse_layer_types(broken), parse_layer_types(real))
        stale = parser_stale(src=broken)
        self.assertTrue(stale,
                        "a single branch that changed shape was not reported")
        self.assertTrue(any("component" in s for s in stale),
                        f"the changed branch was not named: {stale}")

    def test_04_the_canary_does_not_depend_on_the_contract(self):
        """The canary must not be able to go green by touching the
        contract: it reads the renderer, not the schema."""
        constants.LAYER_TYPES.add("probe-canary-type")
        try:
            self.assertEqual(parser_stale(), [])
        finally:
            constants.LAYER_TYPES.discard("probe-canary-type")


class TestTheInvariantAndItsCounterProofs(unittest.TestCase):
    def test_00_a_crafted_mismatch_is_flagged(self):
        self.assertEqual(
            missing_types({"ai", "phantom-type"}, {"ai", "video"}),
            {"phantom-type"})
        self.assertEqual(missing_types({"ai"}, {"ai", "video"}), set())

    def test_01_the_end_to_end_counter_proof(self):
        """Put a type the renderer has no branch for into the contract, and
        the cross-layer check must report exactly that type.

        The injection is in-process and restored in a finally: the contract
        module is imported, not rewritten on disk, so the working tree is
        untouched."""
        # A stale parser would make this counter-proof report the wrong
        # thing — so the freshness guard runs first, and says the same
        # thing everywhere: fix the parser, not the contract.
        parser_fresh_or_fail()
        constants.LAYER_TYPES.add("phantom-type")
        try:
            missing = missing_types(contract_layer_types(), renderer_layer_types())
            self.assertEqual(missing, {"phantom-type"})
        finally:
            constants.LAYER_TYPES.discard("phantom-type")
        self.assertNotIn("phantom-type", contract_layer_types())

    def test_02_a_parser_drift_is_not_the_contract_s_fault(self):
        """A type the renderer DISPATCHES on but the parser did not catch
        means the parser went stale. It must be told apart from a real
        disagreement, so that nobody 'fixes' a stale parser by deleting
        types from the contract."""
        out_of_bounds, parser_drift = classify_missing(
            {"ai", "phantom-type", "video"},
            {"ai"},
            {"ai", "video", "phantom-type"})
        self.assertEqual(out_of_bounds, set())
        self.assertEqual(parser_drift, {"phantom-type", "video"})

    def test_03_a_type_the_renderer_never_dispatches_is_out_of_bounds(self):
        out_of_bounds, parser_drift = classify_missing(
            {"ai", "never-heard-of-it"},
            {"ai"},
            {"ai"})
        self.assertEqual(out_of_bounds, {"never-heard-of-it"})
        self.assertEqual(parser_drift, set())

    def test_04_an_ordinary_string_is_not_a_dispatch(self):
        """A type name that merely appears as some ordinary string in the
        source is not a dispatch. Classifying it as one would point the
        reader at the parser and let a capability be quietly dropped."""
        src = "const palette = { 'phantom-type': '#fff' };"
        self.assertEqual(parse_dispatch_names(src), set())
        out_of_bounds, parser_drift = classify_missing(
            {"phantom-type"}, set(), parse_dispatch_names(src))
        self.assertEqual(out_of_bounds, {"phantom-type"})
        self.assertEqual(parser_drift, set())

    def test_05_the_real_source_yields_no_drift(self):
        """The dispatch scan runs on the real renderer source. With the
        current renderer — which dispatches types by comparison, not by
        switch case — no contract type may end up in the drift class: that
        class means "the parser is behind", and today it is not."""
        out_of_bounds, parser_drift = classify_missing(
            set(contract_layer_types()), renderer_layer_types(),
            renderer_dispatch_names())
        self.assertEqual(parser_drift, set())
        self.assertEqual(out_of_bounds, set())


if __name__ == "__main__":
    unittest.main()
