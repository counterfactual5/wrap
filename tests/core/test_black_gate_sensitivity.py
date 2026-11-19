"""A short black dip must not pass the whole-film gate as "0 intervals".

Measured in the field: the gate ran blackdetect with d=0.2, so a three-frame
dip (0.1 s at 30 fps) was invisible to it and the gates file said
"blackdetect: 0, pass" over a real 100 ms hole in the picture — while the
soundtrack kept playing through it. The gate now reports the dips it finds,
and fails when the picture goes black while the soundtrack is still audible.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.assembly.timeline import _black_spans, gate_full_video

BUILD = os.path.join(ROOT, "build", "tmp-black")


def _gates(timeline_id):
    path = os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")
    with open(path) as f:
        return json.load(f)


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def _make_film(path, black_frames=3, seconds=1.0, fps=30, with_sound=True):
    """A clip: normal picture, `black_frames` black frames at the seam, then
    normal again — with a continuous soundtrack underneath."""
    total = int(seconds * fps)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if with_sound:
        # The tone runs past the dip: the point of the check is a black frame
        # with the soundtrack still playing.
        cmd += ["-f", "lavfi", "-i", "sine=frequency=200:duration=%f" % (seconds + 0.5)]
    # Three source pictures: colour, black, colour.
    cmd += ["-f", "lavfi", "-i", f"color=c=gray:s=320x180:r={fps}:d={seconds}",
            "-f", "lavfi", "-i", f"color=c=black:s=320x180:r={fps}:d={black_frames/fps}",
            "-f", "lavfi", "-i", f"color=c=gray:s=320x180:r={fps}:d={seconds}"]
    # input 0 is the audio (when present), so the three pictures are 1..3
    vi = 1 if with_sound else 0
    vf = f"[{vi}:v][{vi+1}:v][{vi+2}:v]concat=n=3:v=1:a=0[v]"
    cmd += ["-filter_complex", vf, "-map", "[v]"]
    if with_sound:
        cmd += ["-map", "0:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
    subprocess.run(cmd, check=True, timeout=120)


class _BlackSpanParsing(unittest.TestCase):
    def test_parses_blackdetect_output(self):
        stderr = (
            "[Parsed_blackdetect_0 @ 0x1] black_start:5.933333 black_end:6.033333 "
            "black_duration:0.1\n"
        )
        spans = _black_spans(stderr)
        self.assertEqual(len(spans), 1)
        self.assertAlmostEqual(spans[0]["start"], 5.933333, places=4)
        self.assertAlmostEqual(spans[0]["end"], 6.033333, places=4)
        self.assertAlmostEqual(spans[0]["duration"], 0.1, places=4)

    def test_no_spans_when_blackdetect_is_silent(self):
        self.assertEqual(_black_spans(""), [])


class _ShortBlackDipIsCaught(unittest.TestCase):
    def setUp(self):
        os.makedirs(BUILD, exist_ok=True)

    def test_three_frame_dip_is_not_reported_as_zero_intervals(self):
        film = os.path.join(BUILD, "dip.mp4")
        _make_film(film, black_frames=3, with_sound=True)
        dur = _duration(film)
        segments = [("shot-a", 0.0, dur)]
        gate_full_video(film, "black-test", segments, allow_black=False)
        by_id = {r["id"]: r for r in _gates("black-test")}
        self.assertIn("black", by_id)
        self.assertGreater(by_id["black"]["value"], 0,
                           "a three-frame dip must not read as 0 intervals")
        self.assertFalse(by_id["black"]["pass"])
        # The picture is black while the soundtrack plays: that is the case the
        # gate must fail on, whatever the blackdetect threshold was.
        self.assertIn("black_with_sound", by_id)
        self.assertFalse(by_id["black_with_sound"]["pass"],
                         "a black frame under a playing soundtrack must fail")

    def test_a_clean_film_still_passes(self):
        film = os.path.join(BUILD, "clean.mp4")
        _make_film(film, black_frames=0, with_sound=True)
        gate_full_video(film, "black-clean",
                        [("shot-a", 0.0, _duration(film))], allow_black=False)
        by_id = {r["id"]: r for r in _gates("black-clean")}
        self.assertEqual(by_id["black"]["value"], 0)
        self.assertTrue(by_id["black"]["pass"])


if __name__ == "__main__":
    unittest.main()
