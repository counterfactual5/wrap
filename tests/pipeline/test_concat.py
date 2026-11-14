"""Test multi-shot concat command."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.helpers import ensure_rendered, preserve_manifest


class TestConcat(unittest.TestCase):
    def test_00_concat_builds_a_missing_shot_end_to_end(self):
        """A shot with no rendered mp4 must be built by the concat command
        itself — assets, preparation, render, gate — not just rendered.

        S3 refuses to render without the prepared rows, so a build contract
        that runs only S3+S4 leaves a fresh checkout dead on "prepared
        '<shot>/<layer>' not manifest-verified"."""
        shot_spec = "tests/fixtures/shot-01.poster.json"
        mp4 = os.path.join(ROOT, "build", "shot-01.mp4")
        frames = os.path.join(ROOT, "build", "frames", "shot-01")
        prepared = os.path.join(ROOT, "build", "prepared", "shot-01")

        existed = os.path.exists(mp4)
        backup = None
        if existed:
            backup = mp4 + ".bak"
            os.replace(mp4, backup)
        try:
            tl_path = os.path.join(ROOT, "build", "test_timeline.json")
            out_mp4 = os.path.join(ROOT, "build", "test_full_concat.mp4")
            os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
            with open(tl_path, "w") as f:
                json.dump({"id": "full-sequence", "shots": [shot_spec]}, f, indent=2)
            try:
                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path,
                     "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0,
                                 f"concat could not build the missing shot:\n"
                                 f"{res.stdout}\n{res.stderr}")
                self.assertTrue(os.path.exists(out_mp4))
                self.assertTrue(os.path.exists(prepared),
                                "the build contract must prepare the assets too")
                gates_path = os.path.join(ROOT, "build", "gates_full_full-sequence.json")
                self.assertTrue(os.path.exists(gates_path))
                with open(gates_path) as f:
                    gates = json.load(f)
                for g in gates:
                    self.assertTrue(g["pass"], f"gate {g['id']} failed: {g}")
            finally:
                for p in (tl_path, out_mp4,
                          os.path.join(ROOT, "build", "gates_full_full-sequence.json")):
                    if os.path.exists(p):
                        os.remove(p)
        finally:
            if backup is not None:
                os.replace(backup, mp4)

    def test_concat_command(self):
        # 1. Test help
        res = subprocess.run([sys.executable, "pipeline.py", "concat", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, "pipeline.py concat help failed")

        # 2. Test actual concat with a temporary timeline
        tl_path = os.path.join(ROOT, "build", "test_timeline.json")
        out_mp4 = os.path.join(ROOT, "build", "test_full_concat.mp4")
        os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
        with open(tl_path, "w") as f:
            json.dump({"id": "full-sequence", "shots": ["tests/fixtures/shot-01.poster.json"]}, f, indent=2)

        with preserve_manifest():
            try:
                # The shot must be rendered before it can be assembled —
                # `make clean` removes build/, and the dependency used to be
                # implicit in a leftover artifact.
                ensure_rendered("tests/fixtures/shot-01.poster.json", "shot-01")

                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path, "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True
                )
                self.assertEqual(res.returncode, 0, f"concat execution failed:\n{res.stderr}")
                self.assertTrue(os.path.exists(out_mp4))
                self.assertGreater(os.path.getsize(out_mp4), 1000)

                # Full-video gates: written per timeline id, all entries pass,
                # duration is always gated (audio gates only when a track exists).
                gates_path = os.path.join(ROOT, "build", "gates_full_full-sequence.json")
                self.assertTrue(os.path.exists(gates_path), "full-video gates file missing")
                with open(gates_path) as f:
                    gates = json.load(f)
                self.assertTrue(gates, "full-video gates empty")
                for g in gates:
                    self.assertTrue(g["pass"], f"Full-video gate {g['id']} failed: {g}")
                ids = {g["id"] for g in gates}
                self.assertIn("duration", ids)
                self.assertIn("black", ids)
            finally:
                for p in (tl_path, out_mp4,
                          os.path.join(ROOT, "build", "gates_full_full-sequence.json")):
                    if os.path.exists(p):
                        os.remove(p)



    def test_01_timeline_bgm_overlays_full_film(self):
        """A timeline declaring top-level bgm overlays and masters BGM across silent shots."""
        from core import audio
        ensure_rendered("tests/fixtures/shot-01.poster.json", "shot-01")
        tl_path = os.path.join(ROOT, ".tmp", "test_tl_bgm.json")
        out_mp4 = os.path.join(ROOT, ".tmp", "test_tl_bgm_out.mp4")
        os.makedirs(os.path.dirname(tl_path), exist_ok=True)
        with open(tl_path, "w") as f:
            json.dump({
                "id": "tl-bgm-seq",
                "bgm": "ambient",
                "shots": ["tests/fixtures/shot-01.poster.json"]
            }, f, indent=2)
        with preserve_manifest():
            try:
                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path, "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True
                )
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                self.assertIn("timeline bgm:", res.stdout)
                lufs = audio.measure_audio_loudness(out_mp4)
                self.assertIsNotNone(lufs)
                self.assertAlmostEqual(lufs, -16.0, delta=1.5)
            finally:
                for p in (tl_path, out_mp4, os.path.join(ROOT, "build", "gates_full_tl-bgm-seq.json")):
                    if os.path.exists(p):
                        os.remove(p)


if __name__ == "__main__":
    unittest.main()


class TestConcatAudioAlignment(unittest.TestCase):
    """Concat must not leave one shot's audio at the head of the next.

    The concat demuxer copies both streams byte-for-byte and places each
    file's audio by its own track duration. AAC frames are 1024 samples, so a
    shot's audio track is a few ms shorter than its video, and those ms
    accumulate shot after shot: the tail of one shot's audio lands at the
    head of the next. On a shot declared SILENT that shows up as a burst of
    the previous shot's sound — audible at the cut, and fatal for the
    full-video loudness_jump gate.

    The regression signature: the assembled file's AUDIO is much longer than
    its VIDEO, and the silent segment is not silent.
    """

    def _build_audible_spec(self, tmpdir):
        """A copy of the fixture with a locally generated ambient bed.

        The ambient drone is synthesized locally (no network, no credits), so
        this shot is audible at the -16 LUFS target without a TTS call.
        """
        with open(os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")) as f:
            spec = json.load(f)
        spec["id"] = "concat-audible"
        spec["audio"] = {"bgm": "ambient"}
        path = os.path.join(tmpdir, "concat-audible.poster.json")
        with open(path, "w") as f:
            json.dump(spec, f, indent=2)
        return path

    def test_00_silent_segment_stays_silent_and_audio_matches_video(self):
        from core import audio
        tmpdir = os.path.join(ROOT, ".tmp", "concat-audio-test")
        os.makedirs(tmpdir, exist_ok=True)
        audible_spec = self._build_audible_spec(tmpdir)
        tl_path = os.path.join(tmpdir, "timeline.json")
        out_mp4 = os.path.join(tmpdir, "out.mp4")
        with open(tl_path, "w") as f:
            json.dump({"id": "concat-audio-test", "shots": [
                {"spec": audible_spec, "beat": "hook", "reason": "audible"},
                {"spec": "tests/fixtures/shot-01.poster.json",
                 "beat": "resolution", "reason": "silent"},
            ]}, f, indent=2)

        with preserve_manifest():
            try:
                res = subprocess.run(
                    [sys.executable, "pipeline.py", "concat", "--timeline", tl_path,
                     "--output", out_mp4],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"concat failed:\n{res.stderr}")

                av = audio.measure_av_durations(out_mp4)
                self.assertTrue(av.get("has_audio"), "assembled film carries no audio track")
                # The bug's signature: the audio outran the video by seconds.
                self.assertLess(
                    abs(av["audio_duration"] - av["video_duration"]), 0.25,
                    f"audio/video duration drift: audio={av['audio_duration']} "
                    f"video={av['video_duration']}")

                # The second shot is silent BY DESIGN, so the tail of the
                # assembled audio must be silent too.
                shot_seconds = 150 / 30
                tail = audio.measure_audio_silence(
                    out_mp4, start=shot_seconds + 0.3, duration=shot_seconds - 0.6)
                self.assertTrue(
                    tail["is_silent"],
                    f"the silent shot is not silent at the seam: "
                    f"max={tail['max_volume']} dB")

                gates_path = os.path.join(
                    ROOT, "build", "gates_full_concat-audio-test.json")
                with open(gates_path) as f:
                    gates = json.load(f)
                for g in gates:
                    self.assertTrue(g["pass"], f"Full-video gate {g['id']} failed: {g}")
            finally:
                for p in (out_mp4, os.path.join(ROOT, "build", "gates_full_concat-audio-test.json")):
                    if os.path.exists(p):
                        os.remove(p)


class TestRunTimeline(unittest.TestCase):
    """`run --timeline` renders the shots IN ORDER and seams them as it goes.

    The order is the whole point: shot k+1's first_frame may name the asset
    shot k produces, so shot k has to be GENERATED before shot k+1's S1 runs.
    Carrying that ordering in your head is the fragile part; here the timeline
    is the only thing the author has to get right.
    """

    def _write_specs(self, tmpdir):
        with open(os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")) as f:
            shot1 = json.load(f)
        shot1["id"] = "tl-shot-1"
        # A locally generated BGM bed: audible, and no network / no credits.
        shot1["audio"] = {"bgm": "ambient"}
        p1 = os.path.join(tmpdir, "tl-shot-1.poster.json")
        with open(p1, "w") as f:
            json.dump(shot1, f, indent=2)

        shot2 = {
            "id": "tl-shot-2",
            "canvas": {"w": 1920, "h": 1080, "bg": "#070512"},
            "fps": 30, "durationInFrames": 60,
            "style": "tests/fixtures/style.json",
            "layers": [{
                "id": "clip", "type": "video", "asset": "tl-clip",
                "model": "MiniMax-Hailuo-2.3", "duration": 6, "resolution": "768P",
                "first_frame": "tl-shot-1-tail",
                "rect": [0, 0, 1920, 1080], "z": 0, "plate": False, "muted": True,
            }],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0005, "hi": 0.15, "lumaDelta": 6}],
        }
        p2 = os.path.join(tmpdir, "tl-shot-2.poster.json")
        with open(p2, "w") as f:
            json.dump(shot2, f, indent=2)

        tl_path = os.path.join(tmpdir, "timeline.json")
        with open(tl_path, "w") as f:
            json.dump({"id": "run-timeline-test", "shots": [
                {"spec": p1, "beat": "hook", "reason": "first"},
                {"spec": p2, "beat": "resolution", "reason": "seams on the first shot's tail"},
            ]}, f, indent=2)
        return tl_path

    def test_00_seam_is_frozen_automatically_and_the_film_assembles(self):
        from core.runtime import manifest
        tmpdir = os.path.join(ROOT, ".tmp", "run-timeline-test")
        os.makedirs(tmpdir, exist_ok=True)
        tl_path = self._write_specs(tmpdir)
        out_mp4 = os.path.join(tmpdir, "film.mp4")

        with preserve_manifest():
            try:
                # --force: S1 must build the clip with the CURRENT fixture code.
                # Without it a placeholder frozen in the ledger by an earlier
                # run is reused, and the test silently checks yesterday's clip.
                res = subprocess.run(
                    [sys.executable, "pipeline.py", "run", "--timeline", tl_path,
                     "--output", out_mp4, "--fixture", "--force"],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0,
                                 f"run --timeline failed:\n{res.stdout}\n{res.stderr}")
                self.assertIn("seam: freezing tl-shot-1-tail", res.stdout)

                # The seam is a real frozen asset, not a loose file.
                row = manifest.verified("assets", "tl-shot-1-tail")
                self.assertIsNotNone(row, "the seam was not frozen into the manifest")
                self.assertEqual(row["source"], "extracted")

                # And the film exists with its full-video gates green.
                self.assertTrue(os.path.exists(out_mp4))
                gates_path = os.path.join(
                    ROOT, "build", "gates_full_run-timeline-test.json")
                with open(gates_path) as f:
                    gates = json.load(f)
                for g in gates:
                    self.assertTrue(g["pass"], f"Full-video gate {g['id']} failed: {g}")
            finally:
                for p in (out_mp4,
                          os.path.join(ROOT, "build", "gates_full_run-timeline-test.json")):
                    if os.path.exists(p):
                        os.remove(p)
