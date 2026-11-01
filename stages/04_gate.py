"""S4: measure the gates on the lossless PNG frames; exit 1 if any is red.
Writes build/gates/{shot_id}.json — per shot, so concurrent/alternating S4
runs cannot overwrite another shot's verdict (build/gates.json was a
last-writer-wins slot).
Usage: python3 04_gate.py [--spec path/to/spec.json]
"""
import argparse
import json
import os
import subprocess
import sys
import os
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core import manifest, metrics
from core.render import encoder_fingerprint, frames_fingerprint
from core.schema import ROOT, load_spec


def _verify_measured_object(shot_id):
    """The gate must measure THIS shot's artifacts, not another shot's. The
    manifest video section is keyed per shot, so the binding cannot be evicted
    by a later render of a different shot; two fail-fast checks remain:
    1. the sha-verified video row for this shot must exist (i.e. S3 ran for it);
    2. the frame directory's aggregate fingerprint must equal the one S3
       registered, so stale/replaced frames are refused."""
    row = manifest.verified("video", shot_id)
    if row is None:
        raise RuntimeError(
            f"gate: no manifest-verified video row for {shot_id}; "
            f"run S3 (03_compose.py) for this shot first")
    registered = row.get("frames_sha")
    if not registered:
        raise RuntimeError(
            "gate: manifest video row predates frame binding (no frames_sha); "
            "re-run S3 (03_compose.py) to register the frame fingerprint")
    frames_dir = os.path.join(ROOT, "build", "frames", shot_id)
    if not os.path.isdir(frames_dir):
        raise RuntimeError(
            f"gate: build/frames/{shot_id} is missing; run S3 (03_compose.py) "
            f"before gating")
    live = frames_fingerprint(frames_dir)
    if live != registered:
        raise RuntimeError(
            f"gate: build/frames/{shot_id} does not match the fingerprint "
            f"registered for {shot_id} (frames replaced or stale); re-run S3 "
            f"before gating")


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
    frames = os.path.join(ROOT, "build", "frames", shot_id, "%05d.png")
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
            exclude = tuple(band) if band else None
            return metrics.median(metrics.changed_pixel_ratios(frames, W, H, g.get("lumaDelta", 6), inp, exclude_band=exclude))
        if g["metric"] in ("red_pixel_ratio", "accent_color_ratio"):
            if g["metric"] == "accent_color_ratio":
                from core.schema import hex_rgb
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
                row = manifest.verified("prepared", f"{shot_id}/{L['asset']}")
                if row is None:
                    raise RuntimeError(
                        f"prepared asset '{shot_id}/{L['asset']}' not manifest-verified; run S2")
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

    # Audio QC Gates: silence, loudness (LUFS), and AV duration alignment
    if spec.get("audio"):
        from core import audio
        # 1. Silence check: non-silent audio track
        sil_res = audio.measure_audio_silence(mp4)
        sil_ok = not sil_res["is_silent"]
        red |= not sil_ok
        print(f"{'PASS' if sil_ok else 'FAIL'}  silence    audio_max_volume     {sil_res['max_volume']:.1f} dB  [>-45.0 dB]")
        results.append({
            "id": "audio_silence", "metric": "audio_max_volume",
            "value": sil_res["max_volume"], "lo": -45.0, "pass": sil_ok
        })

        # 2. Integrated loudness check: EBU R128 (-16 LUFS target, range [-19.0, -13.0])
        lufs = audio.measure_audio_loudness(mp4)
        if lufs is not None:
            loud_ok = (-19.0 <= lufs <= -13.0)
            red |= not loud_ok
            print(f"{'PASS' if loud_ok else 'FAIL'}  loudness   integrated_loudness  {lufs:.1f} LUFS  [-19.0, -13.0]")
            results.append({
                "id": "audio_loudness", "metric": "integrated_loudness",
                "value": lufs, "lo": -19.0, "hi": -13.0, "pass": loud_ok
            })
        else:
            print("WARN  loudness   integrated_loudness  could not measure")

        # 3. AV Duration sync check (diff <= 100ms)
        av_res = audio.measure_av_durations(mp4)
        if av_res.get("has_audio"):
            delta = av_res["delta"]
            sync_ok = (delta <= 0.10)
            red |= not sync_ok
            print(f"{'PASS' if sync_ok else 'FAIL'}  av_sync    duration_delta       {delta:.3f} s  [<= 0.100 s]")
            results.append({
                "id": "audio_av_sync", "metric": "duration_delta",
                "value": delta, "hi": 0.10, "pass": sync_ok
            })

    # Encoder fingerprint: reproducibility is only claimed for the ffmpeg/x264 that
    # produced the mp4. Mismatch = re-encode expected, not a quality failure.
    vid = manifest.verified("video", shot_id)
    if vid and vid.get("encoder"):
        live = encoder_fingerprint()
        ok = live == vid["encoder"]
        print(f"{'PASS' if ok else 'WARN'}  encoder   ffmpeg_fingerprint   manifest={vid['encoder'][:12]} live={live[:12]}")
        results.append({"id": "encoder", "metric": "ffmpeg_fingerprint",
                        "value": live, "pass": ok, "warn": not ok})

    gate_dir = os.path.join(ROOT, "build", "gates")
    os.makedirs(gate_dir, exist_ok=True)
    gate_out = os.path.join(gate_dir, f"{shot_id}.json")
    with open(gate_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"gates written: build/gates/{shot_id}.json")

    return 1 if red else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as ex:
        print(f"S4 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
