"""S3: build and run ONE ffmpeg command from the spec. No pixel code here.
Output: build/frames/%05d.png (lossless, what S4 measures) and build/{shot_id}.mp4, from the same filter graph.
Usage: python3 03_compose.py [--spec path/to/spec.json]
"""
import argparse
import os
import shutil
import subprocess
import sys

from lib import manifest
from schema import ROOT, load_spec


def main():
    parser = argparse.ArgumentParser(description="S3: Compose layers into frames and mp4")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    W, H, FPS, N = spec["canvas"]["w"], spec["canvas"]["h"], spec["fps"], spec["durationInFrames"]
    layers = sorted(spec["layers"], key=lambda L: L["z"])
    B = lambda p: os.path.join(ROOT, p)

    inputs, chains = [], []
    cur = None
    for idx, L in enumerate(layers):
        m = L.get("motion") or {}
        if L["type"] == "code" and L["draw"] == "grid":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", B(f"build/prepared/{L['id']}.png")]
            chains.append(f"[{idx}]scale={W}:{H},setsar=1[l{idx}]")
            if cur is not None:
                sys.exit("a full-frame code layer must be the bottom layer")
            cur = f"l{idx}"
        elif L["type"] == "ai":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", B(f"build/prepared/{L['asset']}.png")]
            z0, z1 = m.get("zoom", [1.0, 1.0])
            chains.append(
                f"[{idx}]zoompan=z='{z0}+({z1}-{z0})*on/{N - 1}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={N}:s={W}x{H}:fps={FPS},setsar=1[l{idx}]")
            chains.append(f"[{cur}][l{idx}]blend=all_mode={L['blend']}:all_opacity=1[m{idx}]")
            cur = f"m{idx}"
        elif L["type"] == "code" and L["draw"] == "bar":
            x, y, w, h = L["rect"]
            pan = m.get("pan")
            if pan:
                x0, x1 = pan
            else:
                x0 = x1 = x
            c = L["color"].replace("#", "0x")
            inputs += ["-f", "lavfi", "-i", f"color=c={c}:s={w}x{h}:r={FPS}"]
            chains.append(f"[{cur}][{idx}]overlay=x='{x0}+({x1}-{x0})*n/{N - 1}':y='{y}':shortest=1[m{idx}]")
            cur = f"m{idx}"

    graph = ";".join(chains) + f";[{cur}]format=rgb24,split[a][b];[b]format=yuv420p[c]"
    shutil.rmtree(B("build/frames"), ignore_errors=True)
    os.makedirs(B("build/frames"))
    out_mp4 = B(f"build/{shot_id}.mp4")

    cmd = [
        "ffmpeg", "-v", "error", "-y", *inputs,
        "-filter_complex", graph,
        "-map", "[a]", "-frames:v", str(N), "-start_number", "1", B("build/frames/%05d.png"),
        "-map", "[c]", "-frames:v", str(N), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-threads", "1", "-r", str(FPS),
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        out_mp4
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    n = len(os.listdir(B("build/frames")))
    if n != N:
        sys.exit(f"expected {N} frames, got {n}")
    row = manifest.register("video", None, f"build/{shot_id}.mp4", frames=n)
    print(f"frames={n} video sha256={row['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
