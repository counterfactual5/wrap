"""Compatibility tombstone: production fixture generation has been removed.

No builder was relocated by this module. Callers must remove fixture paths;
test-only asset construction, if needed, belongs to test support code. The
legacy symbol remains importable while stage changes are coordinated, but
it cannot create patterns, files, or manifest entries.
"""


def _write_video_fixture(target_path, *args, **kwargs):
    """Reject the removed production fixture path without writing anything."""
    raise RuntimeError(
        "production fixture generation has been removed; use a verified "
        "frozen asset or explicitly configured generation. No placeholder "
        f"will be written to {target_path!r}.")
