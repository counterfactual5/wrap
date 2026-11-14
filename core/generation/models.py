"""Generation capability catalog — environment manifests only, no built-ins.

The pipeline ships NO built-in model catalog and NO fixed model/size
defaults. What a backend can do is declared per environment:

* `POSTER_MODELS_JSON`             video model capability manifest
* `POSTER_VIDEO_MODEL`             default video model (must be declared)
* `POSTER_IMAGE_CAPABILITIES_JSON` image model capability manifest
* `POSTER_IMAGE_MODEL`             default image model (must be declared)
* `POSTER_IMAGE_AREA` (legacy alias `POSTER_IMAGE_RESOLUTION`)
                                   default image area — env-provided, or None

Semantics:

* Manifest unset -> the catalog is EMPTY. Every capability query answers
  "unknown" and nothing fails until a real generation call (or a spec that
  names a model) needs one. Frozen assets, spec validation without models,
  and all other stages are unaffected.
* Manifest set but malformed -> a configuration error that fails LOUDLY at
  import time. There is no built-in catalog to fall back to, so a typo must
  not leave the run half-configured.
* `DEFAULT_*_MODEL` is env-provided or the single declared candidate; with
  zero candidates it is None, and with several candidates there is NO
  default — the caller must pick explicitly.

The spec validator (core/spec/layers.py) and the transport
(stages/01_generate.py -> core/generation/video.py, images.py) read this
catalog, so a model name or a duration bound is defined once.

The `mcode-tools` connector is a TRANSPORT adapter: it moves bytes to and
from a backend. It does not discover models or capabilities — discovery is
not a thing this engine does; the manifest is the single source of truth.
"""
import json
import os


# ---------------------------------------------------------------------------
# Video capability catalog
# ---------------------------------------------------------------------------

# The keys every video capability entry must carry. An entry without them
# cannot be validated against, so a manifest that cannot supply them is
# refused rather than merged half-blind.
REQUIRED_CAP_KEYS = ("min_dur", "max_dur", "resolutions")

# Empty by design: the pipeline ships no built-in models. The catalog is
# populated at import time from POSTER_MODELS_JSON (see _load_env_models).
# Mutated IN PLACE so consumers that aliased the dict at their own import
# (core/generation/video.py) keep seeing the same object.
VIDEO_MODELS = {}


def _parse_manifest(raw, env_name):
    """Parse `raw` (inline JSON or a file path) into {model: capabilities}.

    A malformed manifest is a configuration error, refused loudly: there is
    no built-in catalog to fall back to, so a typo must not leave the run
    half-configured."""
    if not raw:
        return {}
    try:
        if raw.startswith(("{", "[")):
            data = json.loads(raw)
        else:
            with open(raw, encoding="utf-8") as stream:
                data = json.load(stream)
    except Exception as ex:
        raise ValueError(
            f"{env_name} could not be parsed ({ex}); it must be a JSON object "
            f"of {{model: capabilities}} or a path to one — there is no "
            f"built-in catalog to fall back to") from ex
    if not isinstance(data, dict):
        raise ValueError(
            f"{env_name} must be a JSON object of {{model: capabilities}}")
    for m_name, caps in data.items():
        if not isinstance(m_name, str) or not m_name.strip():
            raise ValueError(f"{env_name}: model names must be non-empty strings")
        if not isinstance(caps, dict):
            raise ValueError(
                f"{env_name} entry {m_name!r} must be an object of capabilities")
    return data


def _require_strings(values, label, nonempty=True):
    if (not isinstance(values, (list, tuple)) or (nonempty and not values)
            or any(not isinstance(v, str) or not v.strip() for v in values)):
        raise ValueError(f"{label} must be a {'non-empty ' if nonempty else ''}list of non-empty strings")


def _parse_video_manifest(raw):
    """Validate and normalize one video capability manifest."""
    data = _parse_manifest(raw, "POSTER_MODELS_JSON")
    catalog = {}
    for m_name, caps in data.items():
        entry = dict(caps)
        for key in ("resolutions", "durations", "reference_types", "ratios"):
            if key in entry and entry[key] is not None:
                values = entry[key]
                if not isinstance(values, (list, tuple)):
                    raise ValueError(
                        f"POSTER_MODELS_JSON entry {m_name!r}: {key} must be "
                        f"a list")
                entry[key] = tuple(values)
        missing = [k for k in REQUIRED_CAP_KEYS if not entry.get(k)]
        if missing:
            raise ValueError(
                f"POSTER_MODELS_JSON entry {m_name!r} is missing required "
                f"capabilities {missing} (required: {list(REQUIRED_CAP_KEYS)})")
        lo, hi = entry["min_dur"], entry["max_dur"]
        if type(lo) is not int or type(hi) is not int or lo <= 0 or hi <= 0:
            raise ValueError(
                f"POSTER_MODELS_JSON entry {m_name!r}: min_dur/max_dur must "
                f"be positive integers, got {lo!r}/{hi!r}")
        if lo > hi:
            raise ValueError(
                f"POSTER_MODELS_JSON entry {m_name!r}: min_dur {lo} > max_dur {hi}")
        for key in ("resolutions", "reference_types", "ratios"):
            if key in entry:
                _require_strings(entry[key], f"POSTER_MODELS_JSON {m_name!r}.{key}",
                                 nonempty=key == "resolutions")
        for key in ("audio", "input_image", "last_frame", "reference_media"):
            if key in entry and type(entry[key]) is not bool:
                raise ValueError(f"POSTER_MODELS_JSON {m_name!r}.{key} must be boolean")
        for key in ("resolution_max_dur", "reference_type_max_dur"):
            if key in entry:
                limits = entry[key]
                if not isinstance(limits, dict) or any(
                        not isinstance(k, str) or not k.strip()
                        or type(v) is not int or v <= 0 for k, v in limits.items()):
                    raise ValueError(f"POSTER_MODELS_JSON {m_name!r}.{key} must map names to positive seconds")
        reasons = entry.get("unsupported_reference_types", {})
        if not isinstance(reasons, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in reasons.items()):
            raise ValueError(f"POSTER_MODELS_JSON {m_name!r}.unsupported_reference_types must map names to reasons")
        durations = entry.get("durations")
        if "durations" in entry and not durations:
            raise ValueError(f"POSTER_MODELS_JSON {m_name!r}.durations must be a non-empty list")
        if durations:
            bad = [d for d in durations if type(d) is not int or d <= 0]
            if bad:
                raise ValueError(
                    f"POSTER_MODELS_JSON entry {m_name!r}: durations must be "
                    f"integers, got {bad}")
            if any(d < lo or d > hi for d in durations):
                raise ValueError(
                    f"POSTER_MODELS_JSON {m_name!r}: durations must stay within min_dur/max_dur")
        catalog[m_name] = entry
    return catalog


def _find_project_models():
    """Look for models.json in project root or spec/ if env var unset."""
    try:
        from core.runtime.config import ROOT
        for candidate in ("models.json", os.path.join("spec", "models.json")):
            p = os.path.join(ROOT, candidate)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return None


def _load_env_models():
    """Populate the video catalog from POSTER_MODELS_JSON at import time.

    Returns the catalog. Mutates in place (see the note on VIDEO_MODELS).
    Unset -> empty catalog; malformed -> raises (no built-in fallback)."""
    global VIDEO_MODELS
    raw = os.environ.get("POSTER_MODELS_JSON", "").strip()
    if not raw:
        proj_data = _find_project_models()
        if proj_data:
            v_data = proj_data.get("video_models") or proj_data.get("models")
            if v_data and isinstance(v_data, dict):
                raw = json.dumps(v_data)
    catalog = _parse_video_manifest(raw)
    VIDEO_MODELS.clear()
    VIDEO_MODELS.update(catalog)
    return VIDEO_MODELS


# ---------------------------------------------------------------------------
# Image capability catalog
# ---------------------------------------------------------------------------

# Every image entry declares which aspect ratios and output areas its model
# accepts, so image calls can be checked before a paid generation instead
# of after it.
REQUIRED_IMAGE_CAP_KEYS = ("aspect_ratios", "areas")

# Empty by design (same rules as VIDEO_MODELS); populated at import time
# from POSTER_IMAGE_CAPABILITIES_JSON.
IMAGE_MODELS = {}


def _parse_image_manifest(raw):
    """Validate and normalize one image capability manifest."""
    data = _parse_manifest(raw, "POSTER_IMAGE_CAPABILITIES_JSON")
    catalog = {}
    for m_name, caps in data.items():
        entry = dict(caps)
        for key in REQUIRED_IMAGE_CAP_KEYS:
            values = entry.get(key)
            if not isinstance(values, (list, tuple)) or not values:
                raise ValueError(
                    f"POSTER_IMAGE_CAPABILITIES_JSON entry {m_name!r}: "
                    f"{key} must be a non-empty list (required: "
                    f"{list(REQUIRED_IMAGE_CAP_KEYS)})")
            _require_strings(values, f"POSTER_IMAGE_CAPABILITIES_JSON {m_name!r}.{key}")
            entry[key] = tuple(values)
        catalog[m_name] = entry
    return catalog


def _load_env_image_models():
    """Populate the image catalog from POSTER_IMAGE_CAPABILITIES_JSON.

    Unset -> empty catalog; malformed -> raises (no built-in fallback)."""
    global IMAGE_MODELS
    raw = os.environ.get("POSTER_IMAGE_CAPABILITIES_JSON", "").strip()
    if not raw:
        proj_data = _find_project_models()
        if proj_data:
            i_data = proj_data.get("image_models")
            if i_data and isinstance(i_data, dict):
                raw = json.dumps(i_data)
    catalog = _parse_image_manifest(raw)
    IMAGE_MODELS.clear()
    IMAGE_MODELS.update(catalog)
    return IMAGE_MODELS


_load_env_models()
_load_env_image_models()


# ---------------------------------------------------------------------------
# Defaults: env-provided or the single candidate — never a hardcoded pick
# ---------------------------------------------------------------------------

def _resolve_default_model(env_name, catalog, kind):
    """The default model for one capability catalog.

    * The POSTER_*_MODEL env var names one model: it must be declared in the
      catalog, else the configuration is contradictory and the import fails.
    * Otherwise project models.json default is checked.
    * Otherwise the SOLE catalog entry is the default.
    * Zero or several entries: None — no default, the caller must pick."""
    value = os.environ.get(env_name, "").strip()
    if not value:
        proj_data = _find_project_models()
        if proj_data:
            key = f"default_{kind}_model"
            if proj_data.get(key):
                value = str(proj_data[key]).strip()
    if value:
        if value not in catalog:
            raise ValueError(
                f"{env_name}={value!r} is not in the {kind} capability catalog "
                f"(declared: {sorted(catalog) or '<empty>'}) — declare it in the "
                f"manifest or point {env_name} at a declared model")
        return value
    if len(catalog) == 1:
        return next(iter(catalog))
    return None


def _resolve_default_image_area():
    val = _first_env_value("POSTER_IMAGE_AREA", "POSTER_IMAGE_RESOLUTION")
    if not val:
        proj_data = _find_project_models()
        if proj_data:
            val = proj_data.get("default_image_area") or proj_data.get("default_area")
    return val


def _first_env_value(*names):
    """The first non-empty value among env var names, else None."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


DEFAULT_VIDEO_MODEL = _resolve_default_model("POSTER_VIDEO_MODEL", VIDEO_MODELS, "video")
DEFAULT_IMAGE_MODEL = _resolve_default_model("POSTER_IMAGE_MODEL", IMAGE_MODELS, "image")
# Env-provided or project-provided — there is no hardcoded "2K" to fall back to.
DEFAULT_IMAGE_AREA = _resolve_default_image_area()


# ---------------------------------------------------------------------------
# Capability queries (kept public; empty catalog answers "unknown", never crashes)
# ---------------------------------------------------------------------------

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

    Some backends take an ENUM of durations (e.g. 6 or 10 seconds and
    nothing between), so "6 to 10" is not the truth about what they accept.
    Models whose duration is a continuous range return None here.
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
    """Reference types ('first_frame', 'last_frame', ...) a model accepts."""
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


def image_aspect_ratios(model=None):
    """Aspect ratios a DECLARED image model accepts; () when nothing is declared.

    No hardcoded set: the capability list comes from
    POSTER_IMAGE_CAPABILITIES_JSON. `model=None` reads the env-declared
    default model; nothing declared -> ()."""
    spec = IMAGE_MODELS.get(DEFAULT_IMAGE_MODEL if model is None else model)
    if spec is None:
        return ()
    return tuple(spec.get("aspect_ratios") or ())


def image_resolutions(model=None):
    """Output areas (e.g. 1K/2K/4K) a DECLARED image model accepts; () otherwise.

    Legacy name kept for callers; 'resolutions' for images are the AREA
    values declared under 'areas' in the manifest. `model=None` reads the
    env-declared default model; nothing declared -> ()."""
    spec = IMAGE_MODELS.get(DEFAULT_IMAGE_MODEL if model is None else model)
    if spec is None:
        return ()
    return tuple(spec.get("areas") or ())


def image_model_capabilities(model):
    """The declared capability entry for an image model, or None."""
    return IMAGE_MODELS.get(model)


# ---------------------------------------------------------------------------
# Explicit resolve / require interfaces for stages and validators
# ---------------------------------------------------------------------------

def resolve_video_model(model=None):
    """The video model a call will use — never a silent default.

    * explicit `model`: it must be in the catalog, else RuntimeError
      listing the declared candidates (no fallback to any other model).
    * `model` is None: the env-provided DEFAULT_VIDEO_MODEL (POSTER_VIDEO_MODEL
      or the sole declared candidate). With zero or several candidates there
      is no default and the caller must pick one explicitly."""
    if model is None:
        model = DEFAULT_VIDEO_MODEL
    if model is None:
        candidates = sorted(VIDEO_MODELS)
        if candidates:
            raise RuntimeError(
                f"several video models are declared ({', '.join(candidates)}) "
                f"— no default: name one explicitly (shot layer 'model', style "
                f"'videoModel', or POSTER_VIDEO_MODEL)")
        raise RuntimeError(
            "no video model capability is declared — set POSTER_MODELS_JSON "
            "(and POSTER_VIDEO_MODEL, or a single entry) and name a model")
    if model not in VIDEO_MODELS:
        raise RuntimeError(
            f"unknown video model {model!r}; declared: {sorted(VIDEO_MODELS) or '<none>'} "
            f"(no fallback — declare it in POSTER_MODELS_JSON)")
    return model


def require_video_spec(model):
    """The capability dict for a known video model; RuntimeError otherwise.

    `model` is expected to already be resolved (see resolve_video_model);
    this is the guard for code paths that received a model without
    resolving it."""
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        raise RuntimeError(
            f"unknown video model {model!r}; declared: {sorted(VIDEO_MODELS) or '<none>'}")
    return spec


def require_video_duration(model, duration, resolution=None, reference_type=None):
    """Validate a duration against the model's declared bounds.

    Checks, in the order the backend would: the model's range, its discrete
    duration set (when declared), the resolution cap and the reference-type
    cap. Raises with the exact constraint that failed."""
    spec = require_video_spec(model)
    lo, hi = spec["min_dur"], spec["max_dur"]
    if not (lo <= duration <= hi):
        raise RuntimeError(
            f"{model} duration must be {lo}-{hi}s, got {duration}")
    allowed = video_allowed_durations(model)
    if allowed is not None and duration not in allowed:
        raise RuntimeError(
            f"{model} duration must be one of {list(allowed)}s, got {duration}")
    cap = video_resolution_max_duration(model, resolution)
    if cap is not None and duration > cap:
        raise RuntimeError(
            f"{model} resolution {resolution!r} duration must be <= {cap}s, got {duration}")
    cap = video_reference_type_max_duration(model, reference_type)
    if cap is not None and duration > cap:
        raise RuntimeError(
            f"{model} reference_type {reference_type!r} duration must be "
            f"<= {cap}s, got {duration}")
    return duration


def resolve_video_resolution(model, resolution=None):
    """The resolution a video call will use.

    Explicit `resolution` must be one the model declares; without one, the
    model's SOLE declared resolution is used; several declared resolutions
    and no explicit pick -> RuntimeError (no default size)."""
    allowed = tuple(require_video_spec(model).get("resolutions") or ())
    if resolution is not None:
        if resolution not in allowed:
            raise RuntimeError(
                f"{model} resolution must be one of {list(allowed)}, got {resolution!r}")
        return resolution
    if len(allowed) == 1:
        return allowed[0]
    raise RuntimeError(
        f"explicit resolution required: {model} accepts {list(allowed)} — "
        f"pass one (shot layer 'resolution', style 'videoResolution')")


def resolve_image_model(model=None):
    """The image model a call will use — never a silent default.

    Same rules as resolve_video_model, over the image catalog
    (POSTER_IMAGE_CAPABILITIES_JSON / POSTER_IMAGE_MODEL)."""
    if model is None:
        model = DEFAULT_IMAGE_MODEL
    if model is None:
        candidates = sorted(IMAGE_MODELS)
        if candidates:
            raise RuntimeError(
                f"several image models are declared ({', '.join(candidates)}) "
                f"— no default: name one explicitly (or POSTER_IMAGE_MODEL)")
        raise RuntimeError(
            "no image model capability is declared — set "
            "POSTER_IMAGE_CAPABILITIES_JSON (and POSTER_IMAGE_MODEL, or a "
            "single entry) and name a model")
    if model not in IMAGE_MODELS:
        raise RuntimeError(
            f"unknown image model {model!r}; declared: "
            f"{sorted(IMAGE_MODELS) or '<none>'} (no fallback — declare it in "
            f"POSTER_IMAGE_CAPABILITIES_JSON)")
    return model


def require_image_spec(model):
    """The capability dict for a known image model; RuntimeError otherwise."""
    spec = IMAGE_MODELS.get(model)
    if spec is None:
        raise RuntimeError(
            f"unknown image model {model!r}; declared: {sorted(IMAGE_MODELS) or '<none>'}")
    return spec


def resolve_image_aspect(model, ratio=None):
    """The aspect_ratio an image call will use.

    Explicit `ratio` must be one the model declares (checked only when the
    capability is declared). Without one: the model's SOLE declared aspect
    ratio is used; otherwise explicit input is REQUIRED — there is no
    hardcoded 16:9 or canvas-derived default in the engine."""
    allowed = tuple(require_image_spec(model).get("aspect_ratios") or ())
    if ratio is not None:
        if allowed and ratio not in allowed:
            raise RuntimeError(
                f"{model} aspect_ratio must be one of {list(allowed)}, got {ratio!r}")
        return ratio
    if len(allowed) == 1:
        return allowed[0]
    raise RuntimeError(
        f"explicit aspect_ratio required: {model} declares {list(allowed) or 'no aspect capability'} "
        f"— pass one (or let the stage derive it from the canvas via aspect_for_canvas)")


def resolve_image_area(model, area=None):
    """The output area an image call will use.

    Ladder, in priority order:
    1. explicit `area` (must be one the model declares, when declared);
    2. the env-provided DEFAULT_IMAGE_AREA (POSTER_IMAGE_AREA /
       POSTER_IMAGE_RESOLUTION) — never a hardcoded "2K";
    3. the model's SOLE declared area;
    else RuntimeError — an image call must not guess its size."""
    allowed = tuple(require_image_spec(model).get("areas") or ())
    if area is None:
        area = DEFAULT_IMAGE_AREA
    if allowed:
        if area is not None:
            if area not in allowed:
                raise RuntimeError(
                    f"{model} area must be one of {list(allowed)}, got {area!r}")
            return area
        if len(allowed) == 1:
            return allowed[0]
        raise RuntimeError(
            f"explicit image area required: {model} accepts {list(allowed)} "
            f"(pass one or set POSTER_IMAGE_AREA)")
    if area is not None:
        return area
    raise RuntimeError(
        f"explicit image area required: {model!r} declares no area capability "
        f"and POSTER_IMAGE_AREA is unset")
