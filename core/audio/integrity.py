"""Explicitly freeze and verify audio files in the project manifest.

Register trusted existing files with `python -m core.audio.integrity register PATH`.
Paths outside the project are supported, but remain tied to their absolute location.
"""
import argparse
import hashlib
import os

from core.runtime import manifest
from core.runtime.config import ROOT


def _identity(path):
    path = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(ROOT)
    try:
        inside = os.path.commonpath((root, path)) == root
    except ValueError:
        inside = False
    stored = os.path.relpath(path, root) if inside else path
    key = "audio:" + hashlib.sha256(stored.encode("utf-8")).hexdigest()
    return path, stored, key


def register_audio(path):
    """Explicitly trust the current bytes, including for migration or replacement."""
    full, stored, key = _identity(path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"Audio file not found: {full}")
    return manifest.register("assets", key, stored, source="audio")


def verify_audio(path):
    full, stored, key = _identity(path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"Audio file not found: {full}")
    row = manifest.verified("assets", key)
    if row is None or row.get("path") != stored:
        raise RuntimeError(
            f"Audio integrity check failed (unregistered or changed): {full}. "
            "After independently verifying the file, explicitly register its current bytes with "
            f"python -m core.audio.integrity register {full!r}; "
            "For an untrusted TTS cache, remove both files and their corresponding "
            "audio entries from the manifest before regenerating."
        )
    return full


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["register"])
    parser.add_argument("path", help="Trusted existing audio or TTS metadata file")
    args = parser.parse_args()
    row = register_audio(args.path)
    print(f"Registered {row['path']} sha256={row['sha256']}")


if __name__ == "__main__":
    main()
