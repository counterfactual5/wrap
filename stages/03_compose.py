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
from core.schema import ROOT, load_spec


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
    props = {"spec": spec, "prepared": {}, "preparedVideos": {}}
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
            public_path = os.path.join(ROOT, "public", public_rel)
            os.makedirs(os.path.dirname(public_path), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, row["path"]), public_path)
            props["preparedVideos"][L["id"]] = public_rel
            continue
        with open(os.path.join(ROOT, row["path"]), "rb") as f:
            props["prepared"][L["id"]] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    return props


def render_remotion(spec, out_dir, shot_id):
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
    subprocess.run(cmd, check=True, cwd=ROOT)

    # Renumber 0-indexed [frame] (padded to the frame-count width) -> 1-indexed %05d
    pad = len(str(spec["durationInFrames"] - 1))
    for i in range(spec["durationInFrames"]):
        src = os.path.join(out_dir, "rm", f"{i:0{pad}d}.png")
        dst = os.path.join(out_dir, f"{i + 1:05d}.png")
        os.rename(src, dst)
    shutil.rmtree(os.path.join(out_dir, "rm"))


def encode_mp4(spec, frames_dir, out_mp4):
    FPS = spec["fps"]
    audio_spec = spec.get("audio")
    audio_file = None
    if audio_spec and (audio_spec.get("voiceover") or audio_spec.get("bgm")):
        from core.audio import prepare_shot_audio
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_audio.aac")
        prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file)

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
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
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
