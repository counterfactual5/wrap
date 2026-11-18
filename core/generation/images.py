"""Image generation transport: prompt, request, asset URL, download, PNG.

Asset transport notes (mcode-tools connector):
- get-asset-url returns {"node_id", "download_url"}; url/asset_url stay as a
  compatibility fallback, but a payload with no URL at all is an error — the
  raw JSON must never be handed to the downloader as if it were a URL.
- The generator may return JPEG/WebP regardless of the requested format, so
  every download is normalized to a real PNG before it is frozen. The
  registration order is fixed: write true format -> verify magic -> freeze.

Model / aspect / area are NEVER defaulted here: the call carries the
explicit values the stage resolved (core/generation/models.py), or the
env-declared ones. The connector tool is a transport adapter — it does not
discover models or capabilities, and neither does this module.

The image `model` stays LOCAL: it selects the declared aspect_ratio / area
ladders, but the backend's input schema has no `model` field (and requests[]
forbids additional properties), so the model name is never sent.
"""
import json
import os
import subprocess
import time
import urllib.request

from core.runtime.config import ROOT
from core.generation import models
from core.generation.connector import CALL_TIMEOUT, _connector_call, _run_connector

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _aspect_value(name):
    """'16:9' -> 16/9 as a float, or None for a string we cannot parse."""
    parts = str(name).split(":")
    if len(parts) != 2:
        return None
    try:
        w, h = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return w / h


def aspect_for_canvas(w, h, supported=None):
    """Derive the generator aspect_ratio from the shot's canvas.

    The candidate set is the DECLARED capability list (the env manifest via
    models.image_aspect_ratios, or an explicit `supported` argument) — there
    is no hardcoded ratio table in the engine anymore. With no declared
    capability the function returns None: the caller then has to pass an
    explicit aspect_ratio, and only the actual generation call fails.
    """
    if supported is None:
        supported = models.image_aspect_ratios()
    candidates = []
    for name in supported:
        value = _aspect_value(name)
        if value is not None:
            candidates.append((name, value))
    if not candidates:
        return None
    try:
        w, h = float(w), float(h)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    ratio = w / h
    # Pick the closest declared ratio by canvas proportion rather than
    # distorting the plate to a ratio the backend does not offer.
    best, best_err = None, None
    for name, value in candidates:
        err = abs(ratio - value)
        if best_err is None or err < best_err:
            best, best_err = name, err
    return best


def is_png(data):
    """True when the bytes really are a PNG (magic check, not extension)."""
    return data[:8] == PNG_MAGIC


def ensure_png(src, dst):
    """Normalize an image file to a real PNG at `dst`.

    The generator may deliver JPEG/WebP even when a PNG was asked for, and
    core/png.py:read_size hard-verifies the PNG magic — a renamed JPEG would
    pass an extension check and fail the next stage. Convert through ffmpeg
    (already a hard dependency of this pipeline) and verify the result."""
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(src, "rb") as f:
        already_png = is_png(f.read(8))
    if already_png:
        if os.path.abspath(src) != os.path.abspath(dst):
            import shutil
            shutil.copyfile(src, dst)
        return dst
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", "format=rgb24", dst],
        capture_output=True, text=True, timeout=CALL_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"asset conversion to PNG failed (ffmpeg exit {proc.returncode}): "
            f"{proc.stderr.strip()}")
    with open(dst, "rb") as f:
        if not is_png(f.read(8)):
            raise RuntimeError(
                f"converted asset is still not a PNG after conversion: {dst}")
    return dst


def build_prompt(style, layer_prompt=None):
    """The explicit prompt for one asset — no design defaults are injected.

    Style files no longer contribute subject/composition/background/exclude
    text to generation prompts: a layer (or one of its poses) states its
    own `prompt`, and if it does not, the generation call asks for one
    explicitly instead of silently synthesizing a design brief. The `style`
    argument stays only for signature compatibility with callers that
    already pass it."""
    return (layer_prompt or "").strip()


def call_generate_image(prompt, asset_name, aspect_ratio=None, resolution=None,
                        input_urls=None, model=None):
    """Generate one image asset through the connector transport.

    Nothing is defaulted: the model comes from the explicit argument or the
    env-provided default (core/generation/models.py:resolve_image_model),
    the aspect and area from explicit arguments, env capabilities, or the
    model's sole declared value — and an empty prompt is refused before any
    bytes move. The connector tool below is a transport adapter.

    `model` is a LOCAL capability key, not a request field. It is resolved
    against the declared image catalog (resolve_image_model refuses a model
    that is not declared) and it selects the aspect_ratio / area ladders
    (resolve_image_aspect / resolve_image_area), so the `image_models`
    capability declaration still constrains the call. It is deliberately NOT
    sent to the backend: the connector's input schema has no `model` field
    and requests[] rejects additional properties, so a request carrying one
    only survives while the backend stays lenient.
    """
    if not (prompt or "").strip():
        raise RuntimeError(
            f"no prompt for image generation of {asset_name!r} — give the "
            f"layer (or pose) an explicit `prompt`; style design defaults are "
            f"no longer injected")
    model = models.resolve_image_model(model)
    aspect_ratio = models.resolve_image_aspect(model, aspect_ratio)
    resolution = models.resolve_image_area(model, resolution)
    tmp_dir = os.path.join(ROOT, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    gen_file = os.path.join(tmp_dir, "gen.json")
    request = {
        # No `model` field: the backend's requests[] schema has none and
        # forbids additional properties. The model is not dead weight — it
        # was resolved above against the declared capability catalog and it
        # decided the aspect_ratio / area ladders sent here.
        "prompt": prompt.strip(),
        "aspect_ratio": aspect_ratio,
        "area": resolution,
        "output_file": asset_name,
    }
    if input_urls:
        # Image-to-image: the backend takes reference_images as [{"url": ...}].
        request["reference_images"] = [
            u if isinstance(u, dict) else {"url": str(u)}
            for u in input_urls
        ]
    payload = {"requests": [request]}
    with open(gen_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Calling connector__matrix__generate_image with prompt:\n  {prompt}")
    data = _connector_call("connector__matrix__generate_image", payload)

    # Expected: data contains success_items: [{"node_id": "...", "file_name": "..."}]
    success_items = data.get("success_items") or []
    if not success_items:
        raise RuntimeError(f"No success_items in response:\n{json.dumps(data, indent=2)}")

    node_id = success_items[0].get("node_id")
    if not node_id:
        raise RuntimeError(f"Missing node_id in success_items:\n{success_items[0]}")

    print(f"Generation succeeded, node_id={node_id}")
    return node_id


def fetch_asset_url(node_id, attempts=3):
    cmd = ["mcode-tools", "get-asset-url", str(node_id)]
    last = ""
    for i in range(attempts):
        try:
            proc = _run_connector(cmd)
        except subprocess.TimeoutExpired:
            last = f"timed out after {CALL_TIMEOUT}s"
            continue
        if proc.returncode == 0:
            break
        last = proc.stderr.strip()
        # Transient network faults (ECONNRESET / connect timeout) are common
        # against the connector backend; a retry beats failing the whole stage.
        print(f"  asset URL lookup attempt {i + 1}/{attempts} failed: {last}")
        time.sleep(2 * (i + 1))
    else:
        raise RuntimeError(f"mcode-tools get-asset-url failed after {attempts} attempts:\n{last}")

    out = proc.stdout.strip()
    if out.startswith("{"):
        try:
            d = json.loads(out)
        except Exception:
            raise RuntimeError(
                f"asset URL lookup returned unparseable JSON for node_id={node_id}:\n{out}")
        # download_url is what the CLI returns today; url/asset_url stay as a
        # compatibility fallback. Returning the payload itself would hand a
        # JSON blob to the downloader and fail with "unknown url type".
        url = d.get("download_url") or d.get("url") or d.get("asset_url")
        if not url:
            raise RuntimeError(
                f"asset URL lookup for node_id={node_id} returned no download URL "
                f"(keys: {sorted(d.keys())})")
        return url
    if not out:
        raise RuntimeError(f"asset URL lookup for node_id={node_id} returned nothing")
    return out


def download_file(url, target_path, attempts=3):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    print(f"Downloading asset to {target_path} ...")
    last = None
    for i in range(attempts):
        try:
            urllib.request.urlretrieve(url, target_path)
            last = None
            break
        except Exception as ex:
            last = ex
            print(f"  download attempt {i + 1}/{attempts} failed: {ex}")
            time.sleep(2 * (i + 1))
    if last is not None:
        raise RuntimeError(f"asset download failed after {attempts} attempts: {last}")
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        raise RuntimeError(f"asset download produced an empty file: {target_path}")
