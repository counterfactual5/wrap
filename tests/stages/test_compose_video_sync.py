"""S3 compose: video timeline parity — native-audio playbackRate sync and the
Quartz fallback's trim / speed / rect / contain handling.

The contract under test is read from the installed renderer (remotion
4.0.529, node_modules): remotion/Shot.tsx maps trim -> trimBefore/trimAfter =
Math.round(trim * fps); html5-video.js wraps a looping clip in <Loop
duration = window / playbackRate>; video/get-current-time.js seeks the media
to trimBefore + local * playbackRate. S3 must reproduce that math
twice — when mastering the clip's native audio (atempo + loop window) and
when picking frames for the Quartz fallback — or the picture and the
soundtrack drift apart (the S4 AV sync gate allows <= 100 ms).

The implementation lives in core/rendering/ (stages/03_compose.py keeps only
main() and the flow), so behavior is asserted against the DEFINING submodules
and mocks are patched there — TestStageWiring pins the stage to the same
objects, so submodule behavior IS stage behavior.
"""
import importlib.util
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.helpers import preserve_manifest  # noqa: E402
from core.rendering import encoding, remotion, timeline, video_frames  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "s3_compose_sync", os.path.join(ROOT, "stages", "03_compose.py"))
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)

_spec1 = importlib.util.spec_from_file_location(
    "s1_gen_sync", os.path.join(ROOT, "stages", "01_generate.py"))
s1 = importlib.util.module_from_spec(_spec1)
_spec1.loader.exec_module(s1)


class TestStageWiring(unittest.TestCase):
    """stages/03_compose.py delegates to core.rendering — it must bind the
    SAME function objects, not copies, or the submodule tests below would
    stop being tests of the stage."""

    def test_00_stage_binds_the_rendering_package(self):
        self.assertIs(s3.render_remotion, remotion.render_remotion)
        self.assertIs(s3.encode_mp4, encoding.encode_mp4)


def _layer(**over):
    layer = {"id": "clip", "type": "video", "asset": "aud-clip",
             "rect": [0, 0, 1080, 1920], "z": 0, "muted": False}
    layer.update(over)
    return layer


def _spec(layer_over=None, frames=60, fps=30):
    return {
        "id": "sync-test",
        "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
        "fps": fps,
        "durationInFrames": frames,
        "vibe": False,
        "style": "tests/fixtures/style-quantum.json",
        "layers": [_layer(**(layer_over or {}))],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.3}],
    }


def _png_payload(path):
    """(w, h, first-pixel rgba) of a PNG, stdlib only."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG")
    pos, idat, w, h = 8, b"", None, None
    while pos + 8 <= len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", payload[:8])
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = 1 + 4 * w
    return w, h, raw[1:5]


class TestTimelineMath(unittest.TestCase):
    """The shared timeline helper must round like JavaScript, not like Python."""

    def test_00_js_round_is_half_away_from_zero(self):
        # Python's round() is half-to-even (0, 2, 2); Math.round is 1, 2, 3.
        self.assertEqual([timeline._js_round(x) for x in (0.5, 1.5, 2.5)], [1, 2, 3])
        self.assertEqual(timeline._js_round(-0.5), 0)

    def test_01_no_trim_no_rate_is_identity(self):
        self.assertEqual(timeline.video_timeline({}, 30), (0.0, None, 1.0))

    def test_02_trim_is_frame_rounded_like_trim_before_after(self):
        # 1.04 * 30 = 31.2 -> 31 frames; 2.96 * 30 = 88.8 -> 89 frames.
        t0, t1, rate = timeline.video_timeline({"trim": [1.04, 2.96]}, 30)
        self.assertEqual((t0, t1), (31 / 30, 89 / 30))
        self.assertEqual(rate, 1.0)

    def test_03_half_frame_trims_round_up(self):
        # 1/60 s is exactly half a frame at 30 fps: Math.round gives frame 1,
        # banker's rounding would give frame 0 and desync audio vs picture.
        t0, _, _ = timeline.video_timeline({"trim": [1 / 60, 1.0]}, 30)
        self.assertEqual(t0, 1 / 30)

    def test_04_playback_rate_passthrough(self):
        self.assertEqual(timeline.video_timeline({"playbackRate": 2}, 30)[2], 2.0)
        self.assertEqual(timeline.video_timeline({"playbackRate": 0.5}, 30)[2], 0.5)


class TestAtempoChain(unittest.TestCase):
    def _product(self, parts):
        p = 1.0
        for part in parts:
            p *= float(part.split("=")[1])
        return p

    def test_00_simple_rates_are_one_filter(self):
        self.assertEqual(timeline.atempo_chain(2.0), ["atempo=2"])
        self.assertEqual(timeline.atempo_chain(0.75), ["atempo=0.75"])

    def test_01_rates_below_half_are_chained(self):
        # One atempo accepts [0.5, 100]; 0.25 must be split into factors.
        parts = timeline.atempo_chain(0.25)
        self.assertEqual(parts, ["atempo=0.5", "atempo=0.5"])
        self.assertAlmostEqual(self._product(parts), 0.25)

    def test_02_rates_above_hundred_are_chained(self):
        parts = timeline.atempo_chain(250.0)
        self.assertAlmostEqual(self._product(parts), 250.0, places=4)
        for part in parts:
            f = float(part.split("=")[1])
            self.assertTrue(0.5 <= f <= 100, f"{f} outside a single atempo's range")


class TestNativeAudioMastering(unittest.TestCase):
    """The clip's native track must be warped by the same playbackRate the
    picture runs at, and the loop must repeat the WARPED window."""

    def _master_af(self, spec):
        with mock.patch.object(encoding, "video_audio_source",
                               return_value="/tmp/clip.mp4"), \
             mock.patch.object(encoding.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            encoding.encode_mp4(spec, "/tmp/frames", "/tmp/out.mp4")
        cmd = run.call_args_list[0][0][0]  # loudnorm pass 1
        return cmd, cmd[cmd.index("-af") + 1]

    def test_00_rate_two_with_trim_loops_then_warps_the_window(self):
        # Window [1s, 3s] at rate 2 lasts 1s of shot time; a 2s shot loops it.
        # The loop runs on the UNWARPED window and atempo warps the looped
        # stream (loop-then-warp == Remotion's window/rate period; the
        # reverse order was measured to flatten the track).
        cmd, af = self._master_af(_spec({"trim": [1.0, 3.0], "playbackRate": 2}))
        self.assertIn("atrim=start=1.0:end=3.0", af)
        self.assertIn("aloop=loop=-1:size=88200", af,
                      "the loop repeats the 2s source window")
        self.assertIn("atempo=2", af)
        self.assertLess(af.index("aloop"), af.index("atempo"),
                        "aloop must run before the warp")

    def test_01_rate_one_keeps_the_unwarped_chain(self):
        # Regression guard: no playbackRate, no atempo, loop sized on the
        # source window (3s shot loops the 2s window).
        cmd, af = self._master_af(_spec({"trim": [1.0, 3.0]}, frames=90))
        self.assertNotIn("atempo", af)
        self.assertIn("aloop=loop=-1:size=88200", af)

    def test_02_rate_two_without_trim_uses_stream_loop_plus_atempo(self):
        cmd, af = self._master_af(_spec({"playbackRate": 2}))
        self.assertIn("atempo=2", af)
        self.assertNotIn("aloop", af)
        i = cmd.index("-i")
        self.assertEqual(cmd[i - 2:i], ["-stream_loop", "-1"],
                         "an untrimmed looping clip loops the file at the input")

    def test_03_slow_rate_chains_atempo_below_half(self):
        _, af = self._master_af(_spec({"trim": [0.0, 1.0], "playbackRate": 0.25}))
        self.assertIn("atempo=0.5,atempo=0.5", af)

    def test_04_no_loop_no_warp_window_long_enough_adds_nothing(self):
        # Warped window (1s) fills the 1s shot exactly: no aloop needed.
        _, af = self._master_af(_spec({"trim": [0.0, 1.0], "playbackRate": 2,
                                       "loop": False}, frames=30))
        self.assertNotIn("aloop", af)

    def test_05_rate_one_silent_path_is_unchanged(self):
        cmd, af = self._master_af(_spec({}))
        self.assertEqual(af.split(",loudnorm")[0],
                         "aformat=sample_rates=44100:channel_layouts=stereo")


class _FakeFfmpegWindow:
    """subprocess.run stub: 'decodes' a clip of n frames by writing files whose
    CONTENT is the media frame index, so the picker's mapping is readable."""

    def __init__(self, frames):
        self.frames = frames
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        out = cmd[-1]
        d = os.path.dirname(out)
        os.makedirs(d, exist_ok=True)
        for idx in range(1, self.frames + 1):
            with open(os.path.join(d, f"{idx:05d}.png"), "wb") as f:
                f.write(str(idx - 1).encode())
        return subprocess.CompletedProcess(cmd, 0, "", "")


class TestQuartzFramePicking(unittest.TestCase):
    """Composition frame i must show window frame floor((i mod window/rate) *
    rate) — the frame <Loop> plus the media seek land on."""

    def _pick(self, layer, n, window_frames, rw=100, rh=50):
        fake = _FakeFfmpegWindow(window_frames)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "frames")
            with mock.patch.object(video_frames.subprocess, "run", side_effect=fake):
                video_frames._extract_video_frames(layer, "clip.mp4", out, n, 30, rw, rh)
            picked = []
            for i in range(n):
                with open(os.path.join(out, f"{i + 1:05d}.png"), "rb") as f:
                    head = f.read(8)
                if head == b"\x89PNG\r\n\x1a\n":
                    picked.append(None)  # fill frame, not a media frame
                else:
                    with open(os.path.join(out, f"{i + 1:05d}.png"), "rb") as f:
                        picked.append(int(f.read()))
        return picked, fake.cmds[0]

    def test_00_double_speed_maps_two_media_frames_per_shot_frame(self):
        picked, _ = self._pick(_layer(playbackRate=2), 30, 60)
        self.assertEqual(picked, [min(2 * i, 59) for i in range(30)])

    def test_01_half_speed_doubles_each_media_frame(self):
        picked, _ = self._pick(_layer(playbackRate=0.5), 30, 30)
        self.assertEqual(picked, [i // 2 for i in range(30)])

    def test_02_loop_repeats_the_window_like_loop(self):
        picked, _ = self._pick(_layer(), 25, 10)
        self.assertEqual(picked, [i % 10 for i in range(25)])

    def test_03_no_trim_no_loop_clamps_the_last_frame(self):
        # An untrimmed <video> element clamps once the media ends.
        picked, _ = self._pick(_layer(loop=False), 15, 10)
        self.assertEqual(picked, [min(i, 9) for i in range(15)])

    def test_04_trim_speed_and_loop_wrap_together(self):
        # 30-frame window at rate 1.5 -> loop period 20 shot frames.
        layer = _layer(trim=[0.5, 1.5], playbackRate=1.5)
        picked, cmd = self._pick(layer, 40, 30)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("trim=start=0.5:end=1.5", vf)
        expect = [min(int((i % 20) * 1.5), 29) for i in range(40)]
        self.assertEqual(picked, expect)

    def test_05_trim_no_loop_fills_with_plate_background(self):
        # A trimmed <Video> unmounts when its window ends: Remotion shows the
        # wrapper div's plate background (#030509) for the rest of the shot.
        layer = _layer(trim=[0.0, 0.3333], loop=False)
        fake = _FakeFfmpegWindow(10)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "frames")
            with mock.patch.object(video_frames.subprocess, "run", side_effect=fake):
                video_frames._extract_video_frames(layer, "clip.mp4", out, 15, 30, 100, 50)
            real = 0
            for i in range(15):
                path = os.path.join(out, f"{i + 1:05d}.png")
                with open(path, "rb") as f:
                    head = f.read(8)
                if head != b"\x89PNG\r\n\x1a\n":
                    real += 1
                else:
                    w, h, pixel = _png_payload(path)
                    self.assertEqual((w, h), (100, 50))
                    self.assertEqual(pixel, bytes((3, 5, 9, 255)),
                                     "plate background must fill unmounted frames")
            self.assertEqual(real, 10)

    def test_06_trim_no_loop_plate_false_fills_transparent(self):
        layer = _layer(trim=[0.0, 0.3333], loop=False, plate=False)
        fake = _FakeFfmpegWindow(10)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "frames")
            with mock.patch.object(video_frames.subprocess, "run", side_effect=fake):
                video_frames._extract_video_frames(layer, "clip.mp4", out, 12, 30, 100, 50)
            w, h, pixel = _png_payload(os.path.join(out, "00012.png"))
            self.assertEqual(pixel, bytes((0, 0, 0, 0)),
                             "plate:false must let lower layers show through")

    def test_07_cover_and_contain_build_the_objectfit_chains(self):
        _, cover_cmd = self._pick(_layer(), 10, 40, 320, 180)
        vf = cover_cmd[cover_cmd.index("-vf") + 1]
        self.assertIn("scale=320:180:force_original_aspect_ratio=increase", vf)
        self.assertIn("crop=320:180", vf)

        _, contain_cmd = self._pick(_layer(fit="contain"), 10, 40, 320, 180)
        vf = contain_cmd[contain_cmd.index("-vf") + 1]
        self.assertIn("scale=320:180:force_original_aspect_ratio=decrease", vf)
        self.assertIn("pad=320:180", vf)
        self.assertIn("color=0x030509@1.0", vf,
                      "contain letterboxes in the plate background")

    def test_08_no_stream_loop_and_capped_window_pull(self):
        # Looping is done by the Python picker (Remotion's <Loop>), so ffmpeg
        # never needs -stream_loop, and the pull is capped at what can be picked.
        picked, cmd = self._pick(_layer(playbackRate=2), 30, 60)
        self.assertNotIn("-stream_loop", cmd)
        cap = cmd[cmd.index("-frames:v") + 1]
        self.assertEqual(int(cap), math.ceil(30 * 2) + 8)


class TestQuartzRouting(unittest.TestCase):
    """The direct-to-frames fast path is only valid for a single full-canvas
    video layer; anything else goes through the Swift compositor."""

    def _spec_layers(self, layers):
        spec = _spec()
        spec["layers"] = layers
        return spec

    def test_00_single_full_canvas_video_layer_is_fast(self):
        spec = self._spec_layers([_layer()])
        self.assertIs(video_frames._quartz_fast_path_layer(spec), spec["layers"][0])

    def test_01_offset_rect_needs_the_compositor(self):
        spec = self._spec_layers([_layer(rect=[40, 60, 1080, 1920])])
        self.assertIsNone(video_frames._quartz_fast_path_layer(spec))

    def test_02_partial_rect_needs_the_compositor(self):
        spec = self._spec_layers([_layer(rect=[0, 0, 540, 960])])
        self.assertIsNone(video_frames._quartz_fast_path_layer(spec))

    def test_03_more_than_one_layer_needs_the_compositor(self):
        spec = self._spec_layers([_layer(), {"id": "t", "type": "text",
                                             "text": "x", "rect": [0, 0, 10, 10],
                                             "z": 1}])
        self.assertIsNone(video_frames._quartz_fast_path_layer(spec))


class TestRealExtraction(unittest.TestCase):
    """Real ffmpeg: fitted frame sizes, and rate-driven duplication."""

    def _fixture(self, d, seconds=1):
        path = os.path.join(d, "clip.mp4")
        s1._write_video_fixture(path, seconds=seconds, fps=30, w=270, h=480)
        return path

    def test_00_cover_and_contain_fit_the_rect_exactly(self):
        with tempfile.TemporaryDirectory() as d:
            clip = self._fixture(d)
            for fit in ("cover", "contain"):
                out = os.path.join(d, f"frames-{fit}")
                video_frames._extract_video_frames(_layer(fit=fit), clip, out, 20, 30, 320, 180)
                files = sorted(f for f in os.listdir(out) if f.endswith(".png"))
                self.assertEqual(len(files), 20, fit)
                w, h, _ = _png_payload(os.path.join(out, files[0]))
                self.assertEqual((w, h), (320, 180),
                                 f"{fit} must fill the layer rect exactly")

    def test_01_half_speed_duplicates_real_frames(self):
        # At rate 0.5 shot frames 0 and 1 are the SAME media frame: identical
        # bytes; frame 2 moves on.
        with tempfile.TemporaryDirectory() as d:
            clip = self._fixture(d)
            out = os.path.join(d, "frames")
            video_frames._extract_video_frames(_layer(playbackRate=0.5), clip, out, 6, 30, 320, 180)

            def _md5(i):
                import hashlib
                with open(os.path.join(out, f"{i:05d}.png"), "rb") as f:
                    return hashlib.sha256(f.read()).hexdigest()
            self.assertEqual(_md5(1), _md5(2))
            self.assertEqual(_md5(3), _md5(4))
            self.assertNotEqual(_md5(2), _md5(3))

    def test_02_trim_starts_the_window_at_the_right_frame(self):
        # trim [0.5, 1.0] on a 30-frame clip keeps frames 15..29; the first
        # extracted frame must equal a direct pull of media frame 16 (1-based).
        with tempfile.TemporaryDirectory() as d:
            clip = self._fixture(d)
            out = os.path.join(d, "frames")
            video_frames._extract_video_frames(_layer(trim=[0.5, 1.0], loop=False), clip,
                                               out, 15, 30, 270, 480)
            ref = os.path.join(d, "ref")
            os.makedirs(ref)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip,
                            "-vf", "select=gte(n\\,15)",
                            "-frames:v", "1", os.path.join(ref, "f.png")],
                           check=True, cwd=ROOT)
            import hashlib

            def _md5(p):
                with open(p, "rb") as f:
                    return hashlib.sha256(f.read()).hexdigest()
            self.assertEqual(_md5(os.path.join(out, "00001.png")),
                             _md5(os.path.join(ref, "f.png")))


class TestWarpedAudioActuallySyncs(unittest.TestCase):
    """End to end (real ffmpeg): the mastered native track follows the
    picture's warped timeline, not the source's.

    Source audio: 440 Hz on [0s, 0.5s], 880 Hz on [0.5s, 1s]. Shot: 2s,
    trim [0, 1], playbackRate 2, loop. Warped correctly, the window lasts
    0.5s of shot time and repeats 4x — the tone alternates every 0.25s.
    Unwarped (the old bug), it alternates every 0.5s."""

    @staticmethod
    def _dominant_hz(pcm_bytes, start_s, dur_s, rate=44100):
        samples = struct.unpack(f"<{len(pcm_bytes) // 2}h", pcm_bytes)
        lo, hi = int(start_s * rate), int((start_s + dur_s) * rate)
        crossings = 0
        for a, b in zip(samples[lo:hi - 1], samples[lo + 1:hi]):
            if (a < 0) != (b < 0):
                crossings += 1
        return crossings / 2 / dur_s

    def test_00_mastered_track_alternates_at_the_warped_pace(self):
        with tempfile.TemporaryDirectory() as d:
            clip = os.path.join(d, "clip.mp4")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=0x101830:s=64x64:r=30",
                 "-f", "lavfi", "-i", "sine=f=440:d=0.5",
                 "-f", "lavfi", "-i", "sine=f=880:d=0.5",
                 "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
                 "-map", "0:v", "-map", "[a]", "-t", "1",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                 clip],
                check=True, cwd=ROOT)

            frames = os.path.join(d, "frames")
            os.makedirs(frames)
            for i in range(60):
                video_frames._write_solid_png(os.path.join(frames, f"{i + 1:05d}.png"),
                                              64, 64, (3, 5, 9, 255))

            spec = _spec({"trim": [0.0, 1.0], "playbackRate": 2, "loop": True})
            out_mp4 = os.path.join(d, "out.mp4")
            with preserve_manifest(), \
                    mock.patch.object(encoding.manifest, "verified",
                                       return_value={"path": clip}):
                encoding.encode_mp4(spec, frames, out_mp4)

            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", out_mp4,
                 "-map", "0:a", "-ac", "1", "-ar", "44100", "-f", "s16le", "-"],
                check=True, capture_output=True, cwd=ROOT).stdout

            # Warped window = 0.5s: tone flips at 0.25s boundaries.
            early = self._dominant_hz(raw, 0.05, 0.15)
            mid = self._dominant_hz(raw, 0.30, 0.15)
            self.assertAlmostEqual(early, 440, delta=45,
                                   msg="shot t in [0.05,0.20] must be the 440 Hz half")
            self.assertAlmostEqual(mid, 880, delta=45,
                                   msg="shot t in [0.30,0.45] must already be the 880 Hz "
                                       "half — unwarped audio would still play 440 Hz here")


if __name__ == "__main__":
    unittest.main()
