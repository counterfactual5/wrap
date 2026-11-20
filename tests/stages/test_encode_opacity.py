"""A layer's opacity ramp must reach the encoded picture.

The rendered PNGs carry an alpha channel. Encoding them straight to yuv420p
discarded that alpha, so a backdrop faded to 45% arrived at full strength in
the delivered mp4 — only opacity 0 (the element dropped entirely) read as
black. S3 now composites the frames over an opaque black sheet, so a partial
opacity darkens the picture the way it reads on screen.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.helpers import active_manifest_path, ensure_rendered, preserve_manifest

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")
SHOT = "shot-01-veil"
SPEC = os.path.join(ROOT, "build", "gates", f"{SHOT}.json")


def _mean_luma(mp4, frame_index):
    """Mean luma of one frame, via ffmpeg's signalstats."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", mp4,
         "-vf", f"select=eq(n\\,{frame_index}),signalstats,metadata=print:file=-",
         "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    for line in proc.stdout.splitlines():
        if "YAVG=" in line:
            return float(line.split("=")[1].split()[0])
    raise AssertionError(f"no YAVG for frame {frame_index}")


class _BackdropOpacityReachesTheVideo(unittest.TestCase):
    def test_partial_opacity_darkens_the_encoded_frame(self):
        with preserve_manifest():
            with open(FIXTURE) as f:
                spec = json.load(f)
            spec["id"] = SHOT
            for layer in spec["layers"]:
                if layer.get("type") == "ai":
                    layer["blend"] = "normal"
                    layer["anim"] = {"opacity": [[0, 1.0], [149, 0.45]]}
            spec["gates"] = []
            os.makedirs(os.path.dirname(SPEC), exist_ok=True)
            with open(SPEC, "w") as f:
                json.dump(spec, f)
            try:
                mp4 = ensure_rendered(SPEC, SHOT)
            finally:
                if os.path.exists(SPEC):
                    os.remove(SPEC)
        first = _mean_luma(mp4, 0)
        last = _mean_luma(mp4, 149)
        # 45% opacity over black leaves ~45% of the picture's luminance.
        self.assertGreater(first, 30, "the fixture must not be black to begin with")
        self.assertLess(last, first * 0.7,
                        f"opacity 0.45 did not reach the video (first={first:.1f} last={last:.1f})")
        self.assertGreater(last, first * 0.25,
                           f"the fade went too far — it is not compositing (first={first:.1f} last={last:.1f})")


class _EncodingCanvasBgAndFrameCount(unittest.TestCase):
    """Real ffmpeg checks for declared canvas.bg compositing and exact 1-frame preservation."""

    def test_declared_canvas_bg_reaches_transparent_regions(self):
        import subprocess
        import tempfile
        from unittest import mock
        from core.audio import measure_av_durations
        from core.rendering import encoding
        from core.rendering.video_frames import _write_solid_png

        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            for i in range(1, 11):
                _write_solid_png(os.path.join(frames_dir, f"{i:05d}.png"), 32, 32, (0, 0, 0, 0))
            out_mp4 = os.path.join(tmp, "out.mp4")
            spec = {
                "id": "bg-color-test",
                "canvas": {"w": 32, "h": 32, "bg": "#204080"},
                "fps": 30,
                "durationInFrames": 10,
                "layers": [],
            }
            with mock.patch.object(encoding, "ROOT", tmp):
                encoding.encode_mp4(spec, frames_dir, out_mp4)
            probe = measure_av_durations(out_mp4)
            self.assertEqual(probe["video_frames"], 10)
            rgb = subprocess.check_output([
                "ffmpeg", "-v", "error", "-i", out_mp4,
                "-vf", "select=eq(n\\,0)", "-vframes", "1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ])
            n = len(rgb) // 3
            mean_r = sum(rgb[0::3]) / n
            mean_g = sum(rgb[1::3]) / n
            mean_b = sum(rgb[2::3]) / n
            self.assertLess(abs(mean_r - 0x20), 10, f"expected R~32, got {mean_r:.1f}")
            self.assertLess(abs(mean_g - 0x40), 10, f"expected G~64, got {mean_g:.1f}")
            self.assertLess(abs(mean_b - 0x80), 10, f"expected B~128, got {mean_b:.1f}")

    def test_clip_audio_preserves_all_151_frames_at_30fps(self):
        import subprocess
        import tempfile
        from unittest import mock
        from core.audio import measure_av_durations
        from core.rendering import encoding
        from core.rendering.video_frames import _write_solid_png
        from core.runtime import manifest

        with tempfile.TemporaryDirectory() as tmp:
            clip_mp4 = os.path.join(tmp, "clip.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=#335577:s=32x32:r=30:d=6.0",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=6.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                clip_mp4,
            ], check=True)
            manifest_path = os.path.join(tmp, "manifest.json")
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            for i in range(1, 152):
                _write_solid_png(os.path.join(frames_dir, f"{i:05d}.png"), 32, 32, (40, 80, 120, 255))

            old_manifest = os.environ.get("POSTER_MANIFEST")
            os.environ["POSTER_MANIFEST"] = manifest_path
            try:
                manifest.register("prepared", "frames-151/clip", clip_mp4)
                for trim_end in (5.533, 2.0):
                    out_mp4 = os.path.join(tmp, f"out_{trim_end}.mp4")
                    spec = {
                        "id": "frames-151",
                        "canvas": {"w": 32, "h": 32, "bg": "#000000"},
                        "fps": 30,
                        "durationInFrames": 151,
                        "layers": [{
                            "id": "vid",
                            "type": "video",
                            "asset": "clip",
                            "trim": [0.5, trim_end],
                            "loop": False,
                            "muted": False,
                            "rect": [0, 0, 32, 32],
                            "z": 0,
                        }],
                    }
                    with mock.patch.object(encoding, "ROOT", tmp):
                        encoding.encode_mp4(spec, frames_dir, out_mp4)
                    probe = measure_av_durations(out_mp4)
                    self.assertEqual(
                        probe["video_frames"], 151,
                        f"trim=[0.5, {trim_end}] dropped frames: {probe}",
                    )
                    self.assertTrue(probe["has_audio"])
            finally:
                if old_manifest is None:
                    os.environ.pop("POSTER_MANIFEST", None)
                else:
                    os.environ["POSTER_MANIFEST"] = old_manifest


if __name__ == "__main__":
    unittest.main()
