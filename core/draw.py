"""Code-drawn layers and the fake test fixture (stdlib only).
Palette comes from tests/fixtures/style.json (S2 passes it in); the fallback defaults are
the same values the style file ships, so colors have exactly one source."""
from .png import write_png

DEFAULT_PALETTE = {"paper": "#F4F4F4", "grid": "#D9D9D9", "accent": "#E03A3A", "ink": "#111111"}


def _rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))


def grid(w, h, palette=None):
    p = {**DEFAULT_PALETTE, **(palette or {})}
    paper, line = _rgb(p["paper"]), _rgb(p["grid"])
    rows = []
    paper_row = bytes(paper) * w
    for y in range(h):
        if y % 80 == 0:
            rows.append(bytes(line) * w)
        else:
            row = bytearray(paper_row)
            for x in range(0, w, 80):
                row[x * 3:x * 3 + 3] = bytes(line)
            rows.append(bytes(row))
    return b"".join(rows)


def dots(w, h, palette=None, step=40, radius=2):
    """Draw a procedural dot matrix background."""
    p = {**DEFAULT_PALETTE, **(palette or {})}
    paper, dot = _rgb(p["paper"]), _rgb(p["grid"])
    px = bytearray(bytes(paper) * (w * h))
    for cy in range(step // 2, h, step):
        for cx in range(step // 2, w, step):
            for dy in range(-radius, radius + 1):
                y = cy + dy
                if 0 <= y < h:
                    for dx in range(-radius, radius + 1):
                        x = cx + dx
                        if 0 <= x < w and (dx * dx + dy * dy <= radius * radius):
                            idx = (y * w + x) * 3
                            px[idx:idx + 3] = bytes(dot)
    return bytes(px)


def fake_city(w, h, ink=(17, 17, 17), key=(255, 255, 255)):
    """White canvas + deterministic black 'buildings' on a baseline. No RNG, no externals."""
    px = bytearray(bytes(key) * (w * h))
    x, i = int(w * 0.04), 0
    while x < w * 0.96:
        bw = 70 + (i * 37) % 90
        bh = int(h * (0.18 + 0.5 * (((i * 53) % 100) / 100)))
        base = int(h * 0.88)
        for y in range(base - bh, base):
            px[(y * w + x) * 3:(y * w + min(x + bw, int(w * 0.96))) * 3] = bytes(ink) * (min(x + bw, int(w * 0.96)) - x)
        x += bw + 12
        i += 1
    return bytes(px)


def write_fixture(path, w=2560, h=1440):
    write_png(path, w, h, fake_city(w, h))
