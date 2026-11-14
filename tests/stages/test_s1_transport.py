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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "s1_generate", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

# The transport implementation lives in core/generation/; mocks target the
# defining module. `subprocess` (and `time`) are singleton stdlib modules, so
# patching them through any one importing module intercepts every connector /
# ffmpeg call the generation package makes.
from core.generation import connector as gen_connector
from core.generation import images as gen_images
from core.generation import video as gen_video


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
        with mock.patch.object(gen_connector.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            url = s1.fetch_asset_url("123")
        self.assertEqual(url, "https://example.invalid/a.jpg")

    def test_01_accepts_legacy_url_keys(self):
        for key in ("url", "asset_url"):
            with self.subTest(key=key):
                payload = {"node_id": "123", key: "https://example.invalid/legacy.png"}
                with mock.patch.object(gen_connector.subprocess, "run") as run:
                    run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=json.dumps(payload), stderr="")
                    url = s1.fetch_asset_url("123")
                self.assertEqual(url, "https://example.invalid/legacy.png")

    def test_02_raises_readable_error_when_no_url_field(self):
        """A JSON blob with no url field must not be returned as the URL."""
        payload = {"node_id": "123", "message": "ok"}
        with mock.patch.object(gen_connector.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(payload), stderr="")
            with self.assertRaises(RuntimeError) as ctx:
                s1.fetch_asset_url("123")
        self.assertNotIn("{", str(ctx.exception),
                         "the raw JSON was returned as if it were a URL")


class TestFormatNormalization(unittest.TestCase):
    """Generated assets arrive as JPEG; the pipeline requires real PNG."""

    def test_00_detects_non_png(self):
        self.assertFalse(gen_images.is_png(b"\xff\xd8\xff\xe1\x00" + b"\x00" * 32))
        self.assertTrue(gen_images.is_png(_png_bytes()))

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

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("a subject", "asset-x", aspect_ratio="9:16", resolution="2K")

        req = captured["payload"]["requests"][0]
        self.assertEqual(req["aspect_ratio"], "9:16")
        self.assertEqual(req["area"], "2K")
        self.assertNotIn("resolution", req)
        self.assertNotIn("reference_images", req)
        self.assertEqual(req["prompt"], "a subject")

    def test_01_request_without_references_omits_reference_images(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"success_items": [{"node_id": "77"}]}), stderr="")

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("plain subject", "asset-plain")

        req = captured["payload"]["requests"][0]
        self.assertNotIn("reference_images", req)
        self.assertNotIn("input_urls", req)


def _assert_matches_schema(tc, value, schema, path="root"):
    """Validate a JSON value against a subset of JSON Schema (type, required,
    properties, additionalProperties: false, enum, items, oneOf)."""
    if "oneOf" in schema:
        errors = []
        for sub in schema["oneOf"]:
            try:
                _assert_matches_schema(tc, value, sub, path=path)
                return
            except AssertionError as ex:
                errors.append(str(ex))
        tc.fail(f"{path}: value {value!r} matched none of oneOf schemas: {errors}")

    expected_type = schema.get("type")
    if expected_type == "object":
        tc.assertIsInstance(value, dict, f"{path}: expected object, got {type(value).__name__}")
        for req_key in schema.get("required", ()):
            tc.assertIn(req_key, value, f"{path}: missing required key {req_key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value.keys()) - set(props.keys())
            tc.assertEqual(
                unknown, set(),
                f"{path}: unknown key(s) {sorted(unknown)} rejected by additionalProperties:false "
                f"(allowed: {sorted(props.keys())})"
            )
        for k, v in value.items():
            if k in props:
                _assert_matches_schema(tc, v, props[k], path=f"{path}.{k}")
    elif expected_type == "array":
        tc.assertIsInstance(value, list, f"{path}: expected array, got {type(value).__name__}")
        if "minItems" in schema:
            tc.assertGreaterEqual(len(value), schema["minItems"], f"{path}: array too short")
        if "maxItems" in schema:
            tc.assertLessEqual(len(value), schema["maxItems"], f"{path}: array too long")
        if "items" in schema:
            for idx, item in enumerate(value):
                _assert_matches_schema(tc, item, schema["items"], path=f"{path}[{idx}]")
    elif expected_type == "string":
        tc.assertIsInstance(value, str, f"{path}: expected string, got {value!r}")
        if "enum" in schema:
            tc.assertIn(value, schema["enum"], f"{path}: {value!r} not in enum {schema['enum']}")
    elif expected_type == "integer":
        tc.assertTrue(isinstance(value, int) and not isinstance(value, bool),
                      f"{path}: expected integer, got {value!r}")


class TestConnectorSchemaContract(unittest.TestCase):
    """Task D: Contract tests asserting constructed S1 payloads against the
    authoritative connector input_schema (offline snapshot + live CLI when present)."""

    SNAPSHOT_PATH = os.path.join(ROOT, "tests", "fixtures", "connector_schemas.json")

    def _load_snapshot(self):
        with open(self.SNAPSHOT_PATH) as f:
            return json.load(f)

    def _capture_image_payload(self, **kwargs):
        captured = {}

        def fake_run(cmd, **kw):
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"success_items": [{"node_id": "1"}]}), stderr="")

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("test prompt", "asset-a", **kwargs)
        return captured["payload"]

    def _capture_video_payload(self, **kwargs):
        captured = {}

        def fake_call(tool, payload, timeout=None):
            captured["payload"] = payload
            return {"task_id": "t-1", "status": "submitted"}

        with mock.patch.object(gen_video, "_connector_call", side_effect=fake_call):
            s1.submit_video_generation("test video prompt", **kwargs)
        return captured["payload"]

    def test_00_generate_image_payload_matches_offline_schema_snapshot(self):
        schema = self._load_snapshot()["connector__matrix__generate_image"]["input_schema"]
        req_props = schema["properties"]["requests"]["items"]["properties"]

        # 1. Text-to-image payload
        p1 = self._capture_image_payload(aspect_ratio="16:9", resolution="2K")
        _assert_matches_schema(self, p1, schema)
        for k in p1["requests"][0]:
            self.assertIn(k, req_props)

        # 2. Image-to-image payload with reference_images
        p2 = self._capture_image_payload(
            aspect_ratio="9:16", resolution="4K",
            input_urls=["https://example.invalid/ref.png"]
        )
        _assert_matches_schema(self, p2, schema)

        # 3. Regression guard: legacy 'resolution' or 'input_urls' keys must fail the schema check
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, {"requests": [{"prompt": "x", "resolution": "2K"}]}, schema)
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, {"requests": [{"prompt": "x", "input_urls": ["https://a"]}]}, schema)

    def test_01_submit_video_payload_matches_offline_schema_snapshot(self):
        schema = self._load_snapshot()["connector__matrix__submit_video_generation"]["input_schema"]

        # 1. Text-to-video payload
        v1 = self._capture_video_payload(model="MiniMax-H3-Max", duration=6, ratio="9:16", resolution="768P")
        _assert_matches_schema(self, v1, schema)

        # 2. Keyframe first_frame + last_frame payload
        v2 = self._capture_video_payload(
            model="MiniMax-H3", duration=6, resolution="768P",
            input_image={"url": "https://example.invalid/first.png"},
            last_frame_image={"url": "https://example.invalid/last.png"},
            reference_images=[{"url": "https://example.invalid/ref1.png"}],
        )
        _assert_matches_schema(self, v2, schema)
        self.assertEqual(v2["ratio"], "adaptive")
        self.assertEqual(v2["reference_type"], "first_frame")

    def test_02_live_mcode_tools_schema_matches_payload_and_snapshot(self):
        import shutil
        if not shutil.which("mcode-tools"):
            self.skipTest("mcode-tools CLI is not installed in this environment")
        try:
            proc = subprocess.run(
                ["mcode-tools", "connector", "tool", "connector__matrix__generate_image"],
                capture_output=True, text=True, timeout=15
            )
        except Exception as ex:
            self.skipTest(f"mcode-tools connector tool unreachable: {ex}")
        if proc.returncode != 0 or not proc.stdout.strip():
            self.skipTest(f"mcode-tools connector tool unavailable (code {proc.returncode})")
        try:
            tool_info = json.loads(proc.stdout)
        except Exception as ex:
            self.skipTest(f"mcode-tools output is not JSON: {ex}")

        live_schema = tool_info.get("input_schema") or tool_info.get("inputSchema") or tool_info
        req_schema = ((live_schema.get("properties") or {}).get("requests") or {}).get("items") or {}
        live_props = req_schema.get("properties") or {}
        if not live_props:
            self.skipTest("live tool schema did not contain requests.items.properties")

        for payload in (
            self._capture_image_payload(aspect_ratio="16:9", resolution="2K"),
            self._capture_image_payload(aspect_ratio="9:16", resolution="2K", input_urls=["https://example.invalid/a.png"]),
        ):
            req = payload["requests"][0]
            for k in req:
                self.assertIn(k, live_props, f"payload key {k!r} not in live requests[].properties")


if __name__ == "__main__":
    unittest.main()
