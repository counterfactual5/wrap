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

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core.runtime import manifest
from core.quality import pixels as metrics
from core.media.fingerprints import encoder_fingerprint, frames_fingerprint
from core.runtime.config import ROOT
from core.spec.loader import load_spec


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


def _crop_diagnosis(spec):
    """What the visible window of each video layer actually shows.

    fit:'cover' (the default) keeps the CENTRE of the clip and crops the
    rest: a 9:16 clip in a 16:9 rect shows ~14% of its width and ~32% of its
    height. Whatever moves outside that window never reaches the picture, so
    a shot can PASS the motion gate (some pixels changed somewhere in the
    shot) and still show a completely frozen frame for half a second. The
    numbers here are what turn "the freeze gate fired" into "the freeze gate
    fired because of THIS rectangle"."""
    notes = []
    for L in spec["layers"]:
        if L.get("type") != "video" or L.get("fit", "cover") != "cover":
            continue
        row = manifest.verified("prepared", f"{spec.get('id', 'shot-01')}/{L['asset']}")
        size = (row or {}).get("source_size")
        if not size or len(size) != 2:
            continue
        sw, sh = size
        rect = L.get("rect") or []
        if len(rect) != 4:
            continue
        _, _, rw, rh = rect
        if not sw or not sh or not rw or not rh:
            continue
        scale = max(rw / sw, rh / sh)
        vis_w, vis_h = rw / scale, rh / scale
        notes.append(
            f"{L['asset']}: the clip is {sw}x{sh} but the rect is {rw}x{rh} "
            f"(fit 'cover'), so the frame shows only the centre {vis_w:.0f}x{vis_h:.0f} "
            f"of it — {(1 - vis_w / sw) * 100:.0f}% of the width and "
            f"{(1 - vis_h / sh) * 100:.0f}% of the height are cropped away")
    return notes


def _video_hint(spec, reason="low_motion"):
    """A hint pointing at the video layer when motion/freeze fail.

    A shot whose video layer is a still clip fails both gates, and the raw
    metrics ("changed_pixel_ratio 0.000000", "1 frozen segment") do not say
    where to look. Name the layer, and distinguish the causes: footage that is
    static, footage that ran out before the shot ended, motion exceeding hi,
    and motion that happens OUTSIDE the visible crop (the last one passes the
    motion gate while the picture stands still)."""
    vids = _video_layers(spec)
    if not vids:
        return ""
    names = ", ".join(f"{a}{d}" for a, _, d in vids)
    if reason == "high_motion":
        return (f"\n       -> the shot has a video layer ({names}) whose frame-to-frame "
                f"change exceeds the gate's upper bound (hi); use calmer SOURCE footage, "
                f"reduce playbackRate/zoom, or widen the gate's hi bound.")
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
    if reason == "frozen_window":
        # The motion gate passed but the picture stood still: the change was
        # real, it just never reached the screen.
        crops = _crop_diagnosis(spec)
        if crops:
            return ("\n       -> the picture was IDENTICAL for >= 0.5s although the "
                    "motion gate passed: the motion happened OUTSIDE the visible crop.\n"
                    + "\n".join(f"          {c}" for c in crops)
                    + "\n       -> match the clip's aspect to the rect, set "
                    "\"fit\": \"contain\" to show the whole clip, or keep the motion "
                    "inside the window that is actually on screen.")
        return ("\n       -> the picture was IDENTICAL for >= 0.5s although the motion "
                "gate passed: the source's motion stayed OUTSIDE the visible crop "
                "(fit:'cover' keeps only the centre of the clip), or the per-frame "
                "change was below what the freeze detector counts as motion (its "
                "noise tolerance is 0.1% of the frame).")
    return (f"\n       -> the shot has a video layer ({names}); if both the motion "
            f"and freeze gates fail, the SOURCE footage itself is static (or needs "
            f"motion.zoom / active keyframes), not the composition.")


def main():
    parser = argparse.ArgumentParser(description="S4: Quality gates validation")
    parser.add_argument("--spec", default=None, help="Path to spec file (required)")
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
            band = g.get("region")
            exclude = tuple(band) if band else None
            return metrics.median(metrics.changed_pixel_ratios(frames, W, H, g.get("lumaDelta", 6), inp, exclude_band=exclude))
        if g["metric"] in ("red_pixel_ratio", "accent_color_ratio"):
            from core.spec.naming import hex_rgb
            color = g.get("color")
            if not color:
                raise ValueError("color gate requires explicit color")
            tables = metrics._mask_tables(hex_rgb(color))
            return metrics.median(metrics.color_pixel_ratios(frames, W, H, tables, inp))
        if g["metric"] == "edge_key_purity":
            # Verify sha256 through the manifest (not trust a stored number): a
            # tampered prepared asset must fail the gate, not sail through it.
            rows = []
            for L in spec["layers"]:
                if L["type"] != "ai":
                    continue
                layer_scoped = manifest.verified("prepared", f"{shot_id}/{L['id']}__layer")
                if layer_scoped is not None:
                    rows.append(layer_scoped.get("purity"))
                else:
                    row = manifest.verified("prepared", f"{shot_id}/{L['asset']}")
                    if row is None:
                        raise RuntimeError(
                            f"prepared asset '{shot_id}/{L['asset']}' not manifest-verified; run S2")
                    rows.append(row.get("purity"))
                for p in L.get("poses") or []:
                    pa = p.get("asset")
                    if not pa or pa == L["asset"]:
                        continue
                    prow = manifest.verified("prepared", f"{shot_id}/{pa}")
                    if prow is None:
                        raise RuntimeError(
                            f"prepared asset '{shot_id}/{pa}' not manifest-verified; run S2")
                    rows.append(prow.get("purity"))
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
            reason = "high_motion" if (g.get("hi") is not None and v > g["hi"]) else "low_motion"
            hint = _video_hint(spec, reason=reason)
            if hint:
                print(hint)

    if spec.get("frame_freeze") is True:
        print("SKIP  freeze     freezedetect         spec allows frozen frames (frame_freeze=true)")
        frozen = []
    else:
        fz = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", mp4, "-vf", "freezedetect=n=0.001:d=0.5", "-f", "null", "-"],
            capture_output=True, text=True
        ).stderr
        frozen = [l for l in fz.splitlines() if "freeze_start" in l]
    print(f"{'FAIL' if frozen else 'PASS'}  freeze     freezedetect         {len(frozen)} frozen segment(s)")
    if frozen:
        # The motion gate's verdict picks the diagnosis. If the frame-to-frame
        # change was too LOW, the footage is the problem; if the motion gate
        # PASSED while the picture stood still, the change was real but never
        # reached the screen (it stayed outside the visible crop).
        motion_failed = any(r["metric"] in ("changed_pixel_ratio", "subject_motion_ratio")
                            and not r["pass"] for r in results)
        hint = _video_hint(spec, reason="low_motion" if motion_failed else "frozen_window")
        if not hint:
            hint = ("\n       -> the picture was IDENTICAL for >= 0.5s and the shot has "
                    "no moving media: give a component a camera move / anim / anim-on-"
                    "pose, or allow frozen frames with \"frame_freeze\": true in the spec.")
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
        # The spec asks for no soundtrack at all. The mp4 carries a compliant
        # silent track so concatenation never has to drop a stream, but
        # measuring that track against the speech/loudness gates would report
        # a failure for exactly the shot the author asked to be silent.
        # Intent comes from the spec (core.audio.shot_is_intentionally_silent),
        # never from the rendered file: a shot that declares voiceover/bgm and
        # comes out silent is BROKEN and must still fail.
        if audio.shot_is_intentionally_silent(spec):
            print("PASS  silence    silent shot          spec declares no soundtrack (exempt)")
        else:
            # 1. Silence and content check
            sil_res = audio.measure_audio_silence(mp4)

            sil_ok = not sil_res["is_silent"]

            # Check whether this shot declared voiceover narration
            has_voice = False
            voice_meta_path = os.path.join(ROOT, ".tmp", f"{shot_id}_audio.aac.meta.json")
            if os.path.exists(voice_meta_path):
                try:
                    with open(voice_meta_path) as mf:
                        has_voice = json.load(mf).get("has_voice", False)
                except Exception:
                    has_voice = False
            elif isinstance(spec.get("audio"), dict) and spec.get("audio", {}).get("voiceover"):
                has_voice = True

            # When a shot has voiceover narration, verify speech band content.
            # A shot with no voiceover (pure BGM / music-only shot) is exempt
            # from speech-band detection — it only needs to be non-silent and in LUFS range.
            if sil_ok and has_voice and not sil_res.get("has_content", True):
                sil_ok = False
                sp_m = sil_res.get("speech_max_volume", -99.0)
                print(f"FAIL  silence    audio_content        no voice/foreground content (speech band max {sp_m:.1f} dB <= -25.0 dB). "
                      f"If this shot should not carry speech, remove the voiceover declaration; the engine does not accept an 'ambient' opt-out.")
            else:
                tag = " (music-only)" if not has_voice else ""
                print(f"{'PASS' if sil_ok else 'FAIL'}  silence    audio_max_volume     {sil_res['max_volume']:.1f} dB  [>-45.0 dB]{tag}")

            red |= not sil_ok
            results.append({
                "id": "audio_silence", "metric": "audio_max_volume",
                "value": sil_res["max_volume"], "lo": -45.0, "pass": sil_ok,
                "has_content": sil_res.get("has_content", True),
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
