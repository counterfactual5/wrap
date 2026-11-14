"""Regression suite for the poster pipeline.

The suite drives the real pipeline stages, which write tracked files: the
frozen ledger (manifest.json), fixture assets, and style files. Two suites
running side by side — an acceptance check may run one stage's command in
parallel with a peer's — would overwrite each other's files and leave the
working tree dirty.

Importing this package takes a suite-wide lock, so parallel suites queue
instead of colliding. The lock file lives under .tmp/ (gitignored), so it
never shows up in a working-tree snapshot. The lock is released when the
process exits.
"""
import atexit
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from tests.helpers import MANIFEST_PATH, preserve_manifest, suite_lock  # noqa: E402

# Taken at import time: unittest discovers the package before it loads any
# test module, so this covers the whole run.
_lock = suite_lock()
_lock.__enter__()
atexit.register(_lock.__exit__, None, None, None)

# Legacy tests still write ROOT/manifest.json directly. Snapshot only after
# obtaining the suite lock, and restore before releasing it (atexit is LIFO).
_root_manifest = preserve_manifest(MANIFEST_PATH)
_root_manifest.__enter__()
atexit.register(_root_manifest.__exit__, None, None, None)

# Give the suite a private copy, including any uncommitted ledger entries.
# Children inherit the path; individual tests may temporarily override it.
_ledger_dir = tempfile.TemporaryDirectory(prefix="wrap-test-ledger-")
_ledger = os.path.join(_ledger_dir.name, "manifest.json")
_source = os.environ.get("POSTER_MANIFEST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "manifest.json")
if os.path.isfile(_source):
    shutil.copyfile(_source, _ledger)
os.environ["POSTER_MANIFEST"] = _ledger
atexit.register(_ledger_dir.cleanup)
