"""The S3 render driver must fail on its own errors and fall back only on a
proven browser-environment failure.

`render_remotion` used to treat every `CalledProcessError` and
`FileNotFoundError` as "Chromium is blocked by the sandbox" and silently
re-render with the native Quartz compositor. That turned a broken bundle, a
typo in a spec or a missing `npx` into a different picture — or a second,
unrelated failure — while the log claimed a sandbox problem that never
happened.

The contract pinned here:
  - a bundle/code error fails, naming the renderer's own output;
  - a missing file (no `npx`, no prepared asset) fails — never falls back;
  - only the renderer's explicit "the browser could not start" errors fall
    back, and they say which renderer actually drew the frames;
  - `POSTER_FORCE_QUARTZ=1` still goes straight to Quartz.

The double is `subprocess.Popen` (not `subprocess.run`): `run` is a plain
function that does `with Popen(...)` and then raises `CalledProcessError`
itself, so a stub at the `run` level would still open a real process. The
fake plays both parts — the process `run` drives, and the context manager it
enters — so the driver exercises its real error handling. No Node, no
Chromium, no Swift.
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.rendering import remotion  # noqa: E402


def _spec(frames=4):
    # A bar layer needs no prepared asset, so build_props() succeeds without a
    # manifest row and the test reaches the renderer call itself.
    return {
        "id": "render-driver-test",
        "canvas": {"w": 64, "h": 48, "bg": "#000000"},
        "fps": 30,
        "durationInFrames": frames,
        "layers": [{"id": "bar", "type": "code", "draw": "bar",
                    "rect": [0, 0, 64, 48], "z": 0}],
    }


class _FakeProcess:
    """Factory + stand-in for the Popen `subprocess.run` drives.

    The driver's `subprocess.run(cmd, check=True, ...)` calls this with the
    argv; the returned object plays the process it then drives:
      - `exit_code=0` yields a CompletedProcess (the success path);
      - any other code raises the same CalledProcessError the real `run`
        raises, with the captured output attached — which is what the driver
        reports;
      - `error` is raised by the constructor, standing in for a launcher that
        is not there (FileNotFoundError from Popen itself).
    `side_effect(cmd)` runs where the renderer would have written its frames.
    """

    def __init__(self, exit_code=0, stdout="", stderr="", error=None, side_effect=None):
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._error = error
        self._side_effect = side_effect
        self.args = None
        self.returncode = None

    def __call__(self, cmd, *a, **kw):
        if self._error is not None:
            raise self._error
        if self._side_effect is not None:
            self._side_effect(cmd)
        self.args = cmd
        return self

    # -- the Popen surface run() touches ---------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def communicate(self, input=None, timeout=None):
        return self._stdout, self._stderr

    def poll(self):
        return self._exit_code

    def kill(self):
        pass


def _calls(mock_obj):
    """The argv of each Popen construction, or [] if it was never called."""
    return [c.args[0][0] for c in mock_obj.call_args_list if c.args]


class _DriverCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = os.path.join(self._tmp.name, "frames")
        self.quartz = mock.Mock()
        patcher = mock.patch.object(remotion, "_render_quartz_fallback", self.quartz)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _frames(self):
        return sorted(f for f in os.listdir(self.out_dir) if f.endswith(".png"))

    def _run(self, popen, spec=None, env=None):
        """Drive render_remotion against a fake Popen factory.

        Returns (result_or_exception, stdout, popen_mock)."""
        spec = spec or _spec()
        out = io.StringIO()
        popen_mock = popen if isinstance(popen, mock.Mock) else mock.Mock(side_effect=popen)
        with redirect_stdout(out):
            try:
                with mock.patch.object(remotion.subprocess, "Popen", popen_mock), \
                        mock.patch.dict(os.environ, env or {}, clear=False):
                    result = remotion.render_remotion(spec, self.out_dir, spec["id"])
            except BaseException as ex:  # noqa: BLE001 - the test inspects it
                result = ex
        return result, out.getvalue(), popen_mock


class TestRenderDriverFailurePolicy(_DriverCase):
    def test_00_a_bundle_error_fails_without_falling_back(self):
        """The regression: "bundle failed" is a code error, not a sandbox."""
        result, out, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="Error: Bundle failed with code 1\n  at bundle (webpack)\n"))

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("render error, not a browser-environment failure", str(result))
        self.assertIn("Bundle failed with code 1", str(result))
        self.quartz.assert_not_called()
        self.assertNotIn("Quartz compositor", out)

    def test_01_a_renderer_code_error_names_the_invocation(self):
        """The failure must carry the renderer's output and how it was called,
        or the author is left with an exit code."""
        result, _, _ = self._run(_FakeProcess(
            exit_code=3, stderr="TypeError: Cannot read properties of undefined\n"))

        self.assertIsInstance(result, RuntimeError, result)
        text = str(result)
        self.assertIn("Cannot read properties of undefined", text)
        self.assertIn("npx remotion render", text)
        self.assertIn(str(remotion.ENGINE_ROOT), text)
        self.quartz.assert_not_called()

    def test_02_a_missing_file_does_not_fall_back(self):
        """A missing `npx`/node is a missing tool: say so, do not re-render."""
        result, out, _ = self._run(_FakeProcess(
            error=FileNotFoundError(2, "No such file or directory", "npx")))

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("could not be launched", str(result))
        self.assertIn("npx", str(result))
        self.quartz.assert_not_called()
        self.assertNotIn("Quartz compositor", out)

    def test_03_a_missing_prepared_asset_never_reaches_the_renderer(self):
        """S3 without S2: the props step fails, so there is nothing to fall
        back from — the driver must not quietly render a partial shot."""
        spec = _spec()
        spec["layers"] = [{"id": "plate", "type": "ai", "asset": "never-prepared",
                           "rect": [0, 0, 64, 48], "z": 0}]
        popen = mock.Mock()

        result, _, popen = self._run(popen, spec=spec)

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("not manifest-verified", str(result))
        self.assertEqual(_calls(popen), [])
        self.quartz.assert_not_called()

    def test_04_a_zero_exit_without_frames_is_reported(self):
        """Exit 0 with no frames is not a success: renumbering fails and the
        error must name the directory the renderer actually wrote into."""
        def write_notes(cmd):
            rm = os.path.join(self.out_dir, "rm")
            os.makedirs(rm, exist_ok=True)
            with open(os.path.join(rm, "notes.txt"), "w") as f:
                f.write("renderer wrote no frames")

        result, out, _ = self._run(_FakeProcess(exit_code=0, side_effect=write_notes))

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("no usable frames", str(result))
        self.assertIn("frames/rm/0.png", str(result))
        self.quartz.assert_not_called()
        self.assertFalse(os.path.isdir(os.path.join(self.out_dir, "rm")))

    def _quartz_frame(self, got_spec, out_dir, shot_id):
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "00001.png"), "wb") as f:
            f.write(b"quartz frame")

    def test_05_a_page_crash_is_a_browser_environment_failure(self):
        """`Page crashed!` is the renderer's wording for the browser process
        dying under it (the restricted-sandbox SIGSEGV this fallback exists
        for), so it falls back — and says which renderer drew the frames."""
        self.quartz.side_effect = self._quartz_frame
        result, out, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="Error: Page crashed!\n  at Page.#onTargetCrashed (Target.js)\n"))

        self.assertIsNone(result, result)
        self.quartz.assert_called_once()
        self.assertIn("renderer=quartz (browser unavailable: 1)", out)

    def test_06_an_ordinary_crash_is_never_re_drawn(self):
        """A composition error is not a browser failure: it must stay a hard
        error, or the native compositor quietly draws a different picture."""
        result, _, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="TypeError: Cannot read properties of undefined (reading 'map')\n"
                   "  at Shot (Shot.tsx:42:11)\n"))

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("render error", str(result))
        self.quartz.assert_not_called()

    def test_07_a_browser_launch_failure_falls_back(self):
        """The one case the compositor exists for: the browser process never
        came up inside this environment."""
        self.quartz.side_effect = self._quartz_frame
        result, out, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="Error: Failed to launch the browser process!\n"
                   "  at waitForWSEndpoint (index.mjs)\n"
                   "Timed out after 30000 ms while trying to connect to the browser!\n"))

        self.assertIsNone(result, result)
        self.quartz.assert_called_once()
        self.assertEqual(self._frames(), ["00001.png"])
        self.assertIn("Quartz compositor", out)
        self.assertIn("renderer=quartz (browser unavailable: 1)", out)
        self.assertNotIn("sandbox", out)

    def test_08_an_explicit_browser_error_falls_back_and_records_the_choice(self):
        """A target-closed failure the renderer itself attributes to the
        browser still falls back, and the log says which renderer drew the
        frames."""
        self.quartz.side_effect = self._quartz_frame
        result, out, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="Protocol error (Page.captureScreenshot): Target closed. "
                   "https://www.remotion.dev/docs/target-closed\n"))

        self.assertIsNone(result, result)
        self.quartz.assert_called_once()
        self.assertIn("renderer=quartz (browser unavailable: 1)", out)

    def test_09_poster_force_quartz_skips_the_renderer_entirely(self):
        spec = _spec()
        self.quartz.side_effect = self._quartz_frame
        result, out, popen = self._run(mock.Mock(), spec=spec,
                                       env={"POSTER_FORCE_QUARTZ": "1"})

        self.assertIsNone(result, result)
        self.assertEqual(_calls(popen), [])
        self.quartz.assert_called_once_with(spec, self.out_dir, spec["id"])
        self.assertEqual(self._frames(), ["00001.png"])
        self.assertIn("renderer=quartz (POSTER_FORCE_QUARTZ=1)", out)

    def test_10_a_successful_remotion_render_reports_its_renderer(self):
        """The choice is logged on the success path too, so a log always says
        which compositor produced the frames."""
        frames = _spec()["durationInFrames"]

        def write_frames(cmd):
            rm = os.path.join(self.out_dir, "rm")
            os.makedirs(rm, exist_ok=True)
            for i in range(frames):
                with open(os.path.join(rm, f"{i}.png"), "wb") as f:
                    f.write(b"frame")

        result, out, _ = self._run(_FakeProcess(exit_code=0, stdout="rendered 4 frames\n",
                                             side_effect=write_frames))

        self.assertIsNone(result, result)
        self.assertEqual(self._frames(), ["00001.png", "00002.png", "00003.png", "00004.png"])
        self.quartz.assert_not_called()
        self.assertIn("renderer=remotion", out)
        self.assertIn("rendered 4 frames", out)


class TestBrowserEnvironmentDetection(unittest.TestCase):
    """The marker list is the whole safety margin: too narrow and a real
    sandbox failure becomes a hard error, too wide and a render error is
    silently re-drawn by the native compositor."""

    def test_00_recognises_the_renderers_own_wording(self):
        for stream in (
            "Error: Failed to launch the browser process!\n",
            "Timed out after 30000 ms while trying to connect to the browser!",
            "TypeError: No browser found for rendering frames!",
            "Protocol error (Page.captureScreenshot): Target closed.",
            "Protocol error (Runtime.callFunctionOn): Session closed.",
            "Navigation failed because browser has disconnected!",
            "Error: Page crashed!",
            "Error: `browserExecutable` was specified as '/x' but the path doesn't exist.",
        ):
            with self.subTest(stream=stream.splitlines()[0]):
                self.assertTrue(remotion._looks_like_browser_environment_failure(stream))

    def test_01_ignores_render_errors(self):
        for stream in (
            "Error: Bundle failed with code 1",
            "TypeError: Cannot read properties of undefined (reading 'map')",
            "Error: A delayRender() was called but not cleared after 30000ms",
            "SyntaxError: Unexpected token '}' in bundle",
            "",
        ):
            with self.subTest(stream=stream or "(empty)"):
                self.assertFalse(remotion._looks_like_browser_environment_failure(stream))

    def test_02_ignores_a_bare_errno_or_stack_token(self):
        """A render error whose stack happens to carry `spawn`/`ENOENT` (or a
        path containing one) must stay a hard error: the marker list keys on
        the renderer's own failure wording, never on a bare errno."""
        for stream in (
            "Error: spawn chrome-headless-shell ENOENT\n  at ChildProcess.spawn",
            "Error: EACCES: permission denied, open '/assets/EACCES.png'",
            "Error: bundle failed\n  at spawn (webpack.js:1:1)",
        ):
            with self.subTest(stream=stream.splitlines()[0]):
                self.assertFalse(remotion._looks_like_browser_environment_failure(stream))


if __name__ == "__main__":
    unittest.main()