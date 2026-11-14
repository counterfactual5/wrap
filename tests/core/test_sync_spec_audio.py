import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core.audio import sync_spec_audio, synthesize_voiceover_with_timings


class TestSyncSpecAudio(unittest.TestCase):
    def test_paces_all_nonempty_caption_layers_without_voiceover(self):
        spec = {"id": "shot", "durationInFrames": 120, "layers": [
            {"type": "code", "draw": "captions", "params": {"items": []}},
            {"type": "code", "draw": "captions", "params": {"items": [{"text": "第一句"}, {"text": "第二句"}]}},
            {"type": "code", "draw": "captions", "params": {"items": [{"text": "另一句"}, {"text": "最后一句", "hl": "保留"}]}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spec.json")
            with open(path, "w") as f:
                json.dump(spec, f)
            result = sync_spec_audio(path)
            with open(path) as f:
                layers = json.load(f)["layers"]
        self.assertEqual(result["updated_caption_layers"], 2)
        for layer in layers[1:]:
            items = layer["params"]["items"]
            self.assertEqual(items[0]["frame"], 0)
            self.assertGreater(items[1]["frame"], 0)
            self.assertIn("end_frame", items[1])
        self.assertEqual(layers[2]["params"]["items"][1]["hl"], "保留")

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
                synthesize_voiceover_with_timings(text, out_path=path)
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
                    json.dump({"id": "same", "audio": {"voiceover": str(i)}}, f)
                specs.append(path)
            with patch("core.audio.sync.synthesize_voiceover_with_timings", side_effect=synthesize):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(sync_spec_audio, specs))
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(not os.path.exists(path) for path in paths))


if __name__ == "__main__":
    unittest.main()
