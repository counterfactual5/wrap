"""Backend capability catalog — the single source of truth for the native
generation models the pipeline can drive.

Both the spec validator (core/schema.py) and the transport (stages/01_generate.py)
read this table, so a model name or a duration bound is defined once. Two
copies of these rules would drift: the validator would accept a spec the
backend rejects (or vice versa), and the failure would surface only after a
paid call.

Durations are seconds; resolutions are the strings the backend accepts.
`audio` says whether the model renders a synchronized native audio track.
"""

# model -> capability
VIDEO_MODELS = {
    "MiniMax-H3": {
        "min_dur": 4, "max_dur": 15,
        "resolutions": ("768P", "2K"),
        "audio": True,
    },
    "MiniMax-H3-Max": {
        "min_dur": 5, "max_dur": 15,
        "resolutions": ("480P", "768P"),
        "audio": True,
    },
    "MiniMax-Hailuo-2.3": {
        "min_dur": 6, "max_dur": 10,
        "resolutions": ("768P", "1080P"),
        "audio": False,
    },
}

DEFAULT_VIDEO_MODEL = "MiniMax-H3-Max"


def video_duration_range(model):
    """(min, max) seconds a model accepts, or None for an unknown model."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    return spec["min_dur"], spec["max_dur"]


def video_resolutions(model):
    """Resolutions a model accepts, or () for an unknown model."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return ()
    return spec["resolutions"]


def video_has_audio(model):
    """Whether a model renders a synchronized native audio track."""
    spec = VIDEO_MODELS.get(model)
    return bool(spec["audio"]) if spec else False


def image_aspect_ratios():
    """Aspect ratios the image backend accepts."""
    return ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9")


def image_resolutions():
    """Resolutions the image backend accepts."""
    return ("1K", "2K", "4K")
