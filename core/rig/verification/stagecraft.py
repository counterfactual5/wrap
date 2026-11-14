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
    """Audit a single shot for scrolling backdrop transitions ('推拉换景'), narrative props ('砌末'),
    authentic visual effects (flagging raw wireframe paths on translucent shadow-puppet stages),
    and ensemble character activity (100% domain-agnostic)."""
    layers_list = spec.get("layers", [])
    dur = int(spec.get("durationInFrames", 300))
    start_bg = _dominant_backdrop_at_frame(layers_list, 0)
    end_bg = _dominant_backdrop_at_frame(layers_list, max(0, dur - 1))

    scrolling_backdrops = []
    narrative_props = []
    wireframe_paths = []
    frozen_characters = []

    root_chars = [
        L for L in layers_list
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent") and L.get("role") != "prop"
    ]
    has_shadow_puppets = any(L.get("translucent") for L in root_chars)

    child_layers_by_parent = {}
    for L in layers_list:
        pid = L.get("parent")
        if pid:
            child_layers_by_parent.setdefault(pid, []).append(L)

    for L in layers_list:
        lid = L.get("id", "")
        ltype = L.get("type")
        anim = L.get("anim") or {}
        x_kfs = anim.get("x") or []
        y_kfs = anim.get("y") or []
        op_kfs = anim.get("opacity") or []

        # 1. Non-cutout AI backdrop/scroll layers with significant horizontal/vertical push-pull pan
        if ltype == "ai" and not L.get("cutout"):
            dx = (max(k[1] for k in x_kfs) - min(k[1] for k in x_kfs)) if len(x_kfs) >= 2 else 0.0
            dy = (max(k[1] for k in y_kfs) - min(k[1] for k in y_kfs)) if len(y_kfs) >= 2 else 0.0
            if dx >= 400.0 or dy >= 300.0:
                scrolling_backdrops.append({
                    "id": lid,
                    "asset": L.get("asset"),
                    "pan_dx": round(dx, 1),
                    "pan_dy": round(dy, 1),
                })

        # 2. Detect raw geometric `code: path` wireframes on shadow-puppet stages
        if has_shadow_puppets and ltype == "code" and L.get("draw") == "path":
            wireframe_paths.append(lid)

        # 3. Narrative props ("砌末"): explicit role=="prop", or prop cutout layers
        is_prop = (
            L.get("role") == "prop"
            or "prop" in lid.lower()
            or "scroll" in lid.lower()
            or "cloud" in lid.lower()
            or "circle" in lid.lower()
            or "ring" in lid.lower()
            or "fillet" in lid.lower()
            or "cage" in lid.lower()
            or "talisman" in lid.lower()
            or (not has_shadow_puppets and ltype == "code" and L.get("draw") == "path" and (L.get("params") or {}).get("reveal"))
        )
        if is_prop and ltype != "code" and (x_kfs or y_kfs or op_kfs or anim.get("rotate") or anim.get("scale")):
            narrative_props.append(lid)
        elif is_prop and not has_shadow_puppets and (x_kfs or y_kfs or op_kfs or (L.get("params") or {}).get("reveal")):
            narrative_props.append(lid)

    turnaround_characters = []
    weak_shudder_acting = []
    stale_props = []

    # Determine scroll start frame if an in-shot scroll backdrop exists
    scroll_onset_frame = None
    for L in layers_list:
        if L.get("type") == "ai" and not L.get("cutout"):
            xkfs = (L.get("anim") or {}).get("x") or []
            if len(xkfs) >= 2 and (max(k[1] for k in xkfs) - min(k[1] for k in xkfs)) >= 400.0:
                v0 = xkfs[0][1]
                for idx_k in range(1, len(xkfs)):
                    if abs(xkfs[idx_k][1] - v0) > 10.0:
                        f_onset = int(xkfs[idx_k - 1][0])
                        if scroll_onset_frame is None or f_onset < scroll_onset_frame:
                            scroll_onset_frame = f_onset
                        break

    # Check stationary unparented ground props that linger across/after a stage scroll transition
    if scroll_onset_frame is not None and start_bg != end_bg:
        for L in layers_list:
            if L.get("role") == "prop" and not L.get("parent"):
                anim = L.get("anim") or {}
                xkfs = anim.get("x") or []
                dx = (max(k[1] for k in xkfs) - min(k[1] for k in xkfs)) if len(xkfs) >= 2 else 0.0
                if dx < 15.0:
                    # Check if visible during the second half of the scroll or at the end of the shot
                    check_f = min(dur - 1, scroll_onset_frame + 25)
                    op_mid = eval_channel(anim.get("opacity", []), check_f, 1.0)
                    op_end = eval_channel(anim.get("opacity", []), dur - 1, 1.0)
                    if op_mid > 0.25 or op_end > 0.25:
                        stale_props.append(L["id"])

    weapon_tokens = ("staff", "weapon", "sword", "blade", "spear", "rake", "halberd", "lance", "axe", "club")

    def _has_active_weapon_pose(char_id, check_frame):
        for ch_l in child_layers_by_parent.get(char_id, []):
            lid_l = ch_l.get("id", "").lower()
            ktype = (ch_l.get("kit") or {}).get("type", "")
            base_asset = ch_l.get("asset", "")
            is_weapon_limb = (
                ktype == "weapon"
                or any(tok in lid_l for tok in weapon_tokens)
                or any(tok in base_asset.lower() for tok in weapon_tokens)
            )
            if not is_weapon_limb:
                continue
            active_asset = base_asset
            for ps in (ch_l.get("poses") or []):
                if ps.get("frame", 0) <= check_frame:
                    active_asset = ps.get("asset", active_asset)
            if any(tok in active_asset.lower() for tok in weapon_tokens):
                return ch_l["id"], active_asset
        return None, None

    for C in root_chars:
        cid = C["id"]
        anim = C.get("anim") or {}
        if C.get("flipX") or len(anim.get("flipX") or []) >= 2:
            turnaround_characters.append(cid)
        gait = C.get("gait") or {}
        if gait.get("mode") == "shudder":
            rng = gait.get("range") or [0, dur - 1]
            r0, r1 = max(0, int(rng[0])), min(dur - 1, int(rng[1]))
            max_y = max((eval_channel(anim.get("y", []), f, 0.0) for f in range(r0, r1 + 1)), default=0.0)
            max_pos_rot = max((eval_channel(anim.get("rotate", []), f, 0.0) for f in range(r0, r1 + 1)), default=0.0)
            if max_y < 68.0 or max_pos_rot < 25.0:
                weak_shudder_acting.append(
                    f"{cid}(need_deep_kneel_y>=68_got_{max_y:.1f}_and_forward_pitch_rot>=+25_got_{max_pos_rot:.1f})"
                )
            mid_shudder = (r0 + r1) // 2
            w_lid, w_asset = _has_active_weapon_pose(cid, mid_shudder)
            if w_lid:
                weak_shudder_acting.append(f"{w_lid}(holding_weapon_asset_{w_asset}_during_shudder_instead_of_bare_arm_pose)")
            # Check that other humanoid characters on stage plant their legs stationary during incantation/shudder
            w0, w1 = min(r1, r0 + 12), max(r0, r1 - 12)
            if w1 > w0:
                for other_c in root_chars:
                    ocid = other_c["id"]
                    if ocid == cid:
                        continue
                    o_op = eval_channel((other_c.get("anim") or {}).get("opacity", []), (w0 + w1) // 2, 1.0)
                    if o_op < 0.5:
                        continue
                    o_legs = [
                        ch_l for ch_l in child_layers_by_parent.get(ocid, [])
                        if "leg" in ch_l.get("id", "").lower()
                    ]
                    for leg_l in o_legs:
                        l_kfs = (leg_l.get("anim") or {}).get("rotate") or []
                        vals = [eval_channel(l_kfs, f, 0.0) for f in range(w0, w1 + 1, 4)]
                        if vals and (max(vals) - min(vals)) > 6.0:
                            if ocid not in weak_shudder_acting:
                                weak_shudder_acting.append(f"{ocid}(legs_rocking_during_chant)")

        has_root_motion = any(len(anim.get(ch) or []) >= 2 for ch in ("x", "y", "rotate", "scale")) or bool(C.get("gait")) or bool(C.get("poses"))
        children = child_layers_by_parent.get(cid, [])
        has_child_motion = any(
            any(len((ch_layer.get("anim") or {}).get(ch) or []) >= 2 for ch in ("rotate", "x", "y"))
            for ch_layer in children
        )
        if not (has_root_motion or has_child_motion):
            frozen_characters.append(cid)

    # Domain-agnostic caption-to-acting synchronization check:
    # 1. Any bounded shudder gait [sr0, sr1] must start within [-15, +24] frames of a caption clause onset.
    # 2. Any deep-kneeling bow window (y >= 65 and rotate >= +25 outside shudder) must switch weapon limbs to bare-arm poses.
    caption_action_desync = []
    cap_items = []
    for L in layers_list:
        if L.get("type") == "code" and L.get("draw") == "captions":
            cap_items = (L.get("params") or {}).get("items") or []
            break
    if cap_items:
        clause_onsets = [int(item.get("frame", 0)) for item in cap_items]
        for C in root_chars:
            gait = C.get("gait") or {}
            if gait.get("mode") == "shudder" and gait.get("range"):
                sr0 = int(gait["range"][0])
                aligned = any(-15 <= (sr0 - cf0) <= 24 for cf0 in clause_onsets)
                if not aligned:
                    nearest_cf = min(clause_onsets, key=lambda cf0: abs(sr0 - cf0))
                    caption_action_desync.append(
                        f"{C['id']} shudder starts at frame {sr0}, unaligned with nearest caption clause onset at frame {nearest_cf}"
                    )

    for C in root_chars:
        gait = C.get("gait") or {}
        if gait.get("mode") == "shudder":
            continue
        canim = C.get("anim") or {}
        bow_frames = [
            f for f in range(dur)
            if eval_channel(canim.get("y", []), f, 0.0) >= 65.0
            and eval_channel(canim.get("rotate", []), f, 0.0) >= 25.0
        ]
        if bow_frames:
            mid_bow = bow_frames[len(bow_frames) // 2]
            w_lid, w_asset = _has_active_weapon_pose(C["id"], mid_bow)
            if w_lid:
                caption_action_desync.append(
                    f"{w_lid} still holds weapon asset '{w_asset}' during deep kneeling bow at frame {mid_bow} instead of bare-arm pose"
                )

    return {
        "shot_id": spec.get("id", "shot"),
        "duration_sec": round(dur / max(1, int(spec.get("fps", 30))), 2),
        "start_backdrop": start_bg,
        "end_backdrop": end_bg,
        "has_in_shot_scroll": len(scrolling_backdrops) > 0 and start_bg != end_bg,
        "scrolling_backdrops": scrolling_backdrops,
        "narrative_props": narrative_props,
        "wireframe_paths": wireframe_paths,
        "stale_props": stale_props,
        "turnaround_characters": turnaround_characters,
        "weak_shudder_acting": weak_shudder_acting,
        "caption_action_desync": caption_action_desync,
        "frozen_characters": frozen_characters,
        "root_characters": [c["id"] for c in root_chars],
        "start_states": _extract_root_character_states(spec, 0),
        "end_states": _extract_root_character_states(spec, max(0, dur - 1)),
        "passed": (
            len(frozen_characters) == 0
            and len(wireframe_paths) == 0
            and len(stale_props) == 0
            and len(weak_shudder_acting) == 0
            and len(caption_action_desync) == 0
        ),
    }
