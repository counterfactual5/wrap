"""S1: Generation stage.
Contract:
- Reads: spec/shot-01.poster.json, spec/style.json, manifest.json
- Writes: assets/<asset>.png, manifest.json
- Exit code: 0 = all assets ready and verified, 1 = generation/download failure.
- Invariant: Generation is not re-entrant (no seed in API). If an asset is already verified in manifest.json,
  it is reused. Pass --force to explicitly re-generate.

Asset transport notes (mcode-tools connector):
- get-asset-url returns {"node_id", "download_url"}; url/asset_url stay as a
  compatibility fallback, but a payload with no URL at all is an error — the
  raw JSON must never be handed to the downloader as if it were a URL.
- The generator may return JPEG/WebP regardless of the requested format, so
  every download is normalized to a real PNG before it is frozen. The
  registration order is fixed: write true format -> verify magic -> freeze.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

import os
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core import manifest
from core.schema import ROOT, load_spec

# Every external call is bounded: a hung backend must fail the stage instead
# of hanging the whole pipeline before its gates ever run.
CALL_TIMEOUT = 180

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# canvas ratio -> generator aspect_ratio. The generator offers a fixed set;
# anything else falls back to the closest match rather than distorting.
ASPECTS = {
    (1, 1): "1:1",
    (16, 9): "16:9",
    (9, 16): "9:16",
    (4, 3): "4:3",
    (3, 4): "3:4",
    (21, 9): "21:9",
}


def aspect_for_canvas(w, h):
    """Derive the generator aspect_ratio from the shot's canvas.

    The old code hardcoded 16:9, so a 1080x1920 vertical shot asked for a
    landscape plate and S2 cropped it back. Pick the closest supported ratio
    by canvas proportion."""
    try:
        w, h = float(w), float(h)
    except (TypeError, ValueError):
        return "1:1"
    if w <= 0 or h <= 0:
        return "1:1"
    ratio = w / h
    best, best_err = "1:1", None
    for (aw, ah), name in ASPECTS.items():
        err = abs(ratio - (aw / ah))
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
    """Style-level prompt fields, plus an optional layer-level addition."""
    fields = style.get("promptFields", {})
    parts = []
    for key in ("subject", "composition", "background", "exclude"):
        if key in fields and fields[key].strip():
            parts.append(fields[key].strip())
    if layer_prompt and layer_prompt.strip():
        parts.append(layer_prompt.strip())
    return ", ".join(parts)


def call_generate_image(prompt, asset_name, aspect_ratio="16:9", resolution="2K"):
    tmp_dir = os.path.join(ROOT, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    gen_file = os.path.join(tmp_dir, "gen.json")
    payload = {
        "requests": [
            {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_file": asset_name
            }
        ]
    }
    with open(gen_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Calling connector__matrix__generate_image with prompt:\n  {prompt}")
    cmd = ["mcode-tools", "connector", "call", "connector__matrix__generate_image", "--args-file", gen_file]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"image generation timed out after {CALL_TIMEOUT}s — the backend did "
            f"not answer in time")
    if proc.returncode != 0:
        raise RuntimeError(f"mcode-tools connector call failed (code {proc.returncode}):\n{proc.stderr}")

    try:
        data = json.loads(proc.stdout)
    except Exception as ex:
        raise RuntimeError(f"Failed to parse connector response as JSON:\n{proc.stdout}") from ex

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
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
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


def main():
    parser = argparse.ArgumentParser(description="S1: Generate assets")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    parser.add_argument("--force", action="store_true", help="Force re-generation even if manifest entry exists")
    parser.add_argument("--fixture", action="store_true", help="Use deterministic code fixture instead of API")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    style_path = os.path.join(ROOT, spec.get("style", "spec/style.json"))
    style = {}
    if os.path.exists(style_path):
        with open(style_path) as f:
            style = json.load(f)

    canvas = spec.get("canvas", {})
    aspect_ratio = aspect_for_canvas(canvas.get("w", 16), canvas.get("h", 9))
    resolution = style.get("resolution", "2K")

    for L in spec["layers"]:
        if L["type"] != "ai":
            continue
        asset = L["asset"]
        rel = f"assets/{asset}.png"
        target_path = os.path.join(ROOT, rel)

        if not args.force and manifest.verified("assets", asset):
            print(f"reuse {asset} (frozen in manifest, sha256 verified)")
            continue

        if args.fixture:
            from core.draw import write_fixture
            write_fixture(target_path)
            row = manifest.register("assets", asset, rel, source="fixture")
            print(f"Registered fixture {rel} sha256={row['sha256'][:12]}")
            continue

        # Real generation via connector
        prompt = build_prompt(style, L.get("prompt"))
        node_id = call_generate_image(prompt, asset, aspect_ratio=aspect_ratio,
                                      resolution=resolution)
        url = fetch_asset_url(node_id)
        # Download to a sidecar first: the manifest may only ever record a
        # file whose bytes really are what its extension claims.
        raw_path = os.path.join(ROOT, ".tmp", f"{asset}.download")
        download_file(url, raw_path)
        ensure_png(raw_path, target_path)

        # Register in manifest — after the true-format file exists.
        row = manifest.register("assets", asset, rel, source="ai-generated",
                                node_id=node_id, prompt=prompt,
                                aspect_ratio=aspect_ratio, resolution=resolution)
        print(f"Registered {rel} sha256={row['sha256'][:12]}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"S1 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
