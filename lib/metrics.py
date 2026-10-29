"""Pixel metrics: ffmpeg -> rawvideo -> stdlib. No numpy, no geq.
All ratios are fractions of total pixels (resolution independent)."""
import statistics
import subprocess


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


def changed_pixel_ratios(src, w, h, luma_delta=6, extra_in=()):
    """Per adjacent-frame pair: share of pixels whose luma differs by > luma_delta.
    Identical rows are skipped with a C-level bytes compare, so static content is nearly free."""
    out, prev = [], None
    for f in _frames(src, w, h, "gray", 1, extra_in):
        if prev is not None:
            n = 0
            for y in range(h):
                a, b = prev[y * w:(y + 1) * w], f[y * w:(y + 1) * w]
                if a != b:
                    n += sum(1 for p, q in zip(a, b) if abs(p - q) > luma_delta)
            out.append(n / (w * h))
        prev = f
    return out


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


def edge_key_purity(rgb, w, h, key, ring=8, tol=12):
    """Share of the outer `ring`-px frame whose RGB (Euclidean) distance to `key` <= tol.
    Plain RGB distance, not CIE ΔE: good enough to detect gradients / vignettes / outlines."""
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
