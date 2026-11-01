"""manifest.json: the authority on frozen files. Only already-on-disk, sha256-verified entries.
Sections `assets` and `prepared` are keyed rows; `video` is keyed by shot id
(m["video"][shot_id]) so concurrent/alternating S3 runs cannot evict another
shot's binding. Legacy single-row manifests (m["video"] = row) are migrated on
load, deriving the shot id from the row's build/{shot_id}.mp4 path."""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PATH = os.path.join(ROOT, "manifest.json")


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
    if not os.path.exists(PATH):
        return empty
    with open(PATH) as f:
        m = json.load(f)
    # Tolerate manifests written before a section existed (or hand-trimmed).
    for k, v in empty.items():
        m.setdefault(k, v if not isinstance(v, dict) else {})
    m["video"] = _migrate_video(m["video"])
    return m


def save(m):
    with open(PATH, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)
        f.write("\n")


def register(section, key, relpath, **extra):
    if key is None:
        raise ValueError(f"register({section!r}): key is required (shot id / asset id)")
    m = load()
    full = os.path.join(ROOT, relpath)
    row = {"path": relpath, "sha256": sha256(full), "bytes": os.path.getsize(full), **extra}
    m[section][key] = row
    save(m)
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
