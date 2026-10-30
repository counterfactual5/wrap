"""manifest.json: the authority on frozen files. Only already-on-disk, sha256-verified entries."""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "manifest.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load():
    empty = {"assets": {}, "prepared": {}, "video": None}
    if not os.path.exists(PATH):
        return empty
    with open(PATH) as f:
        m = json.load(f)
    # Tolerate manifests written before a section existed (or hand-trimmed).
    for k, v in empty.items():
        m.setdefault(k, v if not isinstance(v, dict) else {})
    return m


def save(m):
    with open(PATH, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)
        f.write("\n")


def register(section, key, relpath, **extra):
    m = load()
    full = os.path.join(ROOT, relpath)
    row = {"path": relpath, "sha256": sha256(full), "bytes": os.path.getsize(full), **extra}
    if section == "video":
        m["video"] = row
    else:
        m[section][key] = row
    save(m)
    return row


def verified(section, key):
    """Row if listed AND file exists AND sha256 matches, else None."""
    m = load()
    row = m["video"] if section == "video" else m[section].get(key)
    if not row:
        return None
    full = os.path.join(ROOT, row["path"])
    if os.path.exists(full) and sha256(full) == row["sha256"]:
        return row
    return None
