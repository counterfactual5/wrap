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


if __name__ == "__main__":
    unittest.main()
