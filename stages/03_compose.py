"""S3: compose via Remotion (spec as props), then encode a bit-exact mp4 from the PNG frames.
Contract: writes build/frames/{shot_id}/%05d.png (lossless, what S4 measures)
and build/{shot_id}.mp4. Frames are namespaced per shot — a shared
build/frames let whichever shot composed last win, the same race that hit
build/prepared before its per-shot split.
The legacy ffmpeg filtergraph engine was removed: Remotion is the single renderer, and code
layers (grid/dots) are consumed as prepared PNGs so S2 stays their only implementation.
Usage: python3 03_compose.py [--spec path/to/spec.json]

The implementation lives in core/rendering/ (one module per concern —
timeline math, frame extraction, the render driver, the Quartz fallback, the
encode). This script keeps only main() and the flow; dependency mocks must
target the defining core.rendering submodule, not this script.
"""
import argparse
import os
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core.runtime import manifest
from core.media.fingerprints import encoder_fingerprint, frames_fingerprint
from core.rendering import encode_mp4, render_remotion
from core.rendering.compose import compose_frames
from core.runtime.config import ROOT
from core.spec.loader import load_spec


def main():
    parser = argparse.ArgumentParser(description="S3: Compose layers into frames and mp4")
    parser.add_argument("--spec", default=None, help="Path to spec file (required)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec["id"]
    frames_dir = os.path.join(ROOT, "build", "frames", shot_id)

    n = compose_frames(spec, shot_id, frames_dir, render=render_remotion)

    out_mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    encode_mp4(spec, frames_dir, out_mp4)
    row = manifest.register("video", shot_id, f"build/{shot_id}.mp4", frames=n,
                            frames_sha=frames_fingerprint(frames_dir),
                            encoder=encoder_fingerprint())
    print(f"engine=remotion frames={n} video sha256={row['sha256'][:12]} encoder={row['encoder']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
