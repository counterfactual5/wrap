"""Two things the generation path needs, both verified against real behaviour:

  1. A clip generated at 768P (9:16 -> 768x1344) is smaller than the
     1080x1920 canvas, so the pipeline upscales it and the shot comes out
     soft. The preparation stage must measure that and say so.

  2. The video poll runs for minutes while the model works; a single dropped
     connection must not throw away the whole wait. The connector call is
     retried.
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s1 = _load("s1_upscale", os.path.join(ROOT, "stages", "01_generate.py"))
s2 = _load("s2_upscale", os.path.join(ROOT, "stages", "02_prepare.py"))

# _connector_call lives in core/generation/connector.py; `subprocess`/`time`
# are singleton stdlib modules, so patching them through the connector module
# intercepts the calls it makes.
from core.generation import connector as gen_connector


class TestSourceSizeProbe(unittest.TestCase):
    def test_00_reads_the_video_size(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "clip.mp4")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", "color=c=0x203040:s=768x1344:r=24", "-frames:v", "5",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)
            w, h = s2._video_source_size(path)
            self.assertEqual((w, h), (768, 1344))

    def test_01_unreadable_file_yields_none(self):
        w, h = s2._video_source_size("/nonexistent/nope.mp4")
        self.assertIsNone(w)
        self.assertIsNone(h)


class TestUpscaleThreshold(unittest.TestCase):
    def test_00_the_threshold_is_a_real_margin(self):
        self.assertGreater(s2.UPSCALE_WARN, 1.0,
                           "a threshold of 1.0 would warn on every clip")
        self.assertLess(s2.UPSCALE_WARN, 2.0)


class TestConnectorRetry(unittest.TestCase):
    """A transient failure must be retried, not reported."""

    def test_00_retries_after_a_transient_failure(self):
        calls = {"n": 0}

        class _Proc:
            returncode = 0
            stdout = '{"status": "running"}'
            stderr = ""

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return type("P", (), {"returncode": 1, "stdout": "",
                                      "stderr": "fetch failed (ECONNRESET)"})()
            return _Proc()

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(gen_connector.time, "sleep"):
            out = gen_connector._connector_call("connector__matrix__query_video_generation",
                                     {"task_id": "1", "model": "MiniMax-H3-Max"})
        self.assertEqual(calls["n"], 2, "the call was not retried")
        self.assertEqual(out["status"], "running")

    def test_01_gives_up_after_the_attempts(self):
        calls = {"n": 0}

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            return type("P", (), {"returncode": 1, "stdout": "",
                                  "stderr": "fetch failed (ECONNRESET)"})()

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(gen_connector.time, "sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                gen_connector._connector_call("connector__matrix__query_video_generation",
                                   {"task_id": "1", "model": "MiniMax-H3-Max"})
        self.assertEqual(calls["n"], 3)
        self.assertIn("attempts", str(ctx.exception))

    def test_02_a_timeout_is_also_retried(self):
        calls = {"n": 0}

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise subprocess.TimeoutExpired(cmd, 180)
            return type("P", (), {"returncode": 0, "stdout": '{"ok": 1}',
                                  "stderr": ""})()

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(gen_connector.time, "sleep"):
            out = gen_connector._connector_call("connector__matrix__query_video_generation",
                                     {"task_id": "1", "model": "MiniMax-H3-Max"})
        self.assertEqual(out["ok"], 1)


if __name__ == "__main__":
    unittest.main()
