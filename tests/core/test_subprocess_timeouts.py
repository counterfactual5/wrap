"""A wedged subprocess must become an error, not a hang.

Every external command the engine runs can fail in two ways: exit non-zero
(a normal failure the caller reports), or hang forever (a wedged ffmpeg on a
dead mount, a `say` waiting on a stuck audio device, a render whose browser
never comes back). The second kind has no exit code and no output — the
pipeline just stops, silently, holding the process.

So every call is bounded, and a timeout is reported as a RuntimeError that
names the command. These tests pin that behaviour:

* `run_with_timeout` converts `subprocess.TimeoutExpired` into a
  RuntimeError that names the command and the budget;
* the budget helpers scale with the work they cover;
* every `subprocess.run` / `Popen` in production code carries a timeout,
  so a new call cannot silently reintroduce the hang.
"""
import ast
import os
import subprocess
import unittest
from unittest import mock

from core.runtime import timeouts

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Production code only — tests may legitimately mock a subprocess.
PRODUCTION_DIRS = ("core", "stages")
PRODUCTION_FILES = ("pipeline.py",)


def _production_files():
    for d in PRODUCTION_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)
    for fn in PRODUCTION_FILES:
        yield os.path.join(ROOT, fn)


class RunWithTimeoutTests(unittest.TestCase):
    def test_01_a_timeout_becomes_a_runtime_error_naming_the_command(self):
        """The whole point: a hang must be an error a human can act on."""
        with mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(
                                   cmd=["ffmpeg", "-i", "x.mp4"], timeout=42)):
            with self.assertRaises(RuntimeError) as ctx:
                timeouts.run_with_timeout(["ffmpeg", "-i", "x.mp4"], 42)

        message = str(ctx.exception)
        self.assertIn("ffmpeg", message,
                      "the error must name the command that hung")
        self.assertIn("42", message,
                      "the error must state the budget that was exceeded")
        self.assertIn("timed out", message.lower())

    def test_02_the_original_exception_is_chained(self):
        """The TimeoutExpired must stay reachable for debugging."""
        original = subprocess.TimeoutExpired(cmd=["say"], timeout=5)
        with mock.patch.object(subprocess, "run", side_effect=original):
            with self.assertRaises(RuntimeError) as ctx:
                timeouts.run_with_timeout(["say"], 5)
        self.assertIs(ctx.exception.__cause__, original)

    def test_03_a_normal_run_is_returned_untouched(self):
        sentinel = mock.Mock(returncode=0, stdout="ok")
        with mock.patch.object(subprocess, "run", return_value=sentinel) as run:
            result = timeouts.run_with_timeout(["ffprobe", "-version"], 60)
        self.assertIs(result, sentinel)
        self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_04_a_non_zero_exit_is_not_converted(self):
        """A failing command still fails the way the caller expects."""
        failed = subprocess.CalledProcessError(1, ["ffmpeg"])
        with mock.patch.object(subprocess, "run", side_effect=failed):
            with self.assertRaises(subprocess.CalledProcessError):
                timeouts.run_with_timeout(["ffmpeg"], 60, check=True)


class BudgetTests(unittest.TestCase):
    def test_05_the_render_budget_scales_with_the_shot(self):
        short = timeouts.render_timeout_seconds(5)
        long = timeouts.render_timeout_seconds(600)
        self.assertGreater(long, short,
                           "a longer shot must get a longer budget")
        self.assertGreaterEqual(short, timeouts.RENDER_BASE_TIMEOUT,
                                "even a short shot gets the floor")

    def test_06_an_unknown_shot_length_falls_back_to_the_floor(self):
        self.assertEqual(timeouts.render_timeout_seconds(None),
                         timeouts.RENDER_BASE_TIMEOUT)
        self.assertEqual(timeouts.render_timeout_seconds(0),
                         timeouts.RENDER_BASE_TIMEOUT)

    def test_07_the_say_budget_scales_with_the_text(self):
        short = timeouts.say_timeout("hi")
        long = timeouts.say_timeout("word " * 500)
        self.assertGreater(long, short,
                           "a longer narration must get a longer budget")
        self.assertGreaterEqual(short, timeouts.SAY_BASE_TIMEOUT)

    def test_08_the_budgets_are_ordered_as_the_tiers_expect(self):
        """A probe is quicker than a transcode, which is quicker than a render."""
        self.assertLess(timeouts.PROBE_TIMEOUT, timeouts.LOCAL_TOOL_TIMEOUT)
        self.assertLess(timeouts.LOCAL_TOOL_TIMEOUT, timeouts.RENDER_BASE_TIMEOUT)
        self.assertLess(timeouts.SAY_BASE_TIMEOUT, timeouts.STAGE_TIMEOUT)


class EverySubprocessIsBoundedTests(unittest.TestCase):
    """No call in production code may hang forever.

    Checked structurally (AST) rather than by text, so a mention in a
    comment cannot satisfy the check — and cannot trip it either.
    """

    def test_09_every_production_subprocess_call_has_a_timeout(self):
        offenders = []
        for path in _production_files():
            rel = os.path.relpath(path, ROOT)
            with open(path, encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=path)
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if not isinstance(func.value, ast.Name):
                    continue
                if func.value.id != "subprocess":
                    continue
                if func.attr not in ("run", "Popen", "call", "check_output",
                                     "check_call"):
                    continue
                if any(k.arg == "timeout" for k in node.keywords):
                    continue
                # A streaming Popen cannot take a timeout: the frame reader
                # in core/quality/pixels.py bounds itself with a watchdog
                # instead. Allow exactly that one, and require the watchdog.
                if func.attr == "Popen" and rel == "core/quality/pixels.py":
                    continue
                offenders.append(f"{rel}:{node.lineno} subprocess.{func.attr}")

        self.assertEqual(
            offenders, [],
            "every production subprocess call needs a timeout, or a hang "
            "blocks the pipeline forever: " + ", ".join(offenders))

    def test_10_the_streaming_reader_uses_a_watchdog(self):
        """The one Popen without a timeout must bound itself another way."""
        path = os.path.join(ROOT, "core", "quality", "pixels.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("threading.Timer", source,
                      "the streaming frame reader must arm a watchdog")
        self.assertIn("LOCAL_TOOL_TIMEOUT", source,
                      "the watchdog must use the shared budget")


if __name__ == "__main__":
    unittest.main()
