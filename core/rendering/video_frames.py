"""Extract prepared video frames with transparent empty regions."""
import math
import os
import shutil
import struct
import subprocess
import zlib

from core.runtime.config import ROOT
from core.rendering.timeline import video_timeline


def _write_solid_png(path, w, h, rgba):
    """Stdlib-only solid RGBA PNG — the fill for frames Remotion leaves empty
    (a trimmed, non-looping <Video> unmounts once its window ends, and the
    layer becomes transparent)."""
    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
    scanline = b"\x00" + bytes(rgba) * w
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(scanline * h, 9)))
        f.write(chunk(b"IEND", b""))


def _extract_video_frames(layer, clip_path, out_dir, n_frames, fps, rw, rh):
    """Extract a prepared clip's frames with Remotion's <Video> semantics.

    Two steps, mirroring remotion 4.0.529 exactly:
      1. ffmpeg pulls the trim window once, fitted to the layer rect
         (cover = center-crop, contain = transparent letterbox, so lower layers show through
         exactly like the renderer's wrapper div does);
      2. each composition frame picks window frame
         floor((i mod (window / rate)) * rate) — the frame <Loop> plus the
         media seek land on. Picking in Python (not via setpts/fps resampling)
          keeps the mapping exact for any rate.

    Past the window: a looping clip repeats it; a non-looping untrimmed clip
    clamps on its last frame (the <video> element does); a non-looping
    trimmed clip unmounts (its <Sequence> ends) and the fill frames stand in
    for the transparent layer."""
    shutil.rmtree(out_dir, ignore_errors=True)
    window_dir = os.path.join(out_dir, "_window")
    os.makedirs(window_dir)

    t0, t1, rate = video_timeline(layer, fps)
    fit = layer.get("fit") or "cover"
    vf = []
    if t0 > 0 or t1 is not None:
        vf.append(f"trim=start={t0}" + (f":end={t1}" if t1 is not None else ""))
        vf.append("setpts=PTS-STARTPTS")
    if fit == "contain":
        pad = "black@0.0"
        vf.append(f"scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
                  f"format=rgba,pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color={pad}")
    else:
        vf.append(f"scale={rw}:{rh}:force_original_aspect_ratio=increase,"
                  f"crop={rw}:{rh}")
    # No window frame beyond n_frames * rate can ever be picked (looping or
    # not), so the pull is capped there instead of decoding a long clip.
    cap = int(math.ceil(n_frames * max(rate, 1.0))) + 8
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", clip_path,
           "-vf", ",".join(vf), "-frames:v", str(cap),
           os.path.join(window_dir, "%05d.png")]
    try:
        subprocess.run(cmd, check=True, cwd=ROOT)
        window = sorted(f for f in os.listdir(window_dir) if f.endswith(".png"))
        wframes = len(window)
        if not wframes:
            raise RuntimeError(f"video produced no decodable frames: {clip_path}")
        fill = (0, 0, 0, 0)
        for i in range(n_frames):
            # wframes > 0 here: an empty window raised above, so there is no
            # "no frames" case to branch on — every frame maps onto a decoded
            # window frame or onto the transparent fill of an unmounted clip.
            if layer.get("loop", True):
                loop_dur = wframes / rate
                local = i - math.floor(i / loop_dur) * loop_dur
                j = min(int(local * rate), wframes - 1)
            else:
                j = int(i * rate)
                if j >= wframes:
                    # Untrimmed: the <video> element clamps on its last frame.
                    # Trimmed: the <Sequence> unmounts and the layer becomes transparent.
                    j = wframes - 1 if layer.get("trim") is None else None
            dst = os.path.join(out_dir, f"{i + 1:05d}.png")
            if j is None:
                _write_solid_png(dst, rw, rh, fill)
            else:
                shutil.copyfile(os.path.join(window_dir, window[j]), dst)
    finally:
        shutil.rmtree(window_dir, ignore_errors=True)
