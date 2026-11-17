"""Combat weapon-tip to target hitbox contact verification."""
import math

from core.runtime import manifest

from ..kinematics import eval_channel


def verify_combat_contact(spec, attacker_id=None, weapon_id=None,
                          target_id=None, tolerance=None, tip_offset=None, ref_width=None):
    """Verify that the attacker's weapon physically contacts the target hitbox on all punch frames.

    All geometry is declared, never guessed. Sources, in priority order:
    1. Explicit function arguments (`attacker_id`, `weapon_id`, `target_id`, `tolerance`, `tip_offset`, `ref_width`),
    2. Or `spec["combat"]` (`{"attacker": "...", "weapon": "...", "target": "...", "tolerance": 40,
       "tipOffset": [dx, dy], "refWidth": 1090}`).
    `ref_width` may additionally be derived from the weapon asset's frozen
    manifest bytes (its width); when absent everywhere, the call fails before
    any measurement — the engine never invents weapon geometry.
    Missing layers or geometry are reported as a failed verdict with an
    actionable error message, never as a guess.
    """
    combat_cfg = spec.get("combat") if isinstance(spec.get("combat"), dict) else {}
    layers_list = spec.get("layers", [])
    layers = {l["id"]: l for l in layers_list if "id" in l}

    attacker_id = attacker_id or combat_cfg.get("attacker")
    weapon_id = weapon_id or combat_cfg.get("weapon")
    target_id = target_id or combat_cfg.get("target")
    if tolerance is None:
        tolerance = combat_cfg.get("tolerance", 40)
    tip_offset = tip_offset if tip_offset is not None else combat_cfg.get("tipOffset")
    ref_width = ref_width if ref_width is not None else combat_cfg.get("refWidth")

    attacker = layers.get(attacker_id) if attacker_id else None
    weapon = layers.get(weapon_id) if weapon_id else None
    target = layers.get(target_id) if target_id else None

    missing_layers = [f"layer {l!r}" for l in (attacker_id, weapon_id, target_id)
                      if not (layers.get(l))]
    if missing_layers:
        return {
            "passed": False,
            "details": [],
            "errors": [
                f"Missing attacker, weapon, or target layer in spec (resolved attacker={attacker_id!r}, "
                f"weapon={weapon_id!r}, target={target_id!r}; absent: {', '.join(missing_layers)}). "
                f"Declare 'combat': {{'attacker': '...', 'weapon': '...', 'target': '...'}} in spec "
                f"or pass --attacker/--weapon/--target."
            ],
        }

    punches = [event["frame"] for event in (spec.get("tracks") or {}).get("events", []) if event.get("kind") == "contact"]
    if not punches:
        return {"passed": True, "details": [], "message": "No punches defined"}

    errors = []
    details = []

    missing = []
    w_rect = weapon.get("rect")
    if not (isinstance(w_rect, list) and len(w_rect) == 4 and w_rect[2] > 0):
        missing.append(f"weapon layer {weapon_id!r} needs 'rect' [x,y,w,h] with positive width")
    p0 = weapon.get("pivot")
    if not (isinstance(p0, list) and len(p0) == 2):
        missing.append(f"weapon layer {weapon_id!r} needs 'pivot' [x,y] (canvas px) to locate the weapon tip")
    if ref_width is None:
        w_asset = weapon.get("asset")
        w_row = manifest.verified("assets", w_asset) if w_asset else None
        if w_row and isinstance(w_row.get("size"), list) and w_row["size"][0] > 0:
            ref_width = float(w_row["size"][0])
        else:
            missing.append(
                f"weapon asset {w_asset!r}: manifest row lacks 'size' — declare spec.combat 'refWidth' "
                f"(the weapon artwork's width in source pixels)")
    if ref_width is not None and not (
            isinstance(ref_width, (int, float)) and not isinstance(ref_width, bool) and ref_width > 0):
        missing.append("spec.combat 'refWidth' must be a positive number")
    if tip_offset is not None and not (isinstance(tip_offset, (list, tuple)) and len(tip_offset) == 2):
        missing.append("spec.combat 'tipOffset' must be [dx, dy] (source pixels)")
    if tip_offset is None:
        missing.append(
            "declare spec.combat 'tipOffset' [dx, dy] (weapon tip relative to its pivot, in source pixels)")
    t_rect = target.get("rect") if target else None
    if not (isinstance(t_rect, list) and len(t_rect) == 4 and t_rect[2] > 0):
        missing.append(f"target layer {target_id!r} needs 'rect' [x,y,w,h] with positive width")
    if missing:
        return {
            "passed": False,
            "details": [],
            "errors": [f"verify-combat cannot measure contact: {m}." for m in missing],
        }

    scale = w_rect[2] / float(ref_width)
    dx0 = float(tip_offset[0]) * scale
    dy0 = float(tip_offset[1]) * scale

    for f in punches:
        wa_x = eval_channel(attacker.get("anim", {}).get("x", []), f)
        wa_y = eval_channel(attacker.get("anim", {}).get("y", []), f)
        wa_rot = eval_channel(attacker.get("anim", {}).get("rotate", []), f)
        wep_rot = eval_channel(weapon.get("anim", {}).get("rotate", []), f)

        bg_x = eval_channel(target.get("anim", {}).get("x", []), f)
        bg_y = eval_channel(target.get("anim", {}).get("y", []), f)

        px = p0[0] + wa_x
        py = p0[1] + wa_y

        tot_rot = math.radians(wa_rot + wep_rot)
        tip_x = px + (dx0 * math.cos(tot_rot) - dy0 * math.sin(tot_rot))
        tip_y = py + (dx0 * math.sin(tot_rot) + dy0 * math.cos(tot_rot))

        t_rect = target.get("rect")
        t_min = t_rect[0] + bg_x
        t_max = t_min + t_rect[2]

        if tip_x < t_min:
            gap = t_min - tip_x
            status = "WHIFFING_SHORT" if gap > tolerance else "CONTACT_PASS"
        elif tip_x > t_max:
            gap = tip_x - t_max
            status = "OVER_PENETRATION" if gap > tolerance else "CONTACT_PASS"
        else:
            gap = 0.0
            status = "DIRECT_HIT"

        if status not in ("CONTACT_PASS", "DIRECT_HIT"):
            errors.append(
                f"Punch at frame {f}: weapon tip at x={tip_x:.1f} misses target [{t_min:.1f}, {t_max:.1f}] by {gap:.1f}px!"
            )

        details.append({
            "frame": f,
            "weapon_tip": [round(tip_x, 1), round(tip_y, 1)],
            "target_hitbox": [round(t_min, 1), round(t_max, 1)],
            "gap_px": round(gap, 1),
            "status": status,
        })

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "details": details,
    }
