"""Cross-layer agreement between the spec contract and the renderer.

`core/spec/constants.py`'s `LAYER_TYPES` is what a spec may declare; the
Remotion renderer (`remotion/`) is what actually draws. The two are separate
files in separate languages, and nothing kept them honest — R1 (commit
c064196) shipped a case where the contract refused something the renderer
had already implemented, caught only by a human review.

The renderer side is derived from the renderer's OWN source here — never
from a list copied into Python. A copy is a second implementation: it drifts
exactly when the first one changes, and a drifted copy is worse than no
check at all, because it looks like a check.

Zero-template migration: the procedural draw vocabulary (`DRAWS`) was
removed from BOTH sides. The set stays in `core/spec/constants.py`, empty
and loud, as the migration boundary; `tests/contract/test_migration_rejection.py`
owns the refusal contract for the legacy vocabulary.

Two facts are extracted, and the difference between them matters:

  * `renderer_layer_types()` — the layer types with an explicit branch. A
    type in the contract without one is a real disagreement: the contract
    promises something the renderer does not draw.
  * `renderer_dispatch_names()` — type names in any dispatch position (a
    switch case label). A contract type dispatched but not parsed means the
    PARSER went stale, not that the contract is wrong. Conflating the two
    would invite a maintainer to delete types from the contract to make the
    check green — the exact silent narrowing this file exists to prevent.

The renderer's dispatch ends in a LOUD fallback (`Unsupported layer type` —
it refuses, it does not draw a substitute), and the pattern for that throw
is a registered capability: if the renderer ever goes back to silently
drawing something for unknown types, the canary says so.

Known limits: comments are stripped before parsing (a branch that only
appears in a comment is not a branch), but dead code is not detected — a
branch that is unreachable still counts as implemented.

Maintenance: this file owns the parsing of the renderer's dispatch. If the
renderer changes how it dispatches on `type`, fix the parser HERE — never by
removing a type from the contract.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

# The renderer dispatches on the layer type:
# `layer.type === 'video'`, `layer.type === 'component'`, ... The quotes,
# the spacing and the operator are not pinned — a renderer refactor that
# changes any of them must not silently turn the cross-layer check
# into a no-op.
_TYPE_BRANCH = re.compile(r"layer\.type\s*===?\s*['\"]([a-z][a-z0-9-]*)['\"]")

# A type name in a DISPATCH position the branch parser cannot see: a switch
# case label. Deliberately narrow — a plain string that happens to spell a
# type name is NOT a dispatch, and a negated comparison
# (`layer.type !== 'x'`) is not either.
_DISPATCH_NAME = re.compile(r"case\s+['\"]([a-z][a-z0-9-]*)['\"]")

# The loud fallback: an unknown type must throw, never draw a substitute.
# Recognised by the error text and by nothing else.
_UNSUPPORTED_THROW = re.compile(r"Unsupported layer type")

# A LOOSER dispatch pattern: it also accepts the property in bracket form
# and any spacing. It never feeds the implementation set — it exists so the
# canary can compare: a type the loose pattern sees but the parser's own
# pattern does not is a branch whose shape moved, and the implementation
# set would have lost that type without saying so.
_LOOSE_TYPE_DISPATCH = re.compile(
    r"\b\w+\s*(?:\.\s*type|\[\s*['\"]type['\"]\s*\])\s*(?:===|==)"
    r"\s*['\"]([a-z][a-z0-9-]*)['\"]")

# Every capability the PARSER relies on — the parser's single registry.
# The canary checks each of them against the real renderer source: a
# pattern that stops matching means the renderer's shape changed and this
# parser went stale — the cross-layer check would then be silently
# narrowing its own idea of the renderer. The list is derived from the
# parser's own code, never written by hand.
#
# The loose dispatch pattern is NOT a member: it never feeds the
# implementation set, it only compares against it.
PARSER_PATTERNS = (
    ("layer type branch", _TYPE_BRANCH),
    ("unsupported type throw", _UNSUPPORTED_THROW),
)


def _renderer_sources():
    base = os.path.join(ROOT, "remotion")
    out = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            if name.endswith((".tsx", ".ts")):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _renderer_source():
    src = []
    for path in _renderer_sources():
        with open(path, encoding="utf-8") as f:
            src.append(f.read())
    return "\n".join(src)


def strip_comments(src):
    """The source without its comments.

    A branch that only appears in a comment is not a branch: without this,
    a comment mentioning a type would make the cross-layer check believe the
    renderer can draw it — the over-match direction, which silences a real
    disagreement."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def _capability_pattern(name):
    """The pattern of one registered capability (single source with the parser)."""
    for cap, pattern in PARSER_PATTERNS:
        if cap == name:
            return pattern
    raise AssertionError(f"no parser capability named {name!r}")


def parse_layer_types(src):
    """The layer types `src` dispatches on, via explicit branches.

    Pure function on purpose: the tests feed it synthetic sources, so a
    parser that quietly stopped matching would fail there instead of
    turning the cross-layer check into decoration."""
    return set(_capability_pattern("layer type branch")
               .findall(strip_comments(src)))


def parse_dispatch_names(src):
    """The names `src` dispatches on, in any dispatch position (switch case)."""
    return set(_DISPATCH_NAME.findall(strip_comments(src)))


def renderer_layer_types(src=None):
    """The layer types the renderer has an EXPLICIT branch for.

    Parsed from the renderer's source, so a new branch in the renderer shows
    up here without anyone remembering to update a list. The `src` seam lets
    the tests feed it a modified source and watch the result follow.

    Known limit: this reads the source, it does not evaluate it. A branch
    that is present but unreachable still counts as a branch."""
    src = _renderer_source() if src is None else src
    return parse_layer_types(src)


def renderer_dispatch_names(src=None):
    """Every name the renderer dispatches on, in any dispatch position."""
    src = _renderer_source() if src is None else src
    return parse_dispatch_names(src)


def contract_layer_types():
    """The layer types the spec contract accepts."""
    from core.spec.constants import LAYER_TYPES
    return set(LAYER_TYPES)


def contract_draws():
    """The (removed) procedural draw vocabulary: empty after the migration."""
    from core.spec.constants import DRAWS
    return set(DRAWS)


def missing_types(accepted, implemented):
    """The accepted types the implementation has no path for."""
    return set(accepted) - set(implemented)


def contract_leads_renderer():
    """The layer types the renderer has a branch for but the contract refuses.

    Post-migration this is expected to be NON-empty (the renderer keeps
    loud-refused compatibility branches); the invariant that matters is in
    `tests/contract/test_contract_agreement.py`: every type here must be
    REFUSED by the validator, loudly — never silently accepted, never
    silently drawn as something else."""
    return set(renderer_layer_types()) - set(contract_layer_types())


def parser_stale(src=None):
    """What the parser no longer sees in the renderer.

      * a registered capability that no longer matches the source at all —
        the pattern is gone;
      * a type the loose dispatch pattern sees but the parser's own pattern
        does not — the PARTIAL case: a whole-pattern check would stay green
        while the implementation set quietly lost that type.

    Empty means the parser still sees what the renderer does. A non-empty
    result means the implementation set would silently shrink — fix the
    parser here, never the contract."""
    src = _renderer_source() if src is None else src
    stripped = strip_comments(src)
    stale = [name for name, pattern in PARSER_PATTERNS
             if not pattern.search(stripped)]
    strict = set(_capability_pattern("layer type branch").findall(stripped))
    loose = set(_LOOSE_TYPE_DISPATCH.findall(stripped))
    stale += [f"layer type branch:{t}" for t in sorted(loose - strict)]
    return stale


def parser_fresh_or_fail(src=None):
    """Raise with the canonical message when the parser has drifted."""
    stale = parser_stale(src)
    if stale:
        raise AssertionError(
            f"the parser went stale — it no longer matches the renderer's "
            f"shape: {stale}. Fix tests/contract/agreement.py; do not "
            f"change the contract to suit the parser.")
    return True


def classify_missing(accepted, implemented, dispatched):
    """Split the missing types by WHY they are missing.

    ("out_of_bounds", "parser_drift") — a type the renderer never
    dispatches is a real disagreement between the contract and the renderer;
    a type the renderer does dispatch on but the parser did not catch is a
    stale parser, and the fix belongs in this file, not in the contract."""
    missing = missing_types(accepted, implemented)
    out_of_bounds = {t for t in missing if t not in dispatched}
    parser_drift = missing - out_of_bounds
    return out_of_bounds, parser_drift
