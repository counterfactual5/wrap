"""The first run of a pipeline with undeclared generation capability.

With the zero-template contract the failure modes a newcomer hits are:

1. the connector CLI is not installed -> the failure must say what to do
   next, not just hand back an errno;
2. a model call with no declared capability must say exactly what to declare
   (the env vars) — there is no built-in catalog to fall back to;
3. a blank prompt is refused, not filled in from design defaults;
4. a ledger row left over from a legacy `--fixture` rehearsal (the flag is
   gone; test-side placeholders register themselves in tests/) must still be
   visible in a later run — reuse of a `source: fixture` row is called out.

And the docs must document the zero-template contract itself: no placeholder
assets in the production path, capability env vars named.

Test doubles, not network calls: the CLI is invoked through a patched
subprocess.run, and the S1 subprocess runs without the connector on PATH, so
no real generation is billed or awaited.
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

_spec = importlib.util.spec_from_file_location(
    "s1_generate", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

from core.runtime import manifest  # noqa: E402
from core.generation import connector as gen_connector  # noqa: E402 (mock target)

README = os.path.join(ROOT, "README.md")
SKILL = os.path.join(ROOT, "skills", "wrap", "SKILL.md")
PROBE_DIR = os.path.join(ROOT, ".tmp", "first-run-probe")


def _png_bytes(w=4, h=4):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes((10, 20, 30)) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _missing_cli(*args, **kwargs):
    raise FileNotFoundError(2, "No such file or directory", "mcode-tools")


class TestUndeclaredModelGuidance(unittest.TestCase):
    """An undeclared model must produce a message that says what to do: the
    capability catalogs are environment configuration, and every refusal
    names the env var — there is no built-in catalog to fall back to."""

    def test_00_the_image_call_says_what_to_do(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.call_generate_image("a prompt", "probe-asset")
        msg = str(ctx.exception)
        self.assertIn("no image model capability is declared", msg)
        self.assertIn("POSTER_IMAGE_CAPABILITIES_JSON", msg)
        self.assertIn("name a model", msg)

    def test_01_the_video_call_says_the_same(self):
        with self.assertRaises(RuntimeError) as ctx:
            s1.submit_video_generation("a prompt")
        msg = str(ctx.exception)
        self.assertIn("no video model capability is declared", msg)
        self.assertIn("POSTER_MODELS_JSON", msg)
        self.assertIn("name a model", msg)

    def test_02_the_blank_prompt_is_refused_before_anything_moves(self):
        """Design defaults are no longer injected: a layer without an
        explicit prompt is a loud refusal, not a synthesized brief."""
        from tests.helpers import TEST_IMAGE_MODELS
        from core.generation import models
        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS):
            with self.assertRaises(RuntimeError) as ctx:
                s1.call_generate_image("", "probe-asset", model="Test-Image",
                                       aspect_ratio="1:1", resolution="1K")
        self.assertIn("no prompt", str(ctx.exception))
        self.assertIn("explicit", str(ctx.exception))


class TestPlaceholderVisibility(unittest.TestCase):
    """A placeholder registered by a --fixture rehearsal must not be shipped
    silently by a later real run."""

    def setUp(self):
        os.makedirs(PROBE_DIR, exist_ok=True)
        self._ledger = os.environ.get("POSTER_MANIFEST")
        self._ledger_path = os.path.join(PROBE_DIR, "ledger.json")
        os.environ["POSTER_MANIFEST"] = self._ledger_path

    def tearDown(self):
        if self._ledger is None:
            os.environ.pop("POSTER_MANIFEST", None)
        else:
            os.environ["POSTER_MANIFEST"] = self._ledger

    def test_00_reusing_a_fixture_row_is_called_out(self):
        rel = os.path.join(".tmp", "first-run-probe", "placeholder.png")
        with open(os.path.join(ROOT, rel), "wb") as f:
            f.write(_png_bytes())
        manifest.register("assets", "probe-placeholder", rel, source="fixture")

        spec_path = os.path.join(PROBE_DIR, "probe.poster.json")
        with open(spec_path, "w") as f:
            json.dump({
                "id": "first-run-probe",
                "canvas": {"w": 1080, "h": 1920},
                "fps": 30,
                "durationInFrames": 60,
                "style": "tests/fixtures/style.json",
                "layers": [{"id": "l", "type": "ai", "asset": "probe-placeholder",
                            "rect": [0, 0, 1080, 1920], "z": 0,
                            "blend": "normal", "keyColor": "#070512"}],
                "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                           "lo": 0.0001, "hi": 0.15}],
            }, f)

        env = dict(os.environ)
        # No connector on PATH: a run that tried to generate for real would
        # fail fast instead of billing a generation.
        env["PATH"] = "/usr/bin:/bin"
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "stages", "01_generate.py"),
             "--spec", spec_path],
            capture_output=True, text=True, env=env, cwd=ROOT)
        out = proc.stdout.lower()
        self.assertIn("placeholder", out,
                      f"the reuse was not called out: {proc.stdout!r} {proc.stderr!r}")
        self.assertIn("--force", out,
                      f"the reuse did not point at --force: {proc.stdout!r}")


class TestDocsContract(unittest.TestCase):
    """The zero-template contract has to be documented, or the removed
    vocabulary gets re-added by well-meaning future work."""

    def _text(self, path):
        with open(path) as f:
            return f.read()

    def test_00_both_docs_name_the_capability_env_vars(self):
        for var in ("POSTER_MODELS_JSON", "POSTER_IMAGE_CAPABILITIES_JSON"):
            for path in (README, SKILL):
                with self.subTest(doc=os.path.basename(path), var=var):
                    self.assertIn(var, self._text(path))

    def test_01_both_docs_name_the_connector_as_transport_only(self):
        for path in (README, SKILL):
            with self.subTest(doc=os.path.basename(path)):
                text = self._text(path).lower()
                self.assertIn("mcode-tools", text)

    def test_03_docs_keep_the_connector_out_of_the_no_generation_path(self):
        """Running without the connector (frozen assets only) must be
        documented as possible, so the absence of a backend is not mistaken
        for the absence of the pipeline."""
        for path in (README, SKILL):
            with self.subTest(doc=os.path.basename(path)):
                text = self._text(path).lower()
                self.assertIn("frozen", text)
