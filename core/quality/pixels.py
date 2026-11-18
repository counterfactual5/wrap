"""Pixel metrics: ffmpeg -> rawvideo -> stdlib. No numpy, no geq.
All ratios are fractions of total pixels (resolution independent)."""
import statistics
import subprocess

from core.spec.constants import (
    STATIC_ACTIVE_FRACTION,
    DEFAULT_LUMA_DELTA,
    EDGE_KEY_RING,
    EDGE_KEY_TOL,
)


def _frames(src, w, h, pix_fmt, bpp, extra_in=()):
    cmd = ["ffmpeg", "-v", "error", *extra_in, "-i", src, "-f", "rawvideo", "-pix_fmt", pix_fmt, "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * bpp
    try:
        while True:
            b = p.stdout.read(size)
            while b and len(b) < size:
                more = p.stdout.read(size - len(b))
                if not more:
                    break
                b += more
            if len(b) < size:
                break
            yield b
    finally:
        p.stdout.close()
        p.wait()
    if p.returncode not in (0, None):
        raise RuntimeError(f"ffmpeg failed on {src}")


def dedup_cadence_ratios(ratios, dup_tol=5e-5, max_hold=6):
    """Strip short cadence frame holds (e.g. playbackRate < 1 slow motion or
    pulldown repeats) while preserving genuine freezes and static shots.

    Why:
    - When a video layer renders at `playbackRate: 0.5` (or 0.25), each source
      frame is displayed for 2..4 consecutive output frames. Adjacent duplicate
      frames yield `ratio <= 5e-5` (0.0 or 1-2 pixel dither), causing raw
      `median(ratios)` to collapse to ~0.000016 and fail the motion gate even
      though every stepped frame moves by ~0.065 and `freezedetect` (0.5s = 15f)
      passes.
    - A contiguous run of `1..max_hold` (`<= 6` frames = 0.2s at 30fps) near-zero
      pairs bounded by active motion steps is a cadence hold and is stripped so
      the gate measures the actual frame-step motion.
    - A contiguous static run longer than `max_hold` frames (`> 6` frames), or a
      shot where active steps make up `< STATIC_ACTIVE_FRACTION` of frame pairs,
      is a genuine static or frozen clip — its zeros are kept in full so static
      footage still fails.
    """
    if not ratios:
        return ratios
    n = len(ratios)
    active_count = sum(1 for r in ratios if r > dup_tol)
    if active_count == 0 or active_count < max(1, int(n * STATIC_ACTIVE_FRACTION)):
        return ratios

    filtered = []
    i = 0
    while i < n:
        if ratios[i] <= dup_tol:
            j = i
            while j < n and ratios[j] <= dup_tol:
                j += 1
            run_len = j - i
            # Strip short cadence holds (1..max_hold frames); keep long static runs
            if run_len > max_hold:
                filtered.extend(ratios[i:j])
            i = j
        else:
            filtered.append(ratios[i])
            i += 1
    return filtered if filtered else ratios


def changed_pixel_ratios(src, w, h, luma_delta=None, extra_in=(), exclude_band=None, dedup_cadence=True):
    """Per adjacent-frame pair: share of pixels whose luma differs by > luma_delta.
    exclude_band=(y0, y1) drops those canvas rows from both the count and the
    denominator, so a foreground bar panning across the frame cannot mask a
    static subject. Identical rows are skipped with a C-level bytes compare
    first, so static content is nearly free. When dedup_cadence=True (default),
    short cadence repeat holds (<= 6 frames, e.g. slow-motion playbackRate < 1)
    are stripped before returning so the motion gate measures stepped frames."""
    if luma_delta is None:
        luma_delta = DEFAULT_LUMA_DELTA
    out, prev = [], None
    y0, y1 = exclude_band if exclude_band else (h, h)  # empty range when unused
    denom = w * (h - (y1 - y0))
    if denom <= 0:
        return out
    for f in _frames(src, w, h, "gray", 1, extra_in):
        if prev is not None:
            n = 0
            pv = memoryview(prev)
            fv = memoryview(f)
            ld = luma_delta
            for y in range(h):
                if y0 <= y < y1:
                    continue
                base = y * w
                a = pv[base:base + w]
                b = fv[base:base + w]
                if a == b:
                    continue
                na = a.tobytes()
                nb = b.tobytes()
                for p, q in zip(na, nb):
                    if abs(p - q) > ld:
                        n += 1
            out.append(n / denom)
        prev = f
    return dedup_cadence_ratios(out) if dedup_cadence else out


# Per-channel tolerance for the accent-colour mask. One value for every
# channel: the mask must not privilege red, or the same gate measures a
# saturated accent far more loosely than a desaturated one (a neutral grey
# used to accept a 70px band on red and 40px on green/blue, so its shadowed
# pixels fell outside the mask and the measured ratio came out low).
COLOR_MASK_TOL = 40


def _mask_tables(rgb_hex):
    """Per-channel 0/1 translate tables for 'pixel is close to this color'.
    Derived from the spec's layer color, not hardcoded red.

    Each channel gets the SAME tolerance band around its own target value,
    so the mask is invariant under channel permutation: swapping the red and
    green components of the target swaps the accepted set the same way. The
    "dominant channel high, the others low" property the mask is meant to
    keep falls out of the target's own values — the channel whose target is
    high only accepts high values, and the low ones only accept low values —
    rather than from privileging one channel by name."""
    r0, g0, b0 = rgb_hex
    tol = COLOR_MASK_TOL
    t_r = bytes(1 if abs(v - r0) <= tol else 0 for v in range(256))
    t_g = bytes(1 if abs(v - g0) <= tol else 0 for v in range(256))
    t_b = bytes(1 if abs(v - b0) <= tol else 0 for v in range(256))
    return t_r, t_g, t_b


def color_ratio_of_frame(rgb, w, h, tables):
    """Share of pixels matching the derived color mask, via bytes.translate +
    big-int AND + popcount (same trick the old hardcoded red mask used)."""
    t_r, t_g, t_b = tables
    r = rgb[0::3].translate(t_r)
    g = rgb[1::3].translate(t_g)
    b = rgb[2::3].translate(t_b)
    both = int.from_bytes(r, "big") & int.from_bytes(g, "big") & int.from_bytes(b, "big")
    return both.bit_count() / (w * h)


def color_pixel_ratios(src, w, h, tables, extra_in=()):
    return [color_ratio_of_frame(f, w, h, tables) for f in _frames(src, w, h, "rgb24", 3, extra_in)]


# Kept for the existing red gate and tests: the exact old mask (r>120, g<90, b<90).
_T_R = bytes(1 if v > 120 else 0 for v in range(256))
_T_GB = bytes(1 if v < 90 else 0 for v in range(256))


def red_ratio_of_frame(rgb, w, h):
    """r>120 & g<90 & b<90, counted via bytes.translate + big-int AND + popcount."""
    r = rgb[0::3].translate(_T_R)
    g = rgb[1::3].translate(_T_GB)
    b = rgb[2::3].translate(_T_GB)
    both = int.from_bytes(r, "big") & int.from_bytes(g, "big") & int.from_bytes(b, "big")
    return both.bit_count() / (w * h)


def red_pixel_ratios(src, w, h, extra_in=()):
    return [red_ratio_of_frame(f, w, h) for f in _frames(src, w, h, "rgb24", 3, extra_in)]


def edge_key_purity(rgb, w, h, key, ring=None, tol=None):
    """Share of the outer `ring`-px frame whose RGB (Euclidean) distance to `key` <= tol.
    Plain RGB distance, not CIE ΔE: good enough to detect gradients / vignettes / outlines."""
    if ring is None:
        ring = EDGE_KEY_RING
    if tol is None:
        tol = EDGE_KEY_TOL
    kr, kg, kb = key
    t2 = tol * tol
    ok = total = 0

    def scan(x0, x1, y0, y1):
        nonlocal ok, total
        for y in range(y0, y1):
            row = rgb[(y * w + x0) * 3:(y * w + x1) * 3]
            total += x1 - x0
            if row == bytes((kr, kg, kb)) * (x1 - x0):
                ok += x1 - x0
                continue
            for i in range(0, len(row), 3):
                if (row[i] - kr) ** 2 + (row[i + 1] - kg) ** 2 + (row[i + 2] - kb) ** 2 <= t2:
                    ok += 1

    scan(0, w, 0, ring)
    scan(0, w, h - ring, h)
    scan(0, ring, ring, h - ring)
    scan(w - ring, w, ring, h - ring)
    return ok / total


def read_rgb(src, w, h):
    return next(_frames(src, w, h, "rgb24", 3))


def median(xs):
    return statistics.median(xs)