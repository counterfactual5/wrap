"""Contact sheets cover the shot and fill every cell, including short shots."""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
_spec = importlib.util.spec_from_file_location('s5_sampling', os.path.join(ROOT, 'stages', '05_inspect.py'))
s5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s5)


class SamplingTests(unittest.TestCase):
    def test_indices(self):
        self.assertEqual(s5.contact_sample_indices(11, '3x3'), [0, 1, 3, 4, 5, 6, 8, 9, 10])
        self.assertEqual(s5.contact_sample_indices(3, '3x2'), [0, 0, 1, 1, 2, 2])
        self.assertEqual(s5.contact_sample_indices(1, '2x2'), [0, 0, 0, 0])
        self.assertEqual(s5.contact_sample_indices(10, '1x1'), [0])

    def test_invalid_inputs(self):
        for grid in ('0x3', '3x0', '-1x2', '3X3', '3x3x1', '01x2', ''):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                s5.contact_sample_indices(10, grid)
        for frames in (0, -1, 1.5, True):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                s5.contact_sample_indices(frames, '2x2')

    def test_cell_aspect(self):
        self.assertEqual(s5.contact_sheet_cell(1920, 1080), (640, 360))
        self.assertEqual(s5.contact_sheet_cell(1080, 1920), (360, 640))
        self.assertEqual(s5.contact_sheet_cell(0, 0), (640, 640))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
    def test_real_sheet_fills_short_grid_and_reaches_last_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, 'input.mkv')
            sheet = os.path.join(tmp, 'sheet.png')
            # Three distinct lossless solid frames: red, green, blue.
            raw = bytes([255, 0, 0] * 32 * 16 + [0, 255, 0] * 32 * 16 + [0, 0, 255] * 32 * 16)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                            '-s', '32x16', '-r', '1', '-i', 'pipe:0', '-c:v', 'ffv1', video],
                           input=raw, check=True)
            s5.generate_contact_sheet(video, 3, sheet, '3x2')
            self.assertEqual(s5.probe_video_dims(sheet), (1920, 640))
            pixels = subprocess.run(['ffmpeg', '-v', 'error', '-i', sheet, '-f', 'rawvideo',
                                     '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True, check=True).stdout
            for i, expected in enumerate(((255, 0, 0), (255, 0, 0), (0, 255, 0),
                                          (0, 255, 0), (0, 0, 255), (0, 0, 255))):
                x, y = (i % 3) * 640 + 320, (i // 3) * 320 + 160
                offset = (y * 1920 + x) * 3
                self.assertEqual(tuple(pixels[offset:offset + 3]), expected)
            s5.generate_contact_sheet(video, 3, sheet, '1x1')
            self.assertEqual(s5.probe_video_dims(sheet), (640, 320))
            with self.assertRaisesRegex(ValueError, '3 frames, expected 4'):
                s5.generate_contact_sheet(video, 4, sheet, '3x2')


if __name__ == '__main__':
    unittest.main()
