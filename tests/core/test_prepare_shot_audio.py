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
                patch("core.audio.shot.generate_ambient_bgm", side_effect=fake_ambient):
            out1 = os.path.join(tmp, "shot-a.aac")
            out2 = os.path.join(tmp, "shot-b.aac")
            audio.prepare_shot_audio({"voiceover": "你好世界", "bgm": "ambient"}, 30, 30, out1)
            audio.prepare_shot_audio({"voiceover": "你好世界", "bgm": "ambient"}, 30, 30, out2)

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
