"""S1 asset transport tests: URL parsing, format normalization, spec-driven aspect ratio.

These cover the path that actually calls the generation backend
(mcode-tools connector). The end-to-end suite passed while that path was
broken — nothing here exercised it — so the transport layer gets its own
tests: a green suite must mean the download step works, not merely that the
Python files import.

Test doubles, not network calls: the CLI is invoked through a patched
subprocess.run so no real generation is billed or awaited.
"""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "s1_generate", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_bytes(w=4, h=4):
    """A minimal valid PNG (RGB8) so format checks have real bytes to read."""
    import zlib
    import struct
    raw = b"".join(b"\x00" + bytes((10, 20, 30)) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (PNG_MAGIC
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


class TestAssetUrlParsing(unittest.TestCase):
    """The CLI returns download_url; the old code looked for url/asset_url."""

    def test_00_prefers_download_url_key(self):
        payload = {"node_id": "123", "download_url": "https://example.invalid/a.jpg"}
        with mock.patch.object(s1.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            url = s1.fetch_asset_url("123")
        self.assertEqual(url, "https://example.invalid/a.jpg")

    def test_01_accepts_legacy_url_keys(self):
        for key in ("url", "asset_url"):
            with self.subTest(key=key):
                payload = {"node_id": "123", key: "https://example.invalid/legacy.png"}
                with mock.patch.object(s1.subprocess, "run") as run:
                    run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=json.dumps(payload), stderr="")
                    url = s1.fetch_asset_url("123")
                self.assertEqual(url, "https://example.invalid/legacy.png")

    def test_02_raises_readable_error_when_no_url_field(self):
        """A JSON blob with no url field must not be returned as the URL."""
        payload = {"node_id": "123", "message": "ok"}
        with mock.patch.object(s1.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            with self.assertRaises(RuntimeError) as ctx:
                s1.fetch_asset_url("123")
        self.assertNotIn("{", str(ctx.exception),
                         "the raw JSON was returned as if it were a URL")


class TestFormatNormalization(unittest.TestCase):
    """Generated assets arrive as JPEG; the pipeline requires real PNG."""

    def test_00_detects_non_png(self):
        self.assertFalse(s1.is_png(b"\xff\xd8\xff\xe1\x00" + b"\x00" * 32))
        self.assertTrue(s1.is_png(_png_bytes()))

    def test_01_converts_to_true_png(self):
        import tempfile
        # A real JPEG-ish blob is not decodable by ffmpeg; use a PNG payload
        # with a non-PNG extension to exercise the conversion path, and assert
        # the result is a genuine PNG either way.
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "asset.bin")
            dst = os.path.join(d, "asset.png")
            with open(src, "wb") as f:
                f.write(_png_bytes(8, 8))
            s1.ensure_png(src, dst)
            with open(dst, "rb") as f:
                head = f.read(8)
            self.assertEqual(head, PNG_MAGIC, "converted file is not a true PNG")

    def test_02_rejects_unconvertible_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "junk.bin")
            dst = os.path.join(d, "junk.png")
            with open(src, "wb") as f:
                f.write(b"not an image at all" * 8)
            with self.assertRaises(RuntimeError):
                s1.ensure_png(src, dst)


class TestAspectRatioFromCanvas(unittest.TestCase):
    """The generation request must follow the shot's canvas, not a fixed 16:9."""

    def test_00_vertical_canvas_yields_vertical_ratio(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1920), "9:16")

    def test_01_landscape_canvas_yields_landscape_ratio(self):
        self.assertEqual(s1.aspect_for_canvas(1920, 1080), "16:9")

    def test_02_square_canvas(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1080), "1:1")

    def test_03_portrait_four_by_three(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1440), "3:4")


class TestGenerateRequestShape(unittest.TestCase):
    """The request payload must carry the derived ratio, not a hardcoded one."""

    def test_00_request_uses_spec_canvas(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"success_items": [{"node_id": "77"}]}), stderr="")

        with mock.patch.object(s1.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("a subject", "asset-x", aspect_ratio="9:16", resolution="2K")

        req = captured["payload"]["requests"][0]
        self.assertEqual(req["aspect_ratio"], "9:16")
        self.assertEqual(req["resolution"], "2K")
        self.assertEqual(req["prompt"], "a subject")


if __name__ == "__main__":
    unittest.main()
