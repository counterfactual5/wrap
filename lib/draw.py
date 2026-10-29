"""Code-drawn layers and the fake test fixture (stdlib only)."""
from .png import write_png


def grid(w, h, paper=(244, 244, 244), line=(217, 217, 217), step=80):
    rows = []
    paper_row = bytes(paper) * w
    for y in range(h):
        if y % step == 0:
            rows.append(bytes(line) * w)
        else:
            row = bytearray(paper_row)
            for x in range(0, w, step):
                row[x * 3:x * 3 + 3] = bytes(line)
            rows.append(bytes(row))
    return b"".join(rows)


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
