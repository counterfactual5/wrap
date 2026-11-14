"""Render errors retain diagnostics and never switch to substitute artwork."""
import io
import json
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
    # Project components use no implicit assets.
    return {
        "id": "render-driver-test",
        "canvas": {"w": 64, "h": 48, "bg": "#000000"},
        "fps": 30,
        "durationInFrames": frames,
        "layers": [{"id": "scene", "type": "component", "component": "Scene",
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
        root_patch = mock.patch.object(remotion, "ROOT", self._tmp.name)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        env_patch = mock.patch.dict(os.environ, {"POSTER_FORCE_QUARTZ": "0"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
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
        self.assertIn("no fallback was attempted", str(result))
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

    def test_05_a_page_crash_fails_without_substitute(self):
        result, out, _ = self._run(_FakeProcess(
            exit_code=1, stderr="Error: Page crashed!"))
        self.assertIsInstance(result, RuntimeError)
        self.assertIn("Page crashed!", str(result))
        self.quartz.assert_not_called()
        self.assertNotIn("renderer=quartz", out)

    def test_06_an_ordinary_crash_is_never_re_drawn(self):
        """A composition error is not a browser failure: it must stay a hard
        error, or the native compositor quietly draws a different picture."""
        result, _, _ = self._run(_FakeProcess(
            exit_code=1,
            stderr="TypeError: Cannot read properties of undefined (reading 'map')\n"
                   "  at Shot (Shot.tsx:42:11)\n"))

        self.assertIsInstance(result, RuntimeError, result)
        self.assertIn("renderer failed", str(result))
        self.quartz.assert_not_called()

    def test_07_browser_failures_preserve_context_without_fallback(self):
        for message in ("Failed to launch the browser process", "Target closed",
                        "No browser found for rendering frames", "Session closed"):
            with self.subTest(message=message):
                result, out, _ = self._run(_FakeProcess(exit_code=1, stderr=message))
                self.assertIsInstance(result, RuntimeError)
                self.assertIn(message, str(result))
                self.assertIn("npx remotion render", str(result))
                self.quartz.assert_not_called()
                self.assertNotIn("renderer=quartz", out)

    def test_09_explicit_quartz_request_reports_removal(self):
        from core.rendering.quartz import _render_quartz_fallback
        self.quartz.side_effect = _render_quartz_fallback
        result, out, popen = self._run(mock.Mock(), env={"POSTER_FORCE_QUARTZ": "1"})
        self.assertIsInstance(result, RuntimeError)
        self.assertIn("已移除内置Quartz设计后端", str(result))
        popen.assert_not_called()
        self.assertFalse(os.path.exists(self.out_dir))
        self.assertNotIn("renderer=quartz", out)

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


class TestPreparedProps(unittest.TestCase):
    def test_component_props_and_tracks_pass_through_without_palette(self):
        spec = _spec()
        spec["tracks"] = {"captions": [{"frame": 0, "end_frame": 3, "text": "Hello"}],
                          "events": [{"frame": 2, "anything": {"nested": True}}]}
        spec["layers"][0]["props"] = {"colors": ["project-owned"], "nested": {"a": 1}}
        with mock.patch.object(remotion.manifest, "verified") as verified:
            props = remotion.build_props(spec)
        self.assertEqual(props["spec"], spec)
        self.assertEqual(set(props), {"spec", "prepared", "preparedVideos", "preparedPoses"})
        verified.assert_not_called()

    def test_old_code_layer_is_rejected_not_prepared(self):
        spec = _spec()
        spec["layers"][0].update(type="code", draw="grid")
        with self.assertRaisesRegex(RuntimeError, "unsupported layer type: code"):
            remotion.build_props(spec)

    def test_image_alias_and_pose_use_verified_prepared_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "image.png"), "wb") as f:
                f.write(b"verified-image")
            spec = _spec()
            spec["layers"] = [{"id": "image", "type": "image", "asset": "base",
                               "poses": [{"frame": 2, "asset": "pose"}]}]
            with mock.patch.object(remotion, "ROOT", root), mock.patch.object(
                    remotion.manifest, "verified", return_value={"path": "image.png"}) as verified:
                props = remotion.build_props(spec)
            self.assertEqual(props["prepared"]["image"], "data:image/png;base64,dmVyaWZpZWQtaW1hZ2U=")
            self.assertEqual(props["preparedPoses"]["image"]["pose"], props["prepared"]["image"])
            self.assertIn(mock.call("prepared", "render-driver-test/pose"), verified.call_args_list)

    def test_missing_pose_is_not_replaced_by_base_image(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "base.png"), "wb") as f:
                f.write(b"base")
            spec = _spec()
            spec["layers"] = [{"id": "image", "type": "ai", "asset": "base",
                               "poses": [{"frame": 2, "asset": "missing"}]}]
            def row(kind, key):
                return None if key.endswith("/missing") else {"path": "base.png"}
            with mock.patch.object(remotion, "ROOT", root), mock.patch.object(
                    remotion.manifest, "verified", side_effect=row):
                with self.assertRaisesRegex(RuntimeError, "missing.*not manifest-verified"):
                    remotion.build_props(spec)

    def test_video_staging_cannot_escape_prepared_directory(self):
        spec = _spec()
        spec["layers"] = [{"id": "clip", "type": "video", "asset": "../../../escape"}]
        with mock.patch.object(remotion.manifest, "verified", return_value={"path": "clip.mp4"}):
            with self.assertRaisesRegex(RuntimeError, "outside public/prepared"):
                remotion.build_props(spec)

    def test_video_is_staged_and_shared_by_layer_id(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "clip.mp4"), "wb") as f:
                f.write(b"verified-clip")
            spec = _spec()
            spec["layers"].append({"id": "clip", "type": "video", "asset": "source"})
            with mock.patch.object(remotion, "ROOT", root), mock.patch.object(remotion, "ENGINE_ROOT", root), \
                    mock.patch.object(remotion.manifest, "verified", return_value={"path": "clip.mp4"}):
                props = remotion.build_props(spec)
            rel = props["preparedVideos"]["clip"]
            with open(os.path.join(root, "public", rel), "rb") as f:
                self.assertEqual(f.read(), b"verified-clip")


if __name__ == "__main__":
    unittest.main()
