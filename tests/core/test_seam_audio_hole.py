"""A cut whose audio dips and recovers is a hole, not a fade.

Measured in the field: the soundtrack stepped down 17 dB at the cut, dipped
for ~0.45 s and came back 1.5 s later, while the picture was black for
100 ms. No segment-averaged loudness number could see it. The whole-film
gate now looks at the level immediately before and after every cut, and
fails when it drops and then recovers — a deliberate fade-out does not
recover, and that is what tells the two apart.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.assembly.timeline import gate_full_video

BUILD = os.path.join(ROOT, "build", "tmp-seam")


def _film(path, dip_start=1.2, dip_seconds=0.45, total=2.4, fps=30, dip_volume=0.02):
    """A film whose audio drops to near-silence for a moment after 0.9 s and
    then comes back — the shape of a hole at a cut."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=gray:s=320x180:r={fps}:d={total}",
         "-f", "lavfi", "-i", f"sine=frequency=200:duration={total}",
         "-af", f"volume=enable='between(t,{dip_start},{dip_start+dip_seconds})':volume={dip_volume}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", path],
        check=True, timeout=120)


def _gates(timeline_id):
    with open(os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")) as f:
        return {r["id"]: r for r in json.load(f)}


class _SeamAudioHole(unittest.TestCase):
    def setUp(self):
        os.makedirs(BUILD, exist_ok=True)

    def test_a_dip_that_recovers_at_a_cut_fails(self):
        film = os.path.join(BUILD, "hole.mp4")
        # The dip starts AT the cut and ends before the recovery window.
        _film(film, dip_start=1.2, dip_seconds=0.45)
        # Two segments, so there is a cut at 1.2 s — right where the dip is.
        gate_full_video(film, "seam-hole", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-hole")
        self.assertIn("seam_audio_hole", rows)
        self.assertFalse(rows["seam_audio_hole"]["pass"],
                         f"a dip that recovers at a cut must fail: {rows['seam_audio_hole']}")

    def test_a_fade_that_stays_down_is_not_a_hole(self):
        film = os.path.join(BUILD, "fade.mp4")
        # The dip never recovers: the level stays down to the end.
        _film(film, dip_start=1.2, dip_seconds=1.2)
        gate_full_video(film, "seam-fade", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-fade")
        self.assertTrue(rows["seam_audio_hole"]["pass"],
                        f"a fade-out that stays down is not a hole: {rows['seam_audio_hole']}")

    def test_a_dip_immediately_before_a_cut_also_fails(self):
        film = os.path.join(BUILD, "pre-hole.mp4")
        # The dip ends AT the cut, hitting the tail of shot A rather than the head of shot B.
        _film(film, dip_start=0.80, dip_seconds=0.40)
        gate_full_video(film, "seam-pre-hole", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-pre-hole")
        self.assertIn("seam_audio_hole", rows)
        self.assertFalse(rows["seam_audio_hole"]["pass"],
                         f"a pre-cut dip that recovers at a cut must fail: {rows['seam_audio_hole']}")

    def test_a_short_crossfade_at_cut_passes(self):
        film = os.path.join(BUILD, "crossfade.mp4")
        # An 80 ms cross-shot fade centered on the cut is normal audio shaping, not a hole.
        _film(film, dip_start=1.16, dip_seconds=0.08)
        gate_full_video(film, "seam-crossfade", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-crossfade")
        self.assertTrue(rows["seam_audio_hole"]["pass"],
                        f"a short 80 ms crossfade at a cut should pass: {rows['seam_audio_hole']}")

    def test_a_short_deep_dip_at_a_cut_fails(self):
        """A 90 ms / 16 dB dip is short enough that a long analysis window
        averages it away, and deep enough that a viewer hears it. The gate
        used to write "no hole" over exactly this shape: measured on a real
        cut, a 250 ms window's RMS moved by only 1.9 dB."""
        film = os.path.join(BUILD, "short-deep-hole.mp4")
        _film(film, dip_start=1.2, dip_seconds=0.09, dip_volume=0.16)
        gate_full_video(film, "seam-short-deep", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-short-deep")
        self.assertFalse(rows["seam_audio_hole"]["pass"],
                         f"a short deep dip that recovers at a cut must fail: {rows['seam_audio_hole']}")

    def test_a_short_deep_dip_before_a_cut_fails(self):
        film = os.path.join(BUILD, "short-deep-pre-hole.mp4")
        _film(film, dip_start=1.11, dip_seconds=0.09, dip_volume=0.16)
        gate_full_video(film, "seam-short-deep-pre", [("a", 0.0, 1.2), ("b", 1.2, 1.2)], allow_black=False)
        rows = _gates("seam-short-deep-pre")
        self.assertFalse(rows["seam_audio_hole"]["pass"],
                         f"a short deep dip before a cut must fail: {rows['seam_audio_hole']}")


if __name__ == "__main__":
    unittest.main()
