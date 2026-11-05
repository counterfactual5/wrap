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

ROOT = os.path.dirname(os.path.realpath(__file__))
CORE = os.path.join(ROOT, "core")
STAGES = os.path.join(ROOT, "stages")


def run_stage(cmd_args, desc):
    print(f"\n=== [Stage] {desc} ===")
    res = subprocess.run([sys.executable] + cmd_args, cwd=ROOT)
    if res.returncode != 0:
        print(f"FAILED: {desc} exited with code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)


def gate_full_video(out_path, timeline_id, segments):
    """Post-assembly QC on the concatenated full video.

    Per-shot gates (S4) already ran before stitching; this catches what only
    exists after shots are joined: total duration vs the timeline, black
    frames, whole-track silence/loudness, A/V alignment, and loudness jumps
    across cut boundaries (each shot is loudnorm'd independently — two in-band
    shots can still pop at the seam). Writes build/gates_full_{timeline}.json
    (namespaced per timeline, unlike the shared per-shot gates.json)."""
    from core import audio

    results, red = [], False

    def add(gid, metric, value, ok, bound):
        nonlocal red
        red |= not ok
        results.append({"id": gid, "metric": metric, "value": value, "bound": bound, "pass": ok})
        print(f"{'PASS' if ok else 'FAIL'}  {gid:<14} {metric:<22} {value}  [{bound}]")

    # 1. Total duration matches the timeline's declared shot durations.
    expected = sum(d for _, _, d in segments)
    av = audio.measure_av_durations(out_path)
    delta = abs(av["video_duration"] - expected)
    add("duration", "timeline_duration_delta", round(delta, 3), delta <= 0.25, "<= 0.250 s")

    # 2. True digital-black frames (concat fill around missing frames). The dark
    #    space canvas (#06080F, luma ~8) stays above pixel_black_th=0.02 (~5).
    bd = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", out_path,
         "-vf", "blackdetect=d=0.2:picture_black_ratio_th=0.98:pixel_black_th=0.02",
         "-f", "null", "-"],
        capture_output=True, text=True).stderr
    n_black = bd.count("black_start")
    add("black", "blackdetect", n_black, n_black == 0, "0 intervals")

    if av.get("has_audio"):
        sil = audio.measure_audio_silence(out_path)
        add("audio_silence", "audio_max_volume", round(sil["max_volume"], 1),
            not sil["is_silent"], "> -45.0 dB")

        lufs = audio.measure_audio_loudness(out_path)
        if lufs is not None:
            add("audio_loudness", "integrated_loudness", round(lufs, 1),
                -19.0 <= lufs <= -13.0, "-19.0 .. -13.0 LUFS")

        add("av_sync", "duration_delta", round(av["delta"], 3), av["delta"] <= 0.25, "<= 0.250 s")

        # 3. Per-shot loudness at each timeline segment: max pairwise delta.
        seg_lufs = [
            audio.measure_audio_loudness(out_path, start=start, duration=dur)
            for _, start, dur in segments
        ]
        if len(seg_lufs) >= 2 and all(v is not None for v in seg_lufs):
            jump = max(seg_lufs) - min(seg_lufs)
            add("loudness_jump", "max_pairwise_delta", round(jump, 1), jump <= 3.0, "<= 3.0 LU")
    else:
        print("SKIP  audio gates (assembled video has no audio track)")

    gates_out = os.path.join(ROOT, "build", f"gates_full_{timeline_id}.json")
    with open(gates_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"full-video gates -> {gates_out}")
    return 1 if red else 0


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
    p_val.add_argument("--spec", default="spec/shot-01.poster.json")

    # generate (S1)
    p_gen = subparsers.add_parser("generate", help="S1: generate/fetch assets")
    p_gen.add_argument("--spec", default="spec/shot-01.poster.json")
    p_gen.add_argument("--force", action="store_true", help="Force re-generation")
    p_gen.add_argument("--fixture", action="store_true", help="Use deterministic fixture")

    # prepare (S2)
    p_prep = subparsers.add_parser("prepare", help="S2: prepare assets & key purity check")
    p_prep.add_argument("--spec", default="spec/shot-01.poster.json")

    # compose (S3)
    p_comp = subparsers.add_parser("compose", help="S3: ffmpeg compose frames & mp4")
    p_comp.add_argument("--spec", default="spec/shot-01.poster.json")

    # gate (S4)
    p_gate = subparsers.add_parser("gate", help="S4: quality gates & freeze detect")
    p_gate.add_argument("--spec", default="spec/shot-01.poster.json")

    # inspect (S5)
    p_insp = subparsers.add_parser("inspect", help="S5: Generate contact sheet & checklist for visual self-audit")
    p_insp.add_argument("--spec", default="spec/shot-01.poster.json")
    p_insp.add_argument("--grid", default="3x3", help="Contact sheet grid, e.g. 3x3")

    # judge (S5 verdict)
    p_judge = subparsers.add_parser("judge", help="S5: Judge the contact sheet; record pass/fail verdict")
    p_judge.add_argument("--spec", default="spec/shot-01.poster.json")
    p_judge.add_argument("--verdict", choices=["pass", "fail"], default=None,
                         help="Record verdict; omit to regenerate evidence + judge instructions")
    p_judge.add_argument("--notes", default=None, help="Judge findings stored with the verdict")

    # run (S1..S5)
    p_run = subparsers.add_parser("run", help="Run full pipeline: validate -> S1 -> S2 -> S3 -> S4 -> S5")
    p_run.add_argument("--spec", default="spec/shot-01.poster.json")
    p_run.add_argument("--force", action="store_true", help="Force re-generation of assets")
    p_run.add_argument("--fixture", action="store_true", help="Use deterministic fixture")

    # init-shot
    p_init = subparsers.add_parser("init-shot", help="Initialize a new shot specification template")
    p_init.add_argument("shot_id", help="Shot ID, e.g. shot-02")

    # concat
    p_cat = subparsers.add_parser("concat", help="Concatenate multiple rendered shots via timeline")
    p_cat.add_argument("--timeline", default="spec/timeline.json", help="Path to timeline.json")
    p_cat.add_argument("--output", default="build/full.mp4", help="Path to output mp4")

    # test
    subparsers.add_parser("test", help="Run full regression test suite")

    # clean
    subparsers.add_parser("clean", help="Clean build artifacts")

    args = parser.parse_args()

    if args.command == "validate":
        run_stage([os.path.join(CORE, "schema.py"), args.spec], "Spec Validation")

    elif args.command == "generate":
        gen_args = [os.path.join(STAGES, "01_generate.py"), "--spec", args.spec]
        if args.force:
            gen_args.append("--force")
        if args.fixture:
            gen_args.append("--fixture")
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
        with pipeline_lock():
            run_stage([os.path.join(CORE, "schema.py"), args.spec], "Spec Validation")
            gen_args = [os.path.join(STAGES, "01_generate.py"), "--spec", args.spec]
            if args.force:
                gen_args.append("--force")
            if args.fixture:
                gen_args.append("--fixture")
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
        os.makedirs(os.path.join(ROOT, "spec"), exist_ok=True)
        target = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        if os.path.exists(target):
            print(f"Spec already exists: {target}")
            return
        # Schema skeleton only — deliberately NO layout. Composition is a
        # per-episode design decision (SKILL.md "The One Design Law"); a baked
        # skeleton here is how every episode converged to one identical look.
        template = {
            "_design_hints": [
                "Pipeline is fixed; this skeleton has no layout by design.",
                "Design composition from the shot's narrative role FIRST:",
                "  hook -> full-bleed poster (ai plate:false + big title via anim + field/path accents)",
                "  development -> pure diagram (no ai layer; formula card timed to narration)",
                "  resolution -> full-bleed documentary (real footage, slow reveal)",
                "Never clone a previous episode's skeleton. Vocabulary:",
                "  anim (x/y/scale/opacity/rotate keyframes, ease in/out/inout),",
                "  field particles, path reveal/flow lines, vibe:false, plate:false.",
                "Before designing: ROLL THE DICE (SKILL.md 'Creative dice') — sample",
                "  composition x palette x entrance x camera x HUD-density, commit the",
                "  rolled values here; >=4 shared values with a sibling spec = re-roll.",
                "Verified examples: skills/code-driven-shot-pipeline/references/",
                "  reference_hook_poster.json / reference_development_diagram.json /",
                "  reference_resolution_documentary.json (three composition languages).",
            ],
            "id": shot_id,
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 450,
            "style": "spec/style.json",
            "layers": [
                {"id": "bg", "type": "code", "draw": "grid", "rect": [0, 0, 1080, 1920], "z": 0}
            ],
            "gates": [
                {"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.15}
            ]
        }
        with open(target, "w") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        print(f"Initialized schema skeleton: {target} (layout is yours to design — see _design_hints)")

    elif args.command == "concat":
        timeline_path = os.path.join(ROOT, args.timeline)
        if not os.path.exists(timeline_path):
            os.makedirs(os.path.dirname(timeline_path), exist_ok=True)
            with open(timeline_path, "w") as f:
                json.dump({"id": "full-sequence", "shots": ["spec/shot-01.poster.json"]}, f, indent=2)
            print(f"Created default timeline at: {timeline_path}")

        with open(timeline_path) as f:
            tl = json.load(f)

        from core.schema import validate_timeline
        tl_errs = validate_timeline(tl)
        if tl_errs:
            sys.exit(f"Timeline validation failed:\n  " + "\n  ".join(tl_errs))

        shots = tl.get("shots", [])
        print(f"\n=== Timeline Assembly: {tl.get('id', 'sequence')} ({len(shots)} clips) ===")

        rendered_mp4s = []
        segments = []  # (shot_id, start_sec, dur_sec) — the full-gate's measurement windows
        cursor = 0.0
        for idx, shot in enumerate(shots):
            if isinstance(shot, dict):
                shot_spec_rel = shot["spec"]
                beat = shot.get("beat", "scene")
                reason = shot.get("reason", "")
            else:
                shot_spec_rel = shot
                beat = "scene"
                reason = ""

            shot_file = os.path.join(ROOT, shot_spec_rel if shot_spec_rel.endswith(".json") else f"spec/{shot_spec_rel}.poster.json")
            if not os.path.exists(shot_file):
                sys.exit(f"Error: shot spec not found: {shot_file}")
            with open(shot_file) as sf:
                s_data = json.load(sf)
            sid = s_data["id"]

            print(f"  [{idx+1}/{len(shots)}] [{beat.upper():<11}] {sid:<24} | {reason if reason else 'No reason specified'}")

            mp4_path = os.path.join(ROOT, "build", f"{sid}.mp4")
            # Contract: only verified rendered files are assembled
            if not os.path.exists(mp4_path):
                print(f"      [Build Contract] MP4 missing for {sid}. Building and gating now...")
                run_stage([os.path.join(STAGES, "03_compose.py"), "--spec", shot_file], f"Render {sid}")
                run_stage([os.path.join(STAGES, "04_gate.py"), "--spec", shot_file], f"Gate {sid}")
            rendered_mp4s.append(mp4_path)
            dur = s_data["durationInFrames"] / s_data["fps"]
            segments.append((sid, cursor, dur))
            cursor += dur

        out_path = os.path.join(ROOT, args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # Per-timeline list, not a shared slot: two concat runs for different
        # timelines must not clobber each other's input file.
        concat_dir = os.path.join(ROOT, "build", "concat")
        os.makedirs(concat_dir, exist_ok=True)
        concat_txt = os.path.join(concat_dir, f"{tl.get('id', 'sequence')}.txt")
        with open(concat_txt, "w") as f:
            for p in rendered_mp4s:
                f.write(f"file '{os.path.abspath(p)}'\n")

        print(f"\nConcatenating {len(rendered_mp4s)} shots -> {out_path} ...")
        cmd = [
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", "-movflags", "+faststart", out_path
        ]
        subprocess.run(cmd, check=True)
        print(f"Successfully generated: {out_path} (size: {os.path.getsize(out_path)} bytes)")

        print(f"\n=== [Stage] Full-Video Gates ({tl.get('id', 'sequence')}) ===")
        sys.exit(gate_full_video(out_path, tl.get("id", "sequence"), segments))

    elif args.command == "test":
        run_stage(["-m", "unittest", "discover", "tests"], "Regression Test Suite")

    elif args.command == "clean":
        b_dir = os.path.join(ROOT, "build")
        if os.path.exists(b_dir):
            shutil.rmtree(b_dir)
            print("Removed build/ directory.")
        print("Clean complete.")


if __name__ == "__main__":
    main()
