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

import os
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MANIFEST_PATH = os.path.join(ROOT, "manifest.json")
# Backups live under .tmp/ (gitignored): a backup file next to the real one
# would be an untracked file, and a tool that snapshots the tree mid-test
# would read it as "the tree changed".
BACKUP_DIR = os.path.join(ROOT, ".tmp", "testbakups")
# The suite drives the real pipeline, which writes tracked files (the ledger,
# fixture assets). Two suites running side by side — the acceptance check may
# run a stage's command in parallel with a peer's — would then overwrite each
# other's files. One suite at a time keeps the tree stable.
SUITE_LOCK_PATH = os.path.join(ROOT, ".tmp", "test-suite.lock")


@contextlib.contextmanager
def suite_lock():
    """Serialize whole-suite runs against each other.

    The lock file lives under .tmp/ (gitignored), so it never shows up in a
    working-tree snapshot."""
    os.makedirs(os.path.dirname(SUITE_LOCK_PATH), exist_ok=True)
    fh = open(SUITE_LOCK_PATH, "w")
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        pass
    try:
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        fh.close()


def _backup_path(name):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return os.path.join(BACKUP_DIR, name)


def active_manifest_path():
    """Resolve the active ledger at call time, including temporary overrides."""
    return os.path.abspath(os.environ.get("POSTER_MANIFEST") or MANIFEST_PATH)


@contextlib.contextmanager
def preserve_manifest(path=None):
    """Restore original bytes, defaulting to the active ledger.

    An explicit path is used by the suite guard for legacy hardcoded writers.
    Restoration errors propagate rather than silently losing user state.
    """
    path = os.path.abspath(path) if path is not None else active_manifest_path()
    existed = os.path.exists(path)
    if existed:
        with open(path, "rb") as f:
            original = f.read()
    try:
        yield
    finally:
        if existed:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    unchanged = f.read() == original
            else:
                unchanged = False
            if not unchanged:
                directory = os.path.dirname(os.path.abspath(path))
                fd, temporary = tempfile.mkstemp(prefix=".test-ledger-", dir=directory)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(original)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        elif os.path.exists(path):
            os.remove(path)


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
        path = os.path.join(ROOT, "tests", "fixtures", "assets", name)
        if os.path.exists(path):
            backup = _backup_path(name)
            shutil.copyfile(path, backup)
            backups[name] = backup
    try:
        yield
    finally:
        for name, backup in backups.items():
            path = os.path.join(ROOT, "tests", "fixtures", "assets", name)
            try:
                shutil.copyfile(backup, path)
            except OSError:
                pass
            finally:
                if os.path.exists(backup):
                    os.remove(backup)


@contextlib.contextmanager
def preserved_manifest_entry(asset_key, prepared_key=None):
    """Restore the ledger without deleting pre-existing rows with these keys."""
    with preserve_manifest():
        yield


def ensure_rendered(shot_spec, shot_id, through_gate=False):
    """Render a shot if it is not on disk; return the mp4 path.

    Tests that consume a rendered shot (concat, S5 inspect) used to rely on
    build/ surviving from an earlier run. After `make clean` that artifact is
    gone, and the test failed for a reason unrelated to what it checks. The
    shot is rendered here so the dependency is explicit and self-contained.

    The check covers BOTH the mp4 and the manifest row that binds it: a
    previous test's manifest restore can leave the file on disk with no row
    pointing at it, and then every gate refuses for the wrong reason.

    through_gate=True also runs S4, which writes build/gates/{shot_id}.json —
    S5 reads that file, so a contact-sheet test needs it.
    """
    from core.runtime import manifest
    mp4 = os.path.join(ROOT, "build", f"{shot_id}.mp4")
    gates = os.path.join(ROOT, "build", "gates", f"{shot_id}.json")
    bound = manifest.verified("video", shot_id) is not None
    if (os.path.exists(mp4) and bound
            and (not through_gate or os.path.exists(gates))):
        return mp4
    import subprocess
    import sys
    stages = ["01_generate.py", "02_prepare.py", "03_compose.py"]
    if through_gate:
        stages.append("04_gate.py")
    env = dict(os.environ, POSTER_MANIFEST=active_manifest_path())
    for stage in stages:
        command = [sys.executable, os.path.join(ROOT, "stages", stage), "--spec", shot_spec]
        if stage == "01_generate.py":
            command.append("--fixture")
        res = subprocess.run(
            command, env=env, cwd=ROOT, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f"could not prepare {shot_id} ({stage} failed):\n"
                f"{res.stdout}\n{res.stderr}")
    return mp4
