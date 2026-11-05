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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from tests.helpers import suite_lock  # noqa: E402

# Taken at import time: unittest discovers the package before it loads any
# test module, so this covers the whole run.
_lock = suite_lock()
_lock.__enter__()
atexit.register(_lock.__exit__, None, None, None)
