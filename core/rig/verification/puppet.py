"""Puppet joint & socket alignment verification with calibration diagnostics."""
import math
import os

from core.runtime import manifest
from core.runtime.config import ROOT
from core.media.png import read_size

from ..kits import snap_socket_joint
from ..sprites import source_to_canvas_pivot


def verify_puppet_rig(spec, out_dir="build/inspect", tolerance=4):
    """Verify skeletal puppet joint alignment, socket calibration, and render diagnostic overlay."""
    layers = spec.get("layers", [])
    layer_map = {L["id"]: L for L in layers}
    results = []
    errors = []

    os.makedirs(os.path.join(ROOT, out_dir), exist_ok=True)

    # Find root puppets and their child limbs
    for L in layers:
        par_id = L.get("parent")
        if not par_id or par_id not in layer_map:
            continue
        par = layer_map[par_id]
        kit = L.get("kit")
        if not kit:
            continue

        socket_src = kit.get("socket")
        joint_src = kit.get("joint")
        if not socket_src or not joint_src:
            errors.append(f"{L['id']}: missing socket or joint in kit configuration")
            continue

        # Get parent asset and child asset dimensions
        par_asset = par.get("asset")
        child_asset = L.get("asset")
        par_row = manifest.verified("assets", par_asset)
        child_row = manifest.verified("assets", child_asset)

        if not par_row or not child_row:
            errors.append(f"{L['id']}: missing verified manifest asset for parent ({par_asset}) or child ({child_asset})")
            continue

        # Get parent asset and child asset dimensions. The manifest row does
        # NOT always carry the source size — assets frozen before S1 started
        # recording it have no "size" field — so read it from the file, the
        # same way core.spec.resolution.resolve_joints does. The manifest is the
        # authority on WHICH file is frozen; the file is the authority on
        # its dimensions. Reading the row blindly crashed with a KeyError on
        # every rigged shot.
        def _source_size(row):
            if not row:
                return None
            size = row.get("size")
            if (isinstance(size, (list, tuple)) and len(size) == 2
                    and size[0] > 0 and size[1] > 0):
                return (int(size[0]), int(size[1]))
            try:
                w, h = read_size(os.path.join(ROOT, row["path"]))
                return (int(w), int(h))
            except (OSError, ValueError, KeyError, TypeError):
                return None

        par_size = _source_size(par_row)
        child_size = _source_size(child_row)
        if not par_size or not child_size:
            errors.append(
                f"{L['id']}: could not read the source size of parent ({par_asset}) "
                f"or child ({child_asset}) — the asset file is missing or unreadable")
            continue
        par_rect = par.get("rect", [0, 0, par_size[0], par_size[1]])
        part_scale = L.get("partScale", 1.0)

        # Snap socket to joint:
        snapped = snap_socket_joint(par_size, par_rect, socket_src, child_size, joint_src, part_scale=part_scale)
        child_rect = snapped["rect"]
        child_pivot = snapped["pivot"]

        # Calculate canvas position of parent socket:
        par_socket_canvas = source_to_canvas_pivot(par_size[0], par_size[1], par_rect, socket_src[0], socket_src[1])

        # Distance error between parent socket and child pivot
        delta = math.hypot(par_socket_canvas[0] - child_pivot[0], par_socket_canvas[1] - child_pivot[1])
        status = "PASS" if delta <= tolerance else "DISLOCATED"

        if delta > tolerance:
            errors.append(
                f"{L['id']}: joint detached from parent socket! delta={delta:.1f}px > tol={tolerance}px. "
                f"Parent socket canvas={par_socket_canvas}, child pivot={child_pivot}"
            )

        results.append({
            "child_id": L["id"],
            "parent_id": par_id,
            "delta_px": round(delta, 2),
            "status": status,
            "socket_src": socket_src,
            "joint_src": joint_src,
            "pivot_canvas": child_pivot,
            "child_rect": child_rect,
        })

    # Render diagnostic calibration sheet if PIL is available
    diag_path = os.path.join(ROOT, out_dir, f"rig_calibration_{spec.get('id', 'puppet')}.png")
    try:
        from PIL import Image, ImageDraw
        cw, ch = spec["canvas"]["w"], spec["canvas"]["h"]
        img = Image.new("RGBA", (cw, ch), (20, 16, 12, 255))
        draw = ImageDraw.Draw(img)

        # Draw grid
        for x in range(0, cw, 100):
            draw.line([(x, 0), (x, ch)], fill=(40, 32, 24), width=1)
        for y in range(0, ch, 100):
            draw.line([(0, y), (cw, y)], fill=(40, 32, 24), width=1)

        # Plot each calibrated joint
        for r in results:
            px, py = r["pivot_canvas"]
            # Socket crosshair (RED)
            draw.line([(px - 14, py), (px + 14, py)], fill=(255, 60, 60), width=3)
            draw.line([(px, py - 14), (px, py + 14)], fill=(255, 60, 60), width=3)
            # Joint circle (CYAN)
            draw.ellipse([px - 8, py - 8, px + 8, py + 8], outline=(60, 220, 255), width=2)
            # Label
            draw.text((px + 16, py - 8), f"{r['child_id']} (Δ={r['delta_px']}px) [{r['status']}]",
                      fill=(255, 215, 0) if r["status"] == "PASS" else (255, 50, 50))

        img.save(diag_path)
    except Exception:
        pass

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "joints": results,
        "diagnostic_image": diag_path,
    }
