"""manifest.json: the authority on frozen files. Only already-on-disk, sha256-verified entries.
Sections `assets` and `prepared` are keyed rows; `video` is keyed by shot id
(m["video"][shot_id]) so concurrent/alternating S3 runs cannot evict another
shot's binding. Legacy single-row manifests (m["video"] = row) are migrated on
load, deriving the shot id from the row's build/{shot_id}.mp4 path."""
import hashlib
import json
import os

from core.runtime.config import ENGINE_ROOT, ROOT
# POSTER_MANIFEST lets a caller point the ledger elsewhere. A test that runs
# the real stages would otherwise write the project's frozen ledger while it
# runs — and a working-tree snapshot taken during that window reads the write
# as "the tree changed".
LOCK_PATH = os.path.join(ROOT, ".tmp", "manifest.lock")


def _ledger_path():
    """Where the ledger lives, resolved on every call.

    POSTER_MANIFEST is read at call time, not at import time: a caller that
    sets the variable after importing this module would otherwise silently
    write to the project's real ledger."""
    return os.environ.get("POSTER_MANIFEST") or os.path.join(ROOT, "manifest.json")


def __getattr__(name):
    # PEP 562: PATH stays a module attribute (tests and callers use
    # manifest.PATH) but is resolved on each access.
    if name == "PATH":
        return _ledger_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _ledger_lock:
    """Advisory lock around the ledger's read-modify-write.

    Two writers racing (two stages running side by side, the test suite beside
    a render) would otherwise drop one of the rows: both read the same
    snapshot and the second save overwrites the first. fcntl.flock is
    advisory but sufficient here — every writer goes through this class.
    """

    def __enter__(self):
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        self._fh = open(LOCK_PATH, "w")
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            # Without flock the atomic write still prevents a torn document.
            pass
        return self

    def __exit__(self, *exc):
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        self._fh.close()
        return False


def _write_atomic(m):
    """Write the ledger via a temp file + rename: readers see old or new, never a partial document."""
    # POSTER_MANIFEST may point anywhere; make sure its directory exists so a
    # fresh ledger path does not fail on the first write.
    path = _ledger_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _migrate_video(v):
    """Legacy manifests stored the last render as a single row. Re-key it."""
    if isinstance(v, dict) and "path" in v:
        sid = os.path.basename(v.get("path", "")).replace(".mp4", "")
        return {sid: v} if sid else {}
    if isinstance(v, dict):
        return v
    return {}


def load():
    empty = {"assets": {}, "prepared": {}, "video": {}}
    path = _ledger_path()
    if not os.path.exists(path):
        return empty
    with open(path) as f:
        m = json.load(f)
    # Tolerate manifests written before a section existed (or hand-trimmed).
    for k, v in empty.items():
        m.setdefault(k, v if not isinstance(v, dict) else {})
    m["video"] = _migrate_video(m["video"])
    return m


def save(m):
    _write_atomic(m)


def register(section, key, relpath, **extra):
    if key is None:
        raise ValueError(f"register({section!r}): key is required (shot id / asset id)")
    # The ledger is a read-modify-write, so two writers racing (two stages
    # running side by side, a test suite beside a render) would silently drop
    # one of the rows. The lock makes the update atomic; the file is written
    # to a temp name and moved into place, so a reader never sees a partial
    # document.
    with _ledger_lock():
        m = load()
        full = os.path.join(ROOT, relpath)
        row = {"path": relpath, "sha256": sha256(full),
               "bytes": os.path.getsize(full), **extra}
        m[section][key] = row
        _write_atomic(m)
        return row


def verified(section, key):
    """Row if listed AND file exists AND sha256 matches, else None."""
    m = load()
    row = m[section].get(key)
    if not row:
        return None
    full = os.path.join(ROOT, row["path"])
    if os.path.exists(full) and sha256(full) == row["sha256"]:
        return row
    return None
