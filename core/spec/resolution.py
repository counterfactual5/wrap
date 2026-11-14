"""Resolving a layer's canvas geometry from the source image.

The joints and pivots a spec may declare are in SOURCE pixels; the renderer
needs canvas pixels. This module is the one place that converts between them.
"""
import os

from core.runtime.config import ROOT
from core.media.geometry import snap_socket_joint, source_to_canvas_pivot

PIVOT_JOINT_TOL = 8  # canvas px a hand-written pivot may stray from its joint


def resolve_joints(spec):
    """Derive a layer's canvas `pivot` from where its joint sits in the source image.

    A hinge pivot is a point on the *source picture* (a wrist, an elbow, a turret
    ring), but the renderer needs canvas pixels after S2's aspect-preserving
    `contain` scale + pad. Guessing that conversion by eye is what detached a hand
    from its sleeve, so two sources are honoured and cross-checked:

    * the layer's own `joint: [sx, sy]` (source pixels) -> pivot is computed;
    * the `joint` recorded in the manifest by `split-sprite` -> a hand-written
      `pivot` that disagrees by more than PIVOT_JOINT_TOL px is rejected.

    Layers whose asset is not registered yet are left alone (S2 reports that).
    """
    from core.runtime import manifest
    from core.media.png import read_size

    for L in spec.get("layers", []):
        if L.get("type") != "ai":
            continue
        kit = L.get("kit")
        if isinstance(kit, dict):
            if kit.get("joint") is not None and L.get("joint") is None:
                L["joint"] = kit["joint"]
            if kit.get("socket") is not None and L.get("socket") is None:
                L["socket"] = kit["socket"]
            if (kit.get("socket_radius") is not None and kit.get("joint_radius") is not None
                    and L.get("partScale") is None):
                L["partScale"] = round(float(kit["socket_radius"]) / float(kit["joint_radius"]), 4)
            if kit.get("type") in ("limb", "weapon", "turret", "wing") and L.get("snap") is None:
                L["snap"] = "socket"
        if not L.get("rect"):
            continue
        own = L.get("joint")
        row = manifest.verified("assets", L.get("asset"))
        if not row:
            continue
        joint = own if own is not None else row.get("joint")
        if joint is None:
            continue
        try:
            sw, sh = read_size(os.path.join(ROOT, row["path"]))
        except (OSError, ValueError):
            continue
        want = source_to_canvas_pivot(sw, sh, L["rect"], joint[0], joint[1])
        sock = L.get("socket")
        par_id = L.get("parent")
        if par_id:
            par = next((p for p in spec.get("layers", []) if p.get("id") == par_id), None)
            if par and par.get("rect") and par.get("asset"):
                par_row = manifest.verified("assets", par.get("asset"))
                if sock is None and L.get("snap") == "socket" and par_row:
                    sock = par_row.get("socket")
                if sock is not None and par_row:
                    try:
                        psw, psh = read_size(os.path.join(ROOT, par_row["path"]))
                        use_part_scale = (
                            L.get("snap") == "socket"
                            or L.get("partScale") is not None
                            or L["rect"] == par["rect"]
                        )
                        snap = snap_socket_joint(
                            [psw, psh], par["rect"], sock, [sw, sh], joint,
                            part_scale=L.get("partScale", 1.0),
                            child_rect_size=None if use_part_scale else L["rect"][2:],
                        )
                        L["rect"] = snap["rect"]
                        want = snap["pivot"]
                    except (OSError, ValueError):
                        pass
        have = L.get("pivot")
        if have is not None and max(abs(have[0] - want[0]), abs(have[1] - want[1])) > PIVOT_JOINT_TOL:
            raise ValueError(
                f"invalid spec:\n  {L['id']}: pivot {have} is {max(abs(have[0]-want[0]), abs(have[1]-want[1])):.0f}px "
                f"away from its joint {list(joint)} (canvas {want}) — rotating about it "
                f"detaches the part from the body. Delete 'pivot' and declare "
                f"'joint': {list(joint)} instead.")
        L["pivot"] = want
    return spec
