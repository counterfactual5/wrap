"""Deterministic local fixtures: rehearse the pipeline without credits."""
import os
import subprocess

from core.generation.connector import CALL_TIMEOUT


def _write_video_fixture(target_path, seconds=2, fps=30, w=270, h=480,
                         with_audio=False):
    """Build a small deterministic mp4 locally (fixture path spends no credits).

    A dark field with a REPEATING band pattern that scrolls upward: every
    frame differs from its neighbour by a measurable amount, so the motion gate
    sees real motion and the freeze detector sees no frozen segment.

    The repetition is the point, not decoration. A video layer defaults to
    fit:'cover', so a 9:16 clip inside a 16:9 rect shows only its CENTRE — and
    a single narrow band travelling the full height spends most of its life
    outside that window, leaving the picture frozen while the source is not
    (the crop shows no band edge, so nothing on screen moves). A pattern whose
    period is shorter than any window the pipeline can crop to keeps an edge
    inside the visible crop for the whole clip, so the fixture behaves the same
    whatever aspect the composition asks for.

    The pattern is drawn on a canvas one period taller and cropped with a
    time-driven offset: the pattern is periodic, so scrolling by that offset
    is seamless and the wrap never shows.

    with_audio=True adds a steady tone, so a fixture can exercise the
    "the clip owns the audio" path (a native track that must survive S2,
    be mastered in S3 and be measured by S4)."""
    parent = os.path.dirname(target_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    period, band = 120, 60
    canvas_h = h + period
    boxes = "".join(
        f"drawbox=x=0:y={y}:w={w}:h={band}:color=0xB84DFF:t=fill,"
        for y in range(0, canvas_h - band + 1, period))
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x101830:s={w}x{canvas_h}:r={fps}",
    ]
    if with_audio:
        # A steady tone: silent enough to be a placeholder, loud enough that
        # the silence gate can tell it apart from a dead track.
        cmd.extend([
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}",
        ])
    # -vf is an OUTPUT option: it must come after every input, or ffmpeg
    # applies it to the input that follows (the audio tone) and the run dies
    # with "Option vf cannot be applied to input url sine=...".
    cmd.extend([
        "-vf", f"{boxes}crop={w}:{h}:0:'mod(t*60,{period})'",
        "-frames:v", str(seconds * fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(fps),
    ])
    if with_audio:
        cmd.extend(["-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"])
    cmd.extend(["-movflags", "+faststart", target_path])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"video fixture creation failed (ffmpeg exit {proc.returncode}):\n{proc.stderr}")
