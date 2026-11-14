"""S1: Generation stage.
Contract:
- Reads: tests/fixtures/shot-01.poster.json, tests/fixtures/style.json, manifest.json
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

This script owns the spec-driven orchestration and main() only; the
transport implementation lives in core/generation/ (connector, images,
uploads, video, fixtures).
"""
import argparse
import json
import os
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core.runtime import manifest
from core.generation import models
from core.runtime.config import ROOT
from core.spec.loader import load_spec
from core.generation.fixtures import _write_video_fixture
from core.generation.images import (
    aspect_for_canvas,
    build_prompt,
    call_generate_image,
    download_file,
    ensure_png,
    fetch_asset_url,
)
from core.generation.uploads import resolve_reference_image_path, upload_temp_url
from core.generation.video import (
    VIDEO_MODELS,
    _clip_duration,
    download_video,
    submit_video_generation,
    wait_for_video,
)


def main():
    parser = argparse.ArgumentParser(description="S1: Generate assets")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: tests/fixtures/shot-01.poster.json)")
    parser.add_argument("--force", action="store_true", help="Force re-generation even if manifest entry exists")
    parser.add_argument("--fixture", action="store_true", help="Use deterministic code fixture instead of API")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    style_path = os.path.join(ROOT, spec.get("style", "tests/fixtures/style.json"))
    style = {}
    if os.path.exists(style_path):
        with open(style_path) as f:
            style = json.load(f)

    canvas = spec.get("canvas", {})
    aspect_ratio = aspect_for_canvas(canvas.get("w", 16), canvas.get("h", 9))
    resolution = style.get("area") or style.get("resolution") or models.DEFAULT_IMAGE_AREA
    shot_seconds = spec.get("durationInFrames", 0) / max(1, spec.get("fps", 30))

    # Collect and topologically sort asset generation tasks
    # (independent plates/torsos generate first; dependent kit limbs/weapons and video layers generate after)
    tasks = []
    seen = set()
    for L in spec["layers"]:
        ltype = L.get("type")
        if ltype not in ("ai", "video"):
            continue
        is_video = ltype == "video"

        extra_meta = {}
        if L.get("joint") is not None:
            extra_meta["joint"] = L["joint"]
        if L.get("socket") is not None:
            extra_meta["socket"] = L["socket"]
        if L.get("partScale") is not None:
            extra_meta["part_scale"] = L["partScale"]
        if L.get("kit") is not None:
            extra_meta["kit"] = L["kit"]
            if L["kit"].get("parent_asset") and not L.get("input_asset"):
                L["input_asset"] = L["kit"]["parent_asset"]

        first_ref = L.get("first_frame") or L.get("input_asset") or L.get("input_image")
        last_ref = L.get("last_frame") or L.get("last_frame_image") or L.get("last_frame_asset")
        ref_imgs = list(L.get("reference_images") or L.get("reference_assets") or [])
        deps = [d for d in ([first_ref, last_ref] + ref_imgs) if d]

        if L["asset"] not in seen:
            seen.add(L["asset"])
            tasks.append({
                "asset": L["asset"],
                "layer_prompt": L.get("prompt"),
                "is_video": is_video,
                "layer": L,
                "input_asset": first_ref,
                "deps": deps,
                "extra_meta": extra_meta,
            })

        if ltype == "ai":
            for p in L.get("poses") or []:
                pa = p.get("asset")
                if pa and pa not in seen:
                    seen.add(pa)
                    p_dep = p.get("input_asset") or L.get("input_asset")
                    tasks.append({
                        "asset": pa,
                        "layer_prompt": p.get("prompt") or L.get("prompt"),
                        "is_video": False,
                        "layer": L,
                        "input_asset": p_dep,
                        "deps": [p_dep] if p_dep else [],
                        "extra_meta": extra_meta,
                    })

    # Sort tasks so dependencies (input_asset / first_frame / last_frame / reference_images)
    # are generated before dependent assets (supporting both asset names and ai layer IDs)
    ai_layer_id_to_asset = {
        L.get("id"): L.get("asset")
        for L in spec.get("layers", [])
        if isinstance(L, dict) and L.get("type") == "ai" and L.get("id") and L.get("asset")
    }
    sorted_tasks = []
    visited = set()
    visiting = set()

    def visit(t):
        if t["asset"] in visited:
            return
        if t["asset"] in visiting:
            sorted_tasks.append(t)
            visited.add(t["asset"])
            return
        visiting.add(t["asset"])
        for dep in (t.get("deps") or ([t["input_asset"]] if t.get("input_asset") else [])):
            norm_dep = ai_layer_id_to_asset.get(dep, dep)
            dep_t = next((x for x in tasks if x["asset"] == norm_dep), None)
            if dep_t:
                visit(dep_t)
        visiting.remove(t["asset"])
        visited.add(t["asset"])
        sorted_tasks.append(t)

    for t in tasks:
        visit(t)

    for task in sorted_tasks:
        asset = task["asset"]
        layer_prompt = task["layer_prompt"]
        is_video = task["is_video"]
        L = task["layer"]
        extra_meta = task["extra_meta"]
        if is_video:
            rel = f"assets/{asset}.mp4"
        else:
            rel = f"assets/{asset}.png"
        target_path = os.path.join(ROOT, rel)
        # A fresh project directory has no assets/ yet. The engine repo always
        # had one, so the gap only surfaced when POSTER_ROOT pointed at a new
        # project: the download lands in .tmp/ (created for it) and the FREEZE
        # step writes into assets/ — which nobody had made.
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        row = manifest.verified("assets", asset)
        if not args.force and row:
            if row.get("source") == "fixture":
                print(f"reuse {asset} — PLACEHOLDER (a --fixture asset — from a "
                      f"rehearsal or a shipped placeholder — not a generated "
                      f"one; this run ships the placeholder)")
                print(f"  pass --force to S1 to generate {asset} for real")
            else:
                print(f"reuse {asset} (frozen in manifest, sha256 verified)")
            continue

        if args.fixture:
            if is_video:
                _write_video_fixture(target_path)
            else:
                from core.media.draw import write_fixture
                write_fixture(target_path)
            # Record the SOURCE pixel size: the rig calibration (core/rig.py)
            # needs it to convert a source-space joint into canvas pixels, and
            # a manifest row that does not carry it forces that code to guess.
            from core.media.png import read_size
            try:
                sw, sh = read_size(target_path)
            except (OSError, ValueError):
                sw = sh = None
            row = manifest.register("assets", asset, rel, source="fixture",
                                    size=[sw, sh] if sw else None, **extra_meta)
            print(f"Registered fixture {rel} sha256={row['sha256'][:12]}")
            continue

        if is_video:
            prompt = build_prompt(style, layer_prompt)
            model = L.get("model") or style.get("videoModel") or models.DEFAULT_VIDEO_MODEL
            video_res = L.get("resolution") or style.get("videoResolution", "768P")

            first_ref = L.get("first_frame") or L.get("input_asset") or L.get("input_image")
            last_ref = L.get("last_frame") or L.get("last_frame_image") or L.get("last_frame_asset")
            ref_imgs = list(L.get("reference_images") or L.get("reference_assets") or [])

            input_img_payload = None
            last_img_payload = None
            ref_imgs_payload = None

            if first_ref:
                src_path, src_rel = resolve_reference_image_path(first_ref, spec, style=style)
                print(f"  video first_frame from {src_rel} — uploading")
                input_img_payload = {"url": upload_temp_url(src_path)}
                extra_meta["first_frame"] = first_ref
            if last_ref:
                l_path, l_rel = resolve_reference_image_path(last_ref, spec, style=style)
                print(f"  video last_frame from {l_rel} — uploading")
                last_img_payload = {"url": upload_temp_url(l_path)}
                extra_meta["last_frame"] = last_ref
            if ref_imgs:
                ref_imgs_payload = []
                for r_name in ref_imgs:
                    r_path, r_rel = resolve_reference_image_path(r_name, spec, style=style)
                    print(f"  video reference_image from {r_rel} — uploading")
                    ref_imgs_payload.append({"url": upload_temp_url(r_path)})
                extra_meta["reference_images"] = ref_imgs

            has_keyframe_or_ref = bool(input_img_payload or last_img_payload or ref_imgs_payload)
            video_ratio = "adaptive" if has_keyframe_or_ref else (L.get("ratio") or aspect_ratio)
            ref_type = L.get("reference_type") or ("first_frame" if input_img_payload else None)

            # The clip length depends on the resolution and the reference mode
            # (Hailuo accepts 6 or 10 seconds and nothing between, and 1080P
            # caps it at 6), so it can only be computed once both are known.
            duration = int(L.get("duration") or _clip_duration(
                shot_seconds, model, resolution=video_res, reference_type=ref_type))

            task_id, model = submit_video_generation(
                prompt, model=model, duration=duration,
                ratio=video_ratio, resolution=video_res,
                input_image=input_img_payload,
                reference_type=ref_type,
                last_frame_image=last_img_payload,
                reference_images=ref_imgs_payload)
            data = wait_for_video(task_id, model)
            raw_path = os.path.join(ROOT, ".tmp", f"{asset}.download.mp4")
            download_video(data, raw_path)
            os.replace(raw_path, target_path)
            row = manifest.register(
                "assets", asset, rel, source="ai-generated", task_id=task_id,
                prompt=prompt, model=model, duration=duration,
                ratio=video_ratio, resolution=video_res,
                native_audio=VIDEO_MODELS.get(model, {}).get("audio", False),
                **extra_meta)
            print(f"Registered {rel} sha256={row['sha256'][:12]}")
            continue

        # Real generation via connector
        prompt = build_prompt(style, layer_prompt)
        input_urls = None
        src_asset = task.get("input_asset") or L.get("input_asset")
        ref_imgs = list(L.get("reference_images") or L.get("reference_assets") or [])
        all_img_refs = []
        if src_asset:
            all_img_refs.append(src_asset)
        for r_name in ref_imgs:
            if r_name and r_name not in all_img_refs:
                all_img_refs.append(r_name)
        if all_img_refs:
            input_urls = []
            for r_name in all_img_refs:
                src_path, src_rel = resolve_reference_image_path(r_name, spec, style=style)
                print(f"  image-to-image from {src_rel} — uploading")
                input_urls.append(upload_temp_url(src_path))
            if ref_imgs:
                extra_meta["reference_images"] = ref_imgs
        node_id = call_generate_image(prompt, asset, aspect_ratio=aspect_ratio,
                                      resolution=resolution, input_urls=input_urls)
        url = fetch_asset_url(node_id)
        raw_path = os.path.join(ROOT, ".tmp", f"{asset}.download")
        download_file(url, raw_path)
        ensure_png(raw_path, target_path)

        # Record the SOURCE pixel size (see the fixture branch above): the rig
        # calibration needs it, and a manifest row without it makes that
        # code guess — or crash.
        from core.media.png import read_size
        try:
            sw, sh = read_size(target_path)
        except (OSError, ValueError):
            sw = sh = None

        row = manifest.register("assets", asset, rel, source="ai-generated",
                                node_id=node_id, prompt=prompt,
                                aspect_ratio=aspect_ratio, resolution=resolution,
                                size=[sw, sh] if sw else None,
                                input_asset=src_asset, **extra_meta)
        print(f"Registered {rel} sha256={row['sha256'][:12]}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"S1 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
