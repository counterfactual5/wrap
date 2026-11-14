"""Engine and project roots (stdlib only).

`core/runtime/` lives two levels below the repo root: ENGINE_ROOT is the
engine itself. ROOT is the project root (spec/, assets/, build/,
manifest.json) — the engine by default, or POSTER_ROOT when set.

Both are read at import time. Import them from `core.runtime.config`.
Reload this module to pick up changes to POSTER_ROOT.
"""
import os

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
ROOT = os.environ.get("POSTER_ROOT") or ENGINE_ROOT
