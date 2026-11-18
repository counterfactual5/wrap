"""Render project artwork with Remotion; failures never substitute a design backend."""
import base64
import json
import os
import shutil
import subprocess

from core.runtime import manifest
from core.runtime.config import ENGINE_ROOT, ROOT
from core.runtime.timeouts import render_timeout_seconds
from core.rendering.quartz import _render_quartz_fallback

RENDERER_REMOTION = "remotion"


def build_props(spec):
    """Spec + prepared assets as inline props. Every image rides in as a data: URL
    (14 KB PNG -> ~19 KB base64) so the bundle's static-file server is never involved:
    the manifest-verified bytes are the exact bytes the renderer sees, and re-renders
    are reproducible offline. Prepared rows are looked up through the manifest
    (namespaced per shot) so composing a shot whose S2 never ran fails fast
    instead of picking up another shot's leftover assets.

    Video layers cannot use a data: URL (an mp4 is orders of magnitude larger
    than a PNG, and base64-inlining it would bloat every props file). They are
    staged into public/prepared/{shot}/ and referenced through Remotion's
    staticFile(), which resolves against the bundle's public folder."""
    # The shot id names the asset namespace (prepared/<shot>/...) and the
    # directories S3/S4 write to. It is a required field (core/spec/shot.py),
    # so there is no default to fall back on: a missing id must fail here
    # instead of landing two different shots on the same "shot-01" and
    # overwriting each other's assets.
    shot_id = spec["id"]
    props = {"spec": spec, "prepared": {}, "preparedVideos": {}, "preparedPoses": {}}
    for L in spec["layers"]:
        if L["type"] in ("ai", "image"):
            layer_scoped = f"{shot_id}/{L['id']}__layer"
            key = layer_scoped if manifest.verified("prepared", layer_scoped) is not None else f"{shot_id}/{L['asset']}"
        elif L["type"] == "video":
            key = f"{shot_id}/{L['asset']}"
        elif L["type"] == "component":
            continue
        else:
            raise RuntimeError(f"unsupported layer type: {L['type']}")
        row = manifest.verified("prepared", key)
        if row is None:
            raise RuntimeError(
                f"prepared '{key}' not manifest-verified; run S2 (02_prepare.py) "
                f"for this shot first")
        if L["type"] == "video":
            # Stage the clip where Remotion's staticFile() can find it.
            public_rel = f"prepared/{shot_id}/{L['asset']}.mp4"
            # public_rel is relative to public/ — the renderer reads
            # staticFile("prepared/<shot>/<asset>.mp4").
            public_root = os.path.abspath(os.path.join(ENGINE_ROOT, "public"))
            public_path = os.path.join(public_root, public_rel)
            # The staged path must stay inside public/prepared/ — that is the
            # only part the renderer reads. A shot id or asset name with ../
            # would otherwise write outside it.
            prepared_root = os.path.abspath(os.path.join(public_root, "prepared"))
            resolved = os.path.abspath(public_path)
            if not (resolved == prepared_root
                    or resolved.startswith(prepared_root + os.sep)):
                raise RuntimeError(
                    f"video layer {L['id']!r} would stage its clip outside "
                    f"public/prepared/: {public_rel} -> {resolved}")
            os.makedirs(os.path.dirname(public_path), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, row["path"]), public_path)
            props["preparedVideos"][L["id"]] = public_rel
            continue
        with open(os.path.join(ROOT, row["path"]), "rb") as f:
            props["prepared"][L["id"]] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        if L["type"] in ("ai", "image") and L.get("poses"):
            pose_map = {}
            for p in L["poses"]:
                pa = p.get("asset")
                if not pa or pa in pose_map:
                    continue
                pk = f"{shot_id}/{pa}"
                prow = manifest.verified("prepared", pk)
                if prow is None:
                    raise RuntimeError(
                        f"prepared '{pk}' not manifest-verified; run S2 (02_prepare.py) "
                        f"for this shot first")
                with open(os.path.join(ROOT, prow["path"]), "rb") as pf:
                    pose_map[pa] = "data:image/png;base64," + base64.b64encode(pf.read()).decode()
            props["preparedPoses"][L["id"]] = pose_map
    return props


def _tail(text, limit=6000):
    """The end of the renderer's output — where the failure is."""
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _error_context(cmd, proc):
    """The renderer's failure as one readable block: its own output first (the
    last lines carry the cause), then how it was invoked."""
    stream = ((proc.stderr or "").strip() or (proc.stdout or "").strip())
    where = f"cwd={ENGINE_ROOT}"
    parts = []
    if stream:
        parts.append("the renderer reported:\n" + _tail(stream))
    parts.append(f"invoked: {' '.join(cmd)}\n  ({where})")
    return "\n".join(parts)


def _raise_no_frames(ex, cmd, out_dir, shot_id):
    """The renderer exited without leaving a usable frame sequence.

    Renumbering is the only thing between `npx remotion render` and S4's
    measurements, so a missing frame has to name the directory the renderer
    actually wrote into — not just the errno of the rename."""
    shutil.rmtree(os.path.join(out_dir, "rm"), ignore_errors=True)
    listing = sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []
    # A bare errno says nothing about WHERE the frames should have been; name
    # the directory the renderer was asked to fill.
    raise RuntimeError(
        f"the Remotion render produced no usable frames for shot "
        f"{shot_id!r}: {ex}\n"
        f"  {out_dir} holds: {listing or '(nothing)'}\n"
        f"invoked: {' '.join(cmd)}\n  (cwd={ENGINE_ROOT})") from ex


def _dotted_path_segments(path):
    """Path segments that look like a file extension.

    Remotion's image-sequence CLI (`getExtensionOfFilename`) splits the whole
    output path on '.' and rejects any dot anywhere as "the output directory
    of the image sequence cannot have an extension" — a `my.project/` root or
    any dotted parent (`~/Work/foo.bar/`, `.tmp`) fails the render with a
    message that points at the caller's path, not at the rule."""
    return [seg for seg in os.path.normpath(path).split(os.sep) if '.' in seg]


def render_remotion(spec, out_dir, shot_id):
    if os.environ.get("POSTER_FORCE_QUARTZ") == "1":
        _render_quartz_fallback(spec, out_dir, shot_id)
        return
    dotted = _dotted_path_segments(os.path.join(out_dir, "rm"))
    if dotted:
        offender = next(iter(dotted))
        raise RuntimeError(
            f"Remotion's image-sequence CLI rejects an output path containing a dot "
            f"anywhere in it (segment {offender!r} found in {os.path.join(out_dir, 'rm')!r}) — "
            f"its extension check applies to the whole path, not the final directory. "
            f"Use a dot-free POSTER_ROOT / project path (e.g. my-project, not my.project). "
            f"No frames were rendered.")
    props = build_props(spec)
    # Props file is per shot too: two concurrent S3 runs share .tmp/.
    props_file = os.path.join(ROOT, ".tmp", f"render-props-{shot_id}.json")
    os.makedirs(os.path.dirname(props_file), exist_ok=True)
    with open(props_file, "w") as f:
        json.dump(props, f)

    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    cmd = [
        "npx", "remotion", "render", "remotion/index.tsx", "Shot",
        os.path.join(out_dir, "rm"),  # Remotion writes 0-indexed [frame].png here
        "--image-format=png", "--sequence", "--image-sequence-pattern=[frame].png",
        f"--props={props_file}",
    ]
    print(" ".join(cmd))
    env = dict(os.environ)
    # Locate a Node.js runtime without hard-coding a device-specific path:
    # honor NODE_BIN if the caller sets it, otherwise resolve `node` from PATH.
    node_bin = os.environ.get("NODE_BIN")
    if not node_bin:
        node_found = shutil.which("node")
        node_bin = os.path.dirname(node_found) if node_found else None
    if node_bin:
        env["PATH"] = f"{node_bin}{os.pathsep}{env.get('PATH', '')}"
    # remotion.config.ts resolves the engine root from this (webpack rewrites
    # __dirname while bundling the config, so it cannot locate the engine).
    env["WRAP_ENGINE_ROOT"] = ENGINE_ROOT
    # A render drives a headless browser: it can wedge on a dead GPU, a
    # browser that never returns, or a bundle that never finishes. The
    # budget scales with the shot so a long film is not cut off, and the
    # timeout names the command instead of hanging forever.
    render_budget = render_timeout_seconds(
        spec.get("durationInFrames", 0) / max(1, spec.get("fps", 30)))
    try:
        proc = subprocess.run(cmd, check=True, cwd=ENGINE_ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=render_budget)
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
        if proc.stderr:
            print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n")
        # Renumber 0-indexed [frame] (padded to the frame-count width) -> 1-indexed %05d
        pad = len(str(spec["durationInFrames"] - 1))
        for i in range(spec["durationInFrames"]):
            src = os.path.join(out_dir, "rm", f"{i:0{pad}d}.png")
            dst = os.path.join(out_dir, f"{i + 1:05d}.png")
            os.rename(src, dst)
        shutil.rmtree(os.path.join(out_dir, "rm"))
    # FileNotFoundError is an OSError, so this must precede the OSError handler
    # below: a missing executable and a missing frame are different failures.
    except FileNotFoundError as ex:
        # The renderer wrote its frames but the renumbering cannot find one
        # (the frame list moved under us): a render-output problem, not a
        # missing tool.
        if os.sep in str(getattr(ex, "filename", None) or ""):
            _raise_no_frames(ex, cmd, out_dir, shot_id)
        # Anything else is the launcher itself missing — npx, or the node it
        # resolves. A missing tool is not a browser environment: the partial
        # tree goes (the error names the directory it cleared) so a retry
        # starts from a known state.
        shutil.rmtree(os.path.join(out_dir, "rm"), ignore_errors=True)
        raise RuntimeError(
            f"the Remotion renderer could not be launched: {ex}\n"
            f"  `npx` must be on PATH (Node.js), and `node` too unless "
            f"NODE_BIN points at it.\n"
            f"invoked: {' '.join(cmd)}\n  (cwd={ENGINE_ROOT})") from ex
    except subprocess.TimeoutExpired as ex:
        # The renderer wedged. A timeout is neither a missing tool nor a
        # missing frame: say which, and clean the partial tree so a retry
        # starts from a known state.
        shutil.rmtree(os.path.join(out_dir, "rm"), ignore_errors=True)
        raise RuntimeError(
            f"the Remotion renderer timed out after {render_budget}s for shot "
            f"{shot_id!r}; no fallback was attempted.\n"
            f"  the browser may have wedged, or the shot is longer than the "
            f"budget allows.\n"
            f"invoked: {' '.join(cmd)}\n  (cwd={ENGINE_ROOT})") from ex
    except subprocess.CalledProcessError as ex:
        raise RuntimeError(
            f"the Remotion renderer failed for shot {shot_id!r} "
            f"(exit {ex.returncode}); no fallback was attempted.\n"
            f"{_error_context(cmd, ex)}") from ex
    except OSError as ex:
        # Renumbering failed: the renderer exited 0 but wrote no usable frame
        # sequence. Report the cause and what was actually on disk.
        _raise_no_frames(ex, cmd, out_dir, shot_id)
    print(f"renderer={RENDERER_REMOTION}")