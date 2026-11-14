"""Combat weapon-tip to target hitbox contact verification."""
import math

from core.runtime import manifest

from ..kinematics import eval_channel


def verify_combat_contact(spec, attacker_id=None, weapon_id=None,
                          target_id=None, tolerance=None, tip_offset=None, ref_width=None):
    """Verify that the attacker's weapon physically contacts the target hitbox on all punch frames.

    Reads combat participants & weapon geometry from:
    1. Explicit function arguments (`attacker_id`, `weapon_id`, `target_id`, `tolerance`, `tip_offset`, `ref_width`),
    2. Or `spec["combat"]` (`{"attacker": "...", "weapon": "...", "target": "...", "tolerance": 40, "tipOffset": [dx, dy], "refWidth": 1090}`),
    3. Or automatic topological discovery (locating the root parent with an articulated weapon/arm child and the opposing character layer).
    """
    combat_cfg = spec.get("combat") if isinstance(spec.get("combat"), dict) else {}
    layers_list = spec.get("layers", [])
    layers = {l["id"]: l for l in layers_list if "id" in l}

    attacker_id = attacker_id or combat_cfg.get("attacker")
    weapon_id = weapon_id or combat_cfg.get("weapon")
    target_id = target_id or combat_cfg.get("target")
    if tolerance is None:
        tolerance = combat_cfg.get("tolerance", 40)
    tip_offset = tip_offset or combat_cfg.get("tipOffset")
    ref_width = ref_width or combat_cfg.get("refWidth")

    # Auto-discover from layer topology if not explicitly specified
    if not weapon_id:
        for l in layers_list:
            lid = l.get("id", "").lower()
            ktype = (l.get("kit") or {}).get("type", "")
            is_weapon_like = (ktype == "weapon" or "staff" in lid or "weapon" in lid or "sword" in lid or "blade" in lid or "lance" in lid or "spear" in lid or "arm" in lid)
            if is_weapon_like and (l.get("parent") or "pivot" in l):
                weapon_id = l["id"]
                if not attacker_id:
                    if l.get("parent"):
                        attacker_id = l["parent"]
                    elif "-" in l["id"]:
                        prefix = l["id"].split("-")[0]
                        if prefix in layers:
                            attacker_id = prefix
                break

    if not attacker_id and weapon_id and weapon_id in layers:
        attacker_id = layers[weapon_id].get("parent")
        if not attacker_id and "-" in weapon_id:
            prefix = weapon_id.split("-")[0]
            if prefix in layers:
                attacker_id = prefix

    if not target_id:
        for l in layers_list:
            lid = l.get("id")
            if lid and lid not in (attacker_id, weapon_id) and not l.get("parent") and (l.get("cutout") or l.get("poses") or "anim" in l):
                ltype = l.get("type")
                if ltype in (None, "ai", "component", "code") and l.get("draw") not in ("field", "path", "captions", "grid", "dots"):
                    target_id = lid
                    break

    attacker = layers.get(attacker_id) if attacker_id else None
    weapon = layers.get(weapon_id) if weapon_id else None
    target = layers.get(target_id) if target_id else None

    if not attacker or not weapon or not target:
        return {
            "passed": False,
            "details": [],
            "errors": [
                f"Missing attacker, weapon, or target layer in spec (resolved attacker={attacker_id!r}, weapon={weapon_id!r}, target={target_id!r}). "
                f"Declare 'combat': {{'attacker': '...', 'weapon': '...', 'target': '...'}} in spec or pass --attacker/--weapon/--target."
            ],
        }

    punches = spec.get("punches", [])
    if not punches:
        return {"passed": True, "details": [], "message": "No punches defined"}

    errors = []
    details = []

    w_rect = weapon.get("rect", [0, 0, 476, 530])
    p0 = weapon.get("pivot", [attacker["rect"][0] + attacker["rect"][2] * 0.5, attacker["rect"][1] + attacker["rect"][3] * 0.35])

    if ref_width is None:
        w_asset = weapon.get("asset")
        w_row = manifest.verified("assets", w_asset) if w_asset else None
        if w_row and isinstance(w_row.get("size"), list) and w_row["size"][0] > 0:
            ref_width = float(w_row["size"][0])
        else:
            ref_width = 1090.0

    scale = w_rect[2] / float(ref_width) if w_rect[2] > 0 and ref_width > 0 else 0.42

    if tip_offset is not None and len(tip_offset) == 2:
        dx0 = float(tip_offset[0]) * scale
        dy0 = float(tip_offset[1]) * scale
    else:
        dx0 = 535.0 * scale
        dy0 = -268.0 * scale

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

        t_rect = target.get("rect", [980, 509, 246, 330])
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
