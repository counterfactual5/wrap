"""write_png_rgba: RGBA8 PNG output for layered compositing (pitfall 16)."""
import os
import struct
import subprocess
import tempfile
import unittest
import zlib

from core.media.png import read_size, write_png, write_png_rgba


def _png_chunks(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, out = 8, {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        out[tag] = data[pos + 8:pos + 8 + length]
        pos += 12 + length
    return out


class WritePngRgbaTests(unittest.TestCase):
    def test_rgba_header_size_and_roundtrip(self):
        w, h = 4, 3
        rgba = bytes((x % 256 for x in range(w * h * 4)))
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "cup.png")
            write_png_rgba(p, w, h, rgba)
            chunks = _png_chunks(p)
            # IHDR: width, height, bit depth 8, color type 6 (RGBA)
            self.assertEqual(chunks[b"IHDR"][:8], struct.pack(">II", w, h))
            self.assertEqual(chunks[b"IHDR"][8], 8)
            self.assertEqual(chunks[b"IHDR"][9], 6)
            self.assertEqual(read_size(p), (w, h))
            # decompressed scanlines carry the exact bytes (filter 0 per row)
            raw = zlib.decompress(chunks[b"IDAT"])
            self.assertEqual(len(raw), h * (1 + w * 4))
            self.assertEqual(raw[1:1 + w * 4], rgba[:w * 4])

    def test_rgb_writer_still_emits_color_type_2(self):
        w, h = 2, 2
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "flat.png")
            write_png(p, w, h, b"\x80" * (w * h * 3))
            self.assertEqual(_png_chunks(p)[b"IHDR"][9], 2)

    def test_ffmpeg_decodes_alpha(self):
        w, h = 3, 2
        # pixel 0 fully transparent, pixel 1 fully opaque red
        rgba = b"\x00\x00\x00\x00" + b"\xff\x00\x00\xff" * (w * h - 1)
        ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if not ffmpeg.returncode == 0:
            self.skipTest("ffmpeg unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.png")
            out = os.path.join(tmp, "a.raw")
            write_png_rgba(src, w, h, rgba)
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", src,
                 "-vf", "format=rgba", "-f", "rawvideo", out],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            raw = open(out, "rb").read()
            self.assertEqual(len(raw), w * h * 4)
            self.assertEqual(raw[3], 0)      # alpha 0 survives the decode
            self.assertEqual(raw[4:7], b"\xff\x00\x00")

    def test_length_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                write_png_rgba(os.path.join(tmp, "bad.png"), 2, 2, b"\x00" * 7)


if __name__ == "__main__":
    unittest.main()
