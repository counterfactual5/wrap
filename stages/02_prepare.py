"""S2: keying-purity gate (exit 1 = blocked) + normalise/scale + draw code layers.
Usage: python3 02_prepare.py [--spec path/to/spec.json]
"""
import argparse
import json
import math
import os
import subprocess
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core import manifest
from core.draw import dots, grid
from core.metrics import edge_key_purity, read_rgb
from core.png import read_size, write_png
from core.schema import ROOT, gate_of, hex_rgb, load_spec


def main():
    parser = argparse.ArgumentParser(description="S2: Prepare layers and verify key purity")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    W, H = spec["canvas"]["w"], spec["canvas"]["h"]
    FPS = spec.get("fps", 30)
    style_path = os.path.join(ROOT, spec.get("style", "spec/style.json"))
    palette = {}
    if os.path.exists(style_path):
        with open(style_path) as f:
            palette = json.load(f).get("palette", {})
    # Prepared artifacts are namespaced per shot: build/prepared/{shot_id}/.
    # A shared build/prepared/{id}.png let whichever shot ran S2 last win the
    # filename (dark-style shots silently reused a light grid), the same
    # cross-shot contamination S4's frame binding already refuses.
    prep_dir = os.path.join(ROOT, "build", "prepared", shot_id)
    os.makedirs(prep_dir, exist_ok=True)
    blocked = False

    for L in spec["layers"]:
        if L["type"] == "code" and L["draw"] in ("grid", "dots"):
            rel = f"build/prepared/{shot_id}/{L['id']}.png"
            img_data = grid(W, H, palette) if L["draw"] == "grid" else dots(W, H, palette)
            write_png(os.path.join(ROOT, rel), W, H, img_data)
            manifest.register("prepared", f"{shot_id}/{L['id']}", rel, source="code")
            print(f"drew {rel} ({L['draw']})")

        if L["type"] not in ("ai", "video"):
            continue

        if L["type"] == "video":
            # A video layer is a frozen clip, not a keyed still: there is no
            # key color to measure, so the purity gate does not apply. The
            # clip is scaled to cover the layer rect (aspect preserved) and
            # re-encoded at the SHOT's frame rate.
            #
            # The frame rate must match the shot: Remotion computes a video
            # layer's loop period as mediaDuration * shotFps, so a 24fps clip
            # rendered at 30fps would loop over a window longer than the clip
            # itself and freeze on the last frame. Normalizing to the shot's
            # fps here keeps the loop period correct.
            src_row = manifest.verified("assets", L["asset"])
            if not src_row:
                print(f"{L['asset']}: no verified asset in manifest (run S1)", file=sys.stderr)
                sys.exit(2)
            src = os.path.join(ROOT, src_row["path"])
            lrect = L.get("rect", [0, 0, W, H])
            rw, rh = lrect[2], lrect[3]
            rel = f"build/prepared/{shot_id}/{L['asset']}.mp4"
            out_path = os.path.join(ROOT, rel)
            vf = (f"scale={rw}:{rh}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={rw}:{rh},format=yuv420p")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
                 "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-an", out_path],
                check=True
            )
            manifest.register("prepared", f"{shot_id}/{L['asset']}", rel, source="video",
                              fps=FPS)
            print(f"prepared {rel} {rw}x{rh} @ {FPS}fps")
            continue

        src_row = manifest.verified("assets", L["asset"])
        if not src_row:
            print(f"{L['asset']}: no verified asset in manifest (run S1)", file=sys.stderr)
            sys.exit(2)
        src = os.path.join(ROOT, src_row["path"])
        sw, sh = read_size(src)

        g = gate_of(spec, "edge_key_purity")
        if g is not None:
            purity = edge_key_purity(
                read_rgb(src, sw, sh), sw, sh, hex_rgb(L["keyColor"]),
                ring=g.get("ring", 8), tol=g.get("tol", 12)
            )
            lo = g.get("lo", 0.98)
            verdict = "PASS" if purity >= lo else "BLOCKED"
            print(f"{L['asset']}: edge_key_purity={purity:.4f} (>= {lo}) {verdict}")
            if purity < lo:
                blocked = True
                continue
        else:
            purity = 1.0

        zmax = max((L.get("motion") or {}).get("zoom", [1, 1]))
        lrect = L.get("rect", [0, 0, W, H])
        rw, rh = lrect[2], lrect[3]
        if rw == W and rh == H:
            pw = math.ceil(W * zmax * 1.04 / 2) * 2          # headroom so zoom never exposes an edge
            ph = round(pw * H / W / 2) * 2
            vf = f"scale={pw}:{ph}:flags=lanczos,format=rgb24"
        else:
            # Subregion layer: scale to cover bounding box preserving source aspect ratio (never stretch!)
            pw = math.ceil(rw * zmax * 1.04 / 2) * 2
            ph = math.ceil(rh * zmax * 1.04 / 2) * 2
            vf = f"scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,crop={pw}:{ph},format=rgb24"

        rel = f"build/prepared/{shot_id}/{L['asset']}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
             os.path.join(ROOT, rel)],
            check=True
        )
        manifest.register("prepared", f"{shot_id}/{L['asset']}", rel, source="scaled", purity=purity, size=[pw, ph])
        print(f"prepared {rel} {pw}x{ph}")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
