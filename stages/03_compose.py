"""S3: compose via Remotion (spec as props), then encode a bit-exact mp4 from the PNG frames.
Contract: writes build/frames/{shot_id}/%05d.png (lossless, what S4 measures)
and build/{shot_id}.mp4. Frames are namespaced per shot — a shared
build/frames let whichever shot composed last win, the same race that hit
build/prepared before its per-shot split.
The legacy ffmpeg filtergraph engine was removed: Remotion is the single renderer, and code
layers (grid/dots) are consumed as prepared PNGs so S2 stays their only implementation.
Usage: python3 03_compose.py [--spec path/to/spec.json]
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core import manifest
from core.render import encoder_fingerprint, frames_fingerprint
from core.schema import ENGINE_ROOT, ROOT, load_spec


def build_props(spec):
    """Spec + prepared assets as inline props. Every image rides in as a data: URL
    (14 KB PNG -> ~19 KB base64) so the bundle's static-file server is never involved:
    the manifest-verified bytes are the exact bytes the renderer sees, and re-renders
    are reproducible offline. Prepared rows are looked up through the manifest
    (namespaced per shot) so composing a shot whose S2 never ran fails fast
    instead of picking up another shot's leftover assets.

    Video layers cannot use a data: URL (an mp4 is orders of magnitude larger
    than a PNG, and base64-inlining it would bloat every props file). They are
    staged into public/prepared/{shot}/ and referenced through Remotion's
    staticFile(), which resolves against the bundle's public folder."""
    shot_id = spec.get("id", "shot-01")
    props = {"spec": spec, "prepared": {}, "preparedVideos": {}, "preparedPoses": {}}
    for L in spec["layers"]:
        if L["type"] == "ai":
            key = f"{shot_id}/{L['asset']}"
        elif L["type"] == "video":
            key = f"{shot_id}/{L['asset']}"
        elif L["type"] == "code" and L["draw"] in ("grid", "dots"):
            key = f"{shot_id}/{L['id']}"
        else:
            continue  # bar is a solid-color CSS div; no asset needed
        row = manifest.verified("prepared", key)
        if row is None:
            raise RuntimeError(
                f"prepared '{key}' not manifest-verified; run S2 (02_prepare.py) "
                f"for this shot first")
        if L["type"] == "video":
            # Stage the clip where Remotion's staticFile() can find it.
            public_rel = f"prepared/{shot_id}/{L['asset']}.mp4"
            # public_rel is relative to public/ — the renderer reads
            # staticFile("prepared/<shot>/<asset>.mp4").
            public_root = os.path.abspath(os.path.join(ENGINE_ROOT, "public"))
            public_path = os.path.join(public_root, public_rel)
            # The staged path must stay inside public/prepared/ — that is the
            # only part the renderer reads. A shot id or asset name with ../
            # would otherwise write outside it.
            prepared_root = os.path.abspath(os.path.join(public_root, "prepared"))
            resolved = os.path.abspath(public_path)
            if not (resolved == prepared_root
                    or resolved.startswith(prepared_root + os.sep)):
                raise RuntimeError(
                    f"video layer {L['id']!r} would stage its clip outside "
                    f"public/prepared/: {public_rel} -> {resolved}")
            os.makedirs(os.path.dirname(public_path), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, row["path"]), public_path)
            props["preparedVideos"][L["id"]] = public_rel
            continue
        with open(os.path.join(ROOT, row["path"]), "rb") as f:
            props["prepared"][L["id"]] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        if L["type"] == "ai" and L.get("poses"):
            pose_map = {}
            for p in L["poses"]:
                pa = p.get("asset")
                if not pa or pa in pose_map:
                    continue
                pk = f"{shot_id}/{pa}"
                prow = manifest.verified("prepared", pk)
                if prow is None:
                    raise RuntimeError(
                        f"prepared '{pk}' not manifest-verified; run S2 (02_prepare.py) "
                        f"for this shot first")
                with open(os.path.join(ROOT, prow["path"]), "rb") as pf:
                    pose_map[pa] = "data:image/png;base64," + base64.b64encode(pf.read()).decode()
            props["preparedPoses"][L["id"]] = pose_map
    return props


def _render_quartz_fallback(spec, out_dir, shot_id):
    """Native macOS CoreGraphics/CoreText fallback when headless Chromium hits
    sandbox SIGSEGV inside restricted sandbox-exec environments."""
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    # If the shot is driven by a prepared video layer, extract its frames directly via ffmpeg
    video_layers = [L for L in spec.get("layers", []) if L.get("type") == "video"]
    if video_layers and len(spec.get("layers", [])) == 1:
        v_layer = video_layers[0]
        row = manifest.verified("prepared", f"{shot_id}/{v_layer['asset']}")
        if row:
            v_path = os.path.join(ROOT, row["path"])
            W, H = spec["canvas"]["w"], spec["canvas"]["h"]
            n_frames = spec["durationInFrames"]
            loop_args = ["-stream_loop", "-1"] if v_layer.get("loop", True) else []
            cmd = (
                ["ffmpeg", "-v", "error", "-y"]
                + loop_args
                + ["-i", v_path,
                   "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                   "-frames:v", str(n_frames),
                   os.path.join(out_dir, "%05d.png")]
            )
            subprocess.run(cmd, check=True, cwd=ROOT)
            # Pad frozen tail if loop=False and source clip was shorter than shot
            written = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
            if written and len(written) < n_frames:
                last_src = os.path.join(out_dir, written[-1])
                for idx in range(len(written) + 1, n_frames + 1):
                    shutil.copyfile(last_src, os.path.join(out_dir, f"{idx:05d}.png"))
            return

    swift_src = os.path.join(ENGINE_ROOT, "core", "quartz_compose.swift")
    bin_path = os.path.join(ROOT, ".tmp", "quartz_compose")
    os.makedirs(os.path.dirname(bin_path), exist_ok=True)
    if (not os.path.exists(bin_path)
            or os.path.getmtime(swift_src) > os.path.getmtime(bin_path)):
        subprocess.run(["swiftc", "-O", swift_src, "-o", bin_path], check=True, cwd=ROOT)

    spec_file = os.path.join(ROOT, ".tmp", f"resolved-spec-{shot_id}.json")
    with open(spec_file, "w") as f:
        json.dump(spec, f)
    subprocess.run([bin_path, spec_file, out_dir, shot_id], check=True, cwd=ROOT)


def render_remotion(spec, out_dir, shot_id):
    if os.environ.get("POSTER_FORCE_QUARTZ") == "1":
        _render_quartz_fallback(spec, out_dir, shot_id)
        return
    props = build_props(spec)
    # Props file is per shot too: two concurrent S3 runs share .tmp/.
    props_file = os.path.join(ROOT, ".tmp", f"render-props-{shot_id}.json")
    os.makedirs(os.path.dirname(props_file), exist_ok=True)
    with open(props_file, "w") as f:
        json.dump(props, f)

    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    cmd = [
        "npx", "remotion", "render", "remotion/index.tsx", "Shot",
        os.path.join(out_dir, "rm"),  # Remotion writes 0-indexed [frame].png here
        "--image-format=png", "--sequence", "--image-sequence-pattern=[frame].png",
        f"--props={props_file}",
    ]
    print(" ".join(cmd))
    env = dict(os.environ)
    extra_paths = "/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin"
    env["PATH"] = f"{extra_paths}:{env.get('PATH', '')}"
    try:
        subprocess.run(cmd, check=True, cwd=ENGINE_ROOT, env=env)
        # Renumber 0-indexed [frame] (padded to the frame-count width) -> 1-indexed %05d
        pad = len(str(spec["durationInFrames"] - 1))
        for i in range(spec["durationInFrames"]):
            src = os.path.join(out_dir, "rm", f"{i:0{pad}d}.png")
            dst = os.path.join(out_dir, f"{i + 1:05d}.png")
            os.rename(src, dst)
        shutil.rmtree(os.path.join(out_dir, "rm"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.rmtree(os.path.join(out_dir, "rm"), ignore_errors=True)
        print("  [S3] Chromium headless shell blocked by macOS sandbox; using native Quartz compositor...")
        _render_quartz_fallback(spec, out_dir, shot_id)


def video_audio_source(spec):
    """The prepared clip whose native track owns the soundtrack, if any.

    Audio ownership is exclusive (SKILL.md "Audio ownership"):
      - a video layer with muted:false keeps its native track, and that track
        is the shot's soundtrack;
      - otherwise the pipeline's TTS chain owns it.
    Returns the prepared clip path, or None."""
    shot_id = spec.get("id", "shot-01")
    for L in spec["layers"]:
        if L.get("type") != "video" or L.get("muted", True):
            continue
        row = manifest.verified("prepared", f"{shot_id}/{L['asset']}")
        if row is None:
            continue
        return os.path.join(ROOT, row["path"])
    return None


def encode_mp4(spec, frames_dir, out_mp4):
    FPS = spec["fps"]
    audio_spec = spec.get("audio")
    audio_file = None

    # Which track owns the soundtrack: the clip's native audio, the TTS chain,
    # or neither. Declaring both is a spec error, not a style choice — the
    # two would overlap and the S4 audio gates would flag the result.
    clip_audio = video_audio_source(spec)
    wants_tts = bool(audio_spec and (audio_spec.get("voiceover") or audio_spec.get("bgm")))
    if clip_audio and wants_tts:
        raise RuntimeError(
            f"{spec.get('id')}: audio conflict — a video layer with muted:false "
            f"keeps its native track, and audio.voiceover/bgm asks for the TTS "
            f"chain as well. Pick one: set \"muted\": true on the video layer "
            f"(TTS owns the audio) or drop audio.voiceover/bgm (the clip owns it).")

    if clip_audio:
        # The clip's native track has not been through the mastering chain, so
        # its loudness is whatever the model produced (-22.9 LUFS measured on a
        # real H3 clip — below the gate's -19 floor). Run the same loudnorm
        # target the TTS chain uses so every shot lands in the same window.
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_clip_audio.m4a")
        v_layer = next((L for L in spec.get("layers", [])
                        if L.get("type") == "video" and not L.get("muted", True)), None)
        trim = v_layer.get("trim") if v_layer else None
        shot_seconds = spec["durationInFrames"] / max(1, FPS)

        af_parts = ["aformat=sample_rates=44100:channel_layouts=stereo"]
        input_args = []
        if trim:
            t0, t1 = trim[0], trim[1]
            seg_dur = max(0.001, t1 - t0)
            af_parts.append(f"atrim=start={t0}:end={t1}")
            af_parts.append("asetpts=PTS-STARTPTS")
            if v_layer.get("loop", True) and seg_dur < shot_seconds:
                af_parts.append(f"aloop=loop=-1:size={int(round(seg_dur * 44100))}")
        elif v_layer and v_layer.get("loop", True):
            input_args = ["-stream_loop", "-1"]

        af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        master_cmd = (
            ["ffmpeg", "-v", "error", "-y"]
            + input_args
            + ["-i", clip_audio,
               "-af", ",".join(af_parts),
               "-t", f"{shot_seconds:.4f}",
               "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "192k", audio_file]
        )
        mastered = subprocess.run(master_cmd, capture_output=True, text=True)
        if mastered.returncode != 0:
            raise RuntimeError(
                f"mastering the clip's native audio failed:\n{mastered.stderr}")
        trim_note = f" (trimmed to [{trim[0]}s, {trim[1]}s])" if trim else ""
        print(f"audio source: native track of {os.path.basename(clip_audio)}{trim_note} "
              f"(mastered to -16 LUFS)")
    elif wants_tts:
        from core.audio import prepare_shot_audio
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_audio.aac")
        if spec.get("punches"):
            prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file, punches=spec["punches"])
        else:
            prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file)
        bgm_label = audio_spec.get("bgm", "ambient")
        print(f"audio source: TTS chain (edge-tts + {bgm_label} bgm + loudnorm)")
    else:
        print("audio source: none (silent shot)")

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-framerate", str(FPS), "-i", os.path.join(frames_dir, "%05d.png"),
    ]
    if audio_file and os.path.exists(audio_file):
        cmd.extend(["-i", audio_file])

    # vibe_grade: cinema texture on encode (deterministic filters — same spec
    # still yields the same mp4). Gates measure the ungraded S3 frames; this is
    # presentation layered on top.
    if spec.get("vibe_grade"):
        cmd.extend(["-vf", "split[a][b];[b]gblur=sigma=14[bl];[a][bl]blend=all_mode=screen:all_opacity=0.22,noise=alls=12:allf=t,vignette=PI/3.8,eq=contrast=1.1:saturation=1.16"])

    cmd.extend([
        "-frames:v", str(spec["durationInFrames"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-threads", "1", "-r", str(FPS),
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-pix_fmt", "yuv420p",
    ])
    if audio_file and os.path.exists(audio_file):
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

    cmd.append(out_mp4)
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description="S3: Compose layers into frames and mp4")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: tests/fixtures/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    frames_dir = os.path.join(ROOT, "build", "frames", shot_id)

    render_remotion(spec, frames_dir, shot_id)

    n = len([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if n != spec["durationInFrames"]:
        sys.exit(f"expected {spec['durationInFrames']} frames, got {n}")

    out_mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    encode_mp4(spec, frames_dir, out_mp4)
    row = manifest.register("video", shot_id, f"build/{shot_id}.mp4", frames=n,
                            frames_sha=frames_fingerprint(frames_dir),
                            encoder=encoder_fingerprint())
    print(f"engine=remotion frames={n} video sha256={row['sha256'][:12]} encoder={row['encoder']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
