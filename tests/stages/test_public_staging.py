"""The staged clip must land inside public/.

S3 stages each video layer's prepared clip under public/prepared/{shot}/ so
Remotion's staticFile() can find it. A shot id or asset name containing ../
would otherwise write outside public/ — into the repository (or beyond).
The spec validator rejects such ids, and this checks the path construction
itself: the two guards are independent on purpose.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.runtime import manifest
from core.rendering import build_props


class TestPublicStagingPath(unittest.TestCase):
    def _build_props(self, shot_id, asset):
        import tempfile
        spec = {
            "id": shot_id,
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [{"id": "clip", "type": "video", "asset": asset,
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [],
        }
        # build_props copies the prepared clip, so a real file must exist.
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.write(b"fake mp4 bytes")
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.remove(tmp.name))
        row = {"path": tmp.name, "sha256": "0" * 64, "bytes": 13}
        with mock.patch.object(manifest, "verified", return_value=row):
            return build_props(spec)

    def test_00_an_ordinary_shot_stages_inside_public(self):
        props = self._build_props("shot-01", "clip-a")
        rel = props["preparedVideos"]["clip"]
        self.assertTrue(rel.startswith("prepared/"), rel)
        self.assertNotIn("..", rel)

    def test_01_a_traversing_asset_name_is_refused(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._build_props("shot-01", "../../escape")
        self.assertIn("outside", str(ctx.exception))

    def test_02_a_traversing_shot_id_is_refused(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._build_props("../escape", "clip-a")
        self.assertIn("outside", str(ctx.exception))

    def test_03_a_deep_traversal_is_refused(self):
        """Two levels up leaves public/ entirely."""
        with self.assertRaises(RuntimeError) as ctx:
            self._build_props("shot-01", "../../../escape")
        self.assertIn("outside", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
