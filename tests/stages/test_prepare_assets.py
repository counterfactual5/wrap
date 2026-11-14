"""S2 prepared-image geometry for ai layers: fit cover / contain / cutout.

The renderer draws the prepared image inside the layer rect with
objectFit: layer.fit ?? 'cover' (remotion/Shot.tsx MediaLayer), so the
prepared file must already respect that geometry — the source aspect ratio
is always preserved:

- cover: scaled to cover the rect, centre-cropped (never stretched);
- contain: scaled to fit inside the rect, centred on a TRANSPARENT canvas
  (core/media/geometry.py source_to_canvas_pivot assumes exactly this
  mapping for joint/socket pivots);
- cutout: keyed sprite — contain-shaped scaling plus colorkey (unchanged).

Each test drives the real 02_prepare.py on a fixture whose centre carries a
known black square, then measures the square's bounding box in the prepared
PNG: its size proves the uniform scale factor, its aspect proves the ratio
was preserved (a forced stretch would turn the square into a rectangle),
its centre proves the centring, and the corner alpha proves the letterbox
transparency.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from core.media.png import read_size, write_png
from tests.helpers import ROOT, preserve_manifest, register_test_asset

SHOT = "fit-prep-shot"
PREPARED_DIR = os.path.join(ROOT, "build", "prepared", SHOT)
# Source fixture: 320x200 (8:5) with a 40px black square dead centre, on white.
SRC_W, SRC_H, SQ = 320, 200, 40
BG = (255, 255, 255)
INK = (0, 0, 0)


def _marker_fixture(path):
    px = bytearray(bytes(BG) * (SRC_W * SRC_H))
    x0 = (SRC_W - SQ) // 2
    y0 = (SRC_H - SQ) // 2
    for y in range(y0, y0 + SQ):
        row = y * SRC_W
        px[(row + x0) * 3:(row + x0 + SQ) * 3] = bytes(INK) * SQ
    write_png(path, SRC_W, SRC_H, bytes(px))


def _read_rgba(path, w, h):
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True)
    if len(res.stdout) != w * h * 4:
        raise AssertionError(f"expected {w}x{h} rgba from {path}, got {len(res.stdout)} bytes")
    return res.stdout


def _marker_bbox(rgba, w, h):
    """Bounding box (x0, y0, x1, y1 inclusive) of the opaque dark marker."""
    xs, ys = [], []
    for y in range(h):
        base = y * w * 4
        for x in range(w):
            i = base + x * 4
            if rgba[i + 3] < 128:
                continue  # transparent letterbox / keyed background
            if rgba[i] + rgba[i + 1] + rgba[i + 2] < 300:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise AssertionError("marker square not found in prepared image")
    return min(xs), min(ys), max(xs), max(ys)


def _corner_alphas(rgba, w, h):
    return (rgba[3], rgba[(w - 1) * 4 + 3],
            rgba[(h - 1) * w * 4 + 3], rgba[((h - 1) * w + (w - 1)) * 4 + 3])


class TestPrepareAssetFit(unittest.TestCase):
    def _run_prepare(self, layers):
        spec = {
            "id": SHOT,
            "canvas": {"w": 400, "h": 300, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 30,
            "layers": layers,
            "gates": [],
        }
        spec_path = os.path.join(ROOT, ".tmp", f"{SHOT}.poster.json")
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w") as f:
            json.dump(spec, f)
        try:
            res = subprocess.run(
                [sys.executable, "stages/02_prepare.py", "--spec", spec_path],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        finally:
            if os.path.exists(spec_path):
                os.remove(spec_path)

    def setUp(self):
        shutil.rmtree(PREPARED_DIR, ignore_errors=True)
        self._fixture_path = os.path.join(ROOT, ".tmp", "fit-prep-src.png")
        _marker_fixture(self._fixture_path)

    def tearDown(self):
        shutil.rmtree(PREPARED_DIR, ignore_errors=True)
        if os.path.exists(self._fixture_path):
            os.remove(self._fixture_path)

    def _prepared(self, asset):
        path = os.path.join(PREPARED_DIR, f"{asset}.png")
        self.assertTrue(os.path.exists(path), f"missing prepared file: {path}")
        w, h = read_size(path)
        return path, w, h, _read_rgba(path, w, h)

    def test_00_full_canvas_cover_crops_to_rect_without_stretching(self):
        """Default fit (cover) on a full-canvas layer: rect-ratio box, square stays
        square (the old full-canvas branch forced scale to the canvas ratio and
        turned the 40px square into a 52x62 rectangle)."""
        with preserve_manifest():
            register_test_asset("fit-src-a", ".tmp/fit-prep-src.png")
            self._run_prepare([
                {"id": "bg", "type": "ai", "asset": "fit-src-a",
                 "keyColor": "#ffffff", "blend": "normal",
                 "rect": [0, 0, 400, 300], "z": 0},
            ])
        _, w, h, rgba = self._prepared("fit-src-a")
        self.assertEqual((w, h), (416, 312))  # 400x300 * 1.04 zoom headroom, even
        # Cover scale = max(416/320, 312/200) = 1.56 -> square ~62px, ratio kept.
        x0, y0, x1, y1 = _marker_bbox(rgba, w, h)
        self.assertAlmostEqual(x1 - x0 + 1, SQ * 312 / SRC_H, delta=3)  # 62.4
        self.assertAlmostEqual((x1 - x0) - (y1 - y0), 0, delta=3)
        # Centre-cropped: the source-centred marker lands box-centred, opaque corners.
        self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2)
        self.assertAlmostEqual((y0 + y1 + 1) / 2, h / 2, delta=2)
        self.assertEqual(_corner_alphas(rgba, w, h), (255, 255, 255, 255))

    def test_01_subregion_contain_fits_inside_a_transparent_canvas(self):
        """fit:'contain' on a subregion rect: uniform min-scale, centred, letterbox
        transparent (the old subregion branch always cover-cropped)."""
        with preserve_manifest():
            register_test_asset("fit-src-b", ".tmp/fit-prep-src.png")
            self._run_prepare([
                {"id": "sprite", "type": "ai", "asset": "fit-src-b",
                 "keyColor": "#ffffff", "blend": "normal", "fit": "contain",
                 "rect": [50, 50, 200, 250], "z": 0},
            ])
        _, w, h, rgba = self._prepared("fit-src-b")
        self.assertEqual((w, h), (208, 260))  # 200x250 * 1.04, even
        # Contain scale = min(208/320, 260/200) = 0.65 -> square ~26px, ratio kept.
        x0, y0, x1, y1 = _marker_bbox(rgba, w, h)
        self.assertAlmostEqual(x1 - x0 + 1, SQ * 0.65, delta=3)  # 26
        self.assertAlmostEqual((x1 - x0) - (y1 - y0), 0, delta=3)
        # Centred on the padded canvas...
        self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2)
        self.assertAlmostEqual((y0 + y1 + 1) / 2, h / 2, delta=2)
        # ...with the letterbox truly transparent so lower layers show through.
        self.assertEqual(_corner_alphas(rgba, w, h), (0, 0, 0, 0))

    def test_02_full_canvas_contain_letterboxes_transparent(self):
        """fit:'contain' on a full-canvas rect: the whole image stays visible
        (the old full-canvas branch stretched it to the canvas ratio)."""
        with preserve_manifest():
            register_test_asset("fit-src-c", ".tmp/fit-prep-src.png")
            self._run_prepare([
                {"id": "plate", "type": "ai", "asset": "fit-src-c",
                 "keyColor": "#ffffff", "blend": "normal", "fit": "contain",
                 "rect": [0, 0, 400, 300], "z": 0},
            ])
        _, w, h, rgba = self._prepared("fit-src-c")
        self.assertEqual((w, h), (416, 312))
        # Contain scale = min(416/320, 312/200) = 1.3 -> square ~52px, ratio kept.
        x0, y0, x1, y1 = _marker_bbox(rgba, w, h)
        self.assertAlmostEqual(x1 - x0 + 1, SQ * 1.3, delta=3)  # 52
        self.assertAlmostEqual((x1 - x0) - (y1 - y0), 0, delta=3)
        self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2)
        self.assertAlmostEqual((y0 + y1 + 1) / 2, h / 2, delta=2)
        self.assertEqual(_corner_alphas(rgba, w, h), (0, 0, 0, 0))

    def test_03_cutout_still_keys_and_pads_unchanged(self):
        """cutout:true keeps the existing geometry: colorkey the key colour out,
        decrease-scale, transparent pad — independent of fit."""
        with preserve_manifest():
            register_test_asset("fit-src-d", ".tmp/fit-prep-src.png")
            self._run_prepare([
                {"id": "fg", "type": "ai", "asset": "fit-src-d",
                 "keyColor": "#ffffff", "blend": "normal", "cutout": True,
                 "rect": [0, 0, 300, 200], "z": 0},
            ])
        _, w, h, rgba = self._prepared("fit-src-d")
        self.assertEqual((w, h), (312, 208))  # 300x200 * 1.04, even
        # Cutout scale = min(312/320, 208/200) = 0.975 -> square ~39px, ratio kept.
        x0, y0, x1, y1 = _marker_bbox(rgba, w, h)
        self.assertAlmostEqual(x1 - x0 + 1, SQ * 0.975, delta=4)  # 39 (colorkey softens edges)
        self.assertAlmostEqual((x1 - x0) - (y1 - y0), 0, delta=4)
        self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2)
        self.assertAlmostEqual((y0 + y1 + 1) / 2, h / 2, delta=2)
        # The white background is keyed to true transparency.
        self.assertEqual(_corner_alphas(rgba, w, h), (0, 0, 0, 0))

    def test_04_explicit_subregion_cover_behaves_like_the_default(self):
        """fit:'cover' on a subregion rect is the same chain as the default:
        cover-crop, opaque, box-ratio output."""
        with preserve_manifest():
            register_test_asset("fit-src-e", ".tmp/fit-prep-src.png")
            self._run_prepare([
                {"id": "zone", "type": "ai", "asset": "fit-src-e",
                 "keyColor": "#ffffff", "blend": "normal", "fit": "cover",
                 "rect": [50, 50, 200, 250], "z": 0},
            ])
        _, w, h, rgba = self._prepared("fit-src-e")
        self.assertEqual((w, h), (208, 260))
        # Cover scale = max(208/320, 260/200) = 1.3 -> square ~52px, ratio kept.
        x0, y0, x1, y1 = _marker_bbox(rgba, w, h)
        self.assertAlmostEqual(x1 - x0 + 1, SQ * 1.3, delta=3)  # 52
        self.assertAlmostEqual((x1 - x0) - (y1 - y0), 0, delta=3)
        self.assertAlmostEqual((x0 + x1 + 1) / 2, w / 2, delta=2)
        self.assertAlmostEqual((y0 + y1 + 1) / 2, h / 2, delta=2)
        self.assertEqual(_corner_alphas(rgba, w, h), (255, 255, 255, 255))


if __name__ == "__main__":
    unittest.main()
