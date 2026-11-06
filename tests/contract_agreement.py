"""Cross-layer agreement between the spec contract and the renderer.

`core/schema.py`'s DRAWS is what an author may write in a spec; the Remotion
renderer is what actually draws. The two are separate files in separate
languages, and nothing kept them honest: R1 (commit c064196) shipped a case
where the contract refused something the renderer had already implemented.

The renderer side is derived from the renderer's OWN source here — never from
a list copied into Python. A copy is a second implementation: it drifts
exactly when the first one changes, and a drifted copy is worse than no
check at all, because it looks like a check.

Two facts are extracted, and the difference between them matters:

  * `renderer_draws()` — the draws that have an explicit branch. A draw in
    the contract without one is a real disagreement: the contract promises
    something the renderer does not draw.
  * `renderer_dispatch_names()` — the draw names that appear in a DISPATCH
    position (a branch comparison, a switch case). A contract draw that is
    dispatched somewhere but not parsed means the PARSER went stale (the
    renderer changed how it dispatches), not that the contract is wrong.
    Conflating the two would invite a maintainer to delete draws from the
    contract to make the check green — a silent capability contraction,
    which is the very shape this file exists to prevent. For that reason the
    dispatch scan is deliberately narrow: a draw name that merely appears
    as some ordinary string in the source is NOT a dispatch, and a contract
    draw in that position is reported as out of bounds (the safe direction).

Scope — what is machine-checked and what is not:

  * CHECKED: the draw-NAME axis. The contract must not accept a draw the
    renderer has no path for.
  * NOT CHECKED: the capability axis — which motion channels each layer kind
    gets (the per-draw table of `motion.zoom` support lives in
    `core/schema.py` and is read by a human; the tests here pin the
    contract's current side of it, they do not compare it with the
    renderer's). Closing that axis needs the renderer's motion vocabulary
    parsed and compared — deliberately left to another round.

Known limits: comments are stripped before parsing (a branch that only
appears in a comment is not a branch), but dead code is not detected — a
branch that is unreachable still counts as implemented.

Maintenance: this file owns the parsing of the renderer's dispatch. If the
renderer changes how it dispatches on `draw`, fix the parser HERE — never by
removing a draw from the contract.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# The code layer's component chain dispatches on the draw name:
# `layer.draw === 'grid'`, `layer.draw === "dots"`, `case 'field':` … The
# quotes, the spacing and the operator are not pinned — a renderer refactor
# that changes any of them must not silently turn the cross-layer check
# into a no-op.
_DRAW_BRANCH = re.compile(r"layer\.draw\s*===?\s*['\"]([a-z][a-z0-9-]*)['\"]")

# A draw name in a DISPATCH position the branch parser cannot see: a switch
# case label. Deliberately narrow — see the module docstring. A plain string
# that happens to spell a draw name is NOT a dispatch, and a negated
# comparison (`layer.draw !== 'x'`) is not either.
_DISPATCH_NAME = re.compile(r"case\s+['\"]([a-z][a-z0-9-]*)['\"]")

# The chain's fallback: a draw the chain does not match is drawn as a bar
# (remotion/Shot.tsx, CodeLayerComp). It has no branch of its own, so the
# fallback is recognised by the component it draws — and by nothing else:
# `<Bar ` with a delimiter, so a component called `<BarLabel` cannot pass
# for it.
_BAR_FALLBACK = re.compile(r"<Bar[\s/>]")

# A LOOSER dispatch pattern: it also accepts the property in bracket form
# and any spacing. It never feeds the implementation set — it exists so the
# canary can compare: a draw the loose pattern sees but the parser's own
# pattern does not is a branch whose shape moved, and the implementation
# set would have lost that draw without saying so.
_LOOSE_DRAW_DISPATCH = re.compile(
    r"\b\w+\s*(?:\.\s*draw|\[\s*['\"]draw['\"]\s*\])\s*(?:===|==)"
    r"\s*['\"]([a-z][a-z0-9-]*)['\"]")

# Every capability the PARSER relies on. This tuple is the parser's single
# registry: `renderer_draws()` reads its draws out of it, so a capability
# that is added to the parser but not here cannot be missed (the handler
# below refuses a capability it does not know). The canary checks each of
# them against the real renderer source: a pattern that stops matching
# means the renderer's shape changed and this parser went stale — the
# cross-layer check would then be silently narrowing its own idea of the
# renderer, which is the one direction in which a sub-set check cannot
# complain. The list is derived from the parser's own code, never written
# by hand: a hand-written list of "syntax families" would be exactly the
# registry this file exists to avoid.
#
# The loose dispatch pattern above is NOT a member: it never feeds the
# implementation set, it only compares against it.
PARSER_PATTERNS = (
    ("draw branch", _DRAW_BRANCH),
    ("bar fallback", _BAR_FALLBACK),
)

RENDERER_SOURCES = ("Shot.tsx", "layers.tsx")


def _renderer_source():
    src = []
    for name in RENDERER_SOURCES:
        path = os.path.join(ROOT, "remotion", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                src.append(f.read())
    return "\n".join(src)


def strip_comments(src):
    """The source without its comments.

    A branch that only appears in a comment is not a branch: without this,
    a comment mentioning a draw would make the cross-layer check believe the
    renderer can draw it — the over-match direction, which is the dangerous
    one (it silences a real disagreement)."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def parse_draws(src):
    """The draw names `src` dispatches on.

    Pure function on purpose: the tests feed it synthetic sources, so a
    parser that quietly stopped matching would fail there instead of
    turning the cross-layer check into decoration. The pattern comes from
    the registry, so this path and `renderer_draws` cannot diverge."""
    return _draws_of_capability("draw branch", strip_comments(src))


def parse_dispatch_names(src):
    """The draw names `src` dispatches on, in any dispatch position.

    Wider than `parse_draws` on purpose: it catches the `case 'x':` a
    switch statement would use, so a renderer that changed its dispatch
    syntax shows up as "the parser is stale", not as "the contract is
    wrong". Nothing else counts: a draw name in an ordinary string is not a
    dispatch, and a negated comparison is not a dispatch either."""
    return set(_DISPATCH_NAME.findall(strip_comments(src)))


def _capability_pattern(name):
    """The pattern of one registered capability.

    The registry is the single source for the parser's OWN patterns: the
    parser and the canary reach them through here, so they cannot drift
    apart. (The loose dispatch pattern is deliberately not a member — it
    only compares against the implementation set.)"""
    for cap, pattern in PARSER_PATTERNS:
        if cap == name:
            return pattern
    raise AssertionError(f"no parser capability named {name!r}")


def _draws_of_capability(name, stripped):
    """The draws one registered capability finds in the source.

    The pattern comes from the registry by name, never from the caller: a
    caller that paired a name with the wrong pattern would be a silent
    second source of truth.

    An unknown capability raises: the registry and the parser cannot drift
    apart silently — a new capability has to be handled here, and the
    canary covers it from then on."""
    pattern = _capability_pattern(name)
    if name == "draw branch":
        return set(pattern.findall(stripped))
    if name == "bar fallback":
        # bar is the chain's fallback: a draw the chain does not match is
        # drawn as a bar (remotion/Shot.tsx, CodeLayerComp). It has no
        # branch of its own, so the fallback is recognised by the component
        # it draws — and by nothing else: `<Bar ` with a delimiter, so a
        # component called `<BarLabel` cannot pass for it.
        return {"bar"} if pattern.search(stripped) else set()
    raise AssertionError(f"no handler for the parser capability {name!r}")


def renderer_draws(src=None):
    """The draw names the renderer has an EXPLICIT branch for.

    Parsed from the renderer's source, so a new branch in the renderer shows
    up here without anyone remembering to update a list. The `src` seam lets
    the tests feed it a modified source and watch the result follow.

    The chain's fallback is NOT part of this set: a draw that only the
    fallback can draw is not implemented by the renderer, it merely falls
    back to something else (a bar) — counting it as implemented would let
    the contract name a draw that nothing handles.

    Known limit: this reads the source, it does not evaluate it. A branch
    that is present but unreachable (`if (false && layer.draw === 'x')`)
    still counts as a branch — telling those apart needs a runtime probe,
    which is a separate piece of work."""
    src = _renderer_source() if src is None else src
    stripped = strip_comments(src)
    return _draws_of_capability("draw branch", stripped)


def renderer_fallback_draws(src=None):
    """The draws the chain's fallback would draw (today: the bar).

    The fallback is a safety net for a draw nobody named — it must never be
    the only implementation of a draw the contract names, so it is reported
    separately."""
    src = _renderer_source() if src is None else src
    stripped = strip_comments(src)
    return _draws_of_capability("bar fallback", stripped)


def renderer_dispatch_names(src=None):
    """Every draw name the renderer dispatches on, in any dispatch position."""
    src = _renderer_source() if src is None else src
    return parse_dispatch_names(src)


def contract_draws():
    """The draw names the spec contract accepts."""
    from core.schema import DRAWS
    return set(DRAWS)


def missing_draws(accepted, implemented):
    """The accepted names the implementation has no path for."""
    return set(accepted) - set(implemented)


def parser_stale(src=None):
    """What the parser no longer sees in the renderer.

    Two kinds, both meaning the same thing (the parser's idea of the
    renderer has drifted from the renderer):

      * a registered capability that no longer matches the source at all
        ("draw branch", "bar fallback") — the pattern is gone;
      * a draw the loose dispatch pattern sees but the parser's own pattern
        does not ("draw branch:grid") — the PARTIAL case: the pattern still
        matches somewhere else, so a whole-pattern check would stay green
        while the implementation set quietly lost that draw.

    Empty means the parser still sees what the renderer does. A non-empty
    result means the implementation set would silently shrink, and a
    sub-set check cannot complain about a set that shrank on its own. That
    is the failure the canary exists to catch — fix the parser here, never
    the contract."""
    src = _renderer_source() if src is None else src
    stripped = strip_comments(src)
    stale = [name for name, pattern in PARSER_PATTERNS
             if not pattern.search(stripped)]
    strict = set(_capability_pattern("draw branch").findall(stripped))
    loose = set(_LOOSE_DRAW_DISPATCH.findall(stripped))
    stale += [f"draw branch:{d}" for d in sorted(loose - strict)]
    return stale


def parser_fresh_or_fail(src=None):
    """Raise with the canonical message when the parser has drifted.

    One message, one place: both the cross-layer check and the end-to-end
    counter-proof call this, so a stale parser always says the same thing
    (and always says: fix the parser, not the contract)."""
    stale = parser_stale(src)
    if stale:
        raise AssertionError(
            f"the parser went stale — it no longer matches the renderer's "
            f"shape: {stale}. Fix tests/contract_agreement.py; do not "
            f"change the contract to suit the parser.")
    return True


def classify_missing(accepted, implemented, dispatched):
    """Split the missing names by WHY they are missing.

    ("out_of_bounds", "parser_drift") — a name the renderer never
    dispatches is a real disagreement between the contract and the renderer;
    a name the renderer does dispatch on but the parser did not catch is a
    stale parser, and the fix belongs in this file, not in the contract."""
    missing = missing_draws(accepted, implemented)
    out_of_bounds = {d for d in missing if d not in dispatched}
    parser_drift = missing - out_of_bounds
    return out_of_bounds, parser_drift
