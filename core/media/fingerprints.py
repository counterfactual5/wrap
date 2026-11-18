"""Render-artifact helpers shared by S3 (compose) and S4 (gate).

Both stages need to agree on what "the same render" means: the frames
fingerprint pins the exact frame sequence S3 produced, and the encoder
fingerprint pins the ffmpeg/x264 build that encoded it. They live here (not
in the S3 stage script) so S4 can verify without importing a stage module.
"""
import hashlib
import os
import subprocess
from core.runtime.timeouts import PROBE_TIMEOUT


def frames_fingerprint(frames_dir):
    """Aggregate sha256 over the frame sequence: sorted *.png names + contents.
    S4 re-computes this before measuring, so gating a shot against another
    shot's leftover frames (shared build/frames) fails fast instead of
    blessing foreign pixels. Non-PNG entries (.DS_Store, subdirs) are ignored:
    Finder droppings must not invalidate a fresh render."""
    h = hashlib.sha256()
    for name in sorted(n for n in os.listdir(frames_dir) if n.endswith(".png")):
        h.update(name.encode())
        with open(os.path.join(frames_dir, name), "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
    return h.hexdigest()


def encoder_fingerprint():
    """ffmpeg/x264 identity for cross-machine reproducibility checks (S4 compares)."""
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                         timeout=PROBE_TIMEOUT).stdout
    first = out.splitlines()[0] if out else "unknown"
    x264 = next((l.strip() for l in out.splitlines() if "x264" in l), "")
    return hashlib.sha256((first + x264).encode()).hexdigest()[:16]
