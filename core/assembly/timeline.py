"""Timeline assembly: the domain logic behind `pipeline.py concat` and `run --timeline`.

The CLI lives in `pipeline.py` — argparse, the stage subprocesses, the exit
codes. What lives here is the part that does not care about the command line:

* `missing_assets`        the assets a spec needs that are not frozen yet
* `referenced_assets`     every asset name a spec points at
* `spec_references_asset` whether a spec points at one asset
* `extract_frame_asset`   freeze one frame of a clip as a manifest asset
* `load_timeline`         load and validate a timeline file
* `concat_stream_problem` why a set of clips cannot be concatenated
* `gate_full_video`       post-assembly QC on the concatenated film

No CLI semantics here: no argparse, no sys.exit. A precondition that used to
end the process now raises `AssemblyError`; `pipeline.py` turns it into the
exit the author sees.
"""
import json
import os
import subprocess

from core.runtime.config import ROOT


class AssemblyError(Exception):
    """A precondition failed — a missing or invalid timeline.

    Raised instead of exiting so this module carries no CLI semantics;
    `pipeline.py` turns it into `sys.exit(str(ex))`.
    """


def missing_assets(spec):
    """The assets a spec needs that are not frozen in the manifest yet.

    A shot's ai / video layers name their assets; the manifest records the
    frozen ones. Anything missing would have to be GENERATED — which costs a
    model call — so the caller must know before it happens, not after."""
    from core.runtime import manifest
    missing = []
    for layer in spec.get("layers", []):
        if layer.get("type") not in ("ai", "video"):
            continue
        assets = [layer.get("asset")]
        if layer.get("type") == "ai":
            for p in layer.get("poses") or []:
                pa = p.get("asset")
                if pa and pa not in assets:
                    assets.append(pa)
        for asset in assets:
            if not asset:
                continue
            if manifest.verified("assets", asset) is None and asset not in missing:
                missing.append(asset)
    return missing


def referenced_assets(spec):
    """Every asset name the spec points at.

    The reference can sit under several keys — a video layer's first_frame /
    last_frame / input_asset / input_image, an ai layer's input_asset, a
    reference_images list — and a seam is usually named after the shot
    before it.
    """
    names = []
    for layer in spec.get("layers", []):
        for key in ("first_frame", "last_frame", "input_asset", "input_image"):
            v = layer.get(key)
            if isinstance(v, str) and v and v not in names:
                names.append(v)
        for key in ("reference_images", "reference_assets"):
            vals = layer.get(key) or []
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, str) and v and v not in names:
                        names.append(v)
    return names


def spec_references_asset(spec, name):
    """True when any layer of `spec` points at the asset `name`."""
    return name in referenced_assets(spec)


def extract_frame_asset(src, name, at="last"):
    """Freeze one frame of `src` as a manifest asset called `name`.

    This is the cross-shot seam: shot k's tail becomes a frozen asset that
    shot k+1 names as its first_frame. It is registered like any other
    asset, so the manifest stays the single authority on what exists.
    """
    from core.runtime import manifest
    rel_asset = f"assets/{name}.png"
    out_path = os.path.join(ROOT, rel_asset)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if at == "last":
        seek = ["-sseof", "-0.05"]
    elif at == "first":
        seek = []
    else:
        try:
            float(at)
        except ValueError:
            raise ValueError(
                f"--at must be 'last', 'first', or a number of seconds (got {at!r})")
        seek = ["-ss", at]
    cmd = (["ffmpeg", "-v", "error", "-y"] + seek + ["-i", src]
           + ["-frames:v", "1", "-update", "1", out_path])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Frame extraction failed (ffmpeg exit {proc.returncode}):\n"
            f"{proc.stderr.strip()}")
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"Frame extraction produced no file: {out_path}")
    row = manifest.register("assets", name, rel_asset, source="extracted",
                            origin=os.path.relpath(src, ROOT), frame_at=at)
    return row


def load_timeline(rel_path, create_default=False):
    """Load and validate a timeline file; returns the parsed timeline.

    Shared by `concat` and `run --timeline` so both refuse the same broken
    timeline in the same words.
    """
    from core.spec import validate_timeline
    path = os.path.join(ROOT, rel_path)
    if not os.path.exists(path):
        if not create_default:
            raise AssemblyError(f"Timeline not found: {path}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"id": "full-sequence",
                       "shots": ["tests/fixtures/shot-01.poster.json"]}, f, indent=2)
        print(f"Created default timeline at: {path}")
    with open(path) as f:
        tl = json.load(f)
    errs = validate_timeline(tl)
    if errs:
        raise AssemblyError("Timeline validation failed:\n  " + "\n  ".join(errs))
    return tl


def concat_stream_problem(clips):
    """Describe why these clips cannot be concatenated, or None if they can.

    The concat demuxer with `-c copy` is sensitive to the inputs' stream
    configuration: mixing a shot with an audio track and one without makes
    it drop the audio of every shot that had one — with a zero exit code
    and no warning. Native video models that render their own audio track
    and the TTS chain produce different audio streams, so a timeline
    that mixes them is a normal thing for an author to write.

    Returns a readable message naming the shots involved, or None when the
    clips agree."""
    import json as _json
    import subprocess as _subprocess

    if len(clips) < 2:
        return None
    with_audio, without_audio = [], []
    for shot_id, path in clips:
        res = _subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", path], capture_output=True, text=True)
        try:
            streams = _json.loads(res.stdout).get("streams", [])
        except Exception:
            streams = []
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        (with_audio if has_audio else without_audio).append(shot_id)
    if with_audio and without_audio:
        return (f"the shots disagree on audio: {', '.join(with_audio)} carry an "
                f"audio track, {', '.join(without_audio)} do not. Concatenating "
                f"them would silently drop every audio track. Give each shot the "
                f"same audio source — a video layer with \"muted\": false and "
                f"audio.voiceover (or vice versa) — before assembling.")
    return None


def gate_full_video(out_path, timeline_id, segments):
    """Post-assembly QC on the concatenated full video.

    Per-shot gates (S4) already ran before stitching; this catches what only
    exists after shots are joined: total duration vs the timeline, black
    frames, whole-track silence/loudness, A/V alignment, and loudness jumps
    across cut boundaries (each shot is loudnorm'd independently — two in-band
    shots can still pop at the seam). Writes build/gates_full_{timeline}.json
    (namespaced per timeline, unlike the shared per-shot gates.json)."""
    from core import audio

    results, red = [], False

    def add(gid, metric, value, ok, bound):
        nonlocal red
        red |= not ok
        results.append({"id": gid, "metric": metric, "value": value, "bound": bound, "pass": ok})
        print(f"{'PASS' if ok else 'FAIL'}  {gid:<14} {metric:<22} {value}  [{bound}]")

    # 1. Total duration matches the timeline's declared shot durations.
    expected = sum(d for _, _, d in segments)
    av = audio.measure_av_durations(out_path)
    delta = abs(av["video_duration"] - expected)
    add("duration", "timeline_duration_delta", round(delta, 3), delta <= 0.25, "<= 0.250 s")

    # 2. True digital-black frames (concat fill around missing frames). The dark
    #    space canvas (#06080F, luma ~8) stays above pixel_black_th=0.02 (~5).
    bd = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", out_path,
         "-vf", "blackdetect=d=0.2:picture_black_ratio_th=0.98:pixel_black_th=0.02",
         "-f", "null", "-"],
        capture_output=True, text=True).stderr
    n_black = bd.count("black_start")
    add("black", "blackdetect", n_black, n_black == 0, "0 intervals")

    if av.get("has_audio"):
        # A timeline can mix silent shots (no soundtrack by design) with
        # shots that carry sound. The silent ones are not "too quiet" — they
        # are silent on purpose — so they must not eat the loudness budget,
        # and a wholly silent film is not a failed film.
        seg_lufs = []
        for shot_id, start, dur in segments:
            seg_sil = audio.measure_audio_silence(out_path, start=start, duration=dur)
            seg_lufs.append((
                shot_id,
                audio.measure_audio_loudness(out_path, start=start, duration=dur),
                seg_sil["is_silent"],
            ))
        # A silent shot (no soundtrack by design) does NOT read as a very
        # quiet LUFS window: EBU R128's absolute gate sits at -70, so an
        # all-silent window integrates to something in the middle (-29
        # measured) and would blow the jump budget wide open. Judge silence
        # by the segment's PEAK volume, which is unambiguous.
        audible = [l for _, l, silent in seg_lufs if l is not None and not silent]

        if not audible:
            print("PASS  silence    silent shot          every segment is intentionally silent (exempt)")
        else:
            sil = audio.measure_audio_silence(out_path)
            add("audio_silence", "audio_max_volume", round(sil["max_volume"], 1),
                not sil["is_silent"], "> -45.0 dB")

            lufs = audio.measure_audio_loudness(out_path)
            if lufs is not None:
                add("audio_loudness", "integrated_loudness", round(lufs, 1),
                    -19.0 <= lufs <= -13.0, "-19.0 .. -13.0 LUFS")

        add("av_sync", "duration_delta", round(av["delta"], 3), av["delta"] <= 0.25, "<= 0.250 s")

        # 3. Per-shot loudness at each timeline segment: max pairwise delta.
        if len(audible) >= 2:
            jump = max(audible) - min(audible)
            add("loudness_jump", "max_pairwise_delta", round(jump, 1), jump <= 3.0, "<= 3.0 LU")
        elif audible:
            print("SKIP  loudness_jump (fewer than two audible segments)")
        else:
            print("SKIP  loudness_jump (no audible segment)")
    else:
        print("SKIP  audio gates (assembled video has no audio track)")

    gates_out = os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")
    with open(gates_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"full-video gates -> {gates_out}")
    return 1 if red else 0

