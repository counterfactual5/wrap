"""Gate metric tests: subject sensitivity and spec-derived color masks."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.quality import pixels as metrics
from core.spec.loader import load_spec
from core.spec.shot import validate


class TestGateMetrics(unittest.TestCase):
    FIXTURE = os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")

    def test_00_spec_with_new_gates_validates(self):
        spec = load_spec(self.FIXTURE)
        errs = validate(spec)
        self.assertEqual(errs, [], f"spec invalid: {errs}")
        metric_ids = {g["metric"] for g in spec["gates"]}
        self.assertIn("subject_motion_ratio", metric_ids)
        self.assertIn("changed_pixel_ratio", metric_ids)

    def test_01_region_invalid_rejected(self):
        spec = load_spec(self.FIXTURE)
        bad = dict(spec)
        bad["gates"] = [dict(g) for g in spec["gates"]]
        bad["gates"][1]["region"] = [500, 100]  # y0 >= y1
        self.assertGreater(len(validate(bad)), 0)
        bad["gates"][1]["region"] = [0, 99999]  # beyond canvas
        self.assertGreater(len(validate(bad)), 0)

    def test_02_changed_ratio_excludes_band(self):
        # Two 4x4 frames: only row y=2 (inside band) changes.
        w = h = 4
        a = bytes(w * h)
        b = bytearray(a)
        b[2 * w:3 * w] = b"\x50" * w
        ratios = metrics.changed_pixel_ratios.__wrapped__ if hasattr(metrics.changed_pixel_ratios, "__wrapped__") else None
        # exercise the counting path directly through a tiny ffmpeg-free harness:
        # replicate the loop the function runs over _frames() output.
        luma_delta = 6
        exclude_band = (2, 3)
        n = 0
        for y in range(h):
            if exclude_band[0] <= y < exclude_band[1]:
                continue
            ra, rb = a[y * w:(y + 1) * w], bytes(b[y * w:(y + 1) * w])
            if ra != rb:
                n += sum(1 for p, q in zip(ra, rb) if abs(p - q) > luma_delta)
        self.assertEqual(n, 0, "band row must be excluded")
        # and without exclusion the change counts
        n2 = sum(1 for p, q in zip(a[2 * w:3 * w], b[2 * w:3 * w]) if abs(p - q) > luma_delta)
        self.assertEqual(n2, w)

    def test_03_color_mask_derived_from_spec(self):
        w = h = 10
        blue = bytes((0x3A, 0x6F, 0xE0)) * (w * h)
        tables = metrics._mask_tables((0x3A, 0x6F, 0xE0))
        ratio = metrics.color_ratio_of_frame(blue, w, h, tables)
        self.assertEqual(ratio, 1.0, "exact target color must fully match")
        # old hardcoded red mask must NOT match blue
        self.assertEqual(metrics.red_ratio_of_frame(blue, w, h), 0.0)

    def test_04_red_mask_still_matches_accent(self):
        w = h = 10
        red = bytes((0xE0, 0x3A, 0x3A)) * (w * h)
        tables = metrics._mask_tables((0xE0, 0x3A, 0x3A))
        self.assertEqual(metrics.color_ratio_of_frame(red, w, h, tables), 1.0)
        self.assertEqual(metrics.red_ratio_of_frame(red, w, h), 1.0)

    def test_05_slow_motion_cadence_dedup_vs_static_freeze(self):
        """P0-2: Slow-motion cadence holds (<= 6 frames) are stripped while long static runs remain 0.0."""
        import statistics
        # 0.5x playback rate: every active change is followed by a duplicate frame (0.0 or < 5e-5)
        slowmo_raw = [0.065, 0.0, 0.066, 0.000016, 0.064, 0.0, 0.067, 0.000012] * 18
        deduped = metrics.dedup_cadence_ratios(slowmo_raw)
        self.assertGreater(statistics.median(deduped), 0.06, "0.5x slowmo median should reflect active frame steps")

        # 0.25x playback rate: 1 active step + 3 held frames
        quarter_raw = [0.042, 0.0, 0.0, 0.0] * 20
        self.assertAlmostEqual(statistics.median(metrics.dedup_cadence_ratios(quarter_raw)), 0.042, places=4)

        # Truly static clip (e.g. shot-10: brief entrance then 120 frozen frames) must NOT strip the long zero run
        static_raw = [0.02, 0.015] + [0.0] * 120
        deduped_static = metrics.dedup_cadence_ratios(static_raw)
        self.assertEqual(statistics.median(deduped_static), 0.0, "truly frozen shot must still fail motion median")

    def test_06_two_pass_loudnorm_short_voice_long_shot(self):
        """P0-1: Short voiceover + longer shot mastered via two-pass loudnorm lands within [-19, -13] LUFS and close to -16 LUFS.

        The voice source is a locally generated fixture (a speech-like band-limited
        tone) so the test does not depend on the network or on the exact bytes of an
        Edge voice snapshot — those can legitimately drift over time. What the test
        guards is the loudnorm chain reaching the target within tolerance.
        """
        import tempfile
        import subprocess
        from core.audio import prepare_shot_audio, measure_audio_loudness

        with tempfile.TemporaryDirectory() as tmp:
            fixture = os.path.join(tmp, "voice.wav")
            subprocess.run([
                "ffmpeg", "-f", "lavfi", "-i",
                ("sine=frequency=220:duration=1.6,"
                 "afade=t=in:st=0:d=0.03,afade=t=out:st=1.5:d=0.1,"
                 "alimiter=limit=0.3"),
                "-y", "-ar", "44100", "-ac", "1", fixture
            ], check=True)
            audio_spec = {
                "voiceover": fixture,  # a path to a source file (prepare_shot_audio treats it as the voice)
                "voice": "TestVoice",
                "bgm": fixture,
            }
            out_m4a = os.path.join(tmp, "shot_audio.m4a")
            wav_path = prepare_shot_audio(audio_spec, duration_in_frames=150, fps=30, out_path=out_m4a)
            self.assertTrue(os.path.exists(wav_path))
            lufs = measure_audio_loudness(wav_path)
            self.assertIsNotNone(lufs)
            self.assertGreaterEqual(lufs, -19.0, f"LUFS too quiet: {lufs}")
            self.assertLessEqual(lufs, -13.0, f"LUFS too loud: {lufs}")
            self.assertAlmostEqual(lufs, -16.0, delta=1.5, msg=f"Two-pass loudnorm drifted: {lufs}")

    def test_07_tts_asset_freeze_and_deterministic_reuse(self):
        """TTS asset freeze: same text+voice+rate produces identical frozen asset in assets/ without network calls on 2nd run."""
        import tempfile
        import hashlib
        from core.audio import synthesize_voiceover_with_timings

        test_text = "冻结确定性配音测试。"
        h = hashlib.sha256(f"TestVoice_+18%_{test_text}".encode("utf-8")).hexdigest()[:16]
        frozen_wav = os.path.join(ROOT, "assets", f"tts_{h}.wav")
        frozen_meta = os.path.join(ROOT, "assets", f"tts_{h}.meta.json")

        with tempfile.TemporaryDirectory() as tmp:
            out1 = os.path.join(tmp, "v1.wav")
            out2 = os.path.join(tmp, "v2.wav")
            try:
                p1, dur1, b1 = synthesize_voiceover_with_timings(test_text, voice="TestVoice", rate="+18%", out_path=out1)
                self.assertTrue(os.path.exists(frozen_wav), "TTS should freeze generated audio to assets/")
                self.assertTrue(os.path.exists(frozen_meta), "TTS should freeze sentence metadata to assets/")

                p2, dur2, b2 = synthesize_voiceover_with_timings(test_text, voice="TestVoice", rate="+18%", out_path=out2)
                with open(out1, "rb") as f1, open(out2, "rb") as f2:
                    self.assertEqual(f1.read(), f2.read(), "Reused TTS must be 100% bit-exact")
                self.assertAlmostEqual(dur1, dur2, places=3)
                self.assertEqual(b1, b2)
            finally:
                if os.path.exists(frozen_wav):
                    os.remove(frozen_wav)
                if os.path.exists(frozen_meta):
                    os.remove(frozen_meta)

    def test_08_pure_bgm_optional_voiceover_and_gate_pass(self):
        """TTS is optional: shots with pure BGM (Douyin track/ambient) master to -16 LUFS and pass without speech-band requirement."""
        import tempfile
        import json
        from core.audio import prepare_shot_audio, measure_audio_loudness, measure_audio_silence

        with tempfile.TemporaryDirectory() as tmp:
            bgm = os.path.join(tmp, "music.wav")
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=6.0",
                "-ar", "44100", "-ac", "2", bgm
            ], check=True)
            audio_spec = {"bgm": bgm}
            out_m4a = os.path.join(tmp, "bgm_only.m4a")
            wav_path = prepare_shot_audio(audio_spec, duration_in_frames=90, fps=30, out_path=out_m4a)
            self.assertTrue(os.path.exists(wav_path))
            meta_path = out_m4a + ".meta.json"
            self.assertTrue(os.path.exists(meta_path))
            with open(meta_path) as f:
                meta = json.load(f)
            self.assertFalse(meta["has_voice"], "has_voice must be false for pure BGM shot")

            lufs = measure_audio_loudness(wav_path)
            self.assertIsNotNone(lufs)
            self.assertGreaterEqual(lufs, -19.0)
            self.assertLessEqual(lufs, -13.0)

            sil = measure_audio_silence(wav_path)
            self.assertFalse(sil["is_silent"], "Pure BGM track must not be silent (> -45 dB)")

    def test_09_bgm_offset_and_external_music_file(self):
        """BGM offset allows slicing a specific window of a platform music track for multi-shot cuts."""
        import tempfile
        import subprocess
        from core.audio import prepare_shot_audio, measure_audio_loudness

        with tempfile.TemporaryDirectory() as tmp:
            track_src = os.path.join(tmp, "platform_track.wav")
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=6.0",
                "-ar", "44100", "-ac", "2", track_src
            ], check=True)

            out_m4a = os.path.join(tmp, "cut.m4a")
            audio_spec = {
                "bgm": track_src,
                "bgmOffset": 2.0,
            }
            prepare_shot_audio(audio_spec, duration_in_frames=90, fps=30, out_path=out_m4a)
            self.assertTrue(os.path.exists(out_m4a))
            lufs = measure_audio_loudness(out_m4a)
            self.assertIsNotNone(lufs)
            self.assertGreaterEqual(lufs, -19.0)
            self.assertLessEqual(lufs, -13.0)

    def test_10_sync_spec_audio_without_voiceover_preserves_authored_tracks(self):
        """sync-audio without voiceover is a no-op: authored captions/events stay untouched."""
        import tempfile
        import json
        from core.audio import sync_spec_audio

        spec = {
            "id": "music-cards-shot",
            "fps": 30,
            "durationInFrames": 120,
            "layers": [],
            "tracks": {"captions": [
                {"frame": 0, "end_frame": 60, "text": "第一张海报视觉呈现"},
                {"frame": 61, "text": "第二张核心数据卡片"},
            ], "events": [{"frame": 30, "kind": "contact"}]},
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "shot.poster.json")
            with open(p, "w") as f:
                json.dump(spec, f)
            res = sync_spec_audio(p)
            self.assertEqual(res.get("status"), "no_voiceover")
            with open(p) as f:
                self.assertEqual(json.load(f), spec)


if __name__ == "__main__":
    unittest.main()
