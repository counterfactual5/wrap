"""Cross-shot state continuity: carrying the end of a shot into the next."""
import copy


def carry_state_from(prev_spec, new_shot_id):
    """Carry the end-of-shot state of `prev_spec` into a new shot skeleton for `new_shot_id`.

    Solves cross-shot state continuity (#4): each persistent layer keeps its
    final keyframe values (x, y, scale, opacity, rotate) at frame 0 of the next
    shot, and a multi-pose `ai` layer starts from its last active pose asset.
    """
    out = copy.deepcopy(prev_spec)
    out["id"] = new_shot_id
    out.pop("punches", None)
    new_layers = []
    for L in out.get("layers", []):
        # Drop per-shot ephemeral subtitle captions items so the new shot starts clean
        if L.get("type") == "code" and L.get("draw") == "captions":
            L = copy.deepcopy(L)
            if isinstance(L.get("params"), dict):
                L["params"]["items"] = []
        # If an ai layer had poses, carry its final pose asset as the default asset at frame 0
        if L.get("type") == "ai" and isinstance(L.get("poses"), list) and L["poses"]:
            last_pose = L["poses"][-1]
            if isinstance(last_pose, dict) and last_pose.get("asset"):
                L["asset"] = last_pose["asset"]
                L["poses"] = [{"frame": 0, "asset": last_pose["asset"]}]
        # If the layer had anim channels, seed frame 0 with the final keyframe value
        if isinstance(L.get("anim"), dict):
            carried_anim = {}
            for ch, kfs in L["anim"].items():
                if isinstance(kfs, list) and kfs:
                    last_val = kfs[-1][1]
                    carried_anim[ch] = [[0, last_val], [out.get("durationInFrames", 150) - 1, last_val]]
            if carried_anim:
                L["anim"] = carried_anim
        if isinstance(L.get("gait"), dict):
            if L["gait"].get("mode") == "shudder":
                L.pop("gait", None)
            else:
                L["gait"].pop("range", None)
        new_layers.append(L)
    out["layers"] = new_layers
    return out
