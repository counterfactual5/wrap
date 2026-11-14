"""The spec package is executable directly and through the pipeline CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TestSpecCLI(unittest.TestCase):
    def test_validation_exit_codes(self):
        engine = Path(__file__).resolve().parents[2]
        fixture = engine / "tests/fixtures/shot-01.poster.json"
        with tempfile.TemporaryDirectory() as tmp:
            invalid = Path(tmp, "invalid.json")
            spec = json.loads(fixture.read_text())
            spec["id"] = "invalid/name"
            invalid.write_text(json.dumps(spec))
            for command in (("-m", "core.spec"), ("pipeline.py", "validate", "--spec")):
                for path, code, message in ((fixture, 0, "spec ok:"),
                                            (invalid, 1, "invalid spec:")):
                    with self.subTest(command=command, path=path):
                        result = subprocess.run(
                            [sys.executable, *command, str(path)], cwd=engine,
                            capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, code, result.stderr)
                        self.assertIn(message, result.stdout)


if __name__ == "__main__":
    unittest.main()
