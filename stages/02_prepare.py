"""S2: keying-purity gate (exit 1 = blocked) + normalise/scale + draw code layers.
Usage: python3 02_prepare.py [--spec path/to/spec.json]
"""
import argparse
import json
import math
import os
import subprocess
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core.runtime import manifest
from core.quality.pixels import EDGE_KEY_RING, EDGE_KEY_TOL, edge_key_purity, read_rgb
from core.media.png import read_size, write_png
from core.runtime.config import ROOT
from core.spec.shot import gate_of
from core.spec.naming import hex_rgb
from core.spec.loader import load_spec
from core.runtime.timeouts import LOCAL_TOOL_TIMEOUT, PROBE_TIMEOUT


# Upscale factor above which a video layer's softness is worth flagging.
UPSCALE_WARN = 1.2


def _video_source_size(path):
    """(width, height) of a video file, or (None, None) if unreadable."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    parts = res.stdout.strip().split(",")
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return None, None


def _video_source_info(path):
    """(width, height, frames, duration_seconds) of a media file.

    A still image probed as media reports 0 frames — which is how a picture
    used where a clip belongs gets caught."""
    # JSON, not CSV: ffprobe orders CSV fields by its own rules and reports
    # "N/A" for a container that has no frame count.
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames,duration",
         "-of", "json", path],
        capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    w = h = frames = None
    dur = 0.0
    try:
        import json as _json
        streams = _json.loads(res.stdout).get("streams", [])
        if streams:
            s = streams[0]
            w, h = s.get("width"), s.get("height")
            frames = s.get("nb_frames")
            if frames is not None:
                try:
                    frames = int(frames)
                except (TypeError, ValueError):
                    frames = None
            try:
                dur = float(s.get("duration"))
            except (TypeError, ValueError):
                dur = 0.0
    except Exception:
        pass
    if not dur:
        # Some containers report the duration on the format, not the stream.
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True,
            timeout=PROBE_TIMEOUT)
        try:
            dur = float(res.stdout.strip())
        except ValueError:
            dur = 0.0
    return w, h, frames, dur


def main():
    parser = argparse.ArgumentParser(description="S2: Prepare layers and verify key purity")
    parser.add_argument("--spec", default=None, help="Path to spec file (required)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    shot_id = spec["id"]
    W, H = spec["canvas"]["w"], spec["canvas"]["h"]
    FPS = spec["fps"]  # required by the schema — a missing fps is a broken spec, not 30
    # Prepared artifacts are namespaced per shot: build/prepared/{shot_id}/.
    # A shared build/prepared/{id}.png let whichever shot ran S2 last win the
    # filename (dark-style shots silently reused a light grid), the same
    # cross-shot contamination S4's frame binding already refuses.
    prep_dir = os.path.join(ROOT, "build", "prepared", shot_id)
    os.makedirs(prep_dir, exist_ok=True)
    blocked = False
    prepared_asset_configs = {}

    for L in spec["layers"]:
        if L["type"] not in ("ai", "video"):
            continue

        if L["type"] == "video":
            # A video layer is a frozen clip, not a keyed still: there is no
            # key color to measure, so the purity gate does not apply. The
            # clip is scaled to cover the layer rect (aspect preserved) and
            # re-encoded at the SHOT's frame rate.
            #
            # The frame rate must match the shot: Remotion computes a video
            # layer's loop period as mediaDuration * shotFps, so a 24fps clip
            # rendered at 30fps would loop over a window longer than the clip
            # itself and freeze on the last frame. Normalizing to the shot's
            # fps here keeps the loop period correct.
            src_row = manifest.verified("assets", L["asset"])
            if not src_row:
                print(f"{L['asset']}: no verified asset in manifest (run S1)", file=sys.stderr)
                sys.exit(2)
            src = os.path.join(ROOT, src_row["path"])
            lrect = L.get("rect", [0, 0, W, H])
            rw, rh = lrect[2], lrect[3]

            # A video layer must point at actual footage. A picture probed
            # as media reports 0 frames, and ffmpeg would happily "convert"
            # it into a 1-frame mp4 — a still shot the motion and freeze
            # gates would only catch much later, with the wrong reason.
            src_w, src_h, src_frames, src_dur = _video_source_info(src)
            # A picture has no frame count (None) or exactly one frame.
            not_a_clip = src_w is None or src_frames is None or src_frames < 2
            if not_a_clip:
                print(f"{L['asset']}: the video layer points at {src_row['path']}, "
                      f"which is not a moving clip"
                      + (f" (a still image: {src_w}x{src_h})" if src_w else "")
                      + ". Point it at a video asset, or use an \"ai\" layer for "
                        "a picture.", file=sys.stderr)
                sys.exit(2)

            rel = f"build/prepared/{shot_id}/{L['asset']}.mp4"
            out_path = os.path.join(ROOT, rel)
            vf = (f"scale={rw}:{rh}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={rw}:{rh},format=yuv420p")
            # Audio: the clip's own track is kept only when the layer asks for
            # it (muted: false) — the "the clip owns the audio" mode. A muted
            # layer (the default) drops the track, so the pipeline's TTS chain
            # is the only soundtrack.
            keep_audio = not L.get("muted", True)
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
                   "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                   "-pix_fmt", "yuv420p"]
            if keep_audio:
                # Keep the native track, normalized to the mastering format the
                # rest of the pipeline uses (44100 stereo, AAC).
                cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"])
            else:
                cmd.append("-an")
            cmd.append(out_path)
            subprocess.run(cmd, check=True, timeout=LOCAL_TOOL_TIMEOUT)

            # The clip's native size vs the canvas: a clip generated at 768P
            # (9:16 -> 768x1344) is upscaled to 1080x1920, and the upscale
            # eats the high-frequency detail — the shot comes out soft with
            # nothing in the pipeline saying so. Measure it and say it out
            # loud when the margin is thin.
            src_w, src_h = _video_source_size(src)
            upscale = 1.0
            if src_w and src_h:
                upscale = max(rw / src_w, rh / src_h)
            note = ""
            if upscale >= UPSCALE_WARN:
                note = (f" [upscale x{upscale:.2f}: source {src_w}x{src_h} "
                        f"-> {rw}x{rh}]")
                print(f"  {L['asset']}: source {src_w}x{src_h} is smaller than "
                      f"the {rw}x{rh} canvas — upscaled x{upscale:.2f}, detail "
                      f"will soften. Generate at a higher resolution "
                      f"(768P/2K) or reduce the canvas.")
            # The clip vs the shot: a clip shorter than the shot runs out
            # before the shot ends. With loop:true it repeats (fine); with
            # loop:false the tail is frozen. Say which it is, so the S4 hint
            # can tell "the footage is static" from "the footage ran out".
            shot_seconds = spec["durationInFrames"] / max(1, FPS)
            short = bool(src_dur) and src_dur < shot_seconds - 0.05
            if short and not L.get("loop", True):
                print(f"  {L['asset']}: the clip is {src_dur:.2f}s but the shot is "
                      f"{shot_seconds:.2f}s and loop is off — the last "
                      f"{shot_seconds - src_dur:.2f}s will be frozen.")
            manifest.register("prepared", f"{shot_id}/{L['asset']}", rel, source="video",
                              fps=FPS, has_audio=keep_audio,
                              source_size=[src_w, src_h] if src_w else None,
                              upscale=round(upscale, 3) if src_w else None,
                              source_duration=round(src_dur, 3) if src_dur else None,
                              shot_duration=round(shot_seconds, 3),
                              shorter_than_shot=short)
            print(f"prepared {rel} {rw}x{rh} @ {FPS}fps"
                  f"{' (with native audio)' if keep_audio else ''}{note}")
            continue

        ai_assets = [L["asset"]]
        for p in L.get("poses") or []:
            pa = p.get("asset")
            if pa and pa not in ai_assets:
                ai_assets.append(pa)

        zmax = max((L.get("motion") or {}).get("zoom", [1, 1]))
        lrect = L.get("rect", [0, 0, W, H])
        rw, rh = lrect[2], lrect[3]
        cutout = bool(L.get("cutout"))
        # The renderer draws the prepared image inside the layer rect with
        # objectFit: layer.fit ?? 'cover' (remotion/Shot.tsx MediaLayer), so the
        # prepared file must already respect that geometry — the source aspect
        # ratio is always preserved, never stretched or blind-cropped:
        # - cover: scaled to cover the box, centre-cropped to it;
        # - contain: scaled to fit inside the box, centred on a transparent
        #   canvas (the joint/socket pivot math in core/media/geometry.py
        #   assumes exactly this contain mapping);
        # - cutout: keyed sprite (below), which is contain-shaped plus colorkey.
        fit = L.get("fit") or "cover"
        pw = math.ceil(rw * zmax * 1.04 / 2) * 2          # headroom so zoom never exposes an edge
        ph = math.ceil(rh * zmax * 1.04 / 2) * 2
        if cutout:
            # Foreground cutout sprite: key out keyColor to true RGBA transparency
            # and scale with decrease + transparent pad so limbs/weapons are never cropped.
            key_hex = L.get("keyColor", "#000000").lstrip("#")
            sim = L.get("cutoutSimilarity")
            blend = L.get("cutoutBlend")
            if sim is None or blend is None:
                sys.exit(
                    f"{lid}: cutout:true requires explicit 'cutoutSimilarity'/'cutoutBlend' "
                    f"(validate the spec — the engine ships no default key match ratio)")
            vf = (
                f"format=rgba,"
                f"colorkey=0x{key_hex}:{sim}:{blend},"
                f"scale={pw}:{ph}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
            )
        elif fit == "contain":
            # fit:'contain' — the whole image stays visible inside the rect and
            # the letterbox is transparent so lower layers show through, exactly
            # like the renderer's objectFit:'contain' (same chain as
            # core/rendering/video_frames.py uses for contain clips).
            vf = (
                f"format=rgba,"
                f"scale={pw}:{ph}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black@0.0"
            )
        else:
            # fit:'cover' (the default) — cover the box preserving the source
            # aspect and crop the centre. Full-canvas layers take this path
            # too: forcing scale to the canvas ratio would stretch any source
            # whose aspect differs from the canvas.
            vf = (f"scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={pw}:{ph},format=rgb24")

        is_opaque_backdrop = (
            L.get("blend") == "normal"
            and not L.get("cutout")
        )

        for asset_name in ai_assets:
            src_row = manifest.verified("assets", asset_name)
            if not src_row:
                print(f"{asset_name}: no verified asset in manifest (run S1)", file=sys.stderr)
                sys.exit(2)
            src = os.path.join(ROOT, src_row["path"])
            sw, sh = read_size(src)

            g = gate_of(spec, "edge_key_purity")
            if g is not None and not is_opaque_backdrop:
                purity = edge_key_purity(
                    read_rgb(src, sw, sh), sw, sh, hex_rgb(L["keyColor"]),
                    ring=g.get("ring", EDGE_KEY_RING), tol=g.get("tol", EDGE_KEY_TOL)
                )
                lo = g.get("lo", 0.98)
                verdict = "PASS" if purity >= lo else "BLOCKED"
                print(f"{asset_name}: edge_key_purity={purity:.4f} (>= {lo}) {verdict}")
                if purity < lo:
                    blocked = True
                    continue
            else:
                purity = 1.0
                if g is not None and is_opaque_backdrop:
                    print(f"{asset_name}: full-bleed opaque backdrop (blend:normal) — edge_key_purity exempt")

            cfg_sig = (pw, ph, cutout, vf)
            prev_sig = prepared_asset_configs.get(asset_name)
            if prev_sig is None or prev_sig == cfg_sig:
                prepared_asset_configs[asset_name] = cfg_sig
                rel = f"build/prepared/{shot_id}/{asset_name}.png"
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
                     os.path.join(ROOT, rel)],
                    check=True, timeout=LOCAL_TOOL_TIMEOUT
                )
                manifest.register("prepared", f"{shot_id}/{asset_name}", rel, source="scaled", purity=purity, size=[pw, ph])
                print(f"prepared {rel} {pw}x{ph}")
            if prev_sig is not None and prev_sig != cfg_sig and asset_name == L["asset"]:
                # Secondary layer sharing the same asset with a different rect/cutout config:
                # write a layer-scoped prepared image so the primary asset's prepared file is not clobbered.
                layer_key = f"{L['id']}__layer"
                rel_layer = f"build/prepared/{shot_id}/{layer_key}.png"
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
                     os.path.join(ROOT, rel_layer)],
                    check=True, timeout=LOCAL_TOOL_TIMEOUT
                )
                manifest.register("prepared", f"{shot_id}/{layer_key}", rel_layer, source="scaled", purity=purity, size=[pw, ph])
                print(f"prepared {rel_layer} {pw}x{ph} (layer-scoped for {L['id']})")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
