"""The removed Quartz backend must neither launch tools nor replace output."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core.rendering.quartz import _render_quartz_fallback


class QuartzRemovalTests(unittest.TestCase):
    def test_compatibility_entry_point_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "frames"
            output.mkdir()
            frame = output / "00001.png"
            frame.write_bytes(b"project frame")
            with mock.patch("subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "已移除内置Quartz设计后端，使用Remotion或项目后端"):
                    _render_quartz_fallback({}, str(output), "shot")
            run.assert_not_called()
            self.assertEqual(frame.read_bytes(), b"project frame")

    def test_no_output_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "absent"
            with self.assertRaises(RuntimeError):
                _render_quartz_fallback({}, str(output), "shot")
            self.assertFalse(output.exists())
