"""Gate binding: S4 must refuse to measure another shot's frames or replaced frames.
The manifest video row pins which shot build/frames belongs to (path) and what
it contained when S3 rendered it (frames_sha); 04_gate verifies both before
measuring, so a stale or foreign build/frames cannot produce a passing verdict.

The cases are self-sufficient: any state the manifest happens to be in (which
shot was rendered last) is set up and restored inside each test, so the suite
stays green after any legal workflow (including `pipeline.py concat`)."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MANIFEST = os.path.join(ROOT, "manifest.json")
FRAMES = os.path.join(ROOT, "build", "frames")
GATES_JSON = os.path.join(ROOT, "build", "gates.json")


def gate(spec):
    return subprocess.run(
        [sys.executable, "04_gate.py", "--spec", spec],
        cwd=ROOT, capture_output=True, text=True)


class _ManifestState:
    """Rebind the manifest video row's path to a shot, restoring the original
    bytes afterwards. sha256/bytes stay those of the row read from disk, so
    this only makes sense for pinning the row to the shot it already describes
    (that is what the tests use it for); build/frames stays untouched — the
    mismatch between the row and the real frames is exactly the scenario
    under test."""

    def __init__(self, shot_id):
        self.shot_id = shot_id
        self.saved = None

    def __enter__(self):
        with open(MANIFEST, "rb") as f:
            self.saved = f.read()
        with open(MANIFEST) as f:
            m = json.load(f)
        row = dict(m["video"])
        row["path"] = f"build/{self.shot_id}.mp4"
        m["video"] = row
        with open(MANIFEST, "w") as f:
            json.dump(m, f, indent=2, sort_keys=True)
        return self

    def __exit__(self, *exc):
        with open(MANIFEST, "wb") as f:
            f.write(self.saved)


class TestGateBinding(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(os.path.join(FRAMES, "00001.png")):
            self.skipTest("run the pipeline first (build/frames missing)")

    def test_gate_refuses_foreign_frames(self):
        """Gating a shot whose render is NOT the bound one must fail, name the
        shot in stderr, and not rewrite gates.json — regardless of which shot
        the manifest happens to bind."""
        from lib import manifest
        row = manifest.load().get("video") or {}
        bound = os.path.basename(row.get("path", "")).replace(".mp4", "")
        foreign = "shot-02" if bound != "shot-02" else "shot-01"
        with _ManifestState(bound):  # pin the row to `bound` explicitly
            before = None
            if os.path.exists(GATES_JSON):
                with open(GATES_JSON, "rb") as f:
                    before = f.read()
            res = gate(f"spec/{foreign}.poster.json")
            self.assertNotEqual(res.returncode, 0,
                                f"S4 blessed {bound}'s frames for {foreign}'s spec")
            self.assertIn(foreign, res.stderr, f"stderr must name the shot: {res.stderr}")
            if before is not None:
                with open(GATES_JSON, "rb") as f:
                    self.assertEqual(before, f.read(),
                                     "a refused gate must not rewrite gates.json")
            else:
                self.assertFalse(os.path.exists(GATES_JSON),
                                 "a refused gate must not write gates.json")

    def test_gate_accepts_bound_shot(self):
        """The shot whose render is bound in the manifest gates green."""
        from lib import manifest
        row = manifest.load().get("video") or {}
        bound = os.path.basename(row.get("path", "")).replace(".mp4", "")
        self.assertTrue(bound, "manifest has no video row; run S3 first")
        with _ManifestState(bound):
            res = gate(f"spec/{bound}.poster.json")
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_gate_refuses_replaced_frames(self):
        """Frames swapped after S3 registered the fingerprint must be refused
        by the fingerprint branch (not by some other check)."""
        from lib import manifest
        row = manifest.load().get("video") or {}
        bound = os.path.basename(row.get("path", "")).replace(".mp4", "")
        self.assertTrue(bound, "manifest has no video row; run S3 first")
        first = os.path.join(FRAMES, "00001.png")
        with open(first, "rb") as f:
            original = f.read()
        try:
            import lib.png as png
            from lib import metrics
            w, h = png.read_size(first)
            rgb = bytearray(metrics.read_rgb(first, w, h))
            rgb[0:3] = bytes([rgb[0] ^ 0xFF, rgb[1], rgb[2]])
            png.write_png(first, w, h, bytes(rgb))
            res = gate(f"spec/{bound}.poster.json")
            self.assertNotEqual(res.returncode, 0,
                                "S4 blessed replaced frames: fingerprint not checked")
            self.assertIn("fingerprint", res.stderr,
                          f"must fail on the fingerprint branch: {res.stderr}")
        finally:
            with open(first, "wb") as f:
                f.write(original)

    def test_gate_refuses_manifest_without_fingerprint(self):
        """A manifest row predating frame binding (no frames_sha) must be
        refused with a pointer to re-run S3."""
        from lib import manifest
        row = manifest.load().get("video") or {}
        bound = os.path.basename(row.get("path", "")).replace(".mp4", "")
        self.assertTrue(bound, "manifest has no video row; run S3 first")
        with open(MANIFEST, "rb") as f:
            saved = f.read()
        try:
            with open(MANIFEST) as f:
                m = json.load(f)
            row = dict(m["video"])
            row.pop("frames_sha", None)
            m["video"] = row
            with open(MANIFEST, "w") as f:
                json.dump(m, f, indent=2, sort_keys=True)
            res = gate(f"spec/{bound}.poster.json")
            self.assertNotEqual(res.returncode, 0,
                                "S4 blessed frames with no registered fingerprint")
            self.assertIn("frames_sha", res.stderr,
                          f"must name the missing binding: {res.stderr}")
        finally:
            with open(MANIFEST, "wb") as f:
                f.write(saved)


if __name__ == "__main__":
    unittest.main()
