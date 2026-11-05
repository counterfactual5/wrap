"""Unit tests for evolved capabilities:
1. S5 Visual self-audit (contact sheet & checklist)
2. S4 Audio gates (silence detection, integrated loudness, AV sync)
3. Timeline beat & reason validation and narrative contract
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core import audio
from core.schema import VALID_BEATS, validate_timeline
from tests.helpers import ensure_rendered


class TestEvolveFeatures(unittest.TestCase):
    def test_01_timeline_validation(self):
        # 1. Valid string shots (backward compatibility)
        tl_str = {"id": "test-seq", "shots": ["spec/shot-01.poster.json"]}
        self.assertEqual(len(validate_timeline(tl_str)), 0)

        # 2. Valid structured shots with beat and reason
        tl_struct = {
            "id": "test-narrative",
            "shots": [
                {
                    "spec": "spec/shot-01.poster.json",
                    "beat": "hook",
                    "reason": "Dramatic visual introduction"
                },
                {
                    "spec": "spec/shot-02.poster.json",
                    "beat": "climax",
                    "reason": "Core physical inversion"
                }
            ]
        }
        self.assertEqual(len(validate_timeline(tl_struct)), 0)

        # 3. Invalid beat should fail
        tl_bad_beat = {
            "id": "bad-beat",
            "shots": [{"spec": "spec/shot-01.poster.json", "beat": "invalid_beat", "reason": "test"}]
        }
        errs = validate_timeline(tl_bad_beat)
        self.assertGreater(len(errs), 0)
        self.assertTrue(any("invalid beat" in e for e in errs))

        # 4. Missing spec in dict should fail
        tl_no_spec = {
            "id": "bad-dict",
            "shots": [{"beat": "hook", "reason": "no spec"}]
        }
        errs = validate_timeline(tl_no_spec)
        self.assertGreater(len(errs), 0)

    def test_02_audio_qc_helpers(self):
        # Generate temporary sine tone with voice
        tmp_wav = os.path.join(ROOT, ".tmp", "test_tone.wav")
        os.makedirs(os.path.dirname(tmp_wav), exist_ok=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=2",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            tmp_wav
        ], check=True)

        # 1. Silence check
        sil_res = audio.measure_audio_silence(tmp_wav)
        self.assertFalse(sil_res["is_silent"], f"Tone detected as silent: {sil_res}")
        self.assertGreater(sil_res["max_volume"], -40.0)

        # 2. Loudness check
        lufs = audio.measure_audio_loudness(tmp_wav)
        self.assertIsNotNone(lufs)
        self.assertAlmostEqual(lufs, -16.0, delta=2.5)

        # 3. AV sync test helper
        dur_res = audio.measure_av_durations(tmp_wav)
        self.assertTrue(dur_res["has_audio"])
        self.assertAlmostEqual(dur_res["audio_duration"], 2.0, delta=0.2)

        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

    def test_03_visual_inspect_stage(self):
        # S5 inspects a rendered shot and reads the gates S4 wrote.
        # `make clean` removes build/, so the shot is rendered here rather
        # than relying on a leftover artifact.
        ensure_rendered("spec/shot-01.poster.json", "shot-01", through_gate=True)
        res = subprocess.run([
            sys.executable, "stages/05_inspect.py", "--spec", "spec/shot-01.poster.json"
        ], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"05_inspect.py failed:\n{res.stderr}")

        sheet_path = os.path.join(ROOT, "build", "contact_sheet_shot-01.png")
        self.assertTrue(os.path.exists(sheet_path), "Contact sheet not generated")
        self.assertGreater(os.path.getsize(sheet_path), 5000)

        inspect_path = os.path.join(ROOT, "build", "inspection_shot-01.json")
        self.assertTrue(os.path.exists(inspect_path), "Inspection JSON missing")
        with open(inspect_path) as f:
            data = json.load(f)
        self.assertEqual(data["shot_id"], "shot-01")
        self.assertEqual(data["grid"], "3x3")
        self.assertIn("checklist", data)
        # Honest contract: an unjudged inspection never claims pass
        self.assertEqual(data["verdict"], "pending_judge")

        gates_path = os.path.join(ROOT, "build", "gates", "shot-01.json")
        if os.path.exists(gates_path):
            with open(gates_path) as f:
                gates = json.load(f)
            entry = next((g for g in gates if g.get("id") == "visual_inspect"), None)
            if entry is not None:
                self.assertIsNone(entry["pass"], "visual_inspect must be pass=null until judged")
                self.assertEqual(entry["status"], "pending_judge")

        # Recording a fail verdict must flip the gate entry and exit non-zero
        res = subprocess.run([
            sys.executable, "stages/05_inspect.py", "--spec", "spec/shot-01.poster.json",
            "--record", "fail", "--notes", "unit-test fail recording"
        ], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0, "record fail must exit non-zero")
        with open(inspect_path) as f:
            data = json.load(f)
        self.assertEqual(data["verdict"], "fail")
        self.assertEqual(data["notes"], "unit-test fail recording")
        with open(gates_path) as f:
            gates = json.load(f)
        entry = next(g for g in gates if g.get("id") == "visual_inspect")
        self.assertFalse(entry["pass"])
        self.assertEqual(entry["status"], "judged")

        # Recording a pass verdict exits zero and flips the entry back
        res = subprocess.run([
            sys.executable, "stages/05_inspect.py", "--spec", "spec/shot-01.poster.json",
            "--record", "pass", "--notes", "unit-test pass recording"
        ], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(gates_path) as f:
            gates = json.load(f)
        entry = next(g for g in gates if g.get("id") == "visual_inspect")
        self.assertTrue(entry["pass"])
        self.assertEqual(entry["status"], "judged")


if __name__ == "__main__":
    unittest.main()
