"""Names that reach the filesystem, and the colour helper."""
from .constants import NAME_RE


def valid_name(value):
    return isinstance(value, str) and bool(NAME_RE.fullmatch(value))


def hex_rgb(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
