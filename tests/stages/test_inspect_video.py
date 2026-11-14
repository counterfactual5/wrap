"""The review material must cover every layer the spec declares.

A video layer was in the spec but nowhere in the review checklist: the
extracted checklist for a shot with a clip and a title listed only the title,
so the reviewer could not tell from the material what the shot's subject was.
The clip's own facts (duration, upscale) live in the prepared manifest row S2
wrote, so the checklist can carry them.
"""
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "s5_inspect", os.path.join(ROOT, "stages", "05_inspect.py")
)
s5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s5)


def _spec(layers):
    return {
        "id": "clip-shot",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 150,
        "layers": layers,
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.3}],
    }


def _video_layer(**extra):
    layer = {"id": "clip", "type": "video", "asset": "my-clip",
             "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


class TestVideoAssetsInChecklist(unittest.TestCase):
    def test_00_a_video_layer_appears_in_the_checklist(self):
        spec = _spec([_video_layer()])
        checklist = s5.extract_checklist(spec)
        self.assertIn("video_assets", checklist)
        self.assertEqual(len(checklist["video_assets"]), 1)
        self.assertEqual(checklist["video_assets"][0]["asset"], "my-clip")

    def test_01_the_clip_facts_come_from_the_prepared_row(self):
        row = {"path": "build/prepared/clip-shot/my-clip.mp4",
               "source_duration": 5.167, "shot_duration": 5.0, "upscale": 2.308}
        with mock.patch.object(s5.manifest, "verified", return_value=row):
            checklist = s5.extract_checklist(_spec([_video_layer()]))
        entry = checklist["video_assets"][0]
        self.assertEqual(entry["source_duration"], 5.167)
        self.assertEqual(entry["shot_duration"], 5.0)
        self.assertEqual(entry["upscale"], 2.308)

    def test_02_a_missing_prepared_row_still_lists_the_clip(self):
        """S5 may run before S2; the material must not be empty because of it."""
        with mock.patch.object(s5.manifest, "verified", return_value=None):
            checklist = s5.extract_checklist(_spec([_video_layer()]))
        entry = checklist["video_assets"][0]
        self.assertEqual(entry["asset"], "my-clip")
        self.assertNotIn("upscale", entry)

    def test_03_a_video_only_shot_has_review_material(self):
        """The bug this guards: a shot whose only subject is a clip produced
        a checklist with nothing in it."""
        checklist = s5.extract_checklist(_spec([_video_layer()]))
        self.assertGreater(sum(len(v) for v in checklist.values()), 0)

    def test_04_the_other_layer_kinds_still_work(self):
        spec = _spec([
            {"id": "t", "type": "text", "text": "hello", "rect": [0, 0, 10, 10], "z": 0},
            {"id": "a", "type": "ai", "asset": "pic", "keyColor": "#070512",
             "blend": "normal", "rect": [0, 0, 10, 10], "z": 0},
            {"id": "c", "type": "code", "draw": "grid", "rect": [0, 0, 10, 10], "z": 0},
            {"id": "h", "type": "hud", "hudType": "badge", "rect": [0, 0, 10, 10], "z": 0},
            {"id": "cd", "type": "card", "cardType": "quote", "title": "q",
             "rect": [0, 0, 10, 10], "z": 0},
        ])
        checklist = s5.extract_checklist(spec)
        self.assertEqual(len(checklist["texts"]), 1)
        self.assertEqual(len(checklist["ai_assets"]), 1)
        self.assertEqual(len(checklist["code_draws"]), 1)
        self.assertEqual(len(checklist["hud_types"]), 1)
        self.assertEqual(len(checklist["cards"]), 1)


class TestJudgeInstructions(unittest.TestCase):
    def test_00_the_clip_is_named_in_the_reviewer_material(self):
        spec = _spec([_video_layer()])
        with mock.patch.object(s5.manifest, "verified", return_value=None):
            checklist = s5.extract_checklist(spec)
        text = s5.judge_instructions("clip-shot", "build/sheet.png", checklist)
        self.assertIn("my-clip", text)
        self.assertIn("video_assets", text)

    def test_01_the_subject_criterion_covers_video_clips(self):
        joined = " ".join(s5.AUDIT_CRITERIA)
        subject = next(c for c in s5.AUDIT_CRITERIA if c.startswith("subject_fidelity"))
        self.assertIn("video clip", subject)
        self.assertIn("subject_fidelity", joined)


if __name__ == "__main__":
    unittest.main()
