"""The engine's explicit "no BGM" sentinel.

`audio.bgm: "none"` is the engine's own way of saying "this shot has no
background music". `core/audio/shot.py` has honoured that sentinel since the
BGM chain was introduced, but every OTHER consumer of the declared value read
it as a plain truthy string — so a shot declaring `bgm: "none"` rendered a
silent track while the gate still believed it owed a soundtrack, and the
gate failed it for being silent.

Every consumer of a declared `bgm` value must go through this module, so the
sentinel is interpreted in exactly one place.
"""


def is_no_bgm(value):
    """True when a declared `bgm` value means "no background music".

    A missing value, an empty/whitespace-only value, and the literal "none"
    (any case) all mean "no BGM".
    """
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() == "none"


def has_bgm(value):
    """True when a declared `bgm` value names an actual music file."""
    return not is_no_bgm(value)
