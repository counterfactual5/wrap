"""Single-shot stagecraft audit: scrolling backdrops, narrative props, and ensemble acting."""
from ..kinematics import eval_channel


def _dominant_backdrop_at_frame(layers_list, frame):
    """Return the asset name of the topmost visible non-cutout backdrop/scroll layer at `frame`."""
    candidates = []
    for L in layers_list:
        if L.get("type") != "ai" or L.get("cutout"):
            continue
        anim = L.get("anim") or {}
        op = eval_channel(anim.get("opacity", []), frame, 1.0)
        if op < 0.35:
            continue
        x_off = eval_channel(anim.get("x", []), frame, 0.0)
        y_off = eval_channel(anim.get("y", []), frame, 0.0)
        rect = L.get("rect", [0, 0, 1920, 1080])
        rw = max(1.0, float(rect[2]))
        rh = max(1.0, float(rect[3]))
        # Check if the backdrop's center is still inside the stage aperture (not scrolled off-stage)
        if abs(x_off) >= rw * 0.55 or abs(y_off) >= rh * 0.55:
            continue
        candidates.append((L.get("z", 0), abs(x_off) + abs(y_off), L.get("asset", L.get("id", ""))))
    if not candidates:
        return None
    # Prefer highest z-order scroll layer that is centered on stage
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2]


def _extract_root_character_states(spec, frame):
    """Extract (x, y, opacity) canvas state of all root cutout characters at `frame`.

    Canvas position of a layer is `rect[0] + anim.x(frame)` and `rect[1] + anim.y(frame)`
    (Shot.tsx positions the layer at `rect[0], rect[1]` inside an `inset: 0` wrapper
    translated by `anim.x, anim.y`).
    """
    states = {}
    canvas = spec.get("canvas") or {}
    cw = int(canvas.get("w", 1920))
    ch = int(canvas.get("h", 1080))
    for L in spec.get("layers", []):
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent") and L.get("role") != "prop":
            anim = L.get("anim") or {}
            rect = L.get("rect", [0, 0, 300, 400])
            dx = eval_channel(anim.get("x", []), frame, 0.0)
            dy = eval_channel(anim.get("y", []), frame, 0.0)
            x = rect[0] + dx
            y = rect[1] + dy
            op = eval_channel(anim.get("opacity", []), frame, 1.0)
            states[L["id"]] = {
                "x": round(x, 1),
                "y": round(y, 1),
                "dx": round(dx, 1),
                "dy": round(dy, 1),
                "opacity": round(op, 2),
                "rect": rect,
                "canvas": [cw, ch],
            }
    return states



def verify_shot_stagecraft(spec):
    """Report authored geometry, without imposing choreography or an aesthetic."""
    from core.spec import validate
    errors = validate(spec)
    last = spec["durationInFrames"] - 1
    return {"shot_id": spec["id"], "passed": not errors, "errors": errors,
            "duration_sec": spec["durationInFrames"] / spec["fps"],
            "start_backdrop": _dominant_backdrop_at_frame(spec["layers"], 0),
            "end_backdrop": _dominant_backdrop_at_frame(spec["layers"], last),
            "start_states": _extract_root_character_states(spec, 0),
            "end_states": _extract_root_character_states(spec, last)}
