"""Runtime modules preserve isolated roots, dynamic paths, and mock state."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core.runtime import config, manifest


class TestRuntimeModules(unittest.TestCase):
    def test_import_order_and_config_roots(self):
        engine = str(Path(__file__).resolve().parents[2])
        script = '''
import importlib
import os
import sys

for name in sys.argv[1:]:
    importlib.import_module(name)
from core.runtime import config, manifest
assert config.ENGINE_ROOT == os.getcwd()
assert config.ROOT == (os.environ.get("POSTER_ROOT") or os.getcwd())
assert manifest.ROOT == config.ROOT
assert manifest.LOCK_PATH == os.path.join(config.ROOT, ".tmp", "manifest.lock")
original = config.ROOT
os.environ["POSTER_ROOT"] = original + "-changed"
assert config.ROOT == original
assert importlib.reload(config) is config
assert config.ROOT == original + "-changed"
assert importlib.reload(manifest) is manifest
assert manifest.ROOT == config.ROOT
'''
        with tempfile.TemporaryDirectory() as project:
            for root in (None, "", project):
                for order in (("core.runtime.manifest", "core.runtime.config"),
                              ("core.runtime.config", "core.runtime.manifest")):
                    with self.subTest(root=root, order=order):
                        env = dict(os.environ)
                        env.pop("POSTER_ROOT", None)
                        if root is not None:
                            env["POSTER_ROOT"] = root
                        result = subprocess.run(
                            [sys.executable, "-c", script,
                             *order],
                            cwd=engine, env=env, capture_output=True, text=True,
                            timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_assignments_and_dynamic_path(self):
        original_root = manifest.ROOT
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ):
            os.environ.pop("POSTER_MANIFEST", None)
            try:
                manifest.ROOT = root
                self.assertEqual(manifest.PATH, os.path.join(root, "manifest.json"))
                for name in ("one.json", "two.json"):
                    path = os.path.join(root, name)
                    os.environ["POSTER_MANIFEST"] = path
                    self.assertEqual(manifest.PATH, path)
                    manifest.save({"assets": {name: {}}})
                    self.assertIn(name, manifest.load()["assets"])
                with mock.patch("core.runtime.manifest.PATH", "temporary"):
                    self.assertEqual(manifest.PATH, "temporary")
                self.assertNotIn("PATH", vars(manifest))
                self.assertEqual(manifest.PATH, path)
                with self.assertRaises(AttributeError):
                    getattr(manifest, "missing_attribute")
            finally:
                manifest.ROOT = original_root
        self.assertEqual(manifest.ROOT, original_root)

    def test_patches_affect_function_globals_and_restore(self):
        original_load = manifest.load
        original_write = manifest._write_atomic
        original_hash = manifest.sha256
        original_root = manifest.ROOT
        original_lock = manifest.LOCK_PATH
        for target, caller in (("core.runtime.manifest", manifest),):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as root:
                asset = Path(root, "asset.bin")
                asset.write_bytes(b"asset")
                ledger = {"assets": {}, "prepared": {}, "video": {}}
                lock = os.path.join(root, "locks", "ledger.lock")
                with mock.patch(target + ".ROOT", root), \
                        mock.patch(target + ".LOCK_PATH", lock), \
                        mock.patch(target + ".load", return_value=ledger) as load, \
                        mock.patch(target + ".sha256", return_value="digest") as sha, \
                        mock.patch(target + "._write_atomic") as write:
                    row = caller.register("assets", "asset", "asset.bin", source="test")
                    self.assertTrue(os.path.isfile(lock))
                    self.assertEqual(row, {"path": "asset.bin", "sha256": "digest",
                                           "bytes": 5, "source": "test"})
                    load.assert_called_once_with()
                    sha.assert_called_once_with(str(asset))
                    write.assert_called_once_with(ledger)
                    self.assertIs(caller.verified("assets", "asset"), row)
                    write.reset_mock()
                    caller.save(ledger)
                    write.assert_called_once_with(ledger)
                self.assertIs(manifest.load, original_load)
                self.assertIs(manifest._write_atomic, original_write)
                self.assertIs(manifest.sha256, original_hash)
                self.assertEqual(manifest.ROOT, original_root)
                self.assertEqual(manifest.LOCK_PATH, original_lock)


if __name__ == "__main__":
    unittest.main()
