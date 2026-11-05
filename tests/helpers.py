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
        # The block may have moved or removed the file (a test that exercises
        # manifest.load() on a hand-trimmed ledger does exactly that). Restore
        # defensively: every step is guarded, so a missing intermediate file
        # cannot abort the restore halfway and leave the tree broken.
        if backup is not None:
            try:
                if os.path.exists(MANIFEST_PATH):
                    os.remove(MANIFEST_PATH)
            except OSError:
                pass
            try:
                shutil.move(backup, MANIFEST_PATH)
            except OSError:
                # Last resort: copy the bytes back.
                shutil.copyfile(backup, MANIFEST_PATH)
                os.remove(backup)
        elif os.path.exists(MANIFEST_PATH):
            os.remove(MANIFEST_PATH)


@contextlib.contextmanager
def preserve_assets(*asset_names):
    """Restore tracked asset files that a test may rewrite.

    S1's --fixture path writes the asset file. A fixture written for one
    spec's canvas would otherwise overwrite a frozen asset with different
    bytes — the file is tracked, so the working tree ends up dirty and a
    delivery check reads that as "the tree changed" instead of "the tests
    passed"."""
    backups = {}
    for name in asset_names:
        path = os.path.join(ROOT, "assets", name)
        if os.path.exists(path):
            backup = path + ".testbak"
            shutil.copyfile(path, backup)
            backups[name] = backup
    try:
        yield
    finally:
        for name, backup in backups.items():
            path = os.path.join(ROOT, "assets", name)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
            try:
                shutil.move(backup, path)
            except OSError:
                shutil.copyfile(backup, path)
                os.remove(backup)


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


def ensure_rendered(shot_spec, shot_id, through_gate=False):
    """Render a shot if its mp4 is not on disk; return the mp4 path.

    Tests that consume a rendered shot (concat, S5 inspect) used to rely on
    build/ surviving from an earlier run. After `make clean` that artifact is
    gone, and the test failed for a reason unrelated to what it checks. The
    shot is rendered here so the dependency is explicit and self-contained.

    through_gate=True also runs S4, which writes build/gates/{shot_id}.json —
    S5 reads that file, so a contact-sheet test needs it.
    """
    mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    gates = os.path.join(ROOT, "build", "gates", f"{shot_id}.json")
    if os.path.exists(mp4) and (not through_gate or os.path.exists(gates)):
        return mp4
    import subprocess
    import sys
    stages = ["01_generate.py", "02_prepare.py", "03_compose.py"]
    if through_gate:
        stages.append("04_gate.py")
    for stage in stages:
        res = subprocess.run(
            [sys.executable, os.path.join(ROOT, "stages", stage), "--spec", shot_spec],
            cwd=ROOT, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f"could not prepare {shot_id} ({stage} failed):\n"
                f"{res.stdout}\n{res.stderr}")
    return mp4
