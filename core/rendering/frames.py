"""Frame-sequence pixel-format normalization, and the binding check that
proves the delivered mp4 is the encoding of the frame master.

Remotion writes RGBA only for the frames that carry transparency and RGB for
the rest, so one rendered shot can mix color types. The PNG demuxer then
changes the decoded frame format mid-stream, which reconfigures ffmpeg's
filter graph: the overlay's frame sync is reset and the encoder emits the bare
background sheet (a black frame) at positions that differ from run to run.

Measured on a 360-frame shot with 13 transparent frames: five encodes of the
SAME frames produced black frames at {278,279,280}, {139,140,141,147,148},
{1,2,140,141,146,147,148,150,151,279,280} and {140,141,146,147,148,279,280},
while the frames themselves only ever had {140,141,279,280}. The delivered
video therefore stopped matching the frame master it was encoded from, and
WHICH frames were lost changed with every run - a defect that no amount of
re-running could fix.

Normalizing the sequence to one color type removes the reconfiguration
entirely: the decoded stream never changes format, so the graph is configured
once and every frame survives. The pixels do not change - RGB is copied
verbatim, the alpha channel is preserved where the frame had one and added as
opaque where it did not.
"""
import os
import shutil
import subprocess

from core.runtime.timeouts import LOCAL_TOOL_TIMEOUT

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE_RGB = 2
COLOR_TYPE_RGBA = 6
UNIFORM_COLOR_TYPE = COLOR_TYPE_RGBA

# A frame whose mean |dY| against the master exceeds this is not the master's
# picture. Measured on a correct render of the same shot: every frame stayed
# at or below 1.5 (the encoder's own quantization at crf 18), while the
# format-switch defect showed 35-61 on the frames it corrupted.
MASTER_DELTA_LIMIT = 6.0


def png_color_type(path):
    """The IHDR color type of a PNG file (2 = RGB, 6 = RGBA)."""
    with open(path, "rb") as f:
        head = f.read(26)
    if len(head) < 26 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise RuntimeError(f"not a PNG file: {path}")
    return head[25]


def frame_names(frames_dir):
    """The rendered frame files, in order."""
    names = sorted(n for n in os.listdir(frames_dir) if n.lower().endswith(".png"))
    if not names:
        raise RuntimeError(f"no PNG frames in {frames_dir}")
    return names


def sequence_color_types(frames_dir):
    """{color type: [frame names]} for the rendered sequence."""
    types = {}
    for name in frame_names(frames_dir):
        types.setdefault(png_color_type(os.path.join(frames_dir, name)), []).append(name)
    return types


def expected_frame_names(count):
    """The %05d.png names the encoder reads: 1-indexed and contiguous."""
    return [f"{i:05d}.png" for i in range(1, count + 1)]


def _format_name(color_type):
    return {COLOR_TYPE_RGB: "rgb24", COLOR_TYPE_RGBA: "rgba"}.get(color_type, "rgba")


def convert_frame_formats(frames_dir, work_dir, fps=30):
    """Write a single-pixel-format copy of the sequence into work_dir.

    Returns the directory holding the copy (the original directory when it was
    already uniform, so the common case copies nothing). The original frames
    are never touched: the master is what S4 measures, and rewriting it behind
    the manifest's fingerprint would invalidate the binding.
    """
    types = sequence_color_types(frames_dir)
    if len(types) == 1:
        return frames_dir

    names = frame_names(frames_dir)
    expected = expected_frame_names(len(names))
    if names != expected:
        raise RuntimeError(
            f"frame sequence in {frames_dir} is not the contiguous %05d.png the "
            f"encoder reads (first={names[0]}, last={names[-1]}, "
            f"count={len(names)}) - it cannot be normalized safely"
        )

    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%05d.png"),
        "-vf", f"format={_format_name(UNIFORM_COLOR_TYPE)}",
        "-c:v", "png",
        os.path.join(work_dir, "%05d.png"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LOCAL_TOOL_TIMEOUT)
    if proc.returncode != 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(
            f"frame format conversion failed ({' '.join(cmd)}): {proc.stderr.strip()}"
        )

    produced = frame_names(work_dir)
    if produced != expected:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(
            f"frame format conversion produced {len(produced)} frames, "
            f"expected {len(expected)} - the conversion must not drop or add a frame"
        )
    for name in produced:
        ct = png_color_type(os.path.join(work_dir, name))
        if ct != UNIFORM_COLOR_TYPE:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise RuntimeError(
                f"frame format conversion produced {name} with color type "
                f"{ct}, expected {UNIFORM_COLOR_TYPE}"
            )
    return work_dir


def normalize_frame_formats(frames_dir, fps=30, work_dir=None):
    """Rewrite the sequence into a single pixel format (RGBA), in place.

    Returns a report describing what was found and what was done:
    {"normalized", "color_types", "frames", "transparent_frames", "to"}.

    A sequence that already has one color type is left untouched - the
    conversion costs a full decode/encode pass, and most shots do not need it.
    """
    types = sequence_color_types(frames_dir)
    names = frame_names(frames_dir)
    report = {
        "normalized": False,
        "color_types": sorted(types),
        "frames": len(names),
        "transparent_frames": len(types.get(COLOR_TYPE_RGBA, [])),
        "to": UNIFORM_COLOR_TYPE,
    }
    if len(types) == 1:
        return report

    work = work_dir or os.path.join(frames_dir, "_uniform")
    convert_frame_formats(frames_dir, work, fps)
    # Same filesystem, so each rename is atomic: a crash mid-swap leaves a
    # consistent sequence (some frames converted, some not) - and the next
    # normalize call finishes the job.
    for name in expected_frame_names(len(names)):
        os.replace(os.path.join(work, name), os.path.join(frames_dir, name))
    shutil.rmtree(work, ignore_errors=True)
    report["normalized"] = True
    return report


def master_video_deltas(spec, frames_dir, mp4_path, canvas_bg="black"):
    """Per-frame mean |dY| between the delivered mp4 and the frame master.

    The master is composited over the canvas background exactly the way the
    encoder composites it, so the two streams describe the same picture and
    the only difference left is the encoder. A mismatch means the delivered
    video is not the encoding of the frames it claims to come from.
    """
    canvas = spec.get("canvas") or {}
    w = canvas.get("w") or 1920
    h = canvas.get("h") or 1080
    fps = spec.get("fps") or 30
    cmd = [
        "ffmpeg", "-v", "error", "-nostats",
        "-i", mp4_path,
        "-f", "lavfi", "-i", f"color=c={canvas_bg}:s={w}x{h}:r={fps}",
        "-framerate", str(fps), "-i", os.path.join(frames_dir, "%05d.png"),
        "-filter_complex",
        "[1:v][2:v]overlay=shortest=1[bg];"
        "[0:v][bg]blend=all_mode=difference,signalstats,metadata=print:file=-[d]",
        "-map", "[d]", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LOCAL_TOOL_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"master/video comparison failed ({' '.join(cmd)}): {proc.stderr.strip()}"
        )
    deltas = []
    frame = None
    for line in proc.stdout.splitlines():
        if line.startswith("frame:"):
            frame = int(line.split()[0].split(":")[1])
        elif line.startswith("lavfi.signalstats.YAVG=") and frame is not None:
            deltas.append((frame, float(line.split("=", 1)[1])))
    return deltas
