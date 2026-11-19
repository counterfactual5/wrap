"""A truncated download must fail, and a stalled one must not hang the stage.

Measured in the field: `urlretrieve` returned 192017 of 2567341 bytes and the
resulting file was non-empty, so the old emptiness check accepted it — and the
failure surfaced much later, far from the cause. The downloader now streams
with a timeout and compares what arrived against the declared length.
"""
import http.server
import os
import shutil
import tempfile
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.generation.images import download_file


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b""
    declared = None

    def do_GET(self):
        body = _Handler.payload
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        if _Handler.declared is not None:
            self.send_header("Content-Length", str(_Handler.declared))
        else:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _TruncatedDownload(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="dl-")
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/asset.bin"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_truncated_body_raises_instead_of_writing_a_short_file(self):
        # The server promises 4096 bytes but sends 1024 and closes: the
        # response is truncated mid-body — the field failure.
        _Handler.payload = b"x" * 1024
        _Handler.declared = 4096
        target = os.path.join(self.tmpdir, "asset.bin")
        with self.assertRaises(RuntimeError):
            download_file(self.url, target, attempts=1, timeout=10)
        self.assertFalse(os.path.exists(target),
                         "a truncated download must not leave a file in place")

    def test_complete_download_writes_the_file(self):
        _Handler.payload = b"y" * 8192
        _Handler.declared = 8192
        target = os.path.join(self.tmpdir, "asset.bin")
        download_file(self.url, target, attempts=1, timeout=10)
        self.assertEqual(os.path.getsize(target), 8192)


if __name__ == "__main__":
    unittest.main()
