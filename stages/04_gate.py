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


def _video_layers(spec):
    """The video layers of a shot: [(asset, muted, duration_seconds)]."""
    out = []
    for L in spec["layers"]:
        if L.get("type") != "video":
            continue
        row = manifest.verified("prepared", f"{spec.get('id', 'shot-01')}/{L['asset']}")
        dur = ""
        if row:
            path = os.path.join(ROOT, row["path"])
            res = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], capture_output=True, text=True)
            value = res.stdout.strip()
            if value:
                dur = f" ({value}s)"
        out.append((L.get("asset", "?"), L.get("muted", True), dur))
    return out


def _video_hint(spec):
    """A hint pointing at the video layer when motion/freeze fail.

    A shot whose video layer is a still clip fails both gates, and the raw
    metrics ("changed_pixel_ratio 0.000000", "1 frozen segment") do not say
    where to look. Name the layer, and distinguish the two causes: footage
    that is static, and footage that ran out before the shot ended."""
    vids = _video_layers(spec)
    if not vids:
        return ""
    names = ", ".join(f"{a}{d}" for a, _, d in vids)
    # Did the clip run out before the shot ended (and is it not looping)?
    ran_out = False
    for L in spec["layers"]:
        if L.get("type") != "video" or L.get("loop", True):
            continue
        row = manifest.verified("prepared", f"{spec.get('id', 'shot-01')}/{L['asset']}")
        if row and row.get("shorter_than_shot"):
            ran_out = True
    if ran_out:
        return (f"\n       -> the shot has a video layer ({names}) whose clip is "
                f"shorter than the shot and loop is off: the footage RAN OUT "
                f"before the shot ended, so the tail is frozen. Shorten the "
                f"shot, lengthen the clip, or set \"loop\": true.")
    return (f"\n       -> the shot has a video layer ({names}); if the clip is "
            f"static, the motion and freeze gates fail on the SOURCE footage, "
            f"not on the composition.")


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
    parser.add_argument("--spec", default=None, help="Path to spec file (default: tests/fixtures/shot-01.poster.json)")
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
                ai_assets = [L["asset"]]
                for p in L.get("poses") or []:
                    pa = p.get("asset")
                    if pa and pa not in ai_assets:
                        ai_assets.append(pa)
                for asset_name in ai_assets:
                    row = manifest.verified("prepared", f"{shot_id}/{asset_name}")
                    if row is None:
                        raise RuntimeError(
                            f"prepared asset '{shot_id}/{asset_name}' not manifest-verified; run S2")
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
        if not ok and g["metric"] in ("changed_pixel_ratio", "subject_motion_ratio"):
            hint = _video_hint(spec)
            if hint:
                print(hint)

    fz = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", mp4, "-vf", "freezedetect=n=0.001:d=0.5", "-f", "null", "-"],
        capture_output=True, text=True
    ).stderr
    frozen = [l for l in fz.splitlines() if "freeze_start" in l]
    print(f"{'FAIL' if frozen else 'PASS'}  freeze     freezedetect         {len(frozen)} frozen segment(s)")
    if frozen:
        hint = _video_hint(spec)
        if hint:
            print(hint)
    red |= bool(frozen)
    results.append({"id": "freeze", "metric": "freezedetect", "value": len(frozen), "pass": not frozen})

    # Audio QC Gates: silence, loudness (LUFS), and AV duration alignment.
    # They run whenever the RENDERED mp4 actually carries an audio track —
    # not merely when the spec declares one. A shot whose soundtrack comes
    # from a video layer's native track has no `audio` block, and skipping
    # the gates there would let an unmeasured soundtrack through.
    from core import audio
    av_probe = audio.measure_av_durations(mp4)
    if av_probe.get("has_audio"):
        # 1. Silence and content check
        sil_res = audio.measure_audio_silence(mp4)
        is_ambient = spec.get("ambient", False) or (isinstance(spec.get("audio"), dict) and spec.get("audio", {}).get("ambient", False))

        sil_ok = not sil_res["is_silent"]
        # A non-silent track must also carry real content (not just flat noise/drone),
        # unless the shot is explicitly declared as an ambient soundbed.
        if sil_ok and not is_ambient and not sil_res.get("has_content", True):
            sil_ok = False
            sp_m = sil_res.get("speech_max_volume", -99.0)
            print(f"FAIL  silence    audio_content        no voice/foreground content (speech band max {sp_m:.1f} dB <= -25.0 dB). "
                  f"Declare 'ambient': true in spec if this is an ambient shot.")
        else:
            print(f"{'PASS' if sil_ok else 'FAIL'}  silence    audio_max_volume     {sil_res['max_volume']:.1f} dB  [>-45.0 dB]"
                  f"{' (ambient)' if is_ambient else ''}")

        red |= not sil_ok
        results.append({
            "id": "audio_silence", "metric": "audio_max_volume",
            "value": sil_res["max_volume"], "lo": -45.0, "pass": sil_ok,
            "has_content": sil_res.get("has_content", True),
            "ambient": is_ambient
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
        delta = av_probe["delta"]
        sync_ok = (delta <= 0.10)
        red |= not sync_ok
        print(f"{'PASS' if sync_ok else 'FAIL'}  av_sync    duration_delta       {delta:.3f} s  [<= 0.100 s]")
        results.append({
            "id": "audio_av_sync", "metric": "duration_delta",
            "value": delta, "hi": 0.10, "pass": sync_ok
        })

        # 4. Voiceover truncation check: ensure TTS narration was not chopped off by -t shot_duration
        voice_meta_path = os.path.join(ROOT, ".tmp", f"{shot_id}_audio.aac.meta.json")
        if os.path.exists(voice_meta_path):
            try:
                with open(voice_meta_path) as mf:
                    vmeta = json.load(mf)
            except Exception:
                vmeta = {}
            if vmeta.get("has_voice"):
                raw_d = float(vmeta.get("raw_voice_duration", 0.0))
                tgt_d = float(vmeta.get("target_duration", spec["durationInFrames"] / max(1, FPS)))
                trunc_ok = not vmeta.get("truncated", raw_d > tgt_d + 0.25)
                red |= not trunc_ok
                if trunc_ok:
                    print(f"PASS  truncation voiceover_truncation {raw_d:.2f} s  [<= {tgt_d + 0.25:.2f} s]")
                else:
                    print(
                        f"FAIL  truncation voiceover_truncation raw={raw_d:.2f}s > shot={tgt_d:.2f}s "
                        f"(voiceover cut off! Run 'python3 pipeline.py sync-audio --spec <spec>' or increase durationInFrames)"
                    )
                results.append({
                    "id": "voiceover_truncation",
                    "metric": "voiceover_vs_shot_duration",
                    "value": raw_d,
                    "hi": round(tgt_d + 0.25, 3),
                    "pass": trunc_ok,
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
