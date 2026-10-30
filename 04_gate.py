"""S4: measure the gates on the lossless PNG frames; exit 1 if any is red. Writes build/gates.json.
Usage: python3 04_gate.py [--spec path/to/spec.json]
"""
import argparse
import json
import os
import subprocess
import sys
from importlib import import_module

from lib import manifest, metrics
from schema import ROOT, load_spec


def _verify_measured_object(shot_id):
    """The gate must measure THIS shot's artifacts, not whatever last sat in the
    shared build/frames. Two bindings, both fail-fast:
    1. the manifest video row (sha-verified by manifest.verified) must belong to
       this shot — its path is build/{shot_id}.mp4;
    2. the frame directory's aggregate fingerprint must equal the one S3
       registered for that row, so stale/replaced frames are refused."""
    row = manifest.verified("video", None)
    if row is None:
        raise RuntimeError(
            "gate: no manifest-verified video row; run S3 (03_compose.py) first")
    # compare normalized paths: os.path.join stays POSIX-shaped here, but the
    # literal f-string is what 03_compose registers.
    expected_mp4 = os.path.normpath(f"build/{shot_id}.mp4")
    if os.path.normpath(row.get("path", "")) != expected_mp4:
        raise RuntimeError(
            f"gate: manifest video row is {row.get('path')} (another shot's "
            f"render); build/frames holds that shot's frames, not {shot_id}'s — "
            f"re-run S3 for this shot before gating")
    registered = row.get("frames_sha")
    if not registered:
        raise RuntimeError(
            "gate: manifest video row predates frame binding (no frames_sha); "
            "re-run S3 (03_compose.py) to register the frame fingerprint")
    frames_dir = os.path.join(ROOT, "build", "frames")
    if not os.path.isdir(frames_dir):
        raise RuntimeError(
            "gate: build/frames is missing; run S3 (03_compose.py) before gating")
    compose = import_module("03_compose")
    live = compose.frames_fingerprint(frames_dir)
    if live != registered:
        raise RuntimeError(
            f"gate: build/frames does not match the fingerprint registered for "
            f"{shot_id} (frames replaced or stale); re-run S3 before gating")


def _bar_band(spec):
    """Vertical band covering the accent bar's travel (rect y .. y+h, padded)."""
    for L in spec["layers"]:
        if L["type"] == "code" and L.get("draw") == "bar":
            x, y, w, h = L["rect"]
            return [max(0, y - 20), min(spec["canvas"]["h"], y + h + 20)]
    return None


def _accent_color(spec):
    for L in spec["layers"]:
        if L["type"] == "code" and L.get("draw") == "bar":
            return L.get("color")
    return None


def main():
    parser = argparse.ArgumentParser(description="S4: Quality gates validation")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    _verify_measured_object(shot_id)
    W, H, FPS = spec["canvas"]["w"], spec["canvas"]["h"], spec["fps"]
    frames = os.path.join(ROOT, "build", "frames", "%05d.png")
    mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    results, red = [], False

    def measure(g):
        inp = ("-framerate", str(FPS))
        if g["metric"] == "changed_pixel_ratio":
            return metrics.median(metrics.changed_pixel_ratios(frames, W, H, g.get("lumaDelta", 6), inp))
        if g["metric"] == "subject_motion_ratio":
            # Same metric, restricted to the region outside g["region"] — a
            # panning bar can no longer mask a static AI subject.
            band = g.get("region") or _bar_band(spec)
            return metrics.median(metrics.changed_pixel_ratios(frames, W, H, g.get("lumaDelta", 6), inp, exclude_band=tuple(band)))
        if g["metric"] in ("red_pixel_ratio", "accent_color_ratio"):
            if g["metric"] == "accent_color_ratio":
                from schema import hex_rgb
                color = _accent_color(spec)
                if color is None:
                    raise RuntimeError("accent_color_ratio: no bar layer color in spec")
                tables = metrics._mask_tables(hex_rgb(color))
                return metrics.median(metrics.color_pixel_ratios(frames, W, H, tables, inp))
            return metrics.median(metrics.red_pixel_ratios(frames, W, H, inp))
        if g["metric"] == "edge_key_purity":
            # Verify sha256 through the manifest (not trust a stored number): a
            # tampered prepared asset must fail the gate, not sail through it.
            rows = []
            for L in spec["layers"]:
                if L["type"] != "ai":
                    continue
                row = manifest.verified("prepared", L["asset"])
                if row is None:
                    raise RuntimeError(
                        f"prepared asset '{L['asset']}' not manifest-verified; run S2")
                rows.append(row.get("purity"))
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

    # Encoder fingerprint: reproducibility is only claimed for the ffmpeg/x264 that
    # produced the mp4. Mismatch = re-encode expected, not a quality failure.
    compose = import_module("03_compose")
    vid = manifest.verified("video", None)
    if vid and vid.get("encoder"):
        live = compose.encoder_fingerprint()
        ok = live == vid["encoder"]
        print(f"{'PASS' if ok else 'WARN'}  encoder   ffmpeg_fingerprint   manifest={vid['encoder'][:12]} live={live[:12]}")
        results.append({"id": "encoder", "metric": "ffmpeg_fingerprint",
                        "value": live, "pass": ok, "warn": not ok})

    gate_out = os.path.join(ROOT, "build", "gates.json")
    with open(gate_out, "w") as f:
        json.dump(results, f, indent=2)

    return 1 if red else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as ex:
        print(f"S4 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
