import os
import tempfile
import unittest
from unittest.mock import patch

from core import audio


class TestPrepareShotAudioScratchFiles(unittest.TestCase):
    def test_scratch_files_are_scoped_to_out_path(self):
        loudnorm_calls = []

        def fake_synth(text, voice, out_path, rate):
            with open(out_path, "w") as f:
                f.write(text)
            return out_path, 1.0, []

        def fake_loudnorm(inputs, opt, value, target_dur, out_path):
            loudnorm_calls.append(list(inputs))
            with open(out_path, "w") as f:
                f.write("audio")

        def fake_ambient(duration, out_path, **kwargs):
            with open(out_path, "w") as f:
                f.write("bgm")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("core.audio.shot.synthesize_voiceover_with_timings", side_effect=fake_synth), \
                patch("core.audio.shot.run_two_pass_loudnorm", side_effect=fake_loudnorm), \
                patch("core.audio.shot.verify_audio", side_effect=lambda p: p), \
                patch("core.audio.shot.subprocess.run"):
            bgm = os.path.join(tmp, "music.wav")
            fake_ambient(1, bgm)
            out1 = os.path.join(tmp, "shot-a.aac")
            out2 = os.path.join(tmp, "shot-b.aac")
            audio.prepare_shot_audio({"voiceover": "你好世界", "voice": "TestVoice", "bgm": bgm, "bgmUnderVoice": 0.25}, 30, 30, out1)
            audio.prepare_shot_audio({"voiceover": "你好世界", "voice": "TestVoice", "bgm": bgm, "bgmUnderVoice": 0.25}, 30, 30, out2)

        self.assertEqual(len(loudnorm_calls), 2)
        for inputs, out in ((loudnorm_calls[0], out1), (loudnorm_calls[1], out2)):
            scratch = [os.path.basename(p) for p in inputs if p != "-i"]
            self.assertEqual(scratch, [os.path.basename(out) + ".voice.wav", os.path.basename(out) + ".bgm.wav"])
        # No shared legacy scratch names may be used, and the two calls must not overlap.
        for inputs in loudnorm_calls:
            self.assertNotIn("shot_voice.wav", [os.path.basename(p) for p in inputs])
            self.assertNotIn("shot_bgm.wav", [os.path.basename(p) for p in inputs])
        scratch1 = [p for p in loudnorm_calls[0] if p != "-i"]
        scratch2 = [p for p in loudnorm_calls[1] if p != "-i"]
        self.assertTrue(set(scratch1).isdisjoint(scratch2))


if __name__ == "__main__":
    unittest.main()


class TestVoiceOnlyApadPadding(unittest.TestCase):
    """Voice-only shots pad the voice track to full shot duration with silence,
    so -shortest in the compose stage never cuts the video short of
    durationInFrames (S5 frame-count check)."""

    def test_voice_only_loudnorm_includes_apad(self):
        from core import audio

        def fake_synth(text, voice, out_path, rate="+0%"):
            with open(out_path, "w") as f:
                f.write("voice")
            return out_path, 1.0, []

        def fake_loudnorm(inputs, opt, value, target_dur, out_path):
            loudnorm_calls.append((list(inputs), opt, value, target_dur))
            with open(out_path, "w") as f:
                f.write("audio")

        loudnorm_calls = []
        import tempfile, os
        from core.audio import shot as audio_shot
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(audio_shot, "synthesize_voiceover_with_timings", side_effect=fake_synth), \
                patch.object(audio_shot, "run_two_pass_loudnorm", side_effect=fake_loudnorm), \
                patch.object(audio_shot, "verify_audio", side_effect=lambda p: p):
            # 90 frames @ 30fps = 3.0 s shot
            audio_shot.prepare_shot_audio(
                {"voiceover": "你好世界", "voice": "TestVoice"}, 90, 30, os.path.join(tmp, "out.aac"))

        self.assertEqual(len(loudnorm_calls), 1, loudnorm_calls)
        inputs, opt, value, target_dur = loudnorm_calls[0]
        # The voice-only branch must pad the track to the full shot duration,
        # exactly like the voice+BGM branch does — otherwise -shortest cuts the
        # video to speech length and S5's frame check fails.
        self.assertEqual(opt, "-af")
        self.assertEqual(value, "apad=whole_dur=3.0")
        self.assertEqual(target_dur, 3.0)
        self.assertTrue(inputs[0] == "-i" and inputs[1].endswith(".wav"), inputs)


class TestBgmUnderVoiceIsDeclared(unittest.TestCase):
    """Voice+BGM mixes must declare the duck ratio; the engine ships none."""

    def test_voice_and_bgm_without_bgmUnderVoice_is_an_error(self):
        from unittest import mock
        import contextlib
        import tempfile, os
        from core.audio import shot as audio_shot
        from core.audio import mastering

        def fake_synth(text, voice, out_path, rate="+0%"):
            with open(out_path, "w") as f:
                f.write("voice")
            return out_path, 1.0, []

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(audio_shot, "synthesize_voiceover_with_timings", side_effect=fake_synth), \
                mock.patch.object(audio_shot, "verify_audio", side_effect=lambda p: p):
            bgm = os.path.join(tmp, "music.wav")
            with open(bgm, "w") as f:
                f.write("bgm")
            with self.assertRaises(ValueError) as ctx:
                audio_shot.prepare_shot_audio(
                    {"voiceover": "你好", "voice": "TestVoice", "bgm": bgm},
                    30, 30, os.path.join(tmp, "out.aac"))
            self.assertIn("bgmUnderVoice", str(ctx.exception))
