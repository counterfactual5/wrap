"""Backend capability catalog — the single source of truth for the native
generation models the pipeline can drive.

Both the spec validator (core/spec/layers.py) and the transport (stages/01_generate.py)
read this catalog, so a model name or a duration bound is defined once.
Capabilities can be extended or overridden at runtime via environment variables
(`POSTER_MODELS_JSON`, `POSTER_VIDEO_MODEL`, `POSTER_IMAGE_AREA`) so the engine
adapts to the active environment without hardcoding model IDs in shot specs or
skills.
"""
import json
import os
import sys

# Built-in baseline catalog (can be extended/overridden via POSTER_MODELS_JSON)
VIDEO_MODELS = {
    "MiniMax-H3": {
        "min_dur": 4, "max_dur": 15,
        "resolutions": ("768P", "2K"),
        "audio": True,
        "input_image": True,
        "last_frame": True,
        "reference_media": True,
        "reference_types": ("first_frame", "last_frame"),
    },
    "MiniMax-H3-Max": {
        "min_dur": 5, "max_dur": 15,
        "resolutions": ("480P", "768P"),
        "audio": True,
        "input_image": True,
        "last_frame": True,
        "reference_media": False,
        "reference_types": ("first_frame", "last_frame"),
    },
    "MiniMax-Hailuo-2.3": {
        "min_dur": 6, "max_dur": 10,
        # Hailuo takes 6 or 10 seconds and NOTHING between -- the API's
        # duration is an enum [6, 10], not a range. A range alone is a lie
        # the validator would pass and the backend would refuse, so the
        # accepted set is modelled explicitly.
        "durations": (6, 10),
        "resolutions": ("768P", "1080P"),
        "audio": False,
        "input_image": True,
        "last_frame": False,
        "reference_media": False,
        # Legacy 'subject' mode is rejected: upstream video service fails with
        # video_generation_failed after billing. Only 'first_frame' works.
        "reference_types": ("first_frame",),
        "unsupported_reference_types": {
            "subject": "legacy 'subject' reference mode fails upstream on MiniMax-Hailuo-2.3 (video_generation_failed); use 'first_frame' instead",
        },
        "resolution_max_dur": {"1080P": 6},
        "reference_type_max_dur": {"subject": 6},
    },
}


# The keys every capability entry must carry. A model without them cannot be
# validated against, and a half-populated one would crash the validator
# instead of being reported — so an override that cannot supply them is
# refused rather than merged.
REQUIRED_CAP_KEYS = ("min_dur", "max_dur", "resolutions")


def _warn(message):
    """A configuration mistake must be visible.

    A silently ignored override is indistinguishable from one that worked:
    the catalog stays on its defaults and the shot fails later, somewhere
    else, for a reason that points nowhere near the env var that caused it.
    """
    print(f"wrap: {message}", file=sys.stderr)


def _load_env_models():
    """Merge runtime model capability overrides from POSTER_MODELS_JSON if set.

    A malformed override must not take the engine down, but it must also not
    disappear quietly: the whole point of the override is to adapt the
    catalog to the environment, so a typo that leaves the defaults in place
    has to say so.
    """
    raw = os.environ.get("POSTER_MODELS_JSON", "").strip()
    if not raw:
        return
    try:
        data = json.loads(raw) if raw.startswith("{") else json.load(open(raw))
    except Exception as ex:
        _warn(f"POSTER_MODELS_JSON could not be parsed ({ex}); "
              f"using the built-in model catalog.")
        return
    if not isinstance(data, dict):
        _warn("POSTER_MODELS_JSON must be a JSON object of {model: capabilities}; "
              "using the built-in model catalog.")
        return
    for m_name, caps in data.items():
        if not isinstance(caps, dict):
            _warn(f"POSTER_MODELS_JSON entry {m_name!r} is not an object; ignored.")
            continue
        norm = dict(caps)
        for key in ("resolutions", "reference_types", "durations"):
            if key not in norm:
                continue
            if not isinstance(norm[key], (list, tuple)):
                _warn(f"POSTER_MODELS_JSON entry {m_name!r}: {key} must be a list; ignored.")
                norm.pop(key)
                continue
            norm[key] = tuple(norm[key])
        merged = {**VIDEO_MODELS.get(m_name, {}), **norm}
        missing = [k for k in REQUIRED_CAP_KEYS if not merged.get(k)]
        if missing:
            _warn(f"POSTER_MODELS_JSON entry {m_name!r} is missing {missing}; ignored.")
            continue
        if merged["min_dur"] > merged["max_dur"]:
            _warn(f"POSTER_MODELS_JSON entry {m_name!r}: min_dur "
                  f"{merged['min_dur']} > max_dur {merged['max_dur']}; ignored.")
            continue
        durations = merged.get("durations")
        if durations:
            # The discrete set is the stricter truth; widen the range so it
            # stays consistent with it rather than dropping either one.
            merged["min_dur"] = min(merged["min_dur"], min(durations))
            merged["max_dur"] = max(merged["max_dur"], max(durations))
        VIDEO_MODELS[m_name] = merged


_load_env_models()

DEFAULT_VIDEO_MODEL = os.environ.get("POSTER_VIDEO_MODEL", "MiniMax-H3-Max")
DEFAULT_IMAGE_AREA = os.environ.get("POSTER_IMAGE_AREA") or os.environ.get("POSTER_IMAGE_RESOLUTION", "2K")


def video_duration_range(model):
    """(min, max) seconds a model accepts, or None for an unknown model.

    None also covers a catalog entry that is missing the bounds — an
    incomplete entry must read as "no constraint known", never as a crash
    in the validator that is supposed to be reporting it.
    """
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    lo, hi = spec.get("min_dur"), spec.get("max_dur")
    if lo is None or hi is None:
        return None
    return lo, hi


def video_allowed_durations(model):
    """The discrete durations a model accepts, or None if any int in range works.

    Hailuo-2.3's API takes an enum [6, 10]: a 7-second request is rejected
    outright, so "6 to 10" is not the truth about what it accepts. Models
    whose duration is a continuous range (H3, H3-Max) return None here.
    """
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    durations = spec.get("durations")
    return tuple(durations) if durations else None


def video_resolutions(model):
    """Resolutions a model accepts, or () for an unknown model."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return ()
    return tuple(spec.get("resolutions") or ())


def video_has_audio(model):
    """Whether a model renders a synchronized native audio track."""
    spec = VIDEO_MODELS.get(model)
    return bool(spec.get("audio")) if spec else False


def video_supports_input_image(model):
    """Whether a model accepts a first-frame / keyframe input_image."""
    spec = VIDEO_MODELS.get(model)
    return bool(spec.get("input_image")) if spec else False


def video_supports_last_frame(model):
    """Whether a model accepts last_frame_image."""
    spec = VIDEO_MODELS.get(model)
    return bool(spec.get("last_frame")) if spec else False


def video_supports_reference_media(model):
    """Whether a model accepts multimodal reference_images/videos/audios."""
    spec = VIDEO_MODELS.get(model)
    return bool(spec.get("reference_media")) if spec else False


def video_reference_types(model):
    """Reference types ('first_frame', 'last_frame') a model accepts."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return ()
    return spec.get("reference_types", ())


def video_unsupported_reference_type_reason(model, reference_type):
    """Explicit failure reason when a reference_type is known-broken upstream on `model`."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    return (spec.get("unsupported_reference_types") or {}).get(reference_type)


def video_resolution_max_duration(model, resolution):
    """Optional tighter max duration (seconds) for a specific resolution, or None."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    return (spec.get("resolution_max_dur") or {}).get(resolution)


def video_reference_type_max_duration(model, reference_type):
    """Optional tighter max duration (seconds) for a specific reference_type, or None."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        return None
    return (spec.get("reference_type_max_dur") or {}).get(reference_type)


def image_aspect_ratios():
    """Aspect ratios the image backend accepts."""
    return ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9")


def image_resolutions():
    """Resolutions the image backend accepts."""
    return ("1K", "2K", "4K")
