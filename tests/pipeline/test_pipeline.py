"""End-to-end and reproducibility tests for the poster pipeline."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.runtime import manifest
from core.quality import pixels as metrics
from core.spec.loader import load_spec
from core.spec.shot import validate
from tests.helpers import ensure_rendered, preserve_assets, preserve_manifest


class TestPipeline(unittest.TestCase):
    def setUp(self):
        # The stages write to the frozen ledger (manifest.json) and may
        # rewrite tracked assets (S1's --fixture path writes the asset file);
        # snapshot both so a test run leaves the working tree as it found it.
        self._manifest_ctx = preserve_manifest()
        self._manifest_ctx.__enter__()
        self._assets_ctx = preserve_assets("city-silhouette.png", "shot-02-subject.png")
        self._assets_ctx.__enter__()

    def tearDown(self):
        self._assets_ctx.__exit__(None, None, None)
        self._manifest_ctx.__exit__(None, None, None)

    def test_00_spec_validation(self):
        spec = load_spec()
        self.assertEqual(len(validate(spec)), 0)

        # Negative test: invalid spec must be caught
        bad_spec = dict(spec)
        bad_spec["durationInFrames"] = -1
        self.assertGreater(len(validate(bad_spec)), 0)

    def test_01_metrics_pure(self):
        # Edge key purity test
        w, h = 100, 100
        pure_white = bytes((255, 255, 255)) * (w * h)
        purity = metrics.edge_key_purity(pure_white, w, h, (255, 255, 255), ring=8, tol=12)
        self.assertEqual(purity, 1.0)

        # Red ratio test
        pure_red = bytes((200, 50, 50)) * (w * h)
        red_ratio = metrics.red_ratio_of_frame(pure_red, w, h)
        self.assertEqual(red_ratio, 1.0)

    def test_02_stages_run(self):
        # S1 (ensure assets verified, spec-aware)
        res = subprocess.run([sys.executable, "stages/01_generate.py", "--spec", "tests/fixtures/shot-01.poster.json"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S2 (prepare & key purity check)
        res = subprocess.run([sys.executable, "stages/02_prepare.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S3 (compose video & frames)
        res = subprocess.run([sys.executable, "stages/03_compose.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        # S4 (gates)
        res = subprocess.run([sys.executable, "stages/04_gate.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        with open(os.path.join(ROOT, "build", "gates", "shot-01.json")) as f:
            gates = json.load(f)
        for g in gates:
            self.assertTrue(g["pass"], f"Gate {g['id']} failed: {g}")

    def test_03_reproducibility(self):
        """Invariant: Same spec + same manifest -> exact same video sha256."""
        # The prepared rows S3 needs ARE part of "the same manifest" this
        # invariant talks about. They used to arrive as a leak from another
        # test file, so the check passed in a full-suite run and failed when
        # this file was run on its own. Establish the state here instead of
        # inheriting it.
        ensure_rendered("tests/fixtures/shot-01.poster.json", "shot-01")

        v1 = manifest.sha256(os.path.join(ROOT, "build", "shot-01.mp4"))

        # Re-run S3 compose
        res = subprocess.run([sys.executable, "stages/03_compose.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        v2 = manifest.sha256(os.path.join(ROOT, "build", "shot-01.mp4"))
        self.assertEqual(v1, v2, f"Bit-for-bit mismatch: {v1} != {v2}")

    def test_04_init_shot(self):
        test_shot = "test-shot-init"
        target = os.path.join(ROOT, "spec", f"{test_shot}.poster.json")
        try:
            if os.path.exists(target):
                os.remove(target)
            res = subprocess.run([sys.executable, "pipeline.py", "init-shot", test_shot], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(target))
            spec = load_spec(target)
            self.assertEqual(spec["id"], test_shot)
        finally:
            if os.path.exists(target):
                os.remove(target)

    def test_05_keypurity_gate_verifies_sha(self):
        """The keyPurity gate must go red when a prepared asset is tampered with.

        S4 reads purity through manifest.verified() (sha256-checked), not a stored
        number — a modified file must be caught, not trusted."""
        path = os.path.join(ROOT, "build", "prepared", "shot-01", "city-silhouette.png")
        self.assertTrue(os.path.exists(path), "run S2 first")
        original = open(path, "rb").read()
        try:
            # flip one pixel near the edge (inside the 8px purity ring)
            import core.media.png as png
            w, h = png.read_size(path)
            rgb = bytearray(metrics.read_rgb(path, w, h))
            i = (4 * w + 4) * 3
            rgb[i:i + 3] = b"\x00\xff\x00"
            png.write_png(path, w, h, bytes(rgb))

            res = subprocess.run([sys.executable, "stages/04_gate.py"], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(res.returncode, 0,
                                "tampered prepared asset passed the gate; purity path not sha-verified")
        finally:
            with open(path, "wb") as f:
                f.write(original)

    def test_06_style_palette_is_truth(self):
        """S2 must consume style.json palette: change accent -> grid paper changes."""
        style_path = os.path.join(ROOT, "tests", "fixtures", "style.json")
        with open(style_path) as f:
            original = f.read()
        try:
            style = json.loads(original)
            style["palette"]["paper"] = "#101010"
            with open(style_path, "w") as f:
                json.dump(style, f, indent=2)

            res = subprocess.run([sys.executable, "stages/02_prepare.py"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)

            rgb = metrics.read_rgb(os.path.join(ROOT, "build", "prepared", "shot-01", "bg.png"), 1920, 1080)
            # (10, 100): off the 80px grid lines, pure paper
            i = (100 * 1920 + 10) * 3
            self.assertEqual(list(rgb[i:i + 3]), [16, 16, 16],
                             "grid paper did not follow style.palette.paper")
        finally:
            with open(style_path, "w") as f:
                f.write(original)
            subprocess.run([sys.executable, "stages/02_prepare.py"], cwd=ROOT, capture_output=True)

    def test_07_manifest_tolerates_missing_sections(self):
        """An old/hand-trimmed manifest without 'prepared' must not crash load().

        The trimmed ledger is written IN PLACE (the file is never moved
        aside): a tool that snapshots the working tree can catch the window
        in which the file is missing and read that as "the tree changed".
        The original bytes are restored afterwards."""
        with open(manifest.PATH, "rb") as f:
            saved = f.read()
        try:
            with open(manifest.PATH, "w") as f:
                json.dump({"assets": {}}, f)
            m = manifest.load()
            self.assertEqual(m.get("prepared"), {})
            self.assertEqual(m.get("video"), {})
        finally:
            with open(manifest.PATH, "wb") as f:
                f.write(saved)


class TestExtractFrame(unittest.TestCase):
    """The cross-shot handoff: a rendered clip's tail becomes the next shot's first_frame.

    The extracted frame is frozen in the manifest like any other asset, so the
    next shot names it as its first_frame and S1 resolves it through the
    normal manifest path — no special-casing anywhere in the pipeline.
    """

    def _sandbox(self):
        tmp = tempfile.mkdtemp(prefix="wrap-xf-")
        os.makedirs(os.path.join(tmp, "assets"))
        os.makedirs(os.path.join(tmp, "build"))
        clip = os.path.join(tmp, "build", "shot-01.mp4")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x101830:s=270x480:r=30",
            "-f", "lavfi", "-i", "color=c=0xB84DFF:s=270x60:r=30",
            "-filter_complex",
            "[0:v][1:v]overlay=x=0:y='(main_h-overlay_h)*t/3':shortest=1",
            "-frames:v", "90", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", clip,
        ], check=True, capture_output=True)
        return tmp

    def _run(self, tmp, *args):
        env = dict(os.environ)
        env["POSTER_ROOT"] = tmp
        env["POSTER_MANIFEST"] = os.path.join(tmp, "manifest.json")
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "pipeline.py"), "extract-frame"] + list(args),
            cwd=ROOT, capture_output=True, text=True, env=env)

    def test_00_tail_frame_is_extracted_and_registered(self):
        tmp = self._sandbox()
        try:
            res = self._run(tmp, "--video", "build/shot-01.mp4",
                            "--name", "shot-01-tail", "--at", "last")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            png = os.path.join(tmp, "assets", "shot-01-tail.png")
            self.assertTrue(os.path.exists(png))
            with open(png, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
            with open(os.path.join(tmp, "manifest.json")) as f:
                m = json.load(f)
            row = m["assets"]["shot-01-tail"]
            self.assertEqual(row["source"], "extracted")
            self.assertEqual(row["path"], "assets/shot-01-tail.png")
            self.assertIn("sha256", row)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_01_a_nonsense_frame_selector_is_refused(self):
        tmp = self._sandbox()
        try:
            res = self._run(tmp, "--video", "build/shot-01.mp4",
                            "--name", "x", "--at", "middle")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("last", res.stdout + res.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_02_a_missing_clip_names_the_command_to_run(self):
        tmp = self._sandbox()
        try:
            res = self._run(tmp, "--video", "build/nope.mp4", "--name", "x")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("pipeline.py run", res.stdout + res.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
