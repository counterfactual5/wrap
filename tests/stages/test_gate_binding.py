"""Gate binding: S4 must refuse to measure another shot's frames or replaced frames.
The manifest video section is keyed per shot (m["video"][shot_id]) and pins what
the shot's frames contained when S3 rendered them (frames_sha); 04_gate verifies
the row and the fingerprint before measuring, so a stale or foreign frame
directory cannot produce a passing verdict.

The cases are self-sufficient: any state the manifest happens to be in (which
shots were rendered last) is set up and restored inside each test, so the suite
stays green after any legal workflow (including `pipeline.py concat`)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.helpers import active_manifest_path, ensure_rendered, preserve_manifest
FRAMES_ROOT = os.path.join(ROOT, "build", "frames")

# The shot these tests bind to. It is rendered by setUp: the binding checks
# need a real render (frames + a manifest row that points at them), and
# `make clean` removes build/, so relying on a leftover artifact made the
# suite fail for a reason unrelated to what it verifies.
BOUND = "shot-01"
BOUND_SPEC = "tests/fixtures/shot-01.poster.json"


def gate(spec):
    return subprocess.run(
        [sys.executable, "stages/04_gate.py", "--spec", spec],
        cwd=ROOT, env=dict(os.environ, POSTER_MANIFEST=active_manifest_path()),
        capture_output=True, text=True, timeout=60)


def gates_path_for(shot_id):
    return os.path.join(ROOT, "build", "gates", f"{shot_id}.json")


def frames_dir_for(shot_id):
    return os.path.join(FRAMES_ROOT, shot_id)


class _ManifestState:
    """Rebind the manifest video row of a shot, restoring the original bytes
    afterwards. sha256/bytes stay those of the row read from disk, so this only
    makes sense for pinning the row to the shot it already describes (that is
    what the tests use it for); frame directories stay untouched — the mismatch
    between a row and the real frames is exactly the scenario under test."""

    def __init__(self, shot_id):
        self.shot_id = shot_id
        self.saved = None
        self.path = None

    def __enter__(self):
        self.path = active_manifest_path()
        with open(self.path, "rb") as f:
            self.saved = f.read()
        with open(self.path) as f:
            m = json.load(f)
        video = m.get("video") or {}
        if "path" in video:  # legacy single-row manifest
            video = {os.path.basename(video["path"]).replace(".mp4", ""): video}
        row = dict(video.get(self.shot_id) or {})
        row["path"] = f"build/{self.shot_id}.mp4"
        video[self.shot_id] = row
        m["video"] = video
        with open(self.path, "w") as f:
            json.dump(m, f, indent=2, sort_keys=True)
        return self

    def __exit__(self, *exc):
        with open(self.path, "wb") as f:
            f.write(self.saved)


class TestGateBinding(unittest.TestCase):
    def _unrendered_shot(self):
        """A spec that exists on disk but has no rendered mp4 and no manifest
        video row — so S4 has no render bound to it and must refuse.

        The spec is written by this test, so the scenario holds whatever else
        has been rendered before: picking a fixed shot made the test pass
        vacuously once that shot had been rendered by something else."""
        from core.runtime import manifest
        shot_id = "gate-unbound-shot"
        spec_path = os.path.join(ROOT, "tests", "fixtures", f"{shot_id}.poster.json")
        with open(os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")) as f:
            spec = json.load(f)
        spec["id"] = shot_id
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)
        self.addCleanup(lambda: os.path.exists(spec_path) and os.remove(spec_path))
        # It must be genuinely unbound.
        if manifest.verified("video", shot_id) is not None:
            self.skipTest(f"{shot_id} unexpectedly has a manifest video row")
        return shot_id

    def setUp(self):
        # Render FIRST, then snapshot: the render registers the manifest row
        # these tests bind to, and the snapshot must preserve it — restoring a
        # pre-render manifest would leave the shot unbound and every gate
        # would refuse for the wrong reason.
        try:
            ensure_rendered(BOUND_SPEC, BOUND)
        except Exception as ex:
            self.skipTest(f"could not render {BOUND}: {ex}")
        self.manifest_path = active_manifest_path()
        with open(self.manifest_path, "rb") as f:
            self.manifest_snapshot = f.read()
        self._manifest = preserve_manifest(self.manifest_path)
        self._manifest.__enter__()

    def tearDown(self):
        self._manifest.__exit__(None, None, None)
        with open(self.manifest_path, "rb") as f:
            self.assertEqual(self.manifest_snapshot, f.read())

    def test_gate_refuses_foreign_frames(self):
        """Gating a shot with no bound render must fail, name the shot in
        stderr, and not write that shot's gates file.

        The foreign shot is one this test creates and never renders, so the
        scenario does not depend on what happens to be rendered already —
        picking a fixed shot-02 made the test pass vacuously once that shot
        had been rendered by something else."""
        from core.runtime import manifest
        video = manifest.load().get("video") or {}
        bound = BOUND if BOUND in video else None
        if bound is None:
            self.skipTest("manifest has no video row for the bound shot; run S3 first")
        foreign = self._unrendered_shot()
        gp = gates_path_for(foreign)
        before = None
        if os.path.exists(gp):
            with open(gp, "rb") as f:
                before = f.read()
        res = gate(f"tests/fixtures/{foreign}.poster.json")
        self.assertNotEqual(res.returncode, 0,
                            f"S4 blessed {bound}'s frames for {foreign}'s spec")
        self.assertIn(foreign, res.stderr, f"stderr must name the shot: {res.stderr}")
        if before is not None:
            with open(gp, "rb") as f:
                self.assertEqual(before, f.read(),
                                 "a refused gate must not rewrite the gates file")
        else:
            self.assertFalse(os.path.exists(gp),
                             "a refused gate must not write a gates file")

    def test_gate_accepts_bound_shot(self):
        """The shot whose render is bound in the manifest gates green."""
        from core.runtime import manifest
        video = manifest.load().get("video") or {}
        bound = BOUND if BOUND in video else None
        if bound is None:
            self.skipTest("manifest has no video row for the bound shot; run S3 first")
        if not os.path.isdir(frames_dir_for(bound)):
            self.skipTest(f"run S3 for {bound} first (per-shot frames missing)")
        with _ManifestState(bound):
            res = gate(f"tests/fixtures/{bound}.poster.json")
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_gate_refuses_replaced_frames(self):
        """Frames swapped after S3 registered the fingerprint must be refused
        by the fingerprint branch (not by some other check)."""
        from core.runtime import manifest
        video = manifest.load().get("video") or {}
        bound = BOUND if BOUND in video else None
        if bound is None:
            self.skipTest("manifest has no video row for the bound shot; run S3 first")
        frames_dir = frames_dir_for(bound)
        if not os.path.isdir(frames_dir):
            self.skipTest(f"run S3 for {bound} first (per-shot frames missing)")
        first = os.path.join(frames_dir, "00001.png")
        with open(first, "rb") as f:
            original = f.read()
        try:
            import core.media.png as png
            from core.quality import pixels as metrics
            w, h = png.read_size(first)
            rgb = bytearray(metrics.read_rgb(first, w, h))
            rgb[0:3] = bytes([rgb[0] ^ 0xFF, rgb[1], rgb[2]])
            png.write_png(first, w, h, bytes(rgb))
            res = gate(f"tests/fixtures/{bound}.poster.json")
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
        from core.runtime import manifest
        video = manifest.load().get("video") or {}
        bound = BOUND if BOUND in video else None
        if bound is None:
            self.skipTest("manifest has no video row for the bound shot; run S3 first")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.json")
            with open(path, "wb") as f:
                f.write(self.manifest_snapshot)
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": path}):
                self.assertEqual(active_manifest_path(), os.path.abspath(manifest.PATH))
                probe = subprocess.run(
                    [sys.executable, "-c",
                     "import os; from core.runtime import manifest; "
                     "print(os.path.abspath(manifest.PATH))"],
                    cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(probe.returncode, 0, probe.stderr)
                self.assertEqual(active_manifest_path(), probe.stdout.strip())
                with _ManifestState(bound):
                    with open(active_manifest_path()) as f:
                        m = json.load(f)
                    self.assertIn("frames_sha", m["video"][bound])
                    m["video"][bound].pop("frames_sha")
                    with open(active_manifest_path(), "w") as f:
                        json.dump(m, f, indent=2, sort_keys=True)
                    self.assertNotIn("frames_sha", manifest.load()["video"][bound])
                    res = gate(f"tests/fixtures/{bound}.poster.json")
                    self.assertNotEqual(res.returncode, 0,
                                        "S4 blessed frames with no registered fingerprint")
                    self.assertIn("frames_sha", res.stderr,
                                  f"must name the missing binding: {res.stderr}")
                with open(path, "rb") as f:
                    self.assertEqual(self.manifest_snapshot, f.read())


if __name__ == "__main__":
    unittest.main()
