"""The native macOS CoreGraphics/CoreText fallback compositor, used when
headless Chromium cannot run (sandbox SIGSEGV) or POSTER_FORCE_QUARTZ=1."""
import json
import os
import shutil
import subprocess

from core.runtime import manifest
from core.runtime.config import ENGINE_ROOT, ROOT
from core.rendering.video_frames import _extract_video_frames, _quartz_fast_path_layer


def _render_quartz_fallback(spec, out_dir, shot_id):
    """Native macOS CoreGraphics/CoreText fallback when headless Chromium hits
    sandbox SIGSEGV inside restricted sandbox-exec environments.

    Video layers follow the same timeline Remotion renders — trim windows,
    playbackRate speed, loop, layer rect and fit (cover/contain) — so the
    frames handed to the Swift compositor are the frames the renderer would
    show (see _extract_video_frames for the exact math)."""
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    W, H = spec["canvas"]["w"], spec["canvas"]["h"]
    fps = spec.get("fps", 30)
    n_frames = spec["durationInFrames"]

    video_layers = [L for L in spec.get("layers", []) if L.get("type") == "video"]
    temp_video_dirs = []
    if video_layers:
        fast = _quartz_fast_path_layer(spec)
        if fast is not None:
            row = manifest.verified("prepared", f"{shot_id}/{fast['asset']}")
            if row:
                _extract_video_frames(fast, os.path.join(ROOT, row["path"]),
                                      out_dir, n_frames, fps, W, H)
                return
        for v_layer in video_layers:
            row = manifest.verified("prepared", f"{shot_id}/{v_layer['asset']}")
            if not row:
                continue
            lrect = v_layer.get("rect") or [0, 0, W, H]
            v_dir = os.path.join(ROOT, "build", "prepared", shot_id,
                                 f"_video_frames_{v_layer['id']}")
            temp_video_dirs.append(v_dir)
            _extract_video_frames(v_layer, os.path.join(ROOT, row["path"]),
                                  v_dir, n_frames, fps, lrect[2], lrect[3])
    swift_src = os.path.join(ENGINE_ROOT, "renderers", "quartz", "compose.swift")
    bin_path = os.path.join(ROOT, ".tmp", "quartz_compose")
    os.makedirs(os.path.dirname(bin_path), exist_ok=True)
    if (not os.path.exists(bin_path)
            or os.path.getmtime(swift_src) > os.path.getmtime(bin_path)):
        subprocess.run(["swiftc", "-O", swift_src, "-o", bin_path], check=True, cwd=ROOT)

    spec_file = os.path.join(ROOT, ".tmp", f"resolved-spec-{shot_id}.json")
    with open(spec_file, "w") as f:
        json.dump(spec, f)
    try:
        subprocess.run([bin_path, spec_file, out_dir, shot_id], check=True, cwd=ROOT)
    finally:
        for td in temp_video_dirs:
            shutil.rmtree(td, ignore_errors=True)
