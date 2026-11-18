"""The rendering side must fail where it cannot measure — never guess.

Three silent failures lived here, each of them a value the engine could not
measure but filled in anyway:

  * a spec without an id became "shot-01" — two different shots then write
    to the same build/frames/shot-01 and public/prepared/shot-01, and
    overwrite each other's assets;
  * a playbackRate of zero or less reached the atempo chain, whose loop
    divides by 0.5 until the factor is in range — for rate <= 0 that never
    terminates, so the process hangs;
  * the frame picker kept a branch for "the clip decoded no frames", which
    the line above it had already made impossible.

Each one has a test here, and each test would fail if the fix were undone.
"""
import ast
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.rendering import remotion, timeline, video_frames  # noqa: E402


def _get_calls_with_a_default(source, key):
    """Every `x.get(<key>, <default>)` call in the source.

    Read from the AST, not the text: a comment that mentions the old
    default must not be mistaken for the default itself."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) >= 2):
            target = node.args[0]
            if isinstance(target, ast.Constant) and target.value == key:
                found.append(node)
    return found


def _branches_on_wframes(source):
    """Every `if not wframes:` statement in the source."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                    and isinstance(test.operand, ast.Name)
                    and test.operand.id == "wframes"):
                found.append(node)
    return found


def call_with_timeout(fn, *args, timeout=5.0):
    """Call `fn` in a thread; return what it raised, or None if it hung.

    The atempo bug was an infinite loop, so the regression test must fail
    on a hang instead of hanging the suite with it."""
    box = {}

    def runner():
        try:
            fn(*args)
            box["outcome"] = "returned"
        except BaseException as ex:  # noqa: BLE001 - the outcome is the result
            box["outcome"] = ex

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    return box.get("outcome")


class TestTheShotIdIsNotDefaulted(unittest.TestCase):
    """`spec["id"]` is required (core/spec/shot.py). A default would let two
    id-less specs share one asset namespace and overwrite each other."""

    def test_00_a_spec_without_an_id_fails_instead_of_becoming_shot_01(self):
        spec = {"canvas": {"w": 100, "h": 100}, "fps": 30,
                "durationInFrames": 4, "layers": []}
        with self.assertRaises(KeyError) as caught:
            remotion.build_props(spec)
        self.assertEqual(caught.exception.args[0], "id",
                         "the failure must name the missing field")

    def test_01_the_default_literal_is_gone(self):
        with open(remotion.__file__, encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(_get_calls_with_a_default(source, "id"), [],
                         "the silent shot-id default came back")

    def test_02_the_spec_id_is_the_namespace_that_is_used(self):
        """The counter-proof: the id is not merely required, it is what
        namespaces the assets — a shot called shot-42 stages into
        public/prepared/shot-42/, never into shot-01."""
        spec = {"id": "shot-42", "canvas": {"w": 100, "h": 100}, "fps": 30,
                "durationInFrames": 4,
                "layers": [{"id": "v", "type": "video", "asset": "clip",
                            "rect": [0, 0, 10, 10], "z": 0}]}
        copied = {}

        def fake_copy(src, dst):
            copied["dst"] = dst

        with mock.patch.object(remotion.manifest, "verified",
                               return_value={"path": "build/clip.mp4"}), \
                mock.patch.object(remotion.shutil, "copyfile", side_effect=fake_copy), \
                mock.patch.object(remotion.os, "makedirs"):
            props = remotion.build_props(spec)
        self.assertEqual(props["preparedVideos"]["v"], "prepared/shot-42/clip.mp4")
        self.assertIn("prepared/shot-42/clip.mp4",
                      copied["dst"].replace(os.sep, "/"))


class TestANonPositivePlaybackRateCannotReachTheWarpChain(unittest.TestCase):
    """The schema refuses playbackRate <= 0, but the renderer chain is
    reached from more than one path — a hang is not an acceptable answer."""

    def test_00_atempo_refuses_a_non_positive_rate(self):
        for rate in (0, -1, -0.5):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    timeline.atempo_chain(rate)

    def test_01_the_refusal_is_a_failure_not_a_hang(self):
        for rate in (0, -1):
            with self.subTest(rate=rate):
                outcome = call_with_timeout(timeline.atempo_chain, rate)
                self.assertIsInstance(
                    outcome, ValueError,
                    f"atempo_chain({rate}) hung instead of failing")

    def test_02_a_declared_non_positive_rate_fails_in_the_timeline_too(self):
        for rate in (0, -1):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    timeline.video_timeline({"playbackRate": rate}, 30)

    def test_03_an_absent_rate_is_the_renderer_default(self):
        """The counter-proof: only a DECLARED non-positive rate is refused.
        No rate at all means the renderer's own default (playbackRate ?? 1),
        so picture and sound agree."""
        self.assertEqual(timeline.video_timeline({}, 30), (0.0, None, 1.0))
        self.assertEqual(timeline.video_timeline({"playbackRate": 2}, 30)[2], 2.0)
        self.assertEqual(timeline.atempo_chain(0.75), ["atempo=0.75"])


class TestTheFramePickerHasNoDeadBranch(unittest.TestCase):
    """An empty window raises two lines above the picker, so the picker's
    own 'no frames' branch could never run."""

    def test_00_the_unreachable_branch_is_gone(self):
        with open(video_frames.__file__, encoding="utf-8") as f:
            source = f.read()
        branches = _branches_on_wframes(source)
        self.assertEqual(len(branches), 1,
                         "the unreachable 'no decoded frames' branch came back "
                         "(an empty window is refused by the guard above the "
                         "picker, so the picker needs no branch of its own)")
        self.assertTrue(
            any(isinstance(stmt, ast.Raise) for stmt in branches[0].body),
            "the one remaining 'not wframes' branch must be the guard that "
            "refuses an empty window")

    def test_01_an_empty_window_still_fails_loudly(self):
        """The behaviour around the removed branch must be unchanged: a clip
        that decodes nothing is an error, not a run of substitute frames."""
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(video_frames.subprocess, "run"), \
                mock.patch.object(video_frames, "_write_solid_png") as fill:
            with self.assertRaisesRegex(RuntimeError, "no decodable frames"):
                video_frames._extract_video_frames({}, "missing.mp4", tmp, 4, 30, 20, 10)
            fill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
