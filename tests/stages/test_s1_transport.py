"""S1 asset transport tests: URL parsing, format normalization, spec-driven aspect ratio.

These cover the path that actually calls the generation backend
(mcode-tools connector). The end-to-end suite passed while that path was
broken — nothing here exercised it — so the transport layer gets its own
tests: a green suite must mean the download step works, not merely that the
Python files import.

Test doubles, not network calls: the CLI is invoked through a patched
subprocess.run so no real generation is billed or awaited.

tests/fixtures/connector_schemas.json is the offline snapshot of the
connector input schemas. It is copied from the live CLI, so refresh it with
the commands below whenever the backend changes a schema:

    mcode-tools connector tool connector__matrix__generate_image
    mcode-tools connector tool connector__matrix__submit_video_generation

(The CLI may print node warnings before the JSON — parse from the first '{'.)
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
    """The generation request must follow the shot's canvas against the
    DECLARED aspect capability — there is no hardcoded ratio table."""

    SUPPORTED = ("1:1", "16:9", "9:16", "3:4", "4:3", "21:9")

    def test_00_vertical_canvas_yields_vertical_ratio(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1920, self.SUPPORTED), "9:16")

    def test_01_landscape_canvas_yields_landscape_ratio(self):
        self.assertEqual(s1.aspect_for_canvas(1920, 1080, self.SUPPORTED), "16:9")

    def test_02_square_canvas(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1080, self.SUPPORTED), "1:1")

    def test_03_portrait_four_by_three(self):
        self.assertEqual(s1.aspect_for_canvas(1080, 1440, self.SUPPORTED), "3:4")

    def test_04_no_declared_capability_yields_none(self):
        """Without a declared capability the derivation returns None and the
        caller must pass an explicit ratio — the engine never invents one."""
        self.assertIsNone(s1.aspect_for_canvas(1080, 1920, ()))
        self.assertIsNone(s1.aspect_for_canvas(1080, 1920, ("bogus",)))


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

        from tests.helpers import TEST_IMAGE_MODELS
        from core.generation import models
        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS), \
                mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("a subject", "asset-x", model="Test-Image",
                                   aspect_ratio="9:16", resolution="2K")

        req = captured["payload"]["requests"][0]
        # The backend schema has no `model` field: the model is a local
        # capability key, not something the transport sends.
        self.assertNotIn("model", req)
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

        from tests.helpers import TEST_IMAGE_MODELS
        from core.generation import models
        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS), \
                mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("plain subject", "asset-plain", model="Test-Image",
                                   aspect_ratio="1:1", resolution="1K")

        req = captured["payload"]["requests"][0]
        self.assertNotIn("reference_images", req)
        self.assertNotIn("input_urls", req)


def _schema_error(value, schema, path="root"):
    """Return an error message if `value` violates `schema`, else None.

    Covers the JSON Schema subset the live connector schemas actually use:
    type, required, properties, additionalProperties:false, enum, const,
    items, minItems/maxItems, minLength/maxLength, minimum/maximum, and the
    combinators anyOf / oneOf / allOf / not / if-then-else. Object
    constraints apply to every dict value even when the schema omits
    "type" — the live schema writes its if/then conditions as bare
    {"required": [...]} objects."""
    if not isinstance(schema, dict):
        return None

    if "const" in schema and value != schema["const"]:
        return f"{path}: {value!r} != const {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: {value!r} not in enum {schema['enum']!r}"

    for sub in schema.get("allOf", []):
        err = _schema_error(value, sub, path)
        if err:
            return err

    if "anyOf" in schema:
        errs = []
        for sub in schema["anyOf"]:
            err = _schema_error(value, sub, path)
            if err is None:
                break
            errs.append(err)
        else:
            return f"{path}: value {value!r} matched none of anyOf schemas: {errs}"

    if "oneOf" in schema:
        matched = sum(1 for sub in schema["oneOf"]
                      if _schema_error(value, sub, path) is None)
        if matched != 1:
            return (f"{path}: value {value!r} matched {matched} of oneOf "
                    f"schemas (exactly one required)")

    if "not" in schema and _schema_error(value, schema["not"], path) is None:
        return f"{path}: value {value!r} must not match the forbidden schema"

    if "if" in schema:
        branch = ("then" if _schema_error(value, schema["if"], path) is None
                  else "else")
        if branch in schema:
            err = _schema_error(value, schema[branch], path)
            if err:
                return err

    expected = schema.get("type")
    if expected == "object" and not isinstance(value, dict):
        return f"{path}: expected object, got {type(value).__name__}"
    if expected == "array" and not isinstance(value, list):
        return f"{path}: expected array, got {type(value).__name__}"
    if expected == "string" and not isinstance(value, str):
        return f"{path}: expected string, got {value!r}"
    if expected == "integer" and (not isinstance(value, int)
                                  or isinstance(value, bool)):
        return f"{path}: expected integer, got {value!r}"
    if expected == "number" and (not isinstance(value, (int, float))
                                 or isinstance(value, bool)):
        return f"{path}: expected number, got {value!r}"

    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                return f"{path}: missing required key {key!r}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(props))
            if unknown:
                return (f"{path}: unknown key(s) {unknown} rejected by "
                        f"additionalProperties:false (allowed: {sorted(props)})")
        for key, sub_value in value.items():
            if key in props:
                err = _schema_error(sub_value, props[key], f"{path}.{key}")
                if err:
                    return err
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path}: array too short ({len(value)} < {schema['minItems']})"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: array too long ({len(value)} > {schema['maxItems']})"
        if "items" in schema:
            for idx, item in enumerate(value):
                err = _schema_error(item, schema["items"], f"{path}[{idx}]")
                if err:
                    return err
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"{path}: string shorter than minLength {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path}: string longer than maxLength {schema['maxLength']}"
    elif isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: {value!r} < minimum {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path}: {value!r} > maximum {schema['maximum']}"
    return None


def _assert_matches_schema(tc, value, schema, path="root"):
    """Validate a JSON value against a connector input_schema."""
    err = _schema_error(value, schema, path)
    if err:
        tc.fail(err)


def _strip_annotations(schema):
    """The schema without human-readable annotations (description/default).

    Doc text may change server-side without changing the contract; the
    structural part — fields, types, enums, required — must not drift."""
    if isinstance(schema, dict):
        return {k: _strip_annotations(v) for k, v in schema.items()
                if k not in ("description", "default")}
    if isinstance(schema, list):
        return [_strip_annotations(v) for v in schema]
    return schema


class TestConnectorSchemaContract(unittest.TestCase):
    """Task D: Contract tests asserting constructed S1 payloads against the
    authoritative connector input_schema (offline snapshot + live CLI when present)."""

    SNAPSHOT_PATH = os.path.join(ROOT, "tests", "fixtures", "connector_schemas.json")

    # The live video schema constrains `model` to the backend's real model
    # names, so a payload that must MATCH the schema has to use one of them —
    # the shared synthetic fixture catalog ("Test-Max") cannot satisfy that
    # enum. The capability entry below declares what the test payload needs.
    LIVE_VIDEO_MODEL = "MiniMax-H3"
    LIVE_VIDEO_MODELS = {
        "MiniMax-H3": {"min_dur": 4, "max_dur": 15,
                       "resolutions": ["768P", "2K"],
                       "reference_types": ["first_frame", "last_frame"],
                       "audio": True, "input_image": True, "last_frame": True,
                       "reference_media": True},
    }

    def _load_snapshot(self):
        with open(self.SNAPSHOT_PATH) as f:
            return json.load(f)

    def _live_input_schema(self, tool_name):
        """The live input_schema for one connector tool (skips if unreachable)."""
        import shutil
        if not shutil.which("mcode-tools"):
            self.skipTest("mcode-tools CLI is not installed in this environment")
        try:
            proc = subprocess.run(
                ["mcode-tools", "connector", "tool", tool_name],
                capture_output=True, text=True, timeout=30
            )
        except Exception as ex:
            self.skipTest(f"mcode-tools connector tool unreachable: {ex}")
        if proc.returncode != 0 or not proc.stdout.strip():
            self.skipTest(f"mcode-tools connector tool unavailable (code {proc.returncode})")
        # The CLI may print node warnings before the JSON — parse from the
        # first '{' instead of assuming the whole output is JSON.
        raw = proc.stdout
        start = raw.find("{")
        if start < 0:
            self.skipTest("mcode-tools output contained no JSON object")
        try:
            tool_info = json.loads(raw[start:])
        except Exception as ex:
            self.skipTest(f"mcode-tools output is not JSON: {ex}")
        return tool_info.get("input_schema") or tool_info.get("inputSchema") or tool_info

    def _capture_image_payload(self, **kwargs):
        captured = {}
        from tests.helpers import TEST_IMAGE_MODELS
        from core.generation import models
        kwargs.setdefault("model", "Test-Image")

        def fake_run(cmd, **kw):
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"success_items": [{"node_id": "1"}]}), stderr="")

        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS), \
                mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("test prompt", "asset-a", **kwargs)
        return captured["payload"]

    def _capture_video_payload(self, **kwargs):
        captured = {}
        from tests.helpers import TEST_VIDEO_MODELS
        from core.generation import models
        kwargs.setdefault("model", self.LIVE_VIDEO_MODEL)
        kwargs.setdefault("resolution", "768P")
        catalog = dict(self.LIVE_VIDEO_MODELS)
        catalog.update(TEST_VIDEO_MODELS)

        def fake_call(tool, payload, timeout=None):
            captured["payload"] = payload
            return {"task_id": "t-1", "status": "submitted"}

        with mock.patch.dict(models.VIDEO_MODELS, catalog), \
                mock.patch.object(gen_video, "_connector_call", side_effect=fake_call):
            s1.submit_video_generation("test video prompt", **kwargs)
        return captured["payload"]

    def test_00_generate_image_payload_matches_offline_schema_snapshot(self):
        schema = self._load_snapshot()["connector__matrix__generate_image"]["input_schema"]
        req_props = schema["properties"]["requests"]["items"]["properties"]

        # 1. Text-to-image payload
        p1 = self._capture_image_payload(aspect_ratio="16:9", resolution="2K")
        req = p1["requests"][0]
        # The backend schema has no `model` field: the payload must not carry
        # one (it would only survive while the backend stays lenient).
        self.assertNotIn("model", req)
        for key in ("prompt", "aspect_ratio", "area", "output_file"):
            self.assertIn(key, req)
        self.assertEqual(req["prompt"], "test prompt")
        self.assertEqual(req["aspect_ratio"], "16:9")
        self.assertEqual(req["area"], "2K")
        _assert_matches_schema(self, p1, schema)
        for k in req:
            self.assertIn(k, req_props)

        # 2. Image-to-image payload with reference_images
        p2 = self._capture_image_payload(
            aspect_ratio="9:16", resolution="4K",
            input_urls=["https://example.invalid/ref.png"]
        )
        self.assertNotIn("model", p2["requests"][0])
        _assert_matches_schema(self, p2, schema)

        # 3. Regression guard: legacy 'resolution' or 'input_urls' keys must fail the schema check
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, {"requests": [{"prompt": "x", "resolution": "2K"}]}, schema)
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, {"requests": [{"prompt": "x", "input_urls": ["https://a"]}]}, schema)

    def test_01_submit_video_payload_matches_offline_schema_snapshot(self):
        schema = self._load_snapshot()["connector__matrix__submit_video_generation"]["input_schema"]

        # 1. Text-to-video payload
        v1 = self._capture_video_payload(model=self.LIVE_VIDEO_MODEL, duration=6,
                                         ratio="9:16", resolution="768P")
        self.assertEqual(v1["model"], self.LIVE_VIDEO_MODEL)
        _assert_matches_schema(self, v1, schema)

        # 2. Keyframe first_frame + last_frame payload
        v2 = self._capture_video_payload(
            model=self.LIVE_VIDEO_MODEL, duration=6, resolution="768P",
            input_image={"url": "https://example.invalid/first.png"},
            last_frame_image={"url": "https://example.invalid/last.png"},
            reference_images=[{"url": "https://example.invalid/ref1.png"}],
        )
        self.assertEqual(v2["model"], self.LIVE_VIDEO_MODEL)
        _assert_matches_schema(self, v2, schema)
        self.assertEqual(v2["ratio"], "adaptive")
        self.assertEqual(v2["reference_type"], "first_frame")

        # The live schema pins `model` to the backend's real model names and
        # constrains resolution/duration per model — a payload that ignores
        # those must fail the contract check.
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, dict(v1, model="Test-Max"), schema)
        with self.assertRaises(AssertionError):
            _assert_matches_schema(self, dict(v1, resolution="1080P"), schema)

    def test_02_live_mcode_tools_schema_matches_payload_and_snapshot(self):
        live_schema = self._live_input_schema("connector__matrix__generate_image")
        req_schema = ((live_schema.get("properties") or {}).get("requests") or {}).get("items") or {}
        live_props = req_schema.get("properties") or {}
        if not live_props:
            self.skipTest("live tool schema did not contain requests.items.properties")
        self.assertNotIn("model", live_props,
                         "the live image schema no longer declares a `model` field")

        for payload in (
            self._capture_image_payload(aspect_ratio="16:9", resolution="2K"),
            self._capture_image_payload(aspect_ratio="9:16", resolution="2K", input_urls=["https://example.invalid/a.png"]),
        ):
            req = payload["requests"][0]
            self.assertNotIn("model", req)
            for k in req:
                self.assertIn(k, live_props, f"payload key {k!r} not in live requests[].properties")

    def test_03_image_request_keys_are_declared_and_model_is_not(self):
        """Regression guard: every key the image transport sends must be a
        declared field of the schema, and the removed `model` must stay out
        of both the schema and the payload."""
        schema = self._load_snapshot()["connector__matrix__generate_image"]["input_schema"]
        req_props = schema["properties"]["requests"]["items"]["properties"]
        self.assertNotIn("model", req_props,
                         "the snapshot still advertises `model` — the backend "
                         "schema has no such field")
        for payload in (
            self._capture_image_payload(aspect_ratio="16:9", resolution="2K"),
            self._capture_image_payload(aspect_ratio="9:16", resolution="4K",
                                        input_urls=["https://example.invalid/ref.png"]),
        ):
            req = payload["requests"][0]
            self.assertNotIn("model", req, "the image payload must not send `model`")
            for key in req:
                self.assertIn(key, req_props,
                              f"payload key {key!r} is not declared in the schema")

        # The schema itself rejects the removed field — so a payload that
        # carried `model` would be refused by a strict backend.
        with self.assertRaises(AssertionError):
            _assert_matches_schema(
                self, {"requests": [{"prompt": "x", "model": "Test-Image"}]}, schema)

    def test_04_offline_snapshot_matches_live_schema(self):
        """The offline snapshot must stay same-source with the live schema.

        Doc text may change server-side; the structural contract (fields,
        types, enums, required) must not drift without a snapshot refresh."""
        snapshot = self._load_snapshot()
        for tool_name in ("connector__matrix__generate_image",
                          "connector__matrix__submit_video_generation"):
            with self.subTest(tool=tool_name):
                live = self._live_input_schema(tool_name)
                self.assertEqual(
                    _strip_annotations(live),
                    _strip_annotations(snapshot[tool_name]["input_schema"]),
                    f"{tool_name} snapshot is stale — refresh it with "
                    f"`mcode-tools connector tool {tool_name}`")


if __name__ == "__main__":
    unittest.main()
