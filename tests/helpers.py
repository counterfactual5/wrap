"""Shared test helpers: keep the working tree clean while tests run.

Several tests drive the real pipeline stages (S1-S4). Those stages write to
`manifest.json` — the frozen ledger — because re-rendering produces new
build/ artifacts with new checksums. The files those rows point at live under
build/ (gitignored), but the ledger itself is tracked, so a test run would
leave the working tree dirty and a delivery check reading that as "the tree
changed" rather than "the tests passed".

`preserve_manifest` snapshots the ledger and restores it afterwards, so the
suite reports on the code, not on the bookkeeping.
"""
import contextlib
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MANIFEST_PATH = os.path.join(ROOT, "manifest.json")


@contextlib.contextmanager
def preserve_manifest():
    """Restore manifest.json exactly as it was when the block ends."""
    backup = None
    if os.path.exists(MANIFEST_PATH):
        backup = MANIFEST_PATH + ".testbak"
        shutil.copyfile(MANIFEST_PATH, backup)
    try:
        yield
    finally:
        if backup is not None:
            if os.path.exists(MANIFEST_PATH):
                os.remove(MANIFEST_PATH)
            shutil.move(backup, MANIFEST_PATH)
        elif os.path.exists(MANIFEST_PATH):
            os.remove(MANIFEST_PATH)


@contextlib.contextmanager
def preserved_manifest_entry(asset_key, prepared_key=None):
    """Like preserve_manifest, but also drops the named rows afterwards.

    Some stages register rows for assets a test created; removing them keeps
    the ledger free of entries for files that no longer exist.
    """
    with preserve_manifest():
        yield
        try:
            with open(MANIFEST_PATH) as f:
                m = json.load(f)
        except Exception:
            return
        changed = False
        for section, key in (("assets", asset_key),
                             ("prepared", prepared_key or asset_key)):
            rows = m.get(section, {})
            if key in rows:
                rows.pop(key)
                changed = True
        if changed:
            with open(MANIFEST_PATH, "w") as f:
                json.dump(m, f, indent=2, sort_keys=True)
                f.write("\n")
