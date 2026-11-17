#!/usr/bin/env python3
"""Unified CLI runner for the code-driven poster video pipeline.
Commands:
  validate   Check spec against schema
  generate   S1: fetch/verify AI assets into manifest
  prepare    S2: key purity gate & scaling & code layers
  compose    S3: Remotion composition (frames + mp4)
  gate       S4: run quality gates (motion, color, purity, freeze, audio)
  inspect    S5: generate contact sheet + checklist (verdict pending judge)
  judge      S5: record visual verdict (--verdict pass|fail --notes ...)
  run        Execute stages S1 -> S2 -> S3 -> S4 -> S5 in sequence
  init-shot  Initialize a new shot specification template
  concat     Concatenate multiple rendered shots via timeline.json
  test       Execute full automated test suite
  clean      Clean intermediate build artifacts
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

# The engine relies on int.bit_count() (Python >= 3.10). Fail fast with an
# actionable message instead of dying deep inside a stage with an
# AttributeError.
_MIN = (3, 10)
if sys.version_info < _MIN:
    sys.exit(
        f"wrap requires Python >= {_MIN[0]}.{_MIN[1]} (int.bit_count). "
        f"Found {sys.version.split()[0]}. Install a newer interpreter, then run "
        f"`python3.x pipeline.py ...` or `make PY=python3.x verify`."
    )

ENGINE_ROOT = os.path.dirname(os.path.realpath(__file__))
# Project root: where spec/, assets/, build/ and manifest.json live. Defaults to
# the engine itself (development/tests); POSTER_ROOT points the pipeline at an
# external project (e.g. the examples repo).
ROOT = os.environ.get("POSTER_ROOT") or ENGINE_ROOT
CORE = os.path.join(ENGINE_ROOT, "core")
STAGES = os.path.join(ENGINE_ROOT, "stages")

# The assembly domain logic lives in core/assembly/timeline.py; the CLI
# (argparse, the stage subprocesses, the exit codes) stays here. The
# re-export keeps `from pipeline import missing_assets` — and its
# siblings — working.
from core.assembly.timeline import (  # noqa: F401  (re-exported for callers and tests)
    AssemblyError,
    concat_stream_problem,
    extract_frame_asset,
    gate_full_video,
    missing_assets,
    referenced_assets,
    spec_references_asset,
)
from core.assembly.timeline import load_timeline as _load_timeline


def run_stage(cmd_args, desc):
    print(f"\n=== [Stage] {desc} ===")
    env = dict(os.environ)
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = ENGINE_ROOT + (os.pathsep + python_path if python_path else "")
    res = subprocess.run([sys.executable] + cmd_args, cwd=ROOT, env=env)
    if res.returncode != 0:
        print(f"FAILED: {desc} exited with code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)


def load_timeline(rel_path, create_default=False):
    """CLI adapter over `core.assembly.timeline.load_timeline`.

    The domain loader raises `AssemblyError`; the CLI turns that into the exit
    the pipeline has always produced for a timeline it cannot use.
    """
    try:
        return _load_timeline(rel_path, create_default=create_default)
    except AssemblyError as ex:
        sys.exit(str(ex))


def _timeline_shot_specs(tl):
    specs = []
    for shot in tl.get("shots", []):
        rel = shot["spec"] if isinstance(shot, dict) else shot
        path = os.path.join(ROOT, rel if rel.endswith(".json") else f"spec/{rel}.poster.json")
        if not os.path.exists(path):
            sys.exit(f"Error: shot spec not found: {path}")
        with open(path) as sf:
            specs.append((path, json.load(sf)))
    return specs


def _check_timeline_bgm_intent(tl, specs):
    from core.audio.shot import shot_is_intentionally_silent

    if "allow_bgm_override_silent" in tl and not isinstance(tl["allow_bgm_override_silent"], bool):
        sys.exit("timeline 'allow_bgm_override_silent' must be a boolean")
    bgm = (tl.get("bgm") or "").strip() if isinstance(tl.get("bgm"), str) else ""
    if not bgm or bgm.lower() == "none":
        return
    candidates = [bgm, os.path.join(ROOT, bgm), os.path.join(ROOT, "assets", bgm)]
    found_bgm = next((p for p in candidates if os.path.exists(p)), None)
    if not found_bgm:
        raise FileNotFoundError(f"Timeline BGM file not found: {bgm}; built-in music presets were removed")
    silent = [spec["id"] for _, spec in specs if shot_is_intentionally_silent(spec)]
    if silent and tl.get("allow_bgm_override_silent") is not True:
        sys.exit(
            f"Timeline {tl.get('id', 'sequence')}: timeline.bgm would override "
            f"intentionally silent shot(s): {', '.join(silent)}. "
            "Set allow_bgm_override_silent:true explicitly to allow this.")
    from core.audio.integrity import verify_audio
    verify_audio(found_bgm)


def run_timeline(args):
    """Render every shot of a timeline IN ORDER, seam them, assemble, gate.

    The order is the whole point: shot k+1's first_frame may name the asset
    that shot k produces (the "<shot-id>-tail" seam), so shot k has to be
    GENERATED before shot k+1's S1 runs. Carrying that ordering in your head
    is the fragile part; here the timeline is the only thing you have to get
    right.
    """
    tl = load_timeline(args.timeline)
    shots = tl.get("shots", [])
    print(f"\n=== Timeline Run: {tl.get('id', 'sequence')} — {len(shots)} shots, in order ===")

    specs = _timeline_shot_specs(tl)
    _check_timeline_bgm_intent(tl, specs)

    for idx, (path, s_data) in enumerate(specs):
        sid = s_data["id"]
        print(f"\n{'=' * 60}\n[{idx + 1}/{len(specs)}] {sid}\n{'=' * 60}")
        run_stage(["-m", "core.spec", path], f"Spec Validation ({sid})")
        gen_args = [os.path.join(STAGES, "01_generate.py"), "--spec", path]
        if args.force:
            gen_args.append("--force")
        run_stage(gen_args, f"S1: Asset Generation ({sid})")
        run_stage([os.path.join(STAGES, "02_prepare.py"), "--spec", path], f"S2: Prepare ({sid})")
        run_stage([os.path.join(STAGES, "03_compose.py"), "--spec", path], f"S3: Compose ({sid})")
        run_stage([os.path.join(STAGES, "04_gate.py"), "--spec", path], f"S4: Quality Gates ({sid})")
        run_stage([os.path.join(STAGES, "05_inspect.py"), "--spec", path], f"S5: Inspect ({sid})")

        # SEAM: the next shot may want THIS shot's tail. Freeze it NOW —
        # before the next shot's S1 goes looking for it. The name is the
        # "<shot-id>-tail" convention; any unfrozen "<something>-tail" the
        # next shot references is taken as a seam from this shot.
        if idx + 1 < len(specs):
            from core.runtime import manifest
            nxt = specs[idx + 1][1]
            wanted = [n for n in referenced_assets(nxt)
                      if n.endswith("-tail") and manifest.verified("assets", n) is None]
            mp4 = os.path.join(ROOT, "build", f"{sid}.mp4")
            for name in wanted:
                if os.path.exists(mp4):
                    print(f"  seam: freezing {name} from {os.path.basename(mp4)}")
                    extract_frame_asset(mp4, name, at="last")
                else:
                    print(f"  seam: {os.path.basename(mp4)} is missing — {name} cannot be frozen")

    out_path, code = assemble_timeline(tl, args.output)
    print(f"\nTimeline run complete: {len(specs)} shots rendered in order, seams frozen, "
          f"film assembled -> {os.path.relpath(out_path, ROOT)}")
    print("Visual inspection is PENDING judge — review each contact sheet, then run:")
    for path, s_data in specs:
        print(f"  python3 pipeline.py judge --spec {os.path.relpath(path, ROOT)} "
              f"--verdict pass|fail --notes \"...\"")
    return code


def assemble_timeline(tl, out_rel=None):
    """Assemble a timeline into one mp4 and run the full-video gates.

    Shared by `concat` (assemble what already exists) and `run --timeline`
    (render every shot first, then assemble). A shot whose mp4 is missing is
    built from the top — but a missing ASSET would cost a model call, so it is
    never generated here: the author is told exactly which command to run.

    Returns (out_path, exit_code).
    """
    shots = tl.get("shots", [])
    print(f"\n=== Timeline Assembly: {tl.get('id', 'sequence')} ({len(shots)} clips) ===")

    specs = _timeline_shot_specs(tl)
    _check_timeline_bgm_intent(tl, specs)
    rendered_mp4s = []
    segments = []  # (shot_id, start_sec, dur_sec) — the full-gate's measurement windows
    cursor = 0.0
    for idx, shot in enumerate(shots):
        if isinstance(shot, dict):
            beat = shot.get("beat", "scene")
            reason = shot.get("reason", "")
        else:
            beat = "scene"
            reason = ""

        shot_file, s_data = specs[idx]
        sid = s_data["id"]

        print(f"  [{idx+1}/{len(shots)}] [{beat.upper():<11}] {sid:<24} | {reason if reason else 'No reason specified'}")

        mp4_path = os.path.join(ROOT, "build", f"{sid}.mp4")
        # Contract: only verified rendered files are assembled. When one is
        # missing, build it from the top: S1 (reuse the frozen assets),
        # S2 (prepare them — S3 refuses to render without the prepared
        # rows), S3 (render), S4 (gate). Running only S3+S4 left a fresh
        # clone dead on "prepared '<shot>/<layer>' not manifest-verified".
        if not os.path.exists(mp4_path):
            # S1 can also GENERATE, which costs money. "Assemble what I
            # have" must not silently become "generate what is missing":
            # the assets have to be frozen already, or the author is told
            # exactly which command to run.
            missing = missing_assets(s_data)
            if missing:
                rel_spec = os.path.relpath(shot_file, ROOT)
                sys.exit(
                    f"Timeline {tl.get('id', 'sequence')}: the shot {sid} needs "
                    f"asset(s) that are not frozen yet: {', '.join(missing)}.\n"
                    f"  Generating them costs a model call — run it yourself:\n"
                    f"    python3 pipeline.py generate --spec {rel_spec}\n"
                    f"  then re-run this concat.")
            print(f"      [Build Contract] MP4 missing for {sid}. Building and gating now...")
            run_stage([os.path.join(STAGES, "01_generate.py"), "--spec", shot_file], f"Assets {sid}")
            run_stage([os.path.join(STAGES, "02_prepare.py"), "--spec", shot_file], f"Prepare {sid}")
            run_stage([os.path.join(STAGES, "03_compose.py"), "--spec", shot_file], f"Render {sid}")
            run_stage([os.path.join(STAGES, "04_gate.py"), "--spec", shot_file], f"Gate {sid}")
        rendered_mp4s.append(mp4_path)
        dur = s_data["durationInFrames"] / s_data["fps"]
        segments.append((sid, cursor, dur))
        cursor += dur

    # The concat demuxer drops the audio track of every shot that has one
    # when the inputs disagree on whether they carry audio — silently, with
    # a zero exit code. Refuse before assembling rather than shipping a
    # film that lost its soundtrack.
    problem = concat_stream_problem(list(zip(
        [s for s, _, _ in segments], rendered_mp4s)))
    if problem:
        sys.exit(f"Timeline {tl.get('id', 'sequence')}: {problem}")

    tl_id = tl.get("id", "sequence")
    default_out_rel = f"build/{tl_id}.mp4" if tl_id and tl_id != "sequence" else "build/full.mp4"
    explicit_out = out_rel is not None
    out_rel = out_rel or default_out_rel
    out_path = os.path.join(ROOT, out_rel)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # Per-timeline list, not a shared slot: two concat runs for different
    # timelines must not clobber each other's input file.
    concat_dir = os.path.join(ROOT, "build", "concat")
    os.makedirs(concat_dir, exist_ok=True)
    concat_txt = os.path.join(concat_dir, f"{tl_id}.txt")
    with open(concat_txt, "w") as f:
        for p in rendered_mp4s:
            f.write(f"file '{os.path.abspath(p)}'\n")

    print(f"\nConcatenating {len(rendered_mp4s)} shots -> {out_path} ...")
    # The concat DEMUXER copies both streams byte-for-byte and places each
    # file's audio by its own track duration. AAC frames are 1024 samples,
    # so a shot's audio track is a few ms shorter than its video, and
    # those ms accumulate shot after shot: the tail of one shot's audio
    # lands at the head of the next. A shot declared SILENT then starts
    # with a burst of the previous shot's sound — audible at the cut, and
    # fatal for the full-video loudness_jump gate.
    #
    # Split the two jobs: the demuxer aligns the VIDEO correctly and
    # keeps the frames bit-exact (copy, no re-encode), while the concat
    # FILTER rebuilds the AUDIO, re-interleaving by presentation
    # timestamp so each track lands exactly where its video does. Then mux
    # the two back together.
    v_out = os.path.join(ROOT, ".tmp", f"concat_{tl_id}_video.mp4")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt, "-an", "-c:v", "copy", v_out,
    ], check=True)

    a_out = os.path.join(ROOT, ".tmp", f"concat_{tl_id}_audio.m4a")
    raw_a_out = os.path.join(ROOT, ".tmp", f"concat_{tl_id}_raw_audio.m4a")
    audio_inputs = []
    for p in rendered_mp4s:
        audio_inputs += ["-i", p]
    chains = "".join(f"[{i}:a]" for i in range(len(rendered_mp4s)))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y"] + audio_inputs
        + ["-filter_complex", f"{chains}concat=n={len(rendered_mp4s)}:v=0:a=1[aout]",
           "-map", "[aout]", "-c:a", "aac", "-b:a", "192k",
           "-ar", "44100", "-ac", "2", raw_a_out],
        check=True)

    tl_bgm = (tl.get("bgm") or "").strip() if isinstance(tl.get("bgm"), str) else ""
    if tl_bgm and tl_bgm.lower() != "none":
        from core import audio as _audio
        tl_bgm_wav = os.path.join(ROOT, ".tmp", f"concat_{tl_id}_bgm.wav")
        total_dur = max(0.5, cursor)
        candidates = [tl_bgm, os.path.join(ROOT, tl_bgm), os.path.join(ROOT, "assets", tl_bgm)]
        found_bgm = next((p for p in candidates if os.path.exists(p)), None)
        if found_bgm:
            from core.audio.integrity import verify_audio
            found_bgm = verify_audio(found_bgm)
            fade_dur = min(0.05, total_dur * 0.1)
            fade_f = f"afade=t=in:ss=0:d={fade_dur:.3f},afade=t=out:st={max(0.0, total_dur - fade_dur):.3f}:d={fade_dur:.3f}"
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-stream_loop", "-1",
                "-i", found_bgm, "-t", str(total_dur),
                "-af", fade_f, "-ar", "44100", "-ac", "2", tl_bgm_wav
            ], check=True)
        else:
            raise FileNotFoundError(f"Timeline BGM file not found: {tl_bgm}; built-in music presets were removed")

        raw_sil = _audio.measure_audio_silence(raw_a_out)
        if raw_sil.get("is_silent"):
            # Shots carry no own audio: master the timeline BGM across the entire film at -16 LUFS
            _audio.run_two_pass_loudnorm(["-i", tl_bgm_wav], "-af", "", total_dur, a_out)
            print(f"  timeline bgm: overlaid {tl_bgm} across full film ({total_dur:.2f}s, mastered to -16 LUFS)")
        else:
            # Mix shot audio with ducked timeline BGM bed and normalize
            mix_fc = (
                f"[0:a]volume=1.0[v];"
                f"[1:a]volume=0.24[b];"
                f"[v][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
            )
            _audio.run_two_pass_loudnorm(
                ["-i", raw_a_out, "-i", tl_bgm_wav],
                "-filter_complex",
                mix_fc,
                total_dur,
                a_out,
            )
            print(f"  timeline bgm: mixed {tl_bgm} under shot audio ({total_dur:.2f}s, mastered to -16 LUFS)")
    else:
        shutil.copyfile(raw_a_out, a_out)

    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", v_out, "-i", a_out,
        "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", out_path,
    ], check=True)
    print(f"Successfully generated: {out_path} (size: {os.path.getsize(out_path)} bytes)")

    # Keep both build/<timeline_id>.mp4 and build/full.mp4 synchronized when
    # outputting to a canonical path, so opening either filename reflects the
    # latest assembly. build/full.mp4 is an ALIAS of the latest assembly, not
    # a per-timeline output — two timelines cannot both own it.
    canonical_rels = {f"build/{tl_id}.mp4", "build/full.mp4"}
    if not explicit_out or out_rel in canonical_rels:
        for mirror_rel in canonical_rels:
            mirror_path = os.path.join(ROOT, mirror_rel)
            if os.path.abspath(mirror_path) != os.path.abspath(out_path):
                shutil.copy2(out_path, mirror_path)
                print(f"Synchronized alias: {mirror_path}")

    print(f"\n=== [Stage] Full-Video Gates ({tl_id}) ===")
    return out_path, gate_full_video(out_path, tl_id, segments, allow_black=tl.get("allow_black", False))


PIPELINE_LOCK = os.path.join(ROOT, "build", ".pipeline.lock")


class pipeline_lock:
    """Advisory lock around `run`: build artifacts are now per-shot namespaced,
    but a full S1..S5 run still writes shared state (manifest.json, .tmp/), and
    two interleaved full runs are how the bg.png contamination happened. Fail
    fast with a pointer instead of silently interleaving. A crashed run leaves
    the file behind — delete it once you've confirmed no pipeline is live."""

    def __enter__(self):
        if os.path.exists(PIPELINE_LOCK):
            with open(PIPELINE_LOCK) as f:
                info = f.read().strip()
            sys.exit(
                f"pipeline lock held: {PIPELINE_LOCK}\n"
                f"  {info}\n"
                f"  another full pipeline run may be in progress. If none is "
                f"(e.g. a crashed run), delete the lock file and retry.")
        os.makedirs(os.path.dirname(PIPELINE_LOCK), exist_ok=True)
        import datetime
        with open(PIPELINE_LOCK, "w") as f:
            f.write(f"pid={os.getpid()} started={datetime.datetime.now().isoformat(timespec='seconds')}")
        return self

    def __exit__(self, *exc):
        try:
            os.remove(PIPELINE_LOCK)
        except OSError:
            pass
        return False


def main():
    parser = argparse.ArgumentParser(description="Code-driven shot video pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate spec against schema")
    p_val.add_argument("--spec", default=None)

    # generate (S1)
    p_gen = subparsers.add_parser("generate", help="S1: generate/fetch assets")
    p_gen.add_argument("--spec", default=None)
    p_gen.add_argument("--force", action="store_true", help="Force re-generation")

    # prepare (S2)
    p_prep = subparsers.add_parser("prepare", help="S2: prepare assets & key purity check")
    p_prep.add_argument("--spec", default=None)

    # compose (S3)
    p_comp = subparsers.add_parser("compose", help="S3: ffmpeg compose frames & mp4")
    p_comp.add_argument("--spec", default=None)

    # gate (S4)
    p_gate = subparsers.add_parser("gate", help="S4: quality gates & freeze detect")
    p_gate.add_argument("--spec", default=None)

    # inspect (S5)
    p_insp = subparsers.add_parser("inspect", help="S5: Generate contact sheet & checklist for visual self-audit")
    p_insp.add_argument("--spec", default=None)
    p_insp.add_argument("--grid", default="3x3", help="Contact sheet grid, e.g. 3x3")

    # judge (S5 verdict)
    p_judge = subparsers.add_parser("judge", help="S5: Judge the contact sheet; record pass/fail verdict")
    p_judge.add_argument("--spec", default=None)
    p_judge.add_argument("--verdict", choices=["pass", "fail"], default=None,
                         help="Record verdict; omit to regenerate evidence + judge instructions")
    p_judge.add_argument("--notes", default=None, help="Judge findings stored with the verdict")

    # run (S1..S5)
    p_run = subparsers.add_parser("run", help="Run full pipeline: validate -> S1 -> S2 -> S3 -> S4 -> S5")
    p_run.add_argument("--spec", default=None)
    p_run.add_argument("--timeline", default=None,
                       help="Render every shot of a timeline IN ORDER (seaming them as it goes), "
                            "then assemble and gate the film. Mutually exclusive with --spec.")
    p_run.add_argument("--output", default=None,
                       help="Output mp4 for --timeline (default build/<timeline-id>.mp4)")
    p_run.add_argument("--force", action="store_true", help="Force re-generation of assets")

    # init-shot
    p_init = subparsers.add_parser("init-shot", help="Initialize a new shot specification template")
    p_init.add_argument("shot_id", help="Shot ID, e.g. shot-02")
    p_init.add_argument("--canvas", nargs=2, type=int, required=True, metavar=("WIDTH", "HEIGHT"))
    p_init.add_argument("--fps", type=int, required=True)
    p_init.add_argument("--frames", type=int, required=True)
    p_init.add_argument("--from-shot", default=None, help="Path to previous shot spec to carry final layer states from")

    # inspect-sprite
    p_ispr = subparsers.add_parser("inspect-sprite", help="Generate coordinate ruler grid & compute canvas pivot for a sprite asset")
    p_ispr.add_argument("asset", help="Asset name in assets/<asset>.png")
    p_ispr.add_argument("--rect", default=None, help="Layer canvas rect x,y,w,h (e.g. 260,290,448,600)")
    p_ispr.add_argument("--joint", default=None, help="Joint coordinate jx,jy in source pixels or 0..1 floats (e.g. 638,612)")
    p_ispr.add_argument("--key-color", default="#ffffff", help="Solid background hex color (default: #ffffff)")

    # split-sprite
    p_sspr = subparsers.add_parser("split-sprite", help="Split a character sprite into parent body + one or more articulated child limbs/weapons")
    p_sspr.add_argument("--src", required=True, help="Source asset name in assets/<src>.png")
    p_sspr.add_argument("--body", required=True, help="Output parent body asset name")
    p_sspr.add_argument("--part", default=None, help="Output child weapon/limb asset name (single-part mode)")
    p_sspr.add_argument("--box", default=None, help="Child region x0,y0,x1,y1 in source pixels or 0..1 floats (single-part mode)")
    p_sspr.add_argument("--joint", default=None, help="Hinge joint jx,jy in source pixels or 0..1 floats (single-part mode)")
    p_sspr.add_argument("--parts-json", default=None, help="JSON list of part specs [{\"part\":\"...\",\"box\":[x0,y0,x1,y1],\"joint\":[jx,jy],\"radius\":22}] for multi-node splitting")
    p_sspr.add_argument("--clean-boxes-json", default=None, help="Optional JSON list of extra boxes [[x0,y0,x1,y1],...] to sanitize on the parent body")
    p_sspr.add_argument("--radius", type=int, default=22, help="Joint overlap cap radius in source pixels (default: 22)")
    p_sspr.add_argument("--rect", default=None, help="Layer canvas rect x,y,w,h to auto-compute canvas pivot")
    p_sspr.add_argument("--key-color", default="#ffffff", help="Solid background hex color (default: #ffffff)")

    # derive-poses
    p_pose = subparsers.add_parser("derive-poses", help="Slice a multi-pose sprite sheet or derive combat/transformation pose states")
    p_pose.add_argument("--sheet", default=None, help="Horizontal sprite-sheet asset name to slice")
    p_pose.add_argument("--cols", type=int, default=3, help="Number of horizontal panels in --sheet (default: 3)")
    p_pose.add_argument("--out-prefix", default=None, help="Output asset prefix when slicing --sheet")
    p_pose.add_argument("--key-color", default="#ffffff", help="Solid background hex color (default: #ffffff)")

    # snap-joint
    p_snap = subparsers.add_parser("snap-joint", help="Compute child layer canvas rect and pivot to snap onto parent receiving socket")
    p_snap.add_argument("--parent-asset", required=True, help="Parent asset name in assets/<asset>.png")
    p_snap.add_argument("--parent-rect", required=True, help="Parent canvas rect x,y,w,h")
    p_snap.add_argument("--parent-socket", required=True, help="Parent receiving socket coordinate sx,sy in source pixels")
    p_snap.add_argument("--child-asset", required=True, help="Child asset name in assets/<asset>.png")
    p_snap.add_argument("--child-joint", required=True, help="Child joint coordinate jx,jy in source pixels")
    p_snap.add_argument("--scale", type=float, default=None, help="Explicit scale factor (defaults to parent contain scale)")

    # unpack-kit
    p_unpack = subparsers.add_parser("unpack-kit", help="Slice a multi-component runner sheet into registered modular parts")
    p_unpack.add_argument("--sheet", required=True, help="Kit sheet asset name in assets/<sheet>.png")
    p_unpack.add_argument("--prefix", required=True, help="Prefix for extracted part assets")
    p_unpack.add_argument("--labels", default=None, help="Comma-separated part names, e.g. torso,arm,blade")
    p_unpack.add_argument("--min-area", type=int, default=300, help="Minimum pixel area for a valid component (default: 300)")
    p_unpack.add_argument("--pad", type=int, default=16, help="Padding in pixels around each component (default: 16)")
    p_unpack.add_argument("--sort-by", choices=["area", "position"], default="area", help="Sort order (default: area descending)")
    p_unpack.add_argument("--key-color", default="#ffffff", help="Solid background hex color (default: #ffffff)")

    # sync-audio
    p_sync = subparsers.add_parser("sync-audio", help="Synthesize audio.voiceover, fit durationInFrames (no truncation), and warp tracks.captions + layer keyframes to speech clauses")
    p_sync.add_argument("--spec", default=None, help="Path to spec file")
    p_sync.add_argument("--no-fit-duration", action="store_true", help="Do not expand durationInFrames to fit voiceover duration")
    p_sync.add_argument("--no-rescale-anim", action="store_true", help="Do not rescale anim keyframes when durationInFrames expands")
    p_sync.add_argument("--max-chars", type=int, default=20, help="Max characters per subtitle clause (default: 20)")

    # concat
    p_cat = subparsers.add_parser("concat", help="Concatenate multiple rendered shots via timeline")
    p_cat.add_argument("--timeline", default="spec/timeline.json", help="Path to timeline.json")
    p_cat.add_argument("--output", default=None, help="Path to output mp4 (defaults to build/<timeline_id>.mp4 and build/full.mp4)")

    # verify-rig
    p_rig = subparsers.add_parser("verify-rig", help="Verify skeletal puppet joint alignment, socket calibration & render diagnostic overlay")
    p_rig.add_argument("--spec", required=True, help="Path to poster spec JSON")
    p_rig.add_argument("--tolerance", type=int, default=4, help="Maximum allowed socket-joint distance error in canvas px")

    # verify-combat
    p_combat = subparsers.add_parser("verify-combat", help="Verify physical weapon-to-target contact on all punch/strike frames")
    p_combat.add_argument("--spec", required=True, help="Path to poster spec JSON")
    p_combat.add_argument("--attacker", default=None, help="Attacker root layer ID (defaults to spec.combat.attacker or auto-discovered)")
    p_combat.add_argument("--weapon", default=None, help="Articulated weapon layer ID (defaults to spec.combat.weapon or auto-discovered)")
    p_combat.add_argument("--target", default=None, help="Target layer ID (defaults to spec.combat.target or auto-discovered)")
    p_combat.add_argument("--tolerance", type=int, default=None, help="Maximum allowed whiffing gap in canvas px (default: 40)")

    # verify-blocking
    p_block = subparsers.add_parser("verify-blocking", help="Verify co-planar 2D character non-overlap & horizontal stage-lane separation across all frames")
    p_block.add_argument("--spec", required=True, help="Path to poster spec JSON")
    p_block.add_argument("--max-overlap", type=float, default=12.0, help="Maximum allowed torso overlap in canvas px (default: 12.0)")

    # verify-continuity
    p_cont = subparsers.add_parser("verify-continuity", help="Verify cross-shot continuity: backdrop handoff match and character position/visibility seams between consecutive shots")
    p_cont.add_argument("--timeline", default=None, help="Path to timeline.json for cross-shot continuity verification")
    p_cont.add_argument("--spec", default=None, help="Path to a single poster spec JSON for stagecraft & prop verification")
    p_cont.add_argument("--max-jump", type=float, default=None,
                        help="Max character jump across a cut, in canvas px (default: timeline.continuity.max_char_jump_px or 18.0)")
    p_cont.add_argument("--allow-non-seamless", action="store_true",
                        help="Downgrade a backdrop mismatch to BACKDROP_WARN instead of a hard failure (default: require match)")
    p_cont.add_argument("--min-visible-opacity", type=float, default=None,
                        help="Opacity at/above which a character counts as visible in a cut (default: timeline.continuity.min_visible_opacity or 0.20)")

    # detect-punches
    p_dp = subparsers.add_parser("detect-punches", help="Auto-detect audio transient peaks (percussion/plosives/sub-bass) as tracks.events kind=audio_transient")
    p_dp.add_argument("--spec", default=None, help="Path to spec file")
    p_dp.add_argument("--audio", default=None, help="Optional explicit audio/video file path")
    p_dp.add_argument("--max-punches", type=int, default=6, help="Maximum number of punch frames to detect")
    p_dp.add_argument("--min-gap", type=float, default=0.45, help="Minimum gap in seconds between punches")
    p_dp.add_argument("--threshold-sigma", type=float, default=1.6, help="Peak threshold in standard deviations above mean flux (default: 1.6)")
    p_dp.add_argument("--highpass", type=float, default=180.0, help="Highpass filter cutoff in Hz (default 180 for percussion/speech; set 0 or 40 for EDM/sub-bass)")
    p_dp.add_argument("--apply", action="store_true", help="Write detected punches directly into the spec JSON")

    # extract-frame
    p_xf = subparsers.add_parser(
        "extract-frame",
        help="Extract a frame from a rendered clip and freeze it as a manifest asset "
             "(cross-shot handoff: shot k+1's first_frame)")
    p_xf.add_argument("--video", required=True, help="Rendered clip to read (e.g. build/shot-01.mp4)")
    p_xf.add_argument("--name", required=True, help="Asset name to register (e.g. shot-01-tail)")
    p_xf.add_argument("--at", default="last", help="Which frame: 'last', 'first', or a timestamp in seconds")

    # test
    subparsers.add_parser("test", help="Run full regression test suite")

    # clean
    subparsers.add_parser("clean", help="Clean build artifacts")

    args = parser.parse_args()

    if args.command == "validate":
        run_stage(["-m", "core.spec", args.spec], "Spec Validation")

    elif args.command == "generate":
        gen_args = [os.path.join(STAGES, "01_generate.py"), "--spec", args.spec]
        if args.force:
            gen_args.append("--force")
        run_stage(gen_args, "S1: Asset Generation / Verification")

    elif args.command == "prepare":
        run_stage([os.path.join(STAGES, "02_prepare.py"), "--spec", args.spec], "S2: Prepare & Purity Check")

    elif args.command == "compose":
        run_stage([os.path.join(STAGES, "03_compose.py"), "--spec", args.spec], "S3: Compose (FFmpeg)")

    elif args.command == "gate":
        run_stage([os.path.join(STAGES, "04_gate.py"), "--spec", args.spec], "S4: Quality Gates")

    elif args.command == "inspect":
        run_stage([os.path.join(STAGES, "05_inspect.py"), "--spec", args.spec, "--grid", args.grid], "S5: Visual Self-Audit Inspection")

    elif args.command == "judge":
        if args.verdict:
            judge_args = [os.path.join(STAGES, "05_inspect.py"), "--spec", args.spec, "--record", args.verdict]
            if args.notes:
                judge_args += ["--notes", args.notes]
            run_stage(judge_args, f"S5: Record judge verdict ({args.verdict})")
        else:
            run_stage([os.path.join(STAGES, "05_inspect.py"), "--spec", args.spec], "S5: Visual Self-Audit Inspection (evidence + instructions)")

    elif args.command == "run":
        if args.timeline:
            # A timeline run is a WHOLE EPISODE, and its shots have to be
            # rendered in order: shot k+1 may reference the tail that shot k
            # produces, so shot k has to exist before shot k+1's S1 looks for
            # it. The timeline is the only thing the author has to get right.
            with pipeline_lock():
                code = run_timeline(args)
            sys.exit(code)
        with pipeline_lock():
            run_stage(["-m", "core.spec", args.spec], "Spec Validation")
            gen_args = [os.path.join(STAGES, "01_generate.py"), "--spec", args.spec]
            if args.force:
                gen_args.append("--force")
            run_stage(gen_args, "S1: Asset Generation / Verification")
            run_stage([os.path.join(STAGES, "02_prepare.py"), "--spec", args.spec], "S2: Prepare & Purity Check")
            run_stage([os.path.join(STAGES, "03_compose.py"), "--spec", args.spec], "S3: Compose (FFmpeg)")
            run_stage([os.path.join(STAGES, "04_gate.py"), "--spec", args.spec], "S4: Quality Gates")
            run_stage([os.path.join(STAGES, "05_inspect.py"), "--spec", args.spec], "S5: Visual Self-Audit Inspection")
        print(
            "\nPipeline completed: all deterministic gates passed.\n"
            "Visual inspection is PENDING judge — review the contact sheet, then run:\n"
            "  python3 pipeline.py judge --spec " + args.spec + " --verdict pass|fail --notes \"...\""
        )

    elif args.command == "init-shot":
        shot_id = args.shot_id.strip()
        # The shot id becomes the spec file name and every build/ path for
        # that shot — it must not be able to walk out of spec/.
        from core.spec.naming import valid_name
        if not valid_name(shot_id):
            sys.exit(
                f"shot id must be a letters/digits/._- string (got {shot_id!r}); "
                f"it names spec/{shot_id}.poster.json and the build/ paths")
        os.makedirs(os.path.join(ROOT, "spec"), exist_ok=True)
        target = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        if os.path.exists(target):
            print(f"Spec already exists: {target}")
            return
        if args.from_shot:
            from core.spec.state import carry_state_from
            from core.spec.loader import load_spec
            prev_arg = args.from_shot
            if not prev_arg.endswith(".json"):
                prev_arg = f"spec/{prev_arg}.poster.json"
            prev_path = prev_arg if os.path.isabs(prev_arg) else os.path.join(ROOT, prev_arg)
            if not os.path.exists(prev_path) and os.path.exists(prev_arg):
                prev_path = prev_arg
            prev_spec = load_spec(prev_path)
            template = carry_state_from(prev_spec, shot_id)
            template.update(canvas={"w": args.canvas[0], "h": args.canvas[1]}, fps=args.fps, durationInFrames=args.frames)
            with open(target, "w") as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
            print(f"Initialized {target} carrying final layer states from {prev_path}")
            return
        template = {
            "id": shot_id,
            "canvas": {"w": args.canvas[0], "h": args.canvas[1]},
            "fps": args.fps,
            "durationInFrames": args.frames,
            "layers": [], "gates": [],
            "tracks": {"captions": [], "events": []},
        }
        from core.spec import validate
        errors = validate(template)
        if errors:
            sys.exit("; ".join(errors))
        with open(target, "w") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        print(f"Initialized schema skeleton: {target} (zero layers, zero design — composition, colors, components and motion are yours to author)")

    elif args.command == "inspect-sprite":
        from core.rig import inspect_sprite
        rect = [int(v) for v in args.rect.split(",")] if args.rect else None
        joint = [float(v) for v in args.joint.split(",")] if args.joint else None
        info = inspect_sprite(args.asset, rect=rect, joint=joint, key_color=args.key_color)
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif args.command == "split-sprite":
        from core.rig import split_multi_sprite, split_sprite
        rect = [int(v) for v in args.rect.split(",")] if args.rect else None
        if args.parts_json:
            parts = json.loads(args.parts_json)
            clean_boxes = json.loads(args.clean_boxes_json) if args.clean_boxes_json else None
            info = split_multi_sprite(
                args.src, args.body, parts=parts,
                clean_boxes=clean_boxes, rect=rect, key_color=args.key_color,
            )
        else:
            if not (args.part and args.box and args.joint):
                sys.exit("split-sprite requires either --parts-json or (--part, --box, --joint)")
            box = [float(v) for v in args.box.split(",")]
            joint = [float(v) for v in args.joint.split(",")]
            info = split_sprite(
                args.src, args.body, args.part,
                box=box, joint=joint, joint_radius=args.radius,
                rect=rect, key_color=args.key_color,
            )
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif args.command == "derive-poses":
        from core.rig import derive_poses_from_sheet
        if args.sheet:
            prefix = args.out_prefix or args.sheet
            res = derive_poses_from_sheet(args.sheet, prefix, cols=args.cols, key_color=args.key_color)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            sys.exit("derive-poses requires --sheet <asset>; motion presets were removed")

    elif args.command == "snap-joint":
        from core.runtime import manifest
        from core.media.png import read_size
        from core.rig import snap_socket_joint
        p_row = manifest.verified("assets", args.parent_asset)
        c_row = manifest.verified("assets", args.child_asset)
        if not p_row:
            sys.exit(f"parent asset not found or not verified in manifest: {args.parent_asset}")
        if not c_row:
            sys.exit(f"child asset not found or not verified in manifest: {args.child_asset}")
        pw, ph = read_size(os.path.join(ROOT, p_row["path"]))
        cw, ch = read_size(os.path.join(ROOT, c_row["path"]))
        p_rect = [int(v) for v in args.parent_rect.split(",")]
        p_socket = [float(v) for v in args.parent_socket.split(",")]
        c_joint = [float(v) for v in args.child_joint.split(",")]
        res = snap_socket_joint([pw, ph], p_rect, p_socket, [cw, ch], c_joint, scale=args.scale)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "unpack-kit":
        from core.rig import unpack_kit
        labels = [s.strip() for s in args.labels.split(",")] if args.labels else None
        res = unpack_kit(
            args.sheet, args.prefix,
            key_color=args.key_color,
            min_area=args.min_area,
            pad=args.pad,
            sort_by=args.sort_by,
            labels=labels,
        )
        print(f"Unpacked {res['parts_count']} parts from {args.sheet}:")
        for p in res["parts"]:
            print(f"  - {p['asset']}: size={p['size']}, center={p['center']}, area={p['area']}, bbox={p['bbox']}")
        if labels and args.sort_by == "area":
            print("  note: labels bind to islands by descending area — verify bbox placement, or rerun with --sort-by position to map labels left-to-right/top-to-bottom")
        print("\nReady-to-use Remotion Spec Layer Snippet:")
        print(json.dumps(res["spec_layers_snippet"], indent=2, ensure_ascii=False))

    elif args.command == "sync-audio":
        from core.audio import sync_spec_audio
        spec_path = os.path.join(ROOT, args.spec)
        if not os.path.exists(spec_path):
            sys.exit(f"Spec not found: {spec_path}")
        res = sync_spec_audio(
            spec_path,
            fit_duration=not args.no_fit_duration,
            rescale_anim=not args.no_rescale_anim,
            max_chars=args.max_chars,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "verify-rig":
        from core.rig import verify_puppet_rig
        spec_path = os.path.join(ROOT, args.spec)
        if not os.path.exists(spec_path):
            sys.exit(f"Spec not found: {spec_path}")
        with open(spec_path) as f:
            spec_data = json.load(f)
        res = verify_puppet_rig(spec_data, tolerance=args.tolerance)
        print(f"\n=== Puppet Rig Verification: {spec_data.get('id', 'puppet')} ===")
        for j in res["joints"]:
            print(f"  [{j['status']}] {j['child_id']} -> {j['parent_id']}: delta={j['delta_px']}px (socket={j['socket_src']}, joint={j['joint_src']}, pivot={j['pivot_canvas']})")
        if res.get("diagnostic_image") and os.path.exists(res["diagnostic_image"]):
            print(f"  diagnostic overlay rendered: {res['diagnostic_image']}")
        if not res["passed"]:
            print(f"\nRig Verification FAILED:\n  " + "\n  ".join(res["errors"]))
            sys.exit(1)
        print("\nRig Verification PASSED (All joints calibrated within tolerance).")

    elif args.command == "verify-combat":
        from core.rig import verify_combat_contact
        spec_path = os.path.join(ROOT, args.spec)
        if not os.path.exists(spec_path):
            sys.exit(f"Spec not found: {spec_path}")
        with open(spec_path) as f:
            spec_data = json.load(f)
        res = verify_combat_contact(
            spec_data,
            attacker_id=args.attacker,
            weapon_id=args.weapon,
            target_id=args.target,
            tolerance=args.tolerance,
        )
        print(f"\n=== Combat Contact Verification: {spec_data.get('id', 'puppet')} ===")
        for d in (res.get("details") or []):
            print(f"  Frame {d['frame']:3d}: [{d['status']}] weapon_tip={d['weapon_tip']} target_hitbox={d['target_hitbox']} gap={d['gap_px']}px")
        if not res["passed"]:
            print(f"\nCombat Contact FAILED (Whiffing detected):\n  " + "\n  ".join(res["errors"]))
            sys.exit(1)
        print("\nCombat Contact PASSED (Physical weapon collision confirmed on all strikes).")

    elif args.command == "verify-blocking":
        from core.rig import verify_stage_blocking
        spec_path = os.path.join(ROOT, args.spec)
        if not os.path.exists(spec_path):
            sys.exit(f"Spec not found: {spec_path}")
        with open(spec_path) as f:
            spec_data = json.load(f)
        res = verify_stage_blocking(spec_data, max_overlap_px=args.max_overlap)
        print(f"\n=== Stage Blocking & Non-Overlap Verification: {spec_data.get('id', 'puppet')} ===")
        for p in res["pairs"]:
            print(f"  [{p['status']}] {p['pair']:<22} | min_clearance={p['min_clearance_px']:>6.1f}px | max_overlap={p['max_overlap_px']:>5.1f}px (frame {p['worst_frame']})")
        if not res["passed"]:
            print(f"\nStage Blocking FAILED (Co-planar character overlap detected):\n  " + "\n  ".join(res["errors"]))
            sys.exit(1)
        print("\nStage Blocking PASSED (Zero co-planar torso overlap across all frames).")

    elif args.command == "verify-continuity":
        from core.rig import verify_shot_stagecraft, verify_timeline_continuity
        if args.timeline:
            tl_path = os.path.join(ROOT, args.timeline)
            if not os.path.exists(tl_path):
                sys.exit(f"Timeline not found: {tl_path}")
            with open(tl_path) as f:
                tl_data = json.load(f)
            from core.spec import validate_timeline
            tl_errs = validate_timeline(tl_data)
            if tl_errs:
                sys.exit("Timeline validation failed:\n  " + "\n  ".join(tl_errs))
            # Knob resolution: CLI flag > timeline.continuity > function default
            cont = tl_data.get("continuity") or {}
            max_jump = args.max_jump if args.max_jump is not None else cont.get("max_char_jump_px", 18.0)
            min_op = args.min_visible_opacity if args.min_visible_opacity is not None else cont.get("min_visible_opacity", 0.20)
            if args.allow_non_seamless:
                require_seamless = False
            else:
                require_seamless = cont.get("require_seamless_handoff", True)
            print(f"continuity knobs: max_char_jump_px={max_jump} min_visible_opacity={min_op} require_seamless_handoff={require_seamless}")
            res = verify_timeline_continuity(
                tl_data, root_dir=ROOT,
                require_seamless_handoff=require_seamless,
                max_char_jump_px=max_jump,
                min_visible_opacity=min_op,
            )
            print(f"\n=== Multi-Scene Timeline Continuity Verification: {tl_data.get('id', 'timeline')} ===")
            for h in res["handoffs"]:
                print(f"  [{h['status']}] {h['from_shot']} -> {h['to_shot']} | handoff: {h['end_backdrop']} == {h['next_start_backdrop']}")
            if not res["passed"]:
                print(f"\nTimeline Continuity FAILED:\n  " + "\n  ".join(res["errors"]))
                sys.exit(1)
            warns = [h for h in res["handoffs"] if h["status"] == "BACKDROP_WARN"]
            if warns:
                print(f"\nTimeline Continuity PASSED with {len(warns)} backdrop warning(s) (non-seamless cuts allowed by config):")
                for h in warns:
                    print(f"  [BACKDROP_WARN] {h['from_shot']} ends on {h['end_backdrop']!r}, {h['to_shot']} starts on {h['next_start_backdrop']!r}")
            else:
                print("\nTimeline Continuity PASSED (backdrop handoffs & character seams verified).")
        elif args.spec:
            spec_path = os.path.join(ROOT, args.spec)
            if not os.path.exists(spec_path):
                sys.exit(f"Spec not found: {spec_path}")
            with open(spec_path) as f:
                spec_data = json.load(f)
            res = verify_shot_stagecraft(spec_data)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            if not res["passed"]:
                sys.exit(1)
        else:
            sys.exit("verify-continuity requires either --timeline <timeline.json> or --spec <spec.json>")

    elif args.command == "detect-punches":
        from core.audio import detect_audio_punches
        spec_path = os.path.join(ROOT, args.spec)
        if not os.path.exists(spec_path):
            sys.exit(f"Spec not found: {spec_path}")
        with open(spec_path) as f:
            spec_data = json.load(f)
        fps = spec_data.get("fps", 30)
        sid = spec_data.get("id", "shot-01")
        audio_target = args.audio or os.path.join(ROOT, "build", f"{sid}.mp4")
        if not os.path.exists(audio_target):
            audio_target = os.path.join(ROOT, ".tmp", f"{sid}_sync_voice.wav")
        res = detect_audio_punches(
            audio_target,
            fps=fps,
            max_punches=args.max_punches,
            min_gap_sec=args.min_gap,
            threshold_sigma=args.threshold_sigma,
            highpass_hz=args.highpass,
        )
        if args.apply and res["punches"]:
            spec_data.setdefault("tracks", {}).setdefault("events", []).extend(
                {"frame": frame, "kind": "audio_transient"} for frame in res["punches"])
            spec_data["tracks"]["events"].sort(key=lambda event: event["frame"])
            with open(spec_path, "w") as f:
                json.dump(spec_data, f, indent=2, ensure_ascii=False)
            res["applied_to"] = args.spec
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "concat":
        tl = load_timeline(args.timeline, create_default=True)
        out_path, code = assemble_timeline(tl, args.output)
        sys.exit(code)

    elif args.command == "extract-frame":
        # A cross-shot handoff needs the tail of one clip to BE the head of
        # the next. The video model can be told to end on a given image
        # (last_frame), but that only approximates the endpoint; extracting
        # the rendered frame makes the join exact. The result is frozen in
        # the manifest like any other asset, so the next shot can name it as
        # its first_frame with no special path through S1.
        src = args.video if os.path.isabs(args.video) else os.path.join(ROOT, args.video)
        if not os.path.exists(src):
            sys.exit(f"Video not found: {src}\n"
                     f"  render it first:  python3 pipeline.py run --spec <spec>")
        at = str(args.at).strip().lower()
        try:
            row = extract_frame_asset(src, args.name, at)
        except (RuntimeError, ValueError) as ex:
            sys.exit(str(ex))
        print(f"Extracted the {at} frame from {os.path.relpath(src, ROOT)}")
        print(f"Registered assets/{args.name}.png sha256={row['sha256'][:12]}")
        print(f"  next shot: \"type\": \"video\", \"first_frame\": \"{args.name}\"")

    elif args.command == "test":
        # -t . keeps the repo root as the top-level dir, so the test
        # sub-packages are imported as tests.<pkg>.<module>. Without it,
        # discovery treats `tests/` as the top level and imports the
        # sub-packages as `core`, `stages`, `pipeline` — which shadow the
        # engine's own core/ and stages/ packages.
        run_stage(["-m", "unittest", "discover", "-s", "tests", "-t", "."],
                  "Regression Test Suite")

    elif args.command == "clean":
        b_dir = os.path.join(ROOT, "build")
        if os.path.exists(b_dir):
            shutil.rmtree(b_dir)
            print("Removed build/ directory.")
        # public/prepared/ holds the video clips S3 stages for Remotion's
        # staticFile(). Nothing cleans it, so it grows with every render.
        pub_dir = os.path.join(ENGINE_ROOT, "public", "prepared")
        if os.path.exists(pub_dir):
            shutil.rmtree(pub_dir)
            print("Removed public/prepared/ directory.")
        tmp_dir = os.path.join(ROOT, ".tmp")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
            print("Removed .tmp/ directory.")
        print("Clean complete.")


if __name__ == "__main__":
    main()
