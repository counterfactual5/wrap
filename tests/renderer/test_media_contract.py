"""Media extraction preserves timing without injecting artwork."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from core.rendering import video_frames, encoding


class RendererContractTests(unittest.TestCase):
    def test_typescript_runtime_contract(self):
        root = Path(__file__).resolve().parents[2]
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for renderer contract tests")
        subprocess.run([node, "tests/renderer/contract.cjs"], cwd=root,
                       check=True, capture_output=True, text=True, timeout=30)

    def test_trim_rate_loop_and_transparent_end(self):
        for loop, expected in [(True, [0, 2, 0, 2, 0]), (False, [0, 2, None, None, None])]:
            with self.subTest(loop=loop), tempfile.TemporaryDirectory() as tmp:
                commands = []
                def extract(cmd, **kwargs):
                    commands.append(cmd)
                    window = Path(tmp) / "frames" / "_window"
                    for i in range(4):
                        (window / f"{i + 1:05d}.png").write_bytes(bytes([i]))
                output = Path(tmp) / "frames"
                with mock.patch.object(video_frames.subprocess, "run", side_effect=extract), \
                        mock.patch.object(video_frames, "_write_solid_png") as fill:
                    video_frames._extract_video_frames(
                        {"trim": [1, 3], "playbackRate": 2, "loop": loop, "fit": "contain"},
                        "clip.mp4", str(output), 5, 30, 20, 10)
                vf = commands[0][commands[0].index("-vf") + 1]
                self.assertIn("trim=start=1.0:end=3.0", vf)
                self.assertIn("color=black@0.0", vf)
                for i, value in enumerate(expected):
                    if value is not None:
                        self.assertEqual((output / f"{i + 1:05d}.png").read_bytes(), bytes([value]))
                self.assertEqual(fill.call_count, expected.count(None))
                for call in fill.call_args_list:
                    self.assertEqual(call.args[-1], (0, 0, 0, 0))

    def test_empty_decode_fails_instead_of_generating_substitute_frames(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(video_frames.subprocess, "run"), \
                mock.patch.object(video_frames, "_write_solid_png") as fill:
            with self.assertRaisesRegex(RuntimeError, "no decodable frames"):
                video_frames._extract_video_frames({}, "missing.mp4", tmp, 4, 30, 20, 10)
            fill.assert_not_called()

    def test_encoding_has_no_visual_grade_even_for_legacy_input(self):
        spec = {"id": "test", "fps": 30, "durationInFrames": 4, "layers": [], "vibe_grade": True}
        with mock.patch("core.audio.prepare_shot_audio"), \
                mock.patch.object(encoding.subprocess, "run") as run:
            encoding.encode_mp4(spec, "frames", "out.mp4")
        self.assertNotIn("-vf", run.call_args.args[0])
