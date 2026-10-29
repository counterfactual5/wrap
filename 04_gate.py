"""S4: measure the gates on the lossless PNG frames; exit 1 if any is red. Writes build/gates.json.
Usage: python3 04_gate.py [--spec path/to/spec.json]
"""
import argparse
import json
import os
import subprocess
import sys

from lib import manifest, metrics
from schema import ROOT, load_spec


def main():
    parser = argparse.ArgumentParser(description="S4: Quality gates validation")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    W, H, FPS = spec["canvas"]["w"], spec["canvas"]["h"], spec["fps"]
    frames = os.path.join(ROOT, "build", "frames", "%05d.png")
    mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    results, red = [], False

    def measure(g):
        inp = ("-framerate", str(FPS))
        if g["metric"] == "changed_pixel_ratio":
            return metrics.median(metrics.changed_pixel_ratios(frames, W, H, g.get("lumaDelta", 6), inp))
        if g["metric"] == "red_pixel_ratio":
            return metrics.median(metrics.red_pixel_ratios(frames, W, H, inp))
        if g["metric"] == "edge_key_purity":
            rows = [manifest.load()["prepared"].get(L["asset"], {}).get("purity") for L in spec["layers"] if L["type"] == "ai"]
            if not rows or any(r is None for r in rows):
                raise RuntimeError("no purity recorded; run S2")
            return min(rows)
        raise ValueError(g["metric"])

    for g in spec["gates"]:
        v = measure(g)
        ok = (g.get("lo") is None or v >= g["lo"]) and (g.get("hi") is None or v <= g["hi"])
        red |= not ok
        results.append({
            "id": g["id"], "metric": g["metric"], "value": v,
            "lo": g.get("lo"), "hi": g.get("hi"), "pass": ok
        })
        print(f"{'PASS' if ok else 'FAIL'}  {g['id']:<10} {g['metric']:<20} {v:.6f}  [{g.get('lo')}, {g.get('hi')}]")

    fz = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", mp4, "-vf", "freezedetect=n=0.001:d=0.5", "-f", "null", "-"],
        capture_output=True, text=True
    ).stderr
    frozen = [l for l in fz.splitlines() if "freeze_start" in l]
    print(f"{'FAIL' if frozen else 'PASS'}  freeze     freezedetect         {len(frozen)} frozen segment(s)")
    red |= bool(frozen)
    results.append({"id": "freeze", "metric": "freezedetect", "value": len(frozen), "pass": not frozen})

    gate_out = os.path.join(ROOT, "build", "gates.json")
    with open(gate_out, "w") as f:
        json.dump(results, f, indent=2)

    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
