"""One pixel format for the whole frame sequence, and the master/video binding.

The defect these cover: Remotion writes RGBA only for the frames that carry
transparency and RGB for the rest, so a rendered sequence can mix color types.
The PNG demuxer then changes the decoded format mid-stream, ffmpeg
reconfigures the filter graph, the overlay's frame sync is reset, and the
encoder emits the bare background sheet (a black frame) at positions that
differ from run to run - so the delivered video stops matching the frame
master it was encoded from.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

from core.media.png import write_png, write_png_rgba
from core.rendering.frames import (
    COLOR_TYPE_RGBA,
    MASTER_DELTA_LIMIT,
    convert_frame_formats,
    master_video_deltas,
    normalize_frame_formats,
    png_color_type,
    sequence_color_types,
)


def _ffmpeg_available():
    return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


def _write_sequence(frames_dir, count, transparent_at=()):
    """A frame sequence where `transparent_at` holds alpha and the rest is RGB."""
    os.makedirs(frames_dir, exist_ok=True)
    w, h = 8, 6
    for i in range(1, count + 1):
        path = os.path.join(frames_dir, f"{i:05d}.png")
        if i in transparent_at:
            # Fully transparent, as an opacity-0 layer renders: RGB black.
            write_png_rgba(path, w, h, b"\x00" * (w * h * 4))
        else:
            rgb = bytes((30 + i, 40 + i, 50 + i)) * (w * h)
            write_png(path, w, h, rgb)


class FrameFormatTests(unittest.TestCase):
    def test_color_type_is_read_from_the_png_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            rgb = os.path.join(tmp, "a.png")
            rgba = os.path.join(tmp, "b.png")
            write_png(rgb, 2, 2, b"\x10" * 12)
            write_png_rgba(rgba, 2, 2, b"\x10" * 16)
            self.assertEqual(png_color_type(rgb), 2)
            self.assertEqual(png_color_type(rgba), COLOR_TYPE_RGBA)

    def test_uniform_sequence_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 3)
            before = sorted((n, open(os.path.join(frames, n), "rb").read())
                            for n in os.listdir(frames))
            report = normalize_frame_formats(frames, 30)
            self.assertFalse(report["normalized"])
            self.assertEqual(report["color_types"], [2])
            after = sorted((n, open(os.path.join(frames, n), "rb").read())
                           for n in os.listdir(frames))
            self.assertEqual(before, after)

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg unavailable")
    def test_mixed_sequence_is_normalized_to_one_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 4, transparent_at=(2,))
            self.assertEqual(sorted(sequence_color_types(frames)), [2, 6])
            report = normalize_frame_formats(frames, 30)
            self.assertTrue(report["normalized"])
            self.assertEqual(report["frames"], 4)
            self.assertEqual(report["transparent_frames"], 1)
            self.assertEqual(sorted(sequence_color_types(frames)), [COLOR_TYPE_RGBA])
            # No leftovers from the conversion.
            self.assertEqual(sorted(n for n in os.listdir(frames) if n.endswith(".png")),
                             ["00001.png", "00002.png", "00003.png", "00004.png"])

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg unavailable")
    def test_normalization_keeps_the_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 3, transparent_at=(2,))
            before = os.path.join(tmp, "before")
            shutil.copytree(frames, before)
            normalize_frame_formats(frames, 30)
            for i in range(1, 4):
                name = f"{i:05d}.png"
                raw_old = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", os.path.join(before, name),
                     "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                    capture_output=True).stdout
                raw_new = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", os.path.join(frames, name),
                     "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                    capture_output=True).stdout
                self.assertEqual(len(raw_old), len(raw_new))
                # RGB is copied verbatim; alpha is preserved (or added opaque).
                for px in range(0, len(raw_old), 4):
                    self.assertEqual(raw_old[px:px + 3], raw_new[px:px + 3])
                if i == 2:
                    self.assertEqual(raw_new[3], 0)   # transparency survives
                else:
                    self.assertEqual(raw_new[3], 255)  # opaque alpha added

    def test_a_sequence_that_is_not_contiguous_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 3, transparent_at=(2,))
            os.rename(os.path.join(frames, "00002.png"),
                      os.path.join(frames, "00009.png"))
            with self.assertRaises(RuntimeError) as ctx:
                normalize_frame_formats(frames, 30)
            self.assertIn("contiguous", str(ctx.exception))

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg unavailable")
    def test_convert_leaves_the_master_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            work = os.path.join(tmp, "work")
            _write_sequence(frames, 3, transparent_at=(2,))
            before = open(os.path.join(frames, "00001.png"), "rb").read()
            out = convert_frame_formats(frames, work, 30)
            self.assertEqual(out, work)
            self.assertEqual(open(os.path.join(frames, "00001.png"), "rb").read(), before)
            self.assertEqual(sorted(sequence_color_types(out)), [COLOR_TYPE_RGBA])


class MasterVideoBindingTests(unittest.TestCase):
    """The mp4 must show the frame master's picture, frame by frame."""

    SPEC = {"id": "t", "fps": 30, "canvas": {"w": 8, "h": 6}, "durationInFrames": 4}

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg unavailable")
    def test_a_matching_video_shows_no_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 4, transparent_at=(2,))
            work = os.path.join(tmp, "work")
            uniform = convert_frame_formats(frames, work, 30)
            mp4 = os.path.join(tmp, "t.mp4")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=8x6:r=30",
                 "-framerate", "30", "-i", os.path.join(uniform, "%05d.png"),
                 "-filter_complex", "[0:v][1:v]overlay=shortest=1[v]",
                 "-map", "[v]", "-frames:v", "4",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                 "-pix_fmt", "yuv420p", mp4],
                check=True, capture_output=True)
            deltas = master_video_deltas(self.SPEC, uniform, mp4, canvas_bg="black")
            self.assertEqual(len(deltas), 4)
            self.assertLessEqual(max(d[1] for d in deltas), MASTER_DELTA_LIMIT)

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg unavailable")
    def test_a_video_with_a_lost_frame_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_sequence(frames, 4, transparent_at=(2,))
            work = os.path.join(tmp, "work")
            uniform = convert_frame_formats(frames, work, 30)
            mp4 = os.path.join(tmp, "t.mp4")
            # The defect this gate exists for: the picture drops out and the
            # bare background sheet takes its place.
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=8x6:r=30",
                 "-framerate", "30", "-i", os.path.join(uniform, "%05d.png"),
                 "-filter_complex",
                 "[0:v][1:v]overlay=shortest=1[v];"
                 "[v]trim=start_frame=0:end_frame=1,setpts=PTS-STARTPTS[keep];"
                 "[v]trim=start_frame=3:end_frame=4,setpts=PTS-STARTPTS[last];"
                 "[keep][last]concat=n=2:v=1:a=0[out]",
                 "-map", "[out]", "-frames:v", "4",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                 "-pix_fmt", "yuv420p", mp4],
                check=True, capture_output=True)
            deltas = master_video_deltas(self.SPEC, uniform, mp4, canvas_bg="black")
            self.assertGreater(max(d[1] for d in deltas), MASTER_DELTA_LIMIT)


if __name__ == "__main__":
    unittest.main()
