"""The hole guard: the rendered frames must carry the picture the spec promised.

The defect this covers: Remotion paints a video layer from a `<video>`
element, and that element can come up empty on a few frames - the layer
leaves a transparent gap, and the encoder composites the gap over the canvas
background. The delivered film then has a black hole with the soundtrack
still playing under it. Measured on a real H3 clip: a 180-frame shot rendered
with gaps at frames 89 and 90, and the SAME spec re-rendered with none - a
race in the renderer, not a property of the spec. Re-running the pipeline is
not a fix; a guard is.
"""
import os
import tempfile
import unittest

from core.media.png import write_png, write_png_rgba
from core.rendering.compose import compose_frames
from core.rendering.holes import (
    HOLE_TOLERANCE,
    RENDER_ATTEMPTS,
    alpha_basis,
    describe_holes,
    find_holes,
    format_holes,
    measured_opacity,
    required_opacity,
)


def _spec(**over):
    spec = {
        "id": "shot",
        "canvas": {"w": 8, "h": 6},
        "fps": 30,
        "durationInFrames": 3,
        "layers": [
            {"id": "clip", "type": "video", "asset": "clip",
             "rect": [0, 0, 8, 6], "z": 0},
        ],
    }
    spec.update(over)
    return spec


def _write_frames(frames_dir, count, empty_at=(), alpha=255):
    """A frame sequence; the frames listed in `empty_at` are fully transparent."""
    os.makedirs(frames_dir, exist_ok=True)
    for i in range(1, count + 1):
        path = os.path.join(frames_dir, f"{i:05d}.png")
        if i in empty_at:
            write_png_rgba(path, 8, 6, b"\x00" * (8 * 6 * 4))
        elif alpha == 255:
            write_png(path, 8, 6, bytes((30 + i, 40 + i, 50 + i)) * (8 * 6))
        else:
            px = bytes((30 + i, 40 + i, 50 + i, alpha)) * (8 * 6)
            write_png_rgba(path, 8, 6, px)


class RequiredOpacityTests(unittest.TestCase):
    """What the spec promises: the strongest lower bound the video layers give."""

    def test_a_video_layer_covering_the_canvas_promises_a_full_frame(self):
        self.assertEqual(required_opacity(_spec()), [1.0, 1.0, 1.0])

    def test_a_smaller_rect_promises_only_its_own_area(self):
        spec = _spec()
        spec["layers"][0]["rect"] = [0, 0, 4, 6]
        self.assertEqual(required_opacity(spec), [0.5, 0.5, 0.5])

    def test_a_contained_clip_letterboxes_its_rect_and_promises_nothing(self):
        spec = _spec()
        spec["layers"][0]["fit"] = "contain"
        self.assertEqual(required_opacity(spec), [0.0, 0.0, 0.0])

    def test_a_faded_layer_promises_nothing_once_it_is_out(self):
        spec = _spec()
        spec["layers"][0]["anim"] = {"opacity": [[0, 1], [2, 0]]}
        req = required_opacity(spec)
        self.assertEqual(req[0], 1.0)
        self.assertLess(req[2], 0.05)

    def test_an_ancestors_opacity_scales_the_promise(self):
        spec = _spec()
        spec["layers"][0]["parent"] = "group"
        spec["layers"].append({"id": "group", "type": "image", "asset": "g",
                                "rect": [0, 0, 8, 6], "z": 1,
                                "anim": {"opacity": [[0, 0.5], [2, 0.5]]}})
        self.assertEqual(required_opacity(spec), [0.5, 0.5, 0.5])


class MeasuredOpacityTests(unittest.TestCase):
    """What the renderer actually drew: the mean alpha over the canvas."""

    def test_opaque_frames_read_as_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3)
            got = measured_opacity(frames, 30)
            self.assertEqual(len(got), 3)
            for value in got:
                self.assertGreater(value, 0.99)

    def test_a_transparent_frame_reads_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3, empty_at=(2,))
            got = measured_opacity(frames, 30)
            self.assertGreater(got[0], 0.99)
            self.assertLess(got[1], 0.01)


class FindHolesTests(unittest.TestCase):
    """The guard's verdict on a rendered sequence."""

    def test_a_clean_sequence_has_no_holes(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3)
            self.assertEqual(find_holes(_spec(), frames, 30), [])

    def test_the_frame_the_renderer_left_empty_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3, empty_at=(2,))
            holes = find_holes(_spec(), frames, 30)
            self.assertEqual([h["frame"] for h in holes], [1])

    def test_a_faded_layer_is_not_a_hole(self):
        spec = _spec()
        spec["layers"][0]["anim"] = {"opacity": [[0, 1], [1, 0], [2, 0]]}
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            # The layer is gone from frame 1 on, and the renderer drew nothing.
            _write_frames(frames, 3, empty_at=(2, 3))
            self.assertEqual(find_holes(spec, frames, 30), [])

    def test_a_frame_the_spec_promises_nothing_about_is_never_a_hole(self):
        spec = _spec()
        spec["layers"] = []
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3, empty_at=(1, 2, 3))
            self.assertEqual(find_holes(spec, frames, 30), [])

    def test_a_frame_within_the_tolerance_is_not_a_hole(self):
        spec = _spec()
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            # alpha 250 -> mean 0.980, still within the tolerance of 1.0.
            _write_frames(frames, 3, alpha=250)
            self.assertEqual(find_holes(spec, frames, 30), [])

    def test_a_frame_beyond_the_tolerance_is_a_hole(self):
        spec = _spec()
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            # alpha 235 -> mean 0.922, below 1.0 - 0.05.
            _write_frames(frames, 3, alpha=235)
            holes = find_holes(spec, frames, 30)
            self.assertEqual([h["frame"] for h in holes], [0, 1, 2])

    def test_the_guard_compares_against_the_tolerance(self):
        self.assertAlmostEqual(HOLE_TOLERANCE, 0.05)

    def test_the_message_names_the_frames(self):
        message = format_holes([{"frame": 4}, {"frame": 5}], "shot")
        self.assertIn("shot", message)
        self.assertIn("4", message)
        self.assertIn("5", message)


class ComposeFlowTests(unittest.TestCase):
    """S3's flow: render, prove, re-render, and refuse to ship a hole."""

    def test_a_clean_render_is_accepted(self):
        calls = []

        def fake_render(spec, frames_dir, shot_id):
            calls.append(shot_id)
            _write_frames(frames_dir, spec["durationInFrames"])

        with tempfile.TemporaryDirectory() as tmp:
            n = compose_frames(_spec(), "shot", os.path.join(tmp, "frames"),
                               render=fake_render)
            self.assertEqual(n, 3)
            self.assertEqual(len(calls), 1)

    def test_a_hole_earns_a_second_render(self):
        calls = []

        def fake_render(spec, frames_dir, shot_id):
            calls.append(shot_id)
            # The first render comes back with a hole, the second is clean.
            empty = (2,) if len(calls) == 1 else ()
            _write_frames(frames_dir, spec["durationInFrames"], empty_at=empty)

        with tempfile.TemporaryDirectory() as tmp:
            n = compose_frames(_spec(), "shot", os.path.join(tmp, "frames"),
                               render=fake_render)
            self.assertEqual(n, 3)
            self.assertEqual(len(calls), 2)

    def test_a_shot_that_keeps_its_holes_is_never_encoded(self):
        def fake_render(spec, frames_dir, shot_id):
            _write_frames(frames_dir, spec["durationInFrames"], empty_at=(2,))

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                compose_frames(_spec(), "shot", os.path.join(tmp, "frames"),
                               render=fake_render)
            message = str(ctx.exception)
            self.assertIn("black holes", message)
            self.assertIn("1", message)

    def test_the_attempt_budget_is_small_and_finite(self):
        self.assertGreaterEqual(RENDER_ATTEMPTS, 2)
        self.assertLessEqual(RENDER_ATTEMPTS, 5)


class AlphaBasisTests(unittest.TestCase):
    """What the guard's verdict rests on.

    A sequence of frames that carry NO alpha channel reads "mean alpha =
    1.0000" by construction: no frame can hold a transparent hole, so the
    reading is a constant and quoting it as evidence would be a check that
    cannot fail. The guard has to say which of the two it is.
    """

    def test_a_sequence_without_alpha_is_not_a_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3)          # RGB, no alpha
            basis = alpha_basis(frames)
            self.assertEqual(basis["basis"], "no_alpha")
            self.assertFalse(basis["can_show_transparent_hole"])
            self.assertIn("structural argument", basis["note"])

    def test_a_sequence_with_alpha_is_a_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3, empty_at=(2,))   # one frame carries alpha
            basis = alpha_basis(frames)
            self.assertEqual(basis["basis"], "measured")
            self.assertTrue(basis["can_show_transparent_hole"])

    def test_the_summary_names_the_basis(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3)
            summary = describe_holes(_spec(), frames, "shot", 30)
            self.assertIn("not a measurement", summary)
            self.assertIn("alpha channel", summary.lower())

    def test_the_summary_reports_a_measurement_when_it_has_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3, empty_at=(2,))
            summary = describe_holes(_spec(), frames, "shot", 30)
            self.assertIn("measured", summary)
            self.assertIn("min mean alpha", summary)

    def test_a_sequence_without_alpha_still_answers_the_question(self):
        """No alpha channel means no frame CAN hold a transparent hole - the
        verdict is right, it just must not be dressed up as a measurement."""
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "frames")
            _write_frames(frames, 3)
            self.assertEqual(find_holes(_spec(), frames, 30), [])


if __name__ == "__main__":
    unittest.main()
