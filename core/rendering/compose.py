"""S3's render orchestration: render the shot, normalize the sequence, and
prove the frames carry the picture the spec promised.

The renderer can leave a video layer empty on a few frames (core.rendering.
holes). Those frames reach the encoder as transparent gaps and become black
holes in the film, so the shot is re-rendered while the guard still finds
them. The guard never lowers its bar to let a shot through: a shot that still
has holes after the last attempt fails here, before anything is encoded.

The renderer is a parameter so this flow can be exercised without a browser
and without a bill: a caller passes the function that draws the frames.
"""
import os
import sys

from core.rendering.frames import normalize_frame_formats
from core.rendering.holes import RENDER_ATTEMPTS, find_holes, format_holes
from core.rendering.remotion import render_remotion


def compose_frames(spec, shot_id, frames_dir, render=None):
    """Render the shot's frames and return how many frames it produced.

    Raises SystemExit when the frame count is wrong, and when the renderer
    keeps leaving holes: a shot with holes is never encoded.
    """
    render = render or render_remotion
    fps = spec.get("fps", 30)
    holes = []
    for attempt in range(1, RENDER_ATTEMPTS + 1):
        render(spec, frames_dir, shot_id)

        # One pixel format for the whole sequence. Remotion writes RGBA only
        # for the frames that carry transparency and RGB for the rest; a mixed
        # sequence changes the decoded frame format mid-stream, ffmpeg
        # reconfigures the filter graph, and the encoder loses frames at
        # positions that differ from run to run (measured: five encodes of the
        # same 360 frames each lost different ones). The pixels do not change.
        norm = normalize_frame_formats(frames_dir, fps)
        if norm["normalized"]:
            print(f"frames: normalized {norm['frames']} frames to one pixel format "
                  f"(was {norm['color_types']}, {norm['transparent_frames']} with alpha)")

        n = len([f for f in os.listdir(frames_dir) if f.endswith(".png")])
        if n != spec["durationInFrames"]:
            sys.exit(f"expected {spec['durationInFrames']} frames, got {n}")

        holes = find_holes(spec, frames_dir, fps)
        if not holes:
            return n
        print(f"holes: {format_holes(holes, shot_id)} "
              f"(render attempt {attempt}/{RENDER_ATTEMPTS})")
    sys.exit(
        f"{shot_id}: the renderer left {len(holes)} frame(s) empty after "
        f"{RENDER_ATTEMPTS} render attempts "
        f"(composition frames {', '.join(str(h['frame']) for h in holes)}). "
        f"A video layer did not paint; the shot was NOT encoded, because those "
        f"frames would reach the film as black holes."
    )
