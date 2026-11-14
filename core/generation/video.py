"""Video generation (asynchronous native video models).

Video generation is asynchronous: submit returns a task_id, the task is
polled until it succeeds, and the finished clip is downloaded. Render times
vary by model quality tier, so the poll window is generous but bounded.
"""
import json
import math
import time

from core.generation import models
from core.generation.connector import _connector_call
from core.generation.images import download_file, fetch_asset_url

# The capability table lives in core/generation/models.py so the spec validator and this
# transport read the same rules — two copies would drift and the mismatch
# would only surface after a paid call.
VIDEO_MODELS = models.VIDEO_MODELS

VIDEO_POLL_INTERVAL = 15
VIDEO_POLL_TIMEOUT = 2400  # 40 min upper bound for high-resolution video renders


def submit_video_generation(prompt, model=None, duration=6,
                            ratio="9:16", resolution="768P",
                            input_image=None, reference_type=None,
                            last_frame_image=None, reference_images=None,
                            reference_videos=None, reference_audios=None):
    """Submit one asynchronous video task; returns (task_id, model)."""
    model = model or models.DEFAULT_VIDEO_MODEL
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        raise RuntimeError(
            f"unknown video model {model!r}; known: {sorted(VIDEO_MODELS)}")
    if not (spec["min_dur"] <= duration <= spec["max_dur"]):
        raise RuntimeError(
            f"{model} duration must be {spec['min_dur']}-{spec['max_dur']}s, got {duration}")
    allowed_durations = models.video_allowed_durations(model)
    if allowed_durations is not None and duration not in allowed_durations:
        raise RuntimeError(
            f"{model} duration must be one of {list(allowed_durations)}s, got {duration}")
    if resolution not in spec["resolutions"]:
        raise RuntimeError(
            f"{model} resolution must be one of {list(spec['resolutions'])}, got {resolution}")
    max_res_dur = models.video_resolution_max_duration(model, resolution)
    if max_res_dur is not None and duration > max_res_dur:
        raise RuntimeError(
            f"{model} resolution {resolution!r} duration must be <= {max_res_dur}s, got {duration}")
    if input_image is not None and not models.video_supports_input_image(model):
        raise RuntimeError(f"{model} does not support input_image")
    if last_frame_image is not None:
        if not models.video_supports_last_frame(model):
            raise RuntimeError(f"{model} does not support last_frame_image")
        if input_image is None:
            raise RuntimeError("last_frame_image requires input_image")
    if (reference_images or reference_videos or reference_audios) and not models.video_supports_reference_media(model):
        raise RuntimeError(f"{model} does not support reference_images/videos/audios")

    eff_ref_type = reference_type or ("first_frame" if input_image is not None else None)
    if eff_ref_type is not None:
        allowed_rt = models.video_reference_types(model)
        if eff_ref_type not in allowed_rt:
            raise RuntimeError(
                f"{model} reference_type must be one of {list(allowed_rt)}, got {eff_ref_type!r}")
        max_rt_dur = models.video_reference_type_max_duration(model, eff_ref_type)
        if max_rt_dur is not None and duration > max_rt_dur:
            raise RuntimeError(
                f"{model} reference_type {eff_ref_type!r} duration must be <= {max_rt_dur}s, got {duration}")

    # Keyframe and multimodal reference modes require ratio="adaptive"
    eff_ratio = "adaptive" if (input_image is not None or last_frame_image is not None or reference_images) else ratio

    payload = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "ratio": eff_ratio,
        "resolution": resolution,
    }
    if input_image is not None:
        payload["input_image"] = (
            input_image if isinstance(input_image, dict) else {"url": str(input_image)}
        )
    if eff_ref_type is not None:
        payload["reference_type"] = eff_ref_type
    if last_frame_image is not None:
        payload["last_frame_image"] = (
            last_frame_image if isinstance(last_frame_image, dict) else {"url": str(last_frame_image)}
        )
    if reference_images:
        payload["reference_images"] = [
            u if isinstance(u, dict) else {"url": str(u)} for u in reference_images
        ]
    if reference_videos:
        payload["reference_videos"] = [
            u if isinstance(u, dict) else {"url": str(u)} for u in reference_videos
        ]
    if reference_audios:
        payload["reference_audios"] = [
            u if isinstance(u, dict) else {"url": str(u)} for u in reference_audios
        ]

    print(f"Submitting video generation: model={model} duration={duration}s "
          f"ratio={eff_ratio} resolution={resolution}")
    data = _connector_call("connector__matrix__submit_video_generation", payload)
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"video submission returned no task_id:\n{json.dumps(data, indent=2)}")
    print(f"Video task submitted: task_id={task_id}")
    return task_id, model


def query_video_generation(task_id, model=None):
    """Poll one video task; returns the task payload (status + node_id/url)."""
    model = model or models.DEFAULT_VIDEO_MODEL
    data = _connector_call(
        "connector__matrix__query_video_generation",
        {"task_id": task_id, "model": model})
    return data


def wait_for_video(task_id, model=None, timeout=VIDEO_POLL_TIMEOUT,
                   interval=VIDEO_POLL_INTERVAL, max_poll_failures=10):
    """Poll until the task succeeds, fails, or the window runs out.

    The provider is intermittently busy ("connector_busy") while the clip
    renders, and a poll that cannot reach the backend is NOT a failed task —
    the clip is still rendering, and the task is already paid for. Treating
    a transient poll failure as a stage error threw away a render that was
    still in flight. Keep waiting instead; the deadline (and a cap on
    consecutive failures, so a broken auth cannot spin for the full window)
    are the only real bounds."""
    model = model or models.DEFAULT_VIDEO_MODEL
    deadline = time.time() + timeout
    attempt = 0
    consecutive_failures = 0
    while True:
        attempt += 1
        try:
            data = query_video_generation(task_id, model)
            consecutive_failures = 0
        except RuntimeError as ex:
            consecutive_failures += 1
            if consecutive_failures >= max_poll_failures:
                raise RuntimeError(
                    f"video task {task_id} could not be polled {consecutive_failures} "
                    f"times in a row (last error: {ex}); the task may still be "
                    f"rendering — query it by id before resubmitting") from ex
            if time.time() > deadline:
                raise
            print(f"  video task {task_id} poll failed ({ex}); retrying "
                  f"({consecutive_failures}/{max_poll_failures})")
            time.sleep(interval)
            continue
        status = data.get("status")
        if status == "succeeded":
            print(f"Video task {task_id} succeeded after {attempt} poll(s)")
            return data
        if status in ("failed", "cancelled"):
            raise RuntimeError(
                f"video generation {status} for task {task_id}:\n{json.dumps(data, indent=2)}")
        if time.time() > deadline:
            raise RuntimeError(
                f"video generation for task {task_id} did not finish within {timeout}s "
                f"(last status: {status})")
        print(f"  video task {task_id} status={status} — polling again in {interval}s")
        time.sleep(interval)


def download_video(data, target_path):
    """Fetch the finished clip: the query result carries video_url + node_id."""
    url = data.get("video_url")
    if not url and data.get("node_id"):
        url = fetch_asset_url(data["node_id"])
    if not url:
        raise RuntimeError(
            f"finished video task carries no URL (keys: {sorted(data.keys())})")
    download_file(url, target_path)
    return target_path


def _clip_duration(shot_seconds, model=None, resolution=None, reference_type=None):
    """How long to ask the video model for, given the shot's length.

    The model only accepts a bounded duration range (defined in core/generation/models.py),
    and a shot may be shorter than the minimum (a 2s shot cannot be rendered as
    a 2s clip). Round the shot length UP into the model's range: a longer clip
    is trimmed to the shot by the renderer, while a shorter one would leave the
    shot's tail frozen.

    Some models accept only a DISCRETE set of durations (Hailuo: 6 or 10
    seconds, nothing between), and the resolution and the reference mode can
    cap the range further (Hailuo 1080P and its legacy subject mode: 6s).
    The result has to be a duration the backend actually accepts — asking for
    7 seconds is rejected by the API, not rounded for us."""
    model = model or models.DEFAULT_VIDEO_MODEL
    spec = VIDEO_MODELS.get(model, VIDEO_MODELS[models.DEFAULT_VIDEO_MODEL])
    lo, hi = spec["min_dur"], spec["max_dur"]

    # The tightest cap the backend imposes on top of the model's own range.
    upper = hi
    for cap in (models.video_resolution_max_duration(model, resolution),
                models.video_reference_type_max_duration(model, reference_type)):
        if cap is not None:
            upper = min(upper, cap)

    want = lo if shot_seconds <= 0 else int(math.ceil(shot_seconds))

    allowed = models.video_allowed_durations(model)
    if allowed is None:
        return max(lo, min(upper, want))

    # Discrete set: the smallest accepted value that is >= want, else the
    # largest one (a shot longer than the model's longest clip gets the
    # longest clip and loops). A cap below the floor wins over the set.
    candidates = [v for v in sorted(allowed) if v <= upper] or [min(allowed)]
    for value in candidates:
        if value >= want:
            return value
    return candidates[-1]
