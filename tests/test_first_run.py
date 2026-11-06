"""The first run of a native-backend pipeline.

Before any real asset exists, a newcomer hits two things:

1. the connector CLI is not installed -> the failure must say what to do next,
   not just hand back an errno;
2. a zero-cost `--fixture` rehearsal leaves a placeholder in the ledger -> a
   later real run must not ship that placeholder silently (the ledger is
   authoritative, so reuse has to be visible).

And the zero-cost rehearsal path itself has to be findable in the docs: it is
the only way to try the whole pipeline without paying for a generation.

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

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

_spec = importlib.util.spec_from_file_location(
    "s1_generate", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

from core import manifest  # noqa: E402

README = os.path.join(ROOT, "README.md")
SKILL = os.path.join(ROOT, "skills", "code-driven-shot-pipeline", "SKILL.md")
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


class TestMissingConnectorGuidance(unittest.TestCase):
    """A missing connector CLI must produce a message that says what to do."""

    def test_00_the_image_call_says_what_to_do(self):
        with mock.patch.object(s1.subprocess, "run", side_effect=_missing_cli):
            with self.assertRaises(Exception) as ctx:
                s1.call_generate_image("a prompt", "probe-asset")
        msg = str(ctx.exception).lower()
        self.assertIn("mcode-tools", msg)
        self.assertIn("--fixture", msg)
        self.assertIn("asset transport", msg)

    def test_01_the_video_call_says_the_same(self):
        with mock.patch.object(s1.subprocess, "run", side_effect=_missing_cli):
            with self.assertRaises(Exception) as ctx:
                s1.submit_video_generation("a prompt", model="MiniMax-H3-Max")
        msg = str(ctx.exception).lower()
        self.assertIn("mcode-tools", msg)
        self.assertIn("--fixture", msg)
        self.assertIn("asset transport", msg)


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
                "style": "spec/style.json",
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
    """The zero-cost rehearsal path has to be documented, or nobody finds it."""

    def _text(self, path):
        with open(path) as f:
            return f.read()

    def test_00_both_docs_document_the_zero_cost_rehearsal(self):
        for path in (README, SKILL):
            with self.subTest(doc=os.path.basename(path)):
                self.assertIn("fixture", self._text(path))

    def test_01_the_readme_lists_the_connector_as_a_prerequisite(self):
        readme = self._text(README)
        prereq = readme.split("### 1. Prerequisites", 1)[-1].split("###", 1)[0]
        self.assertIn("mcode-tools", prereq)

    def test_02_the_docs_say_a_fixture_is_a_placeholder(self):
        for path in (README, SKILL):
            with self.subTest(doc=os.path.basename(path)):
                self.assertIn("placeholder", self._text(path).lower())
