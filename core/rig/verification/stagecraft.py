"""Single-shot stagecraft audit: scrolling backdrops and character states.

Reports authored geometry; it imposes no choreography and no aesthetic.
Backdrop identity is only reported for layers that can actually be serving as
the backdrop: visible (opacity >= min_visible_opacity), non-cutout `ai` layers
whose center is on stage (strictly inside the canvas aperture, i.e. the
backdrop center sits within half the layer's own width/height). Everything
else — position, opacity — is read from the spec; nothing is guessed.
"""
from ..kinematics import eval_channel

DEFAULT_MIN_VISIBLE_OPACITY = 0.20


def _dominant_backdrop_at_frame(layers_list, frame, min_visible_opacity=DEFAULT_MIN_VISIBLE_OPACITY):
    """Return the backdrop identity at `frame`, or None when none is declared.

    A backdrop is identified by the layer's `backdrop` field (a project-declared
    identity string) — the same identity in two shots means "the same place",
    which is what a cross-shot handoff check compares. Without a declaration
    there is nothing to compare and the result is None: the engine never
    infers a backdrop identity from an asset name, a component name or a
    position, because those are not the same thing.
    """
    candidates = []
    for L in layers_list:
        identity = L.get("backdrop")
        if not identity or not isinstance(identity, str):
            continue
        if L.get("cutout"):
            continue
        rect = L.get("rect")
        if not (isinstance(rect, list) and len(rect) == 4 and rect[2] > 0 and rect[3] > 0):
            continue  # schema-invalid layer: no backdrop claim is made
        anim = L.get("anim") or {}
        op = eval_channel(anim.get("opacity", []), frame, 1.0)
        if op < min_visible_opacity:
            continue
        x_off = eval_channel(anim.get("x", []), frame, 0.0)
        y_off = eval_channel(anim.get("y", []), frame, 0.0)
        rw, rh = float(rect[2]), float(rect[3])
        # A backdrop is off-stage once its center leaves the aperture (strict half rule,
        # not an arbitrary scroll fraction).
        if abs(x_off) >= rw / 2.0 or abs(y_off) >= rh / 2.0:
            continue
        candidates.append((L.get("z", 0), abs(x_off) + abs(y_off), identity))
    if not candidates:
        return None
    # Prefer highest z-order scroll layer that is on stage
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2]


def _extract_root_character_states(spec, frame, min_visible_opacity=DEFAULT_MIN_VISIBLE_OPACITY):
    """Extract (x, y, opacity) canvas state of all root cutout characters at `frame`.

    Canvas position of a layer is `rect[0] + anim.x(frame)` and `rect[1] + anim.y(frame)`
    (Shot.tsx positions the layer at `rect[0], rect[1]` inside an `inset: 0` wrapper
    translated by `anim.x, anim.y`).
    """
    states = {}
    for L in spec.get("layers", []):
        rect = L.get("rect")
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent") and L.get("role") != "prop":
            if not (isinstance(rect, list) and len(rect) == 4):
                continue  # schema-invalid layer: no state claim is made
            anim = L.get("anim") or {}
            dx = eval_channel(anim.get("x", []), frame, 0.0)
            dy = eval_channel(anim.get("y", []), frame, 0.0)
            x = rect[0] + dx
            y = rect[1] + dy
            op = eval_channel(anim.get("opacity", []), frame, 1.0)
            if op < min_visible_opacity:
                continue
            states[L["id"]] = {
                "x": round(x, 1),
                "y": round(y, 1),
                "dx": round(dx, 1),
                "dy": round(dy, 1),
                "opacity": round(op, 2),
                "rect": rect,
            }
    return states


def verify_shot_stagecraft(spec, min_visible_opacity=DEFAULT_MIN_VISIBLE_OPACITY):
    """Report authored geometry, without imposing choreography or an aesthetic."""
    from core.spec import validate
    errors = validate(spec)
    if errors:
        # No fabricated backdrop/state claims for a spec that fails validation;
        # the verdict carries the errors and nothing else.
        last = spec["durationInFrames"] - 1
        return {"shot_id": spec.get("id"), "passed": False, "errors": errors,
                "duration_sec": spec.get("durationInFrames", 0) / max(1, spec.get("fps", 1)),
                "start_backdrop": None, "end_backdrop": None,
                "start_states": {}, "end_states": {}}
    last = spec["durationInFrames"] - 1
    return {"shot_id": spec["id"], "passed": not errors, "errors": errors,
            "duration_sec": spec["durationInFrames"] / spec["fps"],
            "start_backdrop": _dominant_backdrop_at_frame(spec["layers"], 0, min_visible_opacity),
            "end_backdrop": _dominant_backdrop_at_frame(spec["layers"], last, min_visible_opacity),
            "start_states": _extract_root_character_states(spec, 0, min_visible_opacity),
            "end_states": _extract_root_character_states(spec, last, min_visible_opacity)}
