"""The frozen ledger must survive concurrent writers.

The ledger is a read-modify-write: a writer loads the document, changes one
row and saves it back. Two writers doing that at the same time would
silently drop one of the rows — the second save overwrites the first one's
change. The lock in core/manifest.py is what prevents it, and this test is
what keeps the lock from being removed by a later refactor.

The test runs two processes that each register several rows, then checks
that every row survived.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core import manifest

# Each worker registers this many rows under its own prefix.
ROWS_PER_WORKER = 4


def _worker_script():
    return f'''
import sys
sys.path.insert(0, {ROOT!r})
from core import manifest
for i in range({ROWS_PER_WORKER}):
    manifest.register("assets", "conc-test-%s-%d" % (sys.argv[1], i),
                      "assets/city-silhouette.png", source="concurrency-probe")
'''


class TestConcurrentLedgerWrites(unittest.TestCase):
    def test_00_concurrent_registrations_all_survive(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "worker.py")
            with open(script, "w") as f:
                f.write(_worker_script())
            procs = [subprocess.Popen([sys.executable, script, str(w)])
                     for w in range(2)]
            for p in procs:
                p.wait()
                self.assertEqual(p.returncode, 0, "a writer failed")

            m = manifest.load()
            kept = sorted(k for k in m["assets"] if k.startswith("conc-test-"))
            try:
                self.assertEqual(
                    len(kept), ROWS_PER_WORKER * 2,
                    f"concurrent writes lost rows: kept {kept}")
            finally:
                for k in kept:
                    m["assets"].pop(k, None)
                manifest.save(m)

    def test_01_the_ledger_stays_valid_json_while_writing(self):
        """A reader must never see a half-written document."""
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "worker.py")
            with open(script, "w") as f:
                f.write(_worker_script())
            proc = subprocess.Popen([sys.executable, script, "0"])
            reads = 0
            try:
                while proc.poll() is None:
                    with open(manifest.PATH) as f:
                        json.load(f)  # raises on a torn document
                    reads += 1
            finally:
                proc.wait()
                m = manifest.load()
                for k in [k for k in m["assets"] if k.startswith("conc-test-")]:
                    m["assets"].pop(k, None)
                manifest.save(m)
            self.assertGreater(reads, 0, "the writer finished too fast to observe")


if __name__ == "__main__":
    unittest.main()
