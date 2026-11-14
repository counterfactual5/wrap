"""Extract a prepared clip's frames with Remotion's <Video> semantics, plus
the solid-PNG fill for frames the renderer leaves empty and the routing
check for the Quartz fast path."""
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
    layer's plate background shows instead of the clip)."""
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


def _quartz_fast_path_layer(spec):
    """The video layer a direct full-frame extraction can serve, or None.

    Writing extracted frames straight into the frames dir IS the composed
    shot only when the single video layer's rect is the whole canvas; any
    other rect has to go through the Swift compositor, which positions the
    clip like Remotion's absolutely-positioned wrapper div."""
    layers = spec.get("layers", [])
    if len(layers) != 1 or layers[0].get("type") != "video":
        return None
    rect = layers[0].get("rect") or [0, 0, spec["canvas"]["w"], spec["canvas"]["h"]]
    if rect != [0, 0, spec["canvas"]["w"], spec["canvas"]["h"]]:
        return None
    return layers[0]


def _extract_video_frames(layer, clip_path, out_dir, n_frames, fps, rw, rh):
    """Extract a prepared clip's frames with Remotion's <Video> semantics.

    Two steps, mirroring remotion 4.0.529 exactly:
      1. ffmpeg pulls the trim window once, fitted to the layer rect
         (cover = center-crop, contain = letterbox in the plate background
         #030509 — transparent when plate:false, so lower layers show through
         exactly like the renderer's wrapper div does);
      2. each composition frame picks window frame
         floor((i mod (window / rate)) * rate) — the frame <Loop> plus the
         media seek land on. Picking in Python (not via setpts/fps resampling)
          keeps the mapping exact for any rate.

    Past the window: a looping clip repeats it; a non-looping untrimmed clip
    clamps on its last frame (the <video> element does); a non-looping
    trimmed clip unmounts (its <Sequence> ends) and the fill frames stand in
    for the plate background."""
    shutil.rmtree(out_dir, ignore_errors=True)
    window_dir = os.path.join(out_dir, "_window")
    os.makedirs(window_dir)

    t0, t1, rate = video_timeline(layer, fps)
    fit = layer.get("fit") or "cover"
    plate = layer.get("plate") is not False
    vf = []
    if t0 > 0 or t1 is not None:
        vf.append(f"trim=start={t0}" + (f":end={t1}" if t1 is not None else ""))
        vf.append("setpts=PTS-STARTPTS")
    if fit == "contain":
        pad = "0x030509@1.0" if plate else "black@0.0"
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
        fill = (3, 5, 9, 255) if plate else (0, 0, 0, 0)
        for i in range(n_frames):
            if not wframes:
                j = None
            elif layer.get("loop", True):
                loop_dur = wframes / rate
                local = i - math.floor(i / loop_dur) * loop_dur
                j = min(int(local * rate), wframes - 1)
            else:
                j = int(i * rate)
                if j >= wframes:
                    # Untrimmed: the <video> element clamps on its last frame.
                    # Trimmed: the <Sequence> unmounts and the plate shows.
                    j = wframes - 1 if layer.get("trim") is None else None
            dst = os.path.join(out_dir, f"{i + 1:05d}.png")
            if j is None:
                _write_solid_png(dst, rw, rh, fill)
            else:
                shutil.copyfile(os.path.join(window_dir, window[j]), dst)
    finally:
        shutil.rmtree(window_dir, ignore_errors=True)
