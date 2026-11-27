"""A cut whose audio falls to digital silence is a clipped sound, not a fade.

Measured in the field: the third shot of a real film began 27.9 ms after its
picture (the model's sound lagged the image), so the cut fell inside that gap
and the assembled film carried 27.5 ms of digital silence under it. The
dip-and-recover gate calls that clean - its span is below the 40 ms that gate
requires - so the gap needed its own measurement.

What counts as a gap: the sound is present on BOTH sides of it, the gap is
short (10-100 ms) and it touches the cut. A film that is silent on purpose
has no gap to report; a long silence with the sound resuming right after it
is the next shot starting quietly, not a clipped sound.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.assembly.timeline import gate_full_video

BUILD = os.path.join(ROOT, "build", "tmp-seam-gap")


def _film(path, gap_start=1.2, gap_seconds=0.0275, total=2.4, fps=30,
          volume=1.0, silent=False):
    """A film whose audio is silenced for `gap_seconds` starting at `gap_start`.

    `silent=True` silences the whole track (a film with no soundtrack by
    design); `volume` scales the track down around the gap.
    """
    if silent:
        af = "volume=0"
    else:
        af = (f"volume=enable='between(t,{gap_start},{gap_start + gap_seconds})':volume=0")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=gray:s=320x180:r={fps}:d={total}",
         "-f", "lavfi", "-i", f"sine=frequency=200:duration={total}",
         "-af", af,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", path],
        check=True, timeout=120)


def _gates(timeline_id):
    with open(os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")) as f:
        return {r["id"]: r for r in json.load(f)}


class SeamDigitalGap(unittest.TestCase):
    def setUp(self):
        os.makedirs(BUILD, exist_ok=True)

    def test_a_short_digital_gap_at_a_cut_fails(self):
        film = os.path.join(BUILD, "gap.mp4")
        _film(film, gap_start=1.2, gap_seconds=0.0275)
        gate_full_video(film, "gap-short", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-short")
        self.assertIn("seam_digital_gap", rows)
        self.assertFalse(rows["seam_digital_gap"]["pass"],
                         f"a digital gap at a cut must fail: {rows['seam_digital_gap']}")

    def test_a_film_without_a_gap_passes(self):
        film = os.path.join(BUILD, "clean.mp4")
        _film(film, gap_start=1.2, gap_seconds=0.0)
        gate_full_video(film, "gap-clean", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-clean")
        self.assertTrue(rows["seam_digital_gap"]["pass"],
                        f"a continuous soundtrack has no digital gap: {rows['seam_digital_gap']}")

    def test_a_film_that_is_silent_on_purpose_has_no_gap_to_report(self):
        film = os.path.join(BUILD, "silent.mp4")
        _film(film, silent=True)
        gate_full_video(film, "gap-silent", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-silent")
        self.assertTrue(rows["seam_digital_gap"]["pass"],
                        f"a deliberately silent film is not a gapped film: {rows['seam_digital_gap']}")

    def test_a_long_silence_is_a_pause_not_a_clipped_sound(self):
        film = os.path.join(BUILD, "pause.mp4")
        # 0.5 s of silence with the sound resuming right after it: the next
        # shot starting quietly, not a clipped sound.
        _film(film, gap_start=1.2, gap_seconds=0.5)
        gate_full_video(film, "gap-pause", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-pause")
        self.assertTrue(rows["seam_digital_gap"]["pass"],
                        f"a long silence is a pause, not a gap: {rows['seam_digital_gap']}")

    def test_a_gap_that_does_not_touch_the_cut_is_not_this_gates_business(self):
        film = os.path.join(BUILD, "midshot.mp4")
        # The gap sits 0.3 s before the cut: a dropout inside a shot.
        _film(film, gap_start=0.9, gap_seconds=0.0275)
        gate_full_video(film, "gap-midshot", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-midshot")
        self.assertTrue(rows["seam_digital_gap"]["pass"],
                        f"a dropout away from the cut is not a seam gap: {rows['seam_digital_gap']}")

    def test_the_dip_gate_keeps_its_own_verdict(self):
        """The two rows are independent: a dip that recovers is still a hole,
        and a digital gap is not a dip."""
        film = os.path.join(BUILD, "both.mp4")
        _film(film, gap_start=1.2, gap_seconds=0.0275)
        gate_full_video(film, "gap-both", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("gap-both")
        self.assertFalse(rows["seam_digital_gap"]["pass"])
        # The dip-and-recover gate measures an envelope dip; a 27.5 ms gap
        # is below its 40 ms span, so it stays clean. The two rows must not
        # be one verdict wearing two names.
        self.assertTrue(rows["seam_audio_hole"]["pass"],
                        f"a digital gap is not an envelope dip: {rows['seam_audio_hole']}")


if __name__ == "__main__":
    unittest.main()
