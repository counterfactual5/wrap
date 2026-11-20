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
import math
import os
import struct
import subprocess

from core.runtime.config import ROOT
from core.spec.naming import valid_name
from core.runtime.timeouts import (
    EXTRACT_FRAME_TIMEOUT,
    LOCAL_TOOL_TIMEOUT,
    PROBE_TIMEOUT,
)


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
    # The name becomes a path (assets/<name>.png) and a manifest key. A
    # name carrying "../" would write outside the assets directory, so it
    # must be a plain identifier — the same rule the shot id follows
    # (core/spec/naming.py).
    if not valid_name(name):
        raise ValueError(
            f"asset name must be a letters/digits/._- string starting with a "
            f"letter or digit (got {name!r}); it becomes assets/{name}.png "
            f"and must not be able to walk out of the assets directory")
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
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=EXTRACT_FRAME_TIMEOUT)
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
    clips agree.

    A clip that cannot be probed is NOT a clip without audio: the probe
    failed, so the audio configuration is unknown, and the concat demuxer
    would drop every track with a zero exit code. A failed probe is
    therefore reported as a problem, never as an absent track."""
    import json as _json
    import subprocess as _subprocess

    if len(clips) < 2:
        return None
    with_audio, without_audio, unprobeable = [], [], []
    for shot_id, path in clips:
        res = _subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", path], capture_output=True, text=True,
            timeout=PROBE_TIMEOUT)
        if res.returncode != 0:
            unprobeable.append((shot_id, (res.stderr or "").strip()
                                or f"ffprobe exited {res.returncode}"))
            continue
        try:
            streams = _json.loads(res.stdout).get("streams", [])
        except Exception as ex:
            unprobeable.append((shot_id, f"ffprobe output is not JSON ({ex})"))
            continue
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        (with_audio if has_audio else without_audio).append(shot_id)
    if unprobeable:
        names = ", ".join(sid for sid, _ in unprobeable)
        why = "; ".join(f"{sid}: {reason}" for sid, reason in unprobeable)
        return (f"the audio configuration of {names} could not be probed, so "
                f"this timeline's audio streams are UNKNOWN — refusing to "
                f"concatenate on an unmeasured guess. The concat demuxer "
                f"drops every audio track when the inputs disagree, with a "
                f"zero exit code and no warning, and a failed probe looks "
                f"exactly like a shot without audio. Probe failures: {why}")
    if with_audio and without_audio:
        return (f"the shots disagree on audio: {', '.join(with_audio)} carry an "
                f"audio track, {', '.join(without_audio)} do not. Concatenating "
                f"them would silently drop every audio track. Give each shot the "
                f"same audio source — a video layer with \"muted\": false and "
                f"audio.voiceover (or vice versa) — before assembling.")
    return None


def _measurement_available(av):
    """Whether the AV probe measured the file at all.

    `core.audio.metrics.measure_av_durations` reports the probe's success
    as `measurement_ok` — the same key `measure_audio_silence` already
    returns. When that key is absent, the only evidence left is the
    measurement itself: a probed file always has a positive video
    duration, so all-zero durations mean the probe measured nothing and
    every derived number (delta, has_audio) is a placeholder.

    The distinction matters: "the file has no audio track" (measured) may
    skip the audio gates, "the probe failed" (unmeasured) must not."""
    ok = av.get("measurement_ok")
    if ok is not None:
        return bool(ok)
    return (float(av.get("video_duration") or 0) > 0
            or float(av.get("audio_duration") or 0) > 0)


def _black_spans(blackdetect_stderr):
    """Parse blackdetect's stderr into the spans it reported.

    blackdetect prints `black_start:... black_end:... black_duration:...` per
    run. The gate needs the runs' positions and lengths, not just their
    count: a three-frame hole at the cut and a one-second black frame at the
    end are different defects, and only the positions let the audio side
    check whether the soundtrack was still playing underneath.
    """
    spans = []
    start = end = dur = None
    for line in blackdetect_stderr.splitlines():
        # blackdetect prints start, end and duration on ONE line, so these are
        # independent tests, not an elif chain.
        if "black_start:" in line:
            try:
                start = float(line.split("black_start:")[1].split()[0])
            except (IndexError, ValueError):
                start = None
        if "black_end:" in line and start is not None:
            try:
                end = float(line.split("black_end:")[1].split()[0])
            except (IndexError, ValueError):
                end = None
        if "black_duration:" in line and start is not None:
            try:
                dur = float(line.split("black_duration:")[1].split()[0])
            except (IndexError, ValueError):
                dur = None
            if end is not None:
                spans.append({"start": start, "end": end,
                              "duration": dur if dur is not None else end - start})
                start = end = dur = None
    return spans


def _window_rms_db(out_path, start, duration):
    """Mean volume in dBFS over a window, or None when it cannot be read.

    Used for very short windows (a black dip is a few frames), where an
    integrated loudness measurement is not trustworthy.
    """
    proc = subprocess.run(
        # volumedetect reports at the INFO level, so the log level must stay
        # at default (-v error would swallow the very number we come for).
        ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}",
         "-t", f"{duration:.3f}", "-i", out_path, "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=LOCAL_TOOL_TIMEOUT)
    for line in proc.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def _pcm_rms_db(samples, start_idx, end_idx):
    """RMS level in dBFS over `samples[start_idx:end_idx]`, or None if empty."""
    cnt = end_idx - start_idx
    if cnt <= 0:
        return None
    sq = sum(s * s for s in samples[start_idx:end_idx])
    rms = math.sqrt(sq / cnt) / 32768.0
    if rms <= 1e-12:
        return -96.0
    return 20.0 * math.log10(rms)


def _seam_audio_hole_detail(out_path, cut_at, seg_start, next_end):
    """Probe a single cut boundary `[cut_at - 1.0, cut_at + 1.1]` in one decode.

    Detects dip-and-recover holes whether they sit immediately BEFORE the cut
    (e.g. a clip track ending early), ACROSS the cut, or immediately AFTER
    the cut — while remaining insensitive to normal <= 80ms cross-shot fades.
    Returns a formatted summary string when a hole is found, or None.

    The level is read in SHORT windows (20 ms, 10 ms step), because a long
    window averages a short hole away. Measured on a real cut: a 90 ms / 16 dB
    dip at the cut moved a 250 ms window's RMS by only 1.9 dB, so the gate
    wrote "no hole" over a hole a reviewer could hear. A hole is now:
      - deeper than 6 dB below the level before the cut,
      - recovered to within 3 dB of the level after the cut (a fade that
        stays down is not a hole),
      - present for at least 40 ms (one noisy window is not a hole), and
      - not the shape of a cross-shot fade: a dip that straddles the cut and
        is no longer than 200 ms is normal audio shaping, not a defect.
    """
    win_start = max(seg_start, cut_at - 1.0)
    win_end = min(next_end, cut_at + 1.1)
    win_dur = win_end - win_start
    if win_dur < 0.8:
        return None

    sr = 16000
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error",
         "-ss", f"{win_start:.3f}", "-t", f"{win_dur:.3f}",
         "-i", out_path, "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "s16le", "-"],
        capture_output=True, timeout=LOCAL_TOOL_TIMEOUT)
    if proc.returncode != 0 or len(proc.stdout) < int(0.4 * sr) * 2:
        return None

    n_samples = len(proc.stdout) // 2
    samples = struct.unpack(f"<{n_samples}h", proc.stdout[:n_samples * 2])
    cut_idx = int(round((cut_at - win_start) * sr))

    pre_end = max(0, cut_idx - int(0.50 * sr))
    post_start = min(n_samples, cut_idx + int(0.60 * sr))
    min_shoulder = int(0.15 * sr)
    if pre_end < min_shoulder or (n_samples - post_start) < min_shoulder:
        return None

    far_pre = _pcm_rms_db(samples, 0, pre_end)
    far_post = _pcm_rms_db(samples, post_start, n_samples)
    if far_pre is None or far_post is None:
        return None

    # Short windows: a hole is a short event, and averaging it away is what
    # made this gate blind to it.
    bin_n = int(0.020 * sr)
    step_n = int(0.010 * sr)
    near_a = max(0, cut_idx - int(0.45 * sr))
    near_b = min(n_samples, cut_idx + int(0.45 * sr))
    if near_b - near_a < bin_n:
        return None

    slots = []
    pos = near_a
    while pos + bin_n <= near_b:
        v = _pcm_rms_db(samples, pos, pos + bin_n)
        if v is not None:
            slots.append((pos, v))
        pos += step_n
    if not slots:
        return None

    min_pos, min_near = min(slots, key=lambda s: s[1])
    if far_pre - min_near < 6.0:
        return None
    if far_post - min_near < 3.0:
        # The level stays down: a fade, not a hole.
        return None

    # How long the level stays under the pre-cut level: the run of short
    # windows around the minimum that sit 6 dB below the level before the cut.
    threshold = far_pre - 6.0
    below = [i for i, (_, v) in enumerate(slots) if v < threshold]
    if not below:
        return None
    centre = min(range(len(slots)), key=lambda i: slots[i][1])
    if centre not in below:
        return None
    lo = hi = centre
    while lo - 1 in below:
        lo -= 1
    while hi + 1 in below:
        hi += 1
    dip_start = win_start + slots[lo][0] / sr
    dip_end = win_start + (slots[hi][0] + bin_n) / sr
    if dip_end - dip_start < 0.040:
        # A single noisy window is not a hole.
        return None
    # The shape of a cross-shot fade: the level is already down on BOTH sides
    # of the cut. A hole sits on one side (the clip's own audio died there),
    # so it is reported even when it is short.
    pre_level = _pcm_rms_db(samples, max(0, cut_idx - int(0.020 * sr)), cut_idx)
    post_level = _pcm_rms_db(samples, cut_idx, min(n_samples, cut_idx + int(0.020 * sr)))
    if pre_level is not None and post_level is not None \
            and pre_level < threshold and post_level < threshold \
            and dip_end - dip_start <= 0.20:
        return None
    return f"{cut_at:.3f}s ({far_pre:.1f}->{min_near:.1f}->{far_post:.1f} dBFS, " \
           f"{dip_start:.3f}s-{dip_end:.3f}s)"


def gate_full_video(out_path, timeline_id, segments, allow_black=False):
    """Post-assembly QC on the concatenated full video.

    Per-shot gates (S4) already ran before stitching; this catches what only
    exists after shots are joined: total duration vs the timeline, black
    frames, whole-track silence/loudness, A/V alignment, and loudness jumps
    across cut boundaries (each shot is loudnorm'd independently — two in-band
    shots can still pop at the seam). Writes build/gates_full_{timeline}.json
    (namespaced per timeline, unlike the shared per-shot gates.json).
    `allow_black` skips the black-frame check for an intentionally dark film;
    the caller decides — the timeline file is the only thing that can say so."""
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
    measured = _measurement_available(av)
    if not measured:
        # The probe failed: every duration below is a zero, not a
        # measurement. A zero delta against a zero expectation would read
        # as a PASS, so "nothing was measured" has to be a FAIL of its own.
        why = av.get("error") or "the probe measured nothing"
        add("av_probe", "ffprobe_streams", why, False, "probe must succeed")
    if not segments:
        # Nothing was declared, so nothing can be compared: the duration
        # gate below would measure the file against 0 s and call it a pass.
        add("segments", "timeline_segments", 0, False, ">= 1 segment")
    delta = abs(av["video_duration"] - expected)
    add("duration", "timeline_duration_delta", round(delta, 3),
        measured and delta <= 0.25, "<= 0.250 s")

    if allow_black:
        print("SKIP  black          blackdetect         timeline allows black (allow_black=true)")
    else:
        # 2. True digital-black frames (concat fill around missing frames).
        # `d` is the SHORTEST run blackdetect reports: at d=0.2 a three-frame
        # dip (0.1 s at 30 fps) was invisible, and the gate then wrote
        # "0 intervals, pass" over a real 100 ms hole in the picture. 0.05 s
        # catches a two-frame dip, which is the smallest a viewer can see.
        bd = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", out_path,
             "-vf", "blackdetect=d=0.05:picture_black_ratio_th=0.98:pixel_black_th=0.02",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=LOCAL_TOOL_TIMEOUT).stderr
        black_spans = _black_spans(bd)
        n_black = len(black_spans)
        shortest = min((s["duration"] for s in black_spans), default=0.0)
        add("black", "blackdetect", n_black, n_black == 0, "0 intervals")
        if n_black:
            print(f"      black runs: " + ", ".join(
                f"{s['start']:.3f}s-{s['end']:.3f}s ({s['duration']:.3f}s)" for s in black_spans))
        # A black picture with sound still playing is the case that matters:
        # the viewer sees a hole while the soundtrack keeps going. It is also
        # what the old duration threshold could not see.
        if n_black and av.get("has_audio"):
            silent_holes = []
            for s in black_spans:
                # A short window's INTEGRATED loudness is unreliable (the
                # measurement needs a gating block), so the level under the
                # hole is read as a plain RMS instead.
                lvl = _window_rms_db(
                    out_path, max(0.0, s["start"]), max(0.05, s["duration"]))
                if lvl is not None and lvl > -60.0:
                    silent_holes.append((s, lvl))
            if silent_holes:
                add("black_with_sound", "blackdetect+audio_loudness",
                    "; ".join(f"{s['start']:.3f}s ({lvl:.1f} dBFS)" for s, lvl in silent_holes),
                    False, "no black frame while the soundtrack plays")
            else:
                add("black_with_sound", "blackdetect+audio_loudness", 0, True,
                    "no black frame while the soundtrack plays")

    # A cut whose audio DIPS (before, across, or right after the cut) and then
    # comes back is a hole, not a fade: the picture shows a gap while the
    # soundtrack keeps playing. A deliberate fade-out does not recover, so the
    # recovery is what tells the two apart.
    if av.get("has_audio") and len(segments) > 1:
        holes = []
        for i in range(len(segments) - 1):
            _, s0, d0 = segments[i]
            _, s1, d1 = segments[i + 1]
            cut_at = s0 + d0
            hole = _seam_audio_hole_detail(out_path, cut_at, s0, s1 + d1)
            if hole:
                holes.append(hole)
        add("seam_audio_hole", "seam_level_dip_and_recover", len(holes),
            not holes, "no dip-and-recover at a cut")
        if holes:
            for h in holes:
                print(f"      audio hole at the cut: {h}")

    if not measured:
        # The file may well carry a soundtrack — the probe could not say.
        # Skipping the audio gates here would be "did not check" dressed up
        # as "nothing to check", so the unverifiable state is a FAIL.
        why = av.get("error") or "the probe measured nothing"
        add("audio_presence", "audio_track_probe", why, False, "probe must succeed")
    elif av.get("has_audio"):
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
        print("SKIP  audio gates (assembled video has no audio track — measured)")

    gates_out = os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")
    with open(gates_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"full-video gates -> {gates_out}")
    return 1 if red else 0

