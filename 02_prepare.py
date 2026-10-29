"""S2: keying-purity gate (exit 1 = blocked) + normalise/scale + draw code layers.
Usage: python3 02_prepare.py [--spec path/to/spec.json]
"""
import argparse
import math
import os
import subprocess
import sys

from lib import manifest
from lib.draw import grid
from lib.metrics import edge_key_purity, read_rgb
from lib.png import read_size, write_png
from schema import ROOT, gate_of, hex_rgb, load_spec


def main():
    parser = argparse.ArgumentParser(description="S2: Prepare layers and verify key purity")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    W, H = spec["canvas"]["w"], spec["canvas"]["h"]
    os.makedirs(os.path.join(ROOT, "build", "prepared"), exist_ok=True)
    blocked = False

    for L in spec["layers"]:
        if L["type"] == "code" and L["draw"] == "grid":
            rel = f"build/prepared/{L['id']}.png"
            write_png(os.path.join(ROOT, rel), W, H, grid(W, H))
            manifest.register("prepared", L["id"], rel, source="code")
            print(f"drew {rel}")

        if L["type"] != "ai":
            continue
        src_row = manifest.verified("assets", L["asset"])
        if not src_row:
            print(f"{L['asset']}: no verified asset in manifest (run S1)", file=sys.stderr)
            sys.exit(2)
        src = os.path.join(ROOT, src_row["path"])
        sw, sh = read_size(src)

        g = gate_of(spec, "edge_key_purity") or {}
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

        zmax = max((L.get("motion") or {}).get("zoom", [1, 1]))
        pw = math.ceil(W * zmax * 1.04 / 2) * 2          # headroom so zoom never exposes an edge
        ph = round(pw * H / W / 2) * 2
        rel = f"build/prepared/{L['asset']}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", f"scale={pw}:{ph}:flags=lanczos,format=rgb24",
             os.path.join(ROOT, rel)],
            check=True
        )
        manifest.register("prepared", L["asset"], rel, source="scaled", purity=purity, size=[pw, ph])
        print(f"prepared {rel} {pw}x{ph}")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
