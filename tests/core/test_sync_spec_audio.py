import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core.audio import sync_spec_audio, synthesize_voiceover_with_timings


class TestSyncSpecAudio(unittest.TestCase):
    def test_without_voiceover_preserves_authored_track(self):
        spec = {"id": "shot", "fps": 30, "durationInFrames": 120, "layers": [],
                "tracks": {"captions": [{"frame": 12, "end_frame": 80, "text": "Authored"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spec.json")
            with open(path, "w") as f:
                json.dump(spec, f)
            result = sync_spec_audio(path)
            with open(path) as f:
                self.assertEqual(json.load(f), spec)
        self.assertEqual(result["status"], "no_voiceover")

    def test_concurrent_synthesis_isolates_intermediate_audio(self):
        barrier = threading.Barrier(2)
        raw_paths = []

        def download(text, voice, rate, out_mp3):
            raw_paths.append(out_mp3)
            with open(out_mp3, "w") as f:
                f.write(text * 1001)
            barrier.wait(timeout=5)
            return []

        def ffmpeg(args, check):
            with open(args[args.index("-i") + 1]) as src, open(args[-1], "w") as dst:
                dst.write(src.read())

        with tempfile.TemporaryDirectory() as tmp:
            def run(text):
                path = os.path.join(tmp, text + ".wav")
                synthesize_voiceover_with_timings(text, voice="TestVoice", out_path=path)
                with open(path) as f:
                    return f.read()

            with patch("core.audio.tts.ROOT", tmp), patch("core.audio.tts._download_edge_tts", side_effect=download), \
                    patch("core.audio.tts.subprocess.run", side_effect=ffmpeg), patch("core.audio.tts.get_audio_duration", return_value=1.0):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outputs = list(pool.map(run, ["a", "b"]))
            self.assertEqual(outputs, ["a" * 1001, "b" * 1001])
            self.assertEqual(len(set(raw_paths)), 2)
            self.assertTrue(all(not os.path.exists(path) for path in raw_paths))

    def test_concurrent_same_id_has_isolated_temporary_output(self):
        barrier = threading.Barrier(2)
        paths = []
        def synthesize(text, voice, out_path, rate):
            paths.append(out_path)
            with open(out_path, "w") as f:
                f.write(text)
            barrier.wait(timeout=5)
            with open(out_path) as f:
                self.assertEqual(f.read(), text)
            return out_path, 1.0, []

        with tempfile.TemporaryDirectory() as tmp:
            specs = []
            for i in range(2):
                path = os.path.join(tmp, f"{i}.json")
                with open(path, "w") as f:
                    json.dump({"id": "same", "fps": 30, "durationInFrames": 60,
                           "audio": {"voiceover": str(i), "voice": "TestVoice"}}, f)
                specs.append(path)
            with patch("core.audio.sync.synthesize_voiceover_with_timings", side_effect=synthesize):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(sync_spec_audio, specs))
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(not os.path.exists(path) for path in paths))


if __name__ == "__main__":
    unittest.main()
