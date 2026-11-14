"""Regression tests for the suite's ledger isolation."""
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests import helpers


class TestLedgerIsolation(unittest.TestCase):
    def test_suite_and_child_write_only_to_temporary_ledger(self):
        root_ledger = Path(helpers.MANIFEST_PATH)
        before = root_ledger.read_bytes() if root_ledger.exists() else None
        from core.runtime import manifest

        self.assertNotEqual(os.path.realpath(manifest.PATH), os.path.realpath(root_ledger))
        with helpers.preserve_manifest():
            manifest.save({"assets": {"isolation-parent": {}}, "prepared": {}, "video": {}})
            script = ("from core.runtime import manifest; "
                      "m = manifest.load(); m['assets']['isolation-child'] = {}; manifest.save(m)")
            result = subprocess.run([sys.executable, "-c", script], cwd=helpers.ROOT,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("isolation-child", manifest.load()["assets"])
        after = root_ledger.read_bytes() if root_ledger.exists() else None
        self.assertEqual(before, after)

    def test_fresh_suite_preserves_uncommitted_root_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests = root / "tests"
            tests.mkdir()
            for name in ("__init__.py", "helpers.py"):
                shutil.copyfile(Path(helpers.ROOT, "tests", name), tests / name)
            shutil.copytree(Path(helpers.ROOT, "core"), root / "core")
            original = b'{ "assets": {"uncommitted": {"note": "keep"}}, "prepared": {}, "video": {} }\n'
            (root / "manifest.json").write_bytes(original)
            (tests / "test_probe.py").write_text(
                "import subprocess, sys, unittest\n"
                "from pathlib import Path\n"
                "from core.runtime import manifest\n"
                "class Probe(unittest.TestCase):\n"
                " def test_write(self):\n"
                "  m = manifest.load(); assert 'uncommitted' in m['assets']\n"
                "  m['assets']['test'] = {}; manifest.save(m)\n"
                "  Path('manifest.json').write_bytes(b'legacy hardcoded write')\n"
                "  subprocess.run([sys.executable, '-c', \"from core.runtime import manifest; manifest.save({'assets': {'child': {}}, 'prepared': {}, 'video': {}})\"], check=True)\n")
            env = dict(os.environ)
            env.pop("POSTER_MANIFEST", None)
            env.pop("POSTER_ROOT", None)
            result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_probe"],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(original, (root / "manifest.json").read_bytes())

    def test_preservation_respects_override_and_nested_contexts(self):
        from core.runtime import manifest
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp, "ledger.json")
            original = b'{ "assets": {"user": {}}, "prepared": {}, "video": {} }\n'
            ledger.write_bytes(original)
            with mock.patch.dict(os.environ, {"POSTER_MANIFEST": str(ledger)}):
                with helpers.preserve_manifest():
                    manifest.save({"assets": {"outer": {}}, "prepared": {}, "video": {}})
                    outer = ledger.read_bytes()
                    with helpers.preserve_manifest():
                        manifest.save({"assets": {}, "prepared": {}, "video": {}})
                    self.assertEqual(outer, ledger.read_bytes())
                self.assertEqual(original, ledger.read_bytes())

    def test_exception_and_initially_absent_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "absent.json")
            with self.assertRaisesRegex(RuntimeError, "probe"):
                with helpers.preserve_manifest(path):
                    path.write_bytes(b"temporary")
                    raise RuntimeError("probe")
            self.assertFalse(path.exists())
            path.write_bytes(b"original")
            with self.assertRaisesRegex(RuntimeError, "unchanged"):
                with helpers.preserve_manifest(path):
                    raise RuntimeError("unchanged")
            self.assertEqual(b"original", path.read_bytes())

    def test_entry_helper_never_deletes_existing_user_entries(self):
        root = Path(helpers.MANIFEST_PATH)
        before = root.read_bytes() if root.exists() else None
        with helpers.preserved_manifest_entry("user-entry"):
            pass
        self.assertEqual(before, root.read_bytes() if root.exists() else None)
